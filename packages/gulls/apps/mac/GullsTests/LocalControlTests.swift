import Foundation
import XCTest
@testable import Gulls

@MainActor
final class LocalControlTests: XCTestCase {
    private var root: URL!
    private var defaults: UserDefaults!
    private var suiteName: String!
    private var config: GullsConfig!
    private var store: LocalControlStore!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("LocalControlTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        suiteName = "local-control-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)!
        config = GullsConfig(profileID: "local-test", defaults: defaults, tokenStore: MemoryTokenStore())
        config.agentHandle = "@test:gulls.ai"
        config.apiURL = "https://message.example.test"
        config.contextDir = root.appendingPathComponent("context", isDirectory: true).path
        store = LocalControlStore(config: config, defaults: defaults)
        store.enabled = true
        store.addFolder(root)
    }

    override func tearDownWithError() throws {
        defaults.removePersistentDomain(forName: suiteName)
        try? FileManager.default.removeItem(at: root)
    }

    func testRefreshLoadsRequestWithoutExecutingIt() throws {
        let marker = root.appendingPathComponent("marker")
        let request = request(
            kind: .command,
            executable: "/usr/bin/touch",
            arguments: [marker.path],
            workingDirectory: root.path
        )
        try writeRequest(request)

        store.refresh()

        XCTAssertEqual(store.pendingRequests.map(\.requestID), [request.requestID])
        XCTAssertFalse(FileManager.default.fileExists(atPath: marker.path))
        XCTAssertTrue(store.recentResults.isEmpty)
    }

    func testDisabledApprovalDoesNotExecuteOrPersistResult() async throws {
        let marker = root.appendingPathComponent("disabled-marker")
        let request = request(
            kind: .command,
            executable: "/usr/bin/touch",
            arguments: [marker.path],
            workingDirectory: root.path
        )
        try writeRequest(request)
        store.refresh()
        store.enabled = false

        await store.approve(try XCTUnwrap(store.pendingRequests.first))

        XCTAssertFalse(FileManager.default.fileExists(atPath: marker.path))
        XCTAssertTrue(store.recentResults.isEmpty)
        XCTAssertEqual(store.pendingRequests.count, 1)
    }

    func testReadRejectsSymlinkEscape() async throws {
        let outside = root.deletingLastPathComponent().appendingPathComponent("outside-\(UUID().uuidString).txt")
        try Data("secret".utf8).write(to: outside)
        let link = root.appendingPathComponent("linked.txt")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: outside)
        let request = request(kind: .readFile, path: link.path)
        try writeRequest(request)
        store.refresh()

        await store.approve(try XCTUnwrap(store.pendingRequests.first))

        let result = try XCTUnwrap(store.recentResults.first)
        XCTAssertEqual(result.status, .failed)
        XCTAssertNil(result.content)
        try? FileManager.default.removeItem(at: outside)
    }

    func testReadAllowsOneMiBTextResult() async throws {
        let target = root.appendingPathComponent("large-read.txt")
        let content = String(repeating: "\u{0001}", count: LocalControlStore.maximumFileBytes)
        try Data(content.utf8).write(to: target)
        let request = request(kind: .readFile, path: target.path)
        try writeRequest(request)
        store.refresh()

        await store.approve(try XCTUnwrap(store.pendingRequests.first))

        let result = try XCTUnwrap(store.recentResults.first)
        XCTAssertEqual(result.status, .succeeded)
        XCTAssertEqual(result.content?.utf8.count, LocalControlStore.maximumFileBytes)

        store.refresh()
        XCTAssertEqual(store.recentResults.first?.content?.utf8.count, LocalControlStore.maximumFileBytes)
    }

    func testWriteRejectsTargetChangedAfterReview() async throws {
        let target = root.appendingPathComponent("notes.txt")
        try Data("before".utf8).write(to: target)
        let request = request(kind: .writeFile, path: target.path, content: "approved")
        try writeRequest(request)
        store.refresh()
        let reviewed = try XCTUnwrap(store.pendingRequests.first)

        try Data("changed".utf8).write(to: target)
        await store.approve(reviewed)

        let result = try XCTUnwrap(store.recentResults.first)
        XCTAssertEqual(result.status, .rejected)
        XCTAssertEqual(String(data: try Data(contentsOf: target), encoding: .utf8), "changed")
    }

    func testWriteRejectsExistingBinaryTargetBeforeWriting() async throws {
        let target = root.appendingPathComponent("binary.dat")
        try Data([0xFF, 0x00, 0xFE]).write(to: target)
        let request = request(kind: .writeFile, path: target.path, content: "replacement")
        try writeRequest(request)
        store.refresh()
        let reviewed = try XCTUnwrap(store.pendingRequests.first)

        await store.approve(reviewed)

        XCTAssertEqual(store.recentResults.first?.status, .rejected)
        XCTAssertEqual(try Data(contentsOf: target), Data([0xFF, 0x00, 0xFE]))
    }

    func testWriteRejectsExistingOversizedTargetBeforeWriting() async throws {
        let target = root.appendingPathComponent("large.txt")
        try Data(repeating: 0x41, count: LocalControlStore.maximumFileBytes + 1).write(to: target)
        let request = request(kind: .writeFile, path: target.path, content: "replacement")
        try writeRequest(request)
        store.refresh()
        let reviewed = try XCTUnwrap(store.pendingRequests.first)

        await store.approve(reviewed)

        XCTAssertEqual(store.recentResults.first?.status, .rejected)
        XCTAssertEqual(try Data(contentsOf: target).count, LocalControlStore.maximumFileBytes + 1)
    }

    func testWriteRejectsDirectoryTargetBeforeWriting() async throws {
        let target = root.appendingPathComponent("folder", isDirectory: true)
        try FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)
        let request = request(kind: .writeFile, path: target.path, content: "replacement")
        try writeRequest(request)
        store.refresh()
        let reviewed = try XCTUnwrap(store.pendingRequests.first)

        await store.approve(reviewed)

        XCTAssertEqual(store.recentResults.first?.status, .failed)
        XCTAssertTrue(FileManager.default.fileExists(atPath: target.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: target.appendingPathComponent("replacement").path) == false)
    }

    func testIndentedRequestCanExecuteAfterReview() async throws {
        let target = root.appendingPathComponent("pretty.txt")
        let original = request(kind: .writeFile, path: target.path, content: "pretty")
        try writeRequest(original, pretty: true)
        store.refresh()

        await store.approve(try XCTUnwrap(store.pendingRequests.first))

        XCTAssertEqual(store.recentResults.first?.status, .succeeded)
        XCTAssertEqual(String(data: try Data(contentsOf: target), encoding: .utf8), "pretty")
    }

    func testIndentedRequestCanBeReviewedButTamperingAfterRefreshIsRejected() async throws {
        let target = root.appendingPathComponent("draft.txt")
        let original = request(kind: .writeFile, path: target.path, content: "first")
        try writeRequest(original, pretty: true)
        store.refresh()
        let reviewed = try XCTUnwrap(store.pendingRequests.first)

        let changed = request(
            requestID: original.requestID,
            kind: .writeFile,
            path: target.path,
            content: "tampered"
        )
        try writeRequest(changed)
        store.refresh()
        await store.approve(reviewed)

        XCTAssertEqual(store.recentResults.first?.status, .rejected)
        XCTAssertFalse(FileManager.default.fileExists(atPath: target.path))
    }

    func testCommandCapturesOutputAndExitCode() async throws {
        let request = request(
            kind: .command,
            executable: "/usr/bin/printf",
            arguments: ["hello"],
            workingDirectory: root.path
        )
        try writeRequest(request)
        store.enabled = true
        store.refresh()

        await store.approve(try XCTUnwrap(store.pendingRequests.first))

        let result = try XCTUnwrap(store.recentResults.first)
        XCTAssertEqual(result.status, .succeeded)
        XCTAssertEqual(result.stdout, "hello")
        XCTAssertEqual(result.exitCode, 0)
    }

    func testCommandOutputIsBoundedWhenPipeFills() async throws {
        let request = request(
            kind: .command,
            executable: "/usr/bin/printf",
            arguments: [String(repeating: "x", count: LocalControlStore.maximumOutputBytes + 4096)],
            workingDirectory: root.path
        )
        try writeRequest(request)
        store.refresh()

        await store.approve(try XCTUnwrap(store.pendingRequests.first))

        let result = try XCTUnwrap(store.recentResults.first)
        XCTAssertEqual(result.status, .succeeded)
        XCTAssertEqual(result.stdout?.utf8.count, LocalControlStore.maximumOutputBytes)
    }

    func testStopCancelsRunningCommand() async throws {
        let request = request(
            kind: .command,
            executable: "/bin/sleep",
            arguments: ["5"],
            workingDirectory: root.path
        )
        try writeRequest(request)
        store.enabled = true
        store.refresh()
        let reviewed = try XCTUnwrap(store.pendingRequests.first)
        let approval = Task { await store.approve(reviewed) }

        for _ in 0..<20 where !store.isRunning {
            try await Task.sleep(for: .milliseconds(10))
        }
        store.stop()
        await approval.value

        XCTAssertEqual(store.recentResults.first?.status, .cancelled)
    }

    func testTerminationKillsCommandThatIgnoresSIGTERM() async throws {
        let ready = root.appendingPathComponent("termination-ready")
        let request = request(
            kind: .command,
            executable: "/bin/sh",
            arguments: ["-c", "trap '' TERM; /usr/bin/touch '\(ready.path)'; sleep 5"],
            workingDirectory: root.path
        )
        try writeRequest(request)
        store.refresh()
        let reviewed = try XCTUnwrap(store.pendingRequests.first)
        let approval = Task { await store.approve(reviewed) }

        for _ in 0..<100 {
            if FileManager.default.fileExists(atPath: ready.path) { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertTrue(FileManager.default.fileExists(atPath: ready.path))
        store.stop(forTermination: true)
        await approval.value

        XCTAssertEqual(store.recentResults.first?.status, .cancelled)
    }

    func testStoppingCommandAlsoStopsItsChildProcesses() async throws {
        let ready = root.appendingPathComponent("child-ready")
        let escaped = root.appendingPathComponent("child-effect")
        let request = request(
            kind: .command,
            executable: "/bin/sh",
            arguments: ["-c", "(sleep 1; /usr/bin/touch '\(escaped.path)') & /usr/bin/touch '\(ready.path)'; wait"],
            workingDirectory: root.path
        )
        try writeRequest(request)
        store.refresh()
        let reviewed = try XCTUnwrap(store.pendingRequests.first)
        let approval = Task { await store.approve(reviewed) }
        for _ in 0..<100 {
            if FileManager.default.fileExists(atPath: ready.path) { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertTrue(FileManager.default.fileExists(atPath: ready.path))

        store.stop()
        await approval.value
        try await Task.sleep(for: .milliseconds(1100))

        XCTAssertEqual(store.recentResults.first?.status, .cancelled)
        XCTAssertFalse(FileManager.default.fileExists(atPath: escaped.path))
    }

    func testInterruptedClaimIsRecoveredWithoutReplayingRequest() throws {
        let marker = root.appendingPathComponent("interrupted-marker")
        let request = request(
            kind: .command,
            executable: "/usr/bin/touch",
            arguments: [marker.path],
            workingDirectory: root.path
        )
        try writeRequest(request)
        try Data().write(to: store.requestsDirectory.appendingPathComponent("\(request.requestID).claim"))

        store.refresh()

        XCTAssertFalse(FileManager.default.fileExists(atPath: marker.path))
        XCTAssertTrue(store.pendingRequests.isEmpty)
        XCTAssertEqual(store.recentResults.first?.status, .failed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: store.requestsDirectory.appendingPathComponent("\(request.requestID).claim").path))

        store.refresh()
        XCTAssertFalse(FileManager.default.fileExists(atPath: marker.path))
        XCTAssertEqual(store.recentResults.first?.status, .failed)
    }

    func testInterruptedClaimRetainsClaimWhenRecoveryPersistenceFails() throws {
        let request = request(
            kind: .command,
            executable: "/usr/bin/true",
            workingDirectory: root.path
        )
        try writeRequest(request)
        let claim = store.requestsDirectory.appendingPathComponent("\(request.requestID).claim")
        try Data().write(to: claim)
        try Data().write(to: store.resultsDirectory)

        store.refresh()

        XCTAssertTrue(store.error?.contains("Could not recover interrupted local action") == true)
        XCTAssertTrue(FileManager.default.fileExists(atPath: claim.path))
        XCTAssertTrue(store.pendingRequests.isEmpty)
    }

    func testConfigChangesDuringCommandKeepResultInOriginalContext() async throws {
        let originalContext = URL(fileURLWithPath: config.contextDir)
        let newRoot = root.appendingPathComponent("new-context", isDirectory: true)
        try FileManager.default.createDirectory(at: newRoot, withIntermediateDirectories: true)
        let request = request(
            kind: .command,
            executable: "/bin/sleep",
            arguments: ["5"],
            workingDirectory: root.path
        )
        try writeRequest(request)
        store.refresh()
        let reviewed = try XCTUnwrap(store.pendingRequests.first)
        let approval = Task { await store.approve(reviewed) }

        for _ in 0..<50 where !store.isRunning {
            try await Task.sleep(for: .milliseconds(10))
        }
        config.agentHandle = "@new:gulls.ai"
        config.contextDir = newRoot.path
        store.stop()
        await approval.value

        let originalResult = originalContext
            .appendingPathComponent("local-actions/results", isDirectory: true)
            .appendingPathComponent("\(request.requestID).json")
        let newResult = newRoot
            .appendingPathComponent("local-actions/results", isDirectory: true)
            .appendingPathComponent("\(request.requestID).json")
        XCTAssertTrue(FileManager.default.fileExists(atPath: originalResult.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: newResult.path))
        XCTAssertTrue(store.recentResults.isEmpty)

        config.agentHandle = "@test:gulls.ai"
        config.contextDir = originalContext.path
        store.refresh()
        XCTAssertEqual(store.recentResults.first?.requestID, request.requestID)
    }

    func testRejectWhileRunningDoesNotReplaceFinalResult() async throws {
        let request = request(
            kind: .command,
            executable: "/bin/sleep",
            arguments: ["5"],
            workingDirectory: root.path
        )
        try writeRequest(request)
        store.refresh()
        let reviewed = try XCTUnwrap(store.pendingRequests.first)
        let approval = Task { await store.approve(reviewed) }

        for _ in 0..<50 where !store.isRunning {
            try await Task.sleep(for: .milliseconds(10))
        }
        store.reject(reviewed)
        store.stop()
        await approval.value

        XCTAssertEqual(store.recentResults.first?.status, .cancelled)
        XCTAssertEqual(store.recentResults.filter { $0.requestID == request.requestID }.count, 1)
    }

    func testResultPreventsReplayAfterRefresh() async throws {
        let target = root.appendingPathComponent("once.txt")
        let request = request(kind: .writeFile, path: target.path, content: "once")
        try writeRequest(request)
        store.enabled = true
        store.refresh()
        await store.approve(try XCTUnwrap(store.pendingRequests.first))
        let firstResult = try XCTUnwrap(store.recentResults.first)

        store.refresh()

        XCTAssertTrue(store.pendingRequests.isEmpty)
        XCTAssertEqual(store.recentResults.first?.requestID, firstResult.requestID)
        XCTAssertEqual(String(data: try Data(contentsOf: target), encoding: .utf8), "once")
    }

    private func request(
        requestID: String = UUID().uuidString,
        kind: LocalActionKind,
        executable: String? = nil,
        arguments: [String]? = nil,
        workingDirectory: String? = nil,
        path: String? = nil,
        content: String? = nil
    ) -> LocalActionRequest {
        LocalActionRequest(
            requestID: requestID,
            gullHandle: config.agentHandle,
            kind: kind,
            createdAt: ISO8601DateFormatter().string(from: Date()),
            executable: executable,
            arguments: arguments,
            workingDirectory: workingDirectory,
            path: path,
            content: content
        )
    }

    private func writeRequest(_ request: LocalActionRequest, pretty: Bool = false) throws {
        let directory = store.requestsDirectory
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let compact = try JSONEncoder().encode(request)
        let data: Data
        if pretty {
            let object = try JSONSerialization.jsonObject(with: compact)
            data = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
        } else {
            data = compact
        }
        try data.write(to: directory.appendingPathComponent("\(request.requestID).json"))
    }
}

private struct MemoryTokenStore: GullsTokenStore {
    func token(for profileID: String) -> String? { nil }
    func legacyToken() -> String? { nil }
    @discardableResult func setToken(_ token: String, for profileID: String) -> Bool { true }
}
