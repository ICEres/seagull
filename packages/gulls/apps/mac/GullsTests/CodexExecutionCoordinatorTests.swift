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
        XCTAssertEqual(store.tasks.first?.execution?.status, .uncertain)
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

    func testQueuedTaskWaitsForReviewedOperationBeforeStarting() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let config = try makeConfig()
        let suite = "codex-fifo-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
        let control = LocalControlStore(config: config, defaults: defaults)
        control.enabled = true
        control.addFolder(fixture.directory)
        let coordinator = CodexExecutionCoordinator(server: fixture.server)
        let store = CodexTaskStore(config: config, executor: coordinator, localControl: control)
        let first = try makeTask(store, goal: "tool", folder: fixture.directory)
        let second = try makeTask(store, goal: "draft", folder: fixture.directory)
        let running = Task { try? await store.run(first) }

        let firstQueued = await waitUntil { control.pendingRequests.count == 1 }
        XCTAssertTrue(firstQueued)
        try await store.run(second)
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(try readLog(fixture.log).filter { $0["method"] as? String == "turn/start" }.count, 1)
        XCTAssertEqual(store.tasks.first { $0.id == second.id }?.execution?.status, .queued)

        let request = try XCTUnwrap(control.pendingRequests.first)
        await control.approve(request)
        let bothCompleted = await waitUntil {
            store.tasks.first { $0.id == first.id }?.execution?.status == .draftReady
                && store.tasks.first { $0.id == second.id }?.execution?.status == .draftReady
        }
        XCTAssertTrue(bothCompleted)
        XCTAssertEqual(try readLog(fixture.log).filter { $0["method"] as? String == "turn/start" }.count, 2)
        running.cancel()
    }

    func testThreeTurnsKeepOneConversationThreadAndImmutableArtifacts() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let config = try makeConfig()
        let store = CodexTaskStore(config: config, executor: CodexExecutionCoordinator(server: fixture.server))
        let first = try makeConversationTask(store, goal: "draft one", messageID: "message-1")

        try await store.run(first)
        let firstCompleted = await waitUntil { store.tasks.first { $0.id == first.id }?.execution?.status == .draftReady }
        XCTAssertTrue(firstCompleted)
        let firstThread = try XCTUnwrap(store.tasks.first { $0.id == first.id }?.execution?.codexThreadID)
        let secondInput = try XCTUnwrap(store.tasks.first { $0.id == first.id })
        try await store.run(secondInput, followUp: "follow up one")
        let secondCompleted = await waitUntil { store.tasks.contains { $0.request.goal == "follow up one" && $0.execution?.status == .draftReady } }
        XCTAssertTrue(secondCompleted)
        let second = try XCTUnwrap(store.tasks.first { $0.request.goal == "follow up one" })
        try await store.run(second, followUp: "follow up two")
        let thirdCompleted = await waitUntil { store.tasks.contains { $0.request.goal == "follow up two" && $0.execution?.status == .draftReady } }
        XCTAssertTrue(thirdCompleted)

        let turns = store.tasks.filter { $0.execution?.status == .draftReady }
        XCTAssertEqual(turns.count, 3)
        XCTAssertEqual(Set(turns.compactMap { $0.execution?.codexThreadID }), Set([firstThread]))
        for task in turns {
            XCTAssertTrue(FileManager.default.fileExists(atPath: taskDirectory(task, in: store).appendingPathComponent("request.json").path))
            XCTAssertTrue(FileManager.default.fileExists(atPath: taskDirectory(task, in: store).appendingPathComponent("result.json").path))
        }
        let messages = try readLog(fixture.log)
        XCTAssertEqual(messages.filter { $0["method"] as? String == "thread/start" }.count, 1)
        XCTAssertEqual(messages.filter { $0["method"] as? String == "thread/resume" }.count, 2)
    }

    func testIncomingMessagesShareThreadAndConfirmedOwnerReplyIsIncludedOnce() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let config = try makeConfig()
        let store = CodexTaskStore(config: config, executor: CodexExecutionCoordinator(server: fixture.server))
        let ownerReply = CodexContextMessage(id: "owner-reply-1", sender: "owner",
                                             content: "Confirmed owner reply: keep the answer private.", createdAt: nil)
        let first = try makeConversationTask(store, goal: "draft one", messageID: "incoming-1",
                                              messages: [ownerReply])
        let second = try makeConversationTask(store, goal: "draft two", messageID: "incoming-2",
                                               messages: [ownerReply])
        let third = try makeConversationTask(store, goal: "draft three", messageID: "incoming-3",
                                              messages: [ownerReply])

        try await store.run(first)
        let firstReady = await waitUntil { store.tasks.first { $0.id == first.id }?.execution?.status == .draftReady }
        XCTAssertTrue(firstReady)
        try await store.run(try XCTUnwrap(store.tasks.first { $0.id == second.id }))
        let secondReady = await waitUntil { store.tasks.first { $0.id == second.id }?.execution?.status == .draftReady }
        XCTAssertTrue(secondReady)
        try await store.run(try XCTUnwrap(store.tasks.first { $0.id == third.id }))
        let thirdReady = await waitUntil { store.tasks.first { $0.id == third.id }?.execution?.status == .draftReady }
        XCTAssertTrue(thirdReady)

        XCTAssertEqual(store.tasks.first { $0.id == first.id }?.result?.content, "draft-one")
        XCTAssertEqual(store.tasks.first { $0.id == second.id }?.result?.content, "draft-two")
        XCTAssertEqual(store.tasks.first { $0.id == third.id }?.result?.content, "draft-3")

        let messages = try readLog(fixture.log)
        let starts = messages.filter { $0["method"] as? String == "turn/start" }
        XCTAssertEqual(starts.count, 3)
        XCTAssertEqual(messages.filter { $0["method"] as? String == "thread/start" }.count, 1)
        XCTAssertEqual(messages.filter { $0["method"] as? String == "thread/resume" }.count, 2)
        let inputs = starts.map { message -> String in
            let params = message["params"] as? [String: Any]
            let items = params?["input"] as? [[String: Any]] ?? []
            return items.compactMap { $0["text"] as? String }.joined(separator: "\n")
        }
        XCTAssertEqual(inputs.filter { $0.contains(ownerReply.content) }.count, 1)
        XCTAssertFalse(inputs.dropFirst().contains { $0.contains(ownerReply.content) })
        XCTAssertFalse(inputs.dropFirst().contains { $0.contains("draft-one") || $0.contains("draft-two") })
    }

    func testGlobalCapacityAllowsTwoGullsButQueuesTheThird() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let coordinator = CodexExecutionCoordinator(server: fixture.server)
        var stores: [CodexTaskStore] = []
        var controls: [LocalControlStore] = []
        var tasks: [CodexTask] = []
        for (index, profileID) in ["one", "two", "three"].enumerated() {
            let config = try makeConfig(profileID: profileID)
            let suite = "codex-capacity-\(UUID().uuidString)"
            let defaults = UserDefaults(suiteName: suite)!
            addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
            let control = LocalControlStore(config: config, defaults: defaults)
            control.enabled = true
            control.addFolder(fixture.directory)
            let store = CodexTaskStore(config: config, executor: coordinator, localControl: control)
            stores.append(store)
            controls.append(control)
            let task = try makeTask(store, goal: "tool-\(index)", folder: fixture.directory)
            tasks.append(task)
        }
        let runs = tasks.map { task in
            let store = stores[tasks.firstIndex { $0.id == task.id }!]
            return Task { try? await store.run(task) }
        }

        let firstTwoQueued = await waitUntil { controls[0].pendingRequests.count == 1 && controls[1].pendingRequests.count == 1 }
        XCTAssertTrue(firstTwoQueued)
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(try readLog(fixture.log).filter { $0["method"] as? String == "turn/start" }.count, 2)
        XCTAssertEqual(stores[2].tasks.first?.execution?.status, .queued)

        await controls[0].approve(try XCTUnwrap(controls[0].pendingRequests.first))
        await controls[1].approve(try XCTUnwrap(controls[1].pendingRequests.first))
        let thirdQueued = await waitUntil { controls[2].pendingRequests.count == 1 }
        XCTAssertTrue(thirdQueued)
        await controls[2].approve(try XCTUnwrap(controls[2].pendingRequests.first))
        let allCompleted = await waitUntil {
            stores.allSatisfy { $0.tasks.first?.execution?.status == .draftReady }
        }
        XCTAssertTrue(allCompleted)
        runs.forEach { $0.cancel() }
    }

    func testUncertainDispatchIsPersistedAndNeverRequeued() async throws {
        let fixture = try makeFixture()
        let config = try makeConfig()
        let coordinator = CodexExecutionCoordinator(server: fixture.server)
        let store = CodexTaskStore(config: config, executor: coordinator)
        let task = try makeTask(store, goal: "uncertain")
        try? await store.run(task)

        let uncertain = await waitUntil { store.tasks.first?.execution?.status == .uncertain }
        XCTAssertTrue(uncertain)
        let replacementServer = CodexAppServer(executableURL: fixture.server.executableURLForReadiness!)
        defer { replacementServer.shutdown() }
        let recoveryCoordinator = CodexExecutionCoordinator(server: replacementServer)
        let replacement = CodexTaskStore(config: config, executor: recoveryCoordinator)
        let uncertainTask = try XCTUnwrap(replacement.tasks.first)
        XCTAssertEqual(uncertainTask.execution?.status, .uncertain)
        XCTAssertNil(replacement.nextQueuedTask)

        try await recoveryCoordinator.checkStatus(uncertainTask, in: replacement)
        let recovered = await waitUntil { replacement.tasks.first?.execution?.status == .draftReady }
        XCTAssertTrue(recovered)
        XCTAssertEqual(replacement.tasks.first?.result?.content, "Recovered after dispatch")
        XCTAssertEqual(try readLog(fixture.log).filter { $0["method"] as? String == "turn/start" }.count, 1)
    }

    func testExplicitPublicToolSubmitsOnlyPublicContent() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let config = try makeConfig()
        let context = URL(fileURLWithPath: config.contextDir)
        try FileManager.default.createDirectory(at: context, withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        cleanup.append(context)
        let source = context.appendingPathComponent("source.md")
        try Data("Private owner instructions and incoming message.".utf8).write(to: source)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: source.path)
        let store = CodexTaskStore(config: config, executor: CodexExecutionCoordinator(server: fixture.server))
        let task = try store.create(goal: "submit-public-empty", workingDirectory: nil,
            deliveryID: "source-delivery", threadID: "conversation", contextPath: source.path,
            authorizeReply: true, cliExecutableURL: URL(fileURLWithPath: "/usr/bin/true"))
        try await store.run(task)
        let completed = await waitUntil { store.tasks.first?.execution?.status == .draftReady }
        XCTAssertTrue(completed)
        let result = try XCTUnwrap(store.tasks.first)
        XCTAssertEqual(result.reply?.content, "Public answer only.")
        XCTAssertEqual(result.reply?.status, .readyToSend)
        XCTAssertNotEqual(result.reply?.content, result.result?.content)
        XCTAssertNil(result.reply?.messageID)
        let messages = try readLog(fixture.log)
        let start = try XCTUnwrap(messages.first { $0["method"] as? String == "thread/start" })
        let params = try XCTUnwrap(start["params"] as? [String: Any])
        let registered = try XCTUnwrap(params["dynamicTools"] as? [[String: Any]])
        XCTAssertEqual(Set(registered.compactMap { $0["name"] as? String }), ["gulls_reply", "gulls_local_action"])
    }

    func testPublicToolRejectsTaskWithoutDelegation() async throws {
        let fixture = try makeFixture()
        defer { fixture.server.shutdown() }
        let store = CodexTaskStore(config: try makeConfig(), executor: CodexExecutionCoordinator(server: fixture.server))
        let task = try makeTask(store, goal: "submit-public")
        try await store.run(task)
        let completed = await waitUntil { store.tasks.first?.execution?.status == .draftReady }
        XCTAssertTrue(completed)
        XCTAssertNil(store.tasks.first?.reply)
        let response = try XCTUnwrap(try readLog(fixture.log).first { $0["id"] as? String == "tool-reply-1" })
        XCTAssertEqual((response["result"] as? [String: Any])?["success"] as? Bool, false)
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
        RECOVERY = \(pythonString(directory.appendingPathComponent("recovery.json").path))
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
            elif method == "thread/read":
                with open(RECOVERY, "r", encoding="utf-8") as handle:
                    send({"id": ident, "result": {"thread": json.load(handle)}})
            elif method == "turn/start":
                turns += 1
                thread = params["threadId"]
                turn = "00000000-0000-0000-0001-%012d" % turns
                prompt = (((params.get("input") or [{}])[0]).get("text") or "").lower()
                if "uncertain" in prompt:
                    input_text = ((params.get("input") or [{}])[0]).get("text") or ""
                    with open(RECOVERY, "w", encoding="utf-8") as handle:
                        json.dump({
                            "id": thread,
                            "turns": [{
                                "id": turn,
                                "status": "completed",
                                "itemsView": "full",
                                "items": [
                                    {"id": "recovery-user", "type": "userMessage",
                                     "content": [{"type": "text", "text": input_text}]},
                                    {"id": "recovery-agent", "type": "agentMessage",
                                     "phase": "final_answer", "text": "Recovered after dispatch"}
                                ]
                            }]
                        }, handle)
                    sys.exit(0)
                if "draft one" in prompt:
                    draft = "draft-one"
                elif "draft two" in prompt:
                    draft = "draft-two"
                else:
                    draft = "draft-%d" % turns
                if "submit-public-empty" not in prompt:
                    send({"method": "item/agentMessage/delta", "params": {"threadId": thread, "turnId": turn, "itemId": "item-%d" % turns, "delta": draft}})
                send({"id": ident, "result": {"turn": {"id": turn}}})
                if "submit-public" in prompt:
                    tool_id = "tool-reply-%d" % turns
                    tool_context[tool_id] = (thread, turn)
                    send({"id": tool_id, "method": "item/tool/call", "params": {"threadId": thread, "turnId": turn if "wrong-turn" not in prompt else "wrong", "tool": "gulls_reply", "arguments": {"content": "Public answer only."}}})
                elif "tool" in prompt:
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
                    if "submit-public-empty" not in prompt:
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

    private func taskDirectory(_ task: CodexTask, in store: CodexTaskStore) -> URL {
        store.tasksDirectory.appendingPathComponent(task.id, isDirectory: true)
    }

    private func makeConversationTask(
        _ store: CodexTaskStore,
        goal: String,
        messageID: String,
        messages: [CodexContextMessage] = [CodexContextMessage(id: "message", sender: "other", content: "Message", createdAt: nil)]
    ) throws -> CodexTask {
        let base = URL(fileURLWithPath: store.config.contextDir, isDirectory: true)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let source = base.appendingPathComponent("\(messageID).md")
        try Data("Conversation source".utf8).write(to: source)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: source.path)
        return try store.create(
            goal: goal,
            workingDirectory: nil,
            deliveryID: messageID,
            threadID: "conversation-thread",
            contextPath: source.path,
            sourceMessageID: messageID,
            ownerRequestID: "owner-\(messageID)",
            conversationMessages: messages,
            cliExecutableURL: URL(fileURLWithPath: "/usr/bin/true")
        )
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
