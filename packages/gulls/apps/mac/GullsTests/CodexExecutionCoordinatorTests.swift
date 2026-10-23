import Foundation
import XCTest
@testable import Gulls

@MainActor
final class CodexExecutionCoordinatorTests: XCTestCase {
    private final class MemoryTokens: GullsTokenStore {
        func token(for profileID: String) -> String? { nil }
        func legacyToken() -> String? { nil }
        func setToken(_ token: String, for profileID: String) -> Bool { true }
    }

    private struct Fixture {
        let server: CodexAppServer
        let log: URL
        let directory: URL
    }

    private var cleanup: [URL] = []

    override func tearDown() {
        for url in cleanup { try? FileManager.default.removeItem(at: url) }
        cleanup.removeAll()
    }

    func testDeltaBeforeTurnResponseBecomesDraft() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let config = try makeConfig()
        let store = CodexTaskStore(config: config, executor: CodexExecutionCoordinator(server: fixture.server))
        let task = try makeTask(store, goal: "draft")

        try await store.run(task)

        let completed = await waitUntil { store.tasks.first?.execution?.status == .draftReady }
        XCTAssertTrue(completed)
        let execution = try XCTUnwrap(store.tasks.first?.execution)
        XCTAssertEqual(execution.status, .draftReady)
        XCTAssertEqual(execution.output, "draft-1")
        XCTAssertEqual(store.tasks.first?.result?.content, "draft-1")
    }

    func testUnknownModelCannotStartTurn() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let metadata = try JSONSerialization.data(withJSONObject: ["models": [["slug": "allowed-model"]]])
        try metadata.write(to: fixture.directory.appendingPathComponent("models_cache.json"))
        let policy = CodexRuntimePolicy(codexHome: fixture.directory, tempRoot: fixture.directory)
        _ = try policy.startupArguments()
        let store = CodexTaskStore(config: try makeConfig(),
                                  executor: CodexExecutionCoordinator(server: fixture.server, policy: policy))
        let task = try makeTask(store, goal: "draft")
        do {
            try await store.run(task)
            XCTFail("A model outside the restricted catalog must not start a turn.")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("model catalog"))
        }
        XCTAssertEqual(store.tasks.first?.execution?.status, .failed)
        XCTAssertFalse(try readLog(fixture.log).contains { $0["method"] as? String == "turn/start" })
    }

    func testFollowUpResumesExactThread() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let config = try makeConfig()
        let coordinator = CodexExecutionCoordinator(server: fixture.server)
        let store = CodexTaskStore(config: config, executor: coordinator)
        let task = try makeTask(store, goal: "draft")

        try await store.run(task)
        let firstCompleted = await waitUntil { store.tasks.first?.execution?.status == .draftReady }
        XCTAssertTrue(firstCompleted)
        let firstThread = try XCTUnwrap(store.tasks.first?.execution?.codexThreadID)
        let resumedTask = try XCTUnwrap(store.tasks.first)
        try await store.run(resumedTask, followUp: "follow up")
        let followUpCompleted = await waitUntil { store.tasks.first?.execution?.status == .draftReady }
        XCTAssertTrue(followUpCompleted)

        XCTAssertEqual(store.tasks.first?.execution?.codexThreadID, firstThread)
        let messages = try readLog(fixture.log)
        XCTAssertEqual(messages.filter { $0["method"] as? String == "thread/start" }.count, 1)
        XCTAssertEqual(messages.filter { $0["method"] as? String == "thread/resume" }.count, 1)
        let resume = try XCTUnwrap(messages.first { $0["method"] as? String == "thread/resume" })
        let params = try XCTUnwrap(resume["params"] as? [String: Any])
        XCTAssertEqual(params["threadId"] as? String, firstThread)
    }

    func testMultipleGullsKeepSeparateThreads() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let coordinator = CodexExecutionCoordinator(server: fixture.server)
        let first = try makeStore(profileID: "one", coordinator: coordinator)
        let second = try makeStore(profileID: "two", coordinator: coordinator)
        let firstTask = try makeTask(first, goal: "draft one")
        let secondTask = try makeTask(second, goal: "draft two")

        async let firstRun: Void = first.run(firstTask)
        async let secondRun: Void = second.run(secondTask)
        _ = try await (firstRun, secondRun)

        let bothCompleted = await waitUntil {
            first.tasks.first?.execution?.status == .draftReady
                && second.tasks.first?.execution?.status == .draftReady
        }
        XCTAssertTrue(bothCompleted)
        let firstThread = try XCTUnwrap(first.tasks.first?.execution?.codexThreadID)
        let secondThread = try XCTUnwrap(second.tasks.first?.execution?.codexThreadID)
        XCTAssertNotEqual(firstThread, secondThread)
        XCTAssertEqual(first.tasks.first?.result?.content, "draft-one")
        XCTAssertEqual(second.tasks.first?.result?.content, "draft-two")
    }

    func testStopCancelsExactThreadAndQueuedLocalAction() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let config = try makeConfig()
        let suite = "codex-local-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
        let control = LocalControlStore(config: config, defaults: defaults)
        control.enabled = true
        control.addFolder(fixture.directory)
        let coordinator = CodexExecutionCoordinator(server: fixture.server)
        let store = CodexTaskStore(config: config, executor: coordinator, localControl: control)
        let task = try makeTask(store, goal: "tool", folder: fixture.directory)
        let running = Task { try? await store.run(task) }

        let queued = await waitUntil { control.pendingRequests.count == 1 }
        XCTAssertTrue(queued)
        let actionID = try XCTUnwrap(control.pendingRequests.first?.id)
        let thread = try XCTUnwrap(store.tasks.first?.execution?.codexThreadID)
        await store.stop(task)
        let cancelled = await waitUntil { control.pendingRequests.isEmpty }
        XCTAssertTrue(cancelled)
        XCTAssertEqual(store.tasks.first?.execution?.status, .interrupted)
        let cancelledResult = try readActionResult(id: actionID, origin: control.actionsDirectory)
        XCTAssertEqual(cancelledResult.status, .cancelled)
        XCTAssertNil(cancelledResult.stdout)
        XCTAssertNil(cancelledResult.content)
        XCTAssertEqual(store.tasks.first?.execution?.output, "draft-1")

        let messages = try readLog(fixture.log)
        let interrupt = try XCTUnwrap(messages.last { $0["method"] as? String == "turn/interrupt" })
        XCTAssertEqual((interrupt["params"] as? [String: Any])?["threadId"] as? String, thread)
        running.cancel()
    }

    func testDisablingCapabilityCancelsQueuedAction() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let config = try makeConfig()
        let suite = "codex-local-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
        let control = LocalControlStore(config: config, defaults: defaults)
        control.enabled = true
        control.addFolder(fixture.directory)
        let coordinator = CodexExecutionCoordinator(server: fixture.server)
        let store = CodexTaskStore(config: config, executor: coordinator, localControl: control)
        let task = try makeTask(store, goal: "tool", folder: fixture.directory)
        let running = Task { try? await store.run(task) }

        let queued = await waitUntil { control.pendingRequests.count == 1 }
        XCTAssertTrue(queued)
        let actionID = try XCTUnwrap(control.pendingRequests.first?.id)
        config.codexEnabled = false
        store.suspendExecution()
        let cancelled = await waitUntil { control.pendingRequests.isEmpty }
        XCTAssertTrue(cancelled)
        let result = try readActionResult(id: actionID, origin: control.actionsDirectory)
        XCTAssertEqual(result.status, .cancelled)
        XCTAssertNil(result.stdout)
        XCTAssertNil(result.content)
        XCTAssertEqual(store.tasks.first?.execution?.output, "draft-1")
        running.cancel()
    }

    func testChangingContextCancelsQueuedActionFromOriginalDirectory() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let config = try makeConfig()
        let suite = "codex-local-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
        let control = LocalControlStore(config: config, defaults: defaults)
        control.enabled = true
        control.addFolder(fixture.directory)
        let coordinator = CodexExecutionCoordinator(server: fixture.server)
        let store = CodexTaskStore(config: config, executor: coordinator, localControl: control)
        let task = try makeTask(store, goal: "tool", folder: fixture.directory)
        let running = Task { try? await store.run(task) }

        let queued = await waitUntil { control.pendingRequests.count == 1 }
        XCTAssertTrue(queued)
        let actionID = try XCTUnwrap(control.pendingRequests.first?.id)
        let originalActions = control.actionsDirectory
        config.contextDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("codex-reconnected-\(UUID().uuidString)", isDirectory: true).path
        store.suspendExecution()
        let cancelled = await waitUntil { control.pendingRequests.isEmpty }
        XCTAssertTrue(cancelled)
        let result = try readActionResult(id: actionID, origin: originalActions)
        XCTAssertEqual(result.status, .cancelled)
        XCTAssertNil(result.stdout)
        XCTAssertNil(result.content)
        XCTAssertEqual(store.tasks.first?.execution?.output, "draft-1")
        running.cancel()
    }

    func testReconnectCancelsQueuedActionWithoutReplayingIt() async throws {
        let fixture = try makeFixture()
        let config = try makeConfig()
        let suite = "codex-local-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
        let control = LocalControlStore(config: config, defaults: defaults)
        control.enabled = true
        control.addFolder(fixture.directory)
        let store = CodexTaskStore(config: config, executor: CodexExecutionCoordinator(server: fixture.server), localControl: control)
        let task = try makeTask(store, goal: "tool", folder: fixture.directory)
        let running = Task { try? await store.run(task) }

        let queued = await waitUntil { control.pendingRequests.count == 1 }
        XCTAssertTrue(queued)
        let actionID = try XCTUnwrap(control.pendingRequests.first?.id)
        let origin = control.actionsDirectory
        fixture.server.shutdown()
        let cancelled = await waitUntil { control.pendingRequests.isEmpty }
        XCTAssertTrue(cancelled)
        let actionResult = try readActionResult(id: actionID, origin: origin)
        XCTAssertEqual(actionResult.status, .cancelled)
        XCTAssertEqual(store.tasks.first?.execution?.status, .interrupted)
        XCTAssertNil(actionResult.stdout)
        XCTAssertNil(actionResult.content)
        XCTAssertEqual(store.tasks.first?.execution?.output, "draft-1")
        running.cancel()
    }

    func testNativeApprovalsDeclineAndUnknownRequestsAreRejected() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let config = try makeConfig()
        let coordinator = CodexExecutionCoordinator(server: fixture.server)
        let store = CodexTaskStore(config: config, executor: coordinator)
        let task = try makeTask(store, goal: "approval")
        let running = Task { try? await store.run(task) }

        let responded = await waitUntil {
            (try? self.readLog(fixture.log).contains { message in
                message["id"] as? String == "native-1"
                    && message["result"] != nil
            }) == true
            && ((try? self.readLog(fixture.log).contains { message in
                message["id"] as? String == "unknown-1"
                    && message["error"] != nil
            }) == true)
        }
        XCTAssertTrue(responded)
        let messages = try readLog(fixture.log)
        let native = try XCTUnwrap(messages.last { $0["id"] as? String == "native-1" })
        XCTAssertEqual((native["result"] as? [String: Any])?["decision"] as? String, "decline")
        let unknown = try XCTUnwrap(messages.last { $0["id"] as? String == "unknown-1" })
        XCTAssertNotNil(unknown["error"])
        running.cancel()
    }

    func testApprovedReadActionReturnsDraftAndNeverUsesNativeApproval() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let reviewFile = fixture.directory.appendingPathComponent("review.txt")
        try Data("fixture content".utf8).write(to: reviewFile)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: reviewFile.path)
        let config = try makeConfig()
        let suite = "codex-local-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
        let control = LocalControlStore(config: config, defaults: defaults)
        control.enabled = true
        control.addFolder(fixture.directory)
        let coordinator = CodexExecutionCoordinator(server: fixture.server)
        let store = CodexTaskStore(config: config, executor: coordinator, localControl: control)
        let task = try makeTask(store, goal: "read-tool", folder: fixture.directory)
        let running = Task { try? await store.run(task) }

        let queued = await waitUntil { control.pendingRequests.count == 1 }
        XCTAssertTrue(queued)
        let reviewed = try XCTUnwrap(control.pendingRequests.first)
        await control.approve(reviewed)
        let resultReady = await waitUntil {
            control.recentResults.first(where: { $0.id == reviewed.id })?.content == "fixture content"
        }
        XCTAssertTrue(resultReady)
        let completed = await waitUntil { store.tasks.first?.execution?.status == .draftReady }
        XCTAssertTrue(completed)
        XCTAssertTrue(store.tasks.first?.result?.content.lowercased().contains("read") == true)
        let messages = try readLog(fixture.log)
        XCTAssertFalse(messages.contains { $0["id"] as? String == "native-1" })
        running.cancel()
    }

    private func makeFixture() throws -> Fixture {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("codex-coordinator-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        cleanup.append(directory)
        let log = directory.appendingPathComponent("messages.jsonl")
        let executable = directory.appendingPathComponent("fake-codex.py")
        let script = """
        #!/usr/bin/python3
        import json, sys, uuid

        LOG = \(pythonString(log.path))
        TOOL_FOLDER = \(pythonString(directory.path))
        threads = 0
        turns = 0
        tool_context = {}

        def send(value):
            sys.stdout.write(json.dumps(value, separators=(",", ":")) + chr(10))
            sys.stdout.flush()

        def log(value):
            with open(LOG, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, separators=(",", ":")) + chr(10))

        for raw in sys.stdin:
            message = json.loads(raw)
            log(message)
            method = message.get("method")
            ident = message.get("id")
            params = message.get("params") or {}
            if method == "initialize":
                send({"id": ident, "result": {"platformFamily": "unix", "platformOs": "macos"}})
            elif method == "config/read":
                send({"id": ident, "result": {"config": {"mcp_servers": {}}}})
            elif method == "thread/start":
                threads += 1
                thread = "00000000-0000-0000-0000-%012d" % threads
                send({"id": ident, "result": {"thread": {"id": thread}, "model": "mock"}})
            elif method == "thread/resume":
                send({"id": ident, "result": {"thread": {"id": params["threadId"]}, "model": "mock"}})
            elif method == "turn/start":
                turns += 1
                thread = params["threadId"]
                turn = "00000000-0000-0000-0001-%012d" % turns
                prompt = (((params.get("input") or [{}])[0]).get("text") or "").lower()
                if "draft one" in prompt:
                    draft = "draft-one"
                elif "draft two" in prompt:
                    draft = "draft-two"
                else:
                    draft = "draft-%d" % turns
                send({"method": "item/agentMessage/delta", "params": {"threadId": thread, "turnId": turn, "itemId": "item-%d" % turns, "delta": draft}})
                send({"id": ident, "result": {"turn": {"id": turn}}})
                if "tool" in prompt:
                    if "read-tool" in prompt:
                        arguments = {"kind": "read_file", "path": TOOL_FOLDER + "/review.txt"}
                    else:
                        arguments = {"kind": "command", "executable": "/bin/echo", "arguments": ["hello"], "working_directory": TOOL_FOLDER}
                    tool_id = "tool-%d" % turns
                    tool_context[tool_id] = (thread, turn)
                    send({"id": tool_id, "method": "item/tool/call", "params": {"threadId": thread, "turnId": turn, "tool": "gulls_local_action", "arguments": arguments}})
                elif "approval" in prompt:
                    send({"id": "native-1", "method": "item/commandExecution/requestApproval", "params": {"threadId": thread, "turnId": turn, "command": "echo test"}})
                    send({"id": "unknown-1", "method": "item/unknown/requestApproval", "params": {"threadId": thread, "turnId": turn}})
                else:
                    send({"method": "turn/completed", "params": {"threadId": thread, "turnId": turn, "turn": {"id": turn, "status": "completed"}}})
            elif method == "turn/interrupt":
                send({"id": ident, "result": {"ok": True}})
            elif ident is not None and method is None:
                if str(ident).startswith("tool-"):
                    thread, turn = tool_context[str(ident)]
                    send({"method": "item/completed", "params": {"threadId": thread, "turnId": turn, "item": {"type": "agentMessage", "id": "final-%s" % ident, "phase": "final_answer", "text": "Read tool completed"}}})
                    send({"method": "turn/completed", "params": {"threadId": thread, "turnId": turn, "turn": {"id": turn, "status": "completed"}}})
                else:
                    send({"id": ident, "result": {"ok": True}})
        """
        try Data(script.utf8).write(to: executable, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
        return Fixture(server: CodexAppServer(executableURL: executable), log: log, directory: directory)
    }

    private func makeConfig(profileID: String = "one") throws -> GullsConfig {
        let suite = "codex-coordinator-config-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
        let context = FileManager.default.temporaryDirectory.appendingPathComponent(suite, isDirectory: true)
        let config = GullsConfig(profileID: profileID, defaults: defaults, tokenStore: MemoryTokens())
        config.apiURL = "https://messages.example.test"
        config.agentHandle = "@\(profileID):gulls.ai"
        config.contextDir = context.path
        config.token = "test-token"
        config.codexEnabled = true
        return config
    }

    private func makeStore(profileID: String, coordinator: CodexExecutionCoordinator) throws -> CodexTaskStore {
        CodexTaskStore(config: try makeConfig(profileID: profileID), executor: coordinator)
    }

    private func makeTask(_ store: CodexTaskStore, goal: String, folder: URL? = nil) throws -> CodexTask {
        try store.create(goal: goal, workingDirectory: folder, cliExecutableURL: URL(fileURLWithPath: "/usr/bin/true"))
    }

    private func waitUntil(_ condition: @escaping () -> Bool) async -> Bool {
        for _ in 0..<80 {
            if condition() { return true }
            try? await Task.sleep(for: .milliseconds(50))
        }
        return false
    }

    private func readLog(_ url: URL) throws -> [[String: Any]] {
        guard let data = try? Data(contentsOf: url), !data.isEmpty else { return [] }
        return try data.split(separator: 0x0A).map { try XCTUnwrap(JSONSerialization.jsonObject(with: Data($0)) as? [String: Any]) }
    }

    private func readActionResult(id: String, origin: URL) throws -> LocalActionResult {
        let url = origin.appendingPathComponent("results", isDirectory: true).appendingPathComponent("\(id).json")
        return try JSONDecoder().decode(LocalActionResult.self, from: Data(contentsOf: url))
    }

    private func pythonString(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'") + "'"
    }
}
