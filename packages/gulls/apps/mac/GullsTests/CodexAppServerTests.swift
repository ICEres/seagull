import Foundation
import XCTest
@testable import Gulls

@MainActor
final class CodexAppServerTests: XCTestCase {
    private var temporaryDirectories: [URL] = []

    override func tearDown() {
        for directory in temporaryDirectories {
            try? FileManager.default.removeItem(at: directory)
        }
        temporaryDirectories.removeAll()
    }

    func testConcurrentRequestsInitializeOnlyOnce() async throws {
        let server = try makeServer()
        defer { server.shutdown() }

        let initialized = expectation(description: "initialized notification")
        var initializationCount = 0
        server.onNotification = { method, _ in
            guard method == "test/initialized-once" else { return }
            initializationCount += 1
            initialized.fulfill()
        }

        async let first = server.request("ping")
        async let second = server.request("ping")
        _ = try await (first, second)
        await fulfillment(of: [initialized], timeout: 2)
        XCTAssertEqual(initializationCount, 1)
    }

    func testNotificationsArriveInSourceOrder() async throws {
        let server = try makeServer()
        defer { server.shutdown() }

        var sequence: [Int] = []
        let received = expectation(description: "ordered notifications")
        server.onNotification = { method, params in
            guard method == "test/sequence", let value = params["value"] as? Int else { return }
            sequence.append(value)
            if sequence.count == 3 { received.fulfill() }
        }

        let response = try await server.request("ordered")
        await fulfillment(of: [received], timeout: 2)
        XCTAssertEqual(sequence, [1, 2, 3])
        XCTAssertEqual(response["ok"] as? Bool, true)
    }

    func testStringRequestIDCanBeAnswered() async throws {
        let server = try makeServer()
        defer { server.shutdown() }

        let requestReceived = expectation(description: "approval request")
        let responseReceived = expectation(description: "approval response")
        var requestID: Any?
        server.onRequest = { id, params, method in
            guard method == "item/commandExecution/requestApproval", params["action"] as? String == "write" else { return }
            requestID = id
            requestReceived.fulfill()
            do {
                try server.respond(id: id, result: ["decision": "accept"])
            } catch {
                XCTFail("approval response failed: \(error)")
            }
        }
        server.onNotification = { method, _ in
            if method == "test/approval-received" { responseReceived.fulfill() }
        }

        let response = try await server.request("approval")
        await fulfillment(of: [requestReceived, responseReceived], timeout: 2)
        XCTAssertEqual(requestID as? String, "approval-1")
        XCTAssertEqual(response["approved"] as? Bool, true)
    }

    func testChildCrashFailsPendingRequestAndDisconnects() async throws {
        let server = try makeServer()
        defer { server.shutdown() }

        let disconnected = expectation(description: "disconnect")
        var disconnectCount = 0
        server.onDisconnect = {
            guard disconnectCount == 0 else { return }
            disconnectCount += 1
            disconnected.fulfill()
        }

        do {
            _ = try await server.request("crash")
            XCTFail("crashed app-server should fail the request")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("app-server"))
        }
        await fulfillment(of: [disconnected], timeout: 2)
    }

    func testCancellationDoesNotReplayRequest() async throws {
        let server = try makeServer()
        defer { server.shutdown() }

        let slowSeen = expectation(description: "slow request received")
        let slowResponseSent = expectation(description: "late slow response sent")
        var slowCount = 0
        server.onNotification = { method, _ in
            switch method {
            case "test/slow-seen":
                slowCount += 1
                slowSeen.fulfill()
            case "test/slow-response-sent":
                slowResponseSent.fulfill()
            default:
                break
            }
        }

        let task = Task { try await server.request("slow") }
        await fulfillment(of: [slowSeen], timeout: 2)
        task.cancel()
        do {
            _ = try await task.value
            XCTFail("cancelled request should not succeed")
        } catch is CancellationError {
            // Expected.
        }

        let response = try await server.request("fast")
        XCTAssertEqual(response["ok"] as? Bool, true)
        await fulfillment(of: [slowResponseSent], timeout: 2)
        XCTAssertEqual(slowCount, 1)
    }

    private func makeServer() throws -> CodexAppServer {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("gulls-codex-app-server-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        temporaryDirectories.append(directory)

        let executable = directory.appendingPathComponent("fake-codex.py")
        let source = """
        #!/usr/bin/python3
        import json
        import sys
        import threading
        import time

        def send(value):
            sys.stdout.write(json.dumps(value, separators=(",", ":")) + chr(10))
            sys.stdout.flush()

        for raw in sys.stdin:
            message = json.loads(raw)
            method = message.get("method")
            ident = message.get("id")
            if method == "initialize":
                send({"id": ident, "result": {"platformFamily": "unix", "platformOs": "macos"}})
                send({"method": "test/initialized-once", "params": {}})
            elif method == "ping":
                send({"id": ident, "result": {"ok": True}})
            elif method == "ordered":
                for value in (1, 2, 3):
                    send({"method": "test/sequence", "params": {"value": value}})
                send({"id": ident, "result": {"ok": True}})
            elif method == "approval":
                send({"id": "approval-1", "method": "item/commandExecution/requestApproval", "params": {"action": "write"}})
                approval = json.loads(sys.stdin.readline())
                if approval.get("id") != "approval-1" or approval.get("result", {}).get("decision") != "accept":
                    sys.exit(2)
                send({"method": "test/approval-received", "params": {}})
                send({"id": ident, "result": {"approved": True}})
            elif method == "crash":
                sys.exit(0)
            elif method == "slow":
                send({"method": "test/slow-seen", "params": {}})
                def send_late_response():
                    time.sleep(0.1)
                    send({"id": ident, "result": {"ok": True}})
                    send({"method": "test/slow-response-sent", "params": {}})
                threading.Thread(target=send_late_response, daemon=True).start()
            elif method == "fast":
                send({"id": ident, "result": {"ok": True}})
        """
        try Data(source.utf8).write(to: executable, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
        return CodexAppServer(executableURL: executable)
    }
}
