import CryptoKit
import SQLite3
import XCTest
@testable import Gulls

@MainActor
final class CodexTaskStoreTests: XCTestCase {
    private final class MemoryTokens: GullsTokenStore {
        func token(for profileID: String) -> String? { nil }
        func legacyToken() -> String? { nil }
        func setToken(_ token: String, for profileID: String) -> Bool { true }
    }

    private func config(profileID: String = "one", context: URL? = nil) throws -> GullsConfig {
        let name = "codex-tasks-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        let directory = context ?? FileManager.default.temporaryDirectory.appendingPathComponent(name, isDirectory: true)
        if context == nil { addTeardownBlock { try? FileManager.default.removeItem(at: directory) } }
        let config = GullsConfig(profileID: profileID, defaults: defaults, tokenStore: MemoryTokens())
        config.apiURL = "https://messages.example.test"
        config.agentHandle = "@\(profileID):gulls.ai"
        config.contextDir = directory.path
        config.token = "test-connector-secret"
        config.codexEnabled = true
        return config
    }

    private func taskDirectory(_ task: CodexTask, in store: CodexTaskStore) -> URL {
        store.tasksDirectory.appendingPathComponent(task.id, isDirectory: true)
    }

    private func create(_ store: CodexTaskStore, deliveryID: String? = nil, folder: URL? = nil) throws -> CodexTask {
        var contextPath: String?
        if deliveryID != nil {
            let base = URL(fileURLWithPath: store.config.contextDir, isDirectory: true)
            try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let source = base.appendingPathComponent("delivery.md")
            try Data("Private owner guidance and untrusted message.".utf8).write(to: source)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: source.path)
            contextPath = source.path
        }
        return try store.create(goal: "Draft an answer & keep it private.", workingDirectory: folder,
                                deliveryID: deliveryID, threadID: deliveryID == nil ? nil : "thread-one",
                                contextPath: contextPath, cliExecutableURL: URL(fileURLWithPath: "/Applications/Gulls.app/Contents/Resources/gulls"))
    }

    private func writeResult(_ task: CodexTask, in store: CodexTaskStore,
                             changing: (inout [String: Any]) -> Void = { _ in }) throws {
        _ = try store.selectRoute(.external, for: task)
        let directory = taskDirectory(task, in: store)
        let request = try Data(contentsOf: directory.appendingPathComponent("request.json"))
        var object: [String: Any] = [
            "version": 1, "task_id": task.id, "profile_id": task.request.profileID,
            "gull_handle": task.request.gullHandle, "connection_revision": task.request.connectionRevision,
            "request_sha256": SHA256.hash(data: request).map { String(format: "%02x", $0) }.joined(),
            "content": "A proposed reply, not a sent message.", "completed_at": "2026-10-21T09:00:00.123Z"
        ]
        changing(&object)
        let resultURL = directory.appendingPathComponent("result.json")
        try JSONSerialization.data(withJSONObject: object).write(to: resultURL)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: resultURL.path)
        store.refresh()
    }

    private func replacePersistedSession(_ record: CodexSessionDatabase.Record,
                                         forTaskID taskID: String, at url: URL) throws {
        var handle: OpaquePointer?
        guard sqlite3_open_v2(url.path, &handle, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK,
              let handle else {
            defer { sqlite3_close(handle) }
            throw NSError(domain: "CodexTaskStoreTests", code: 1)
        }
        defer { sqlite3_close(handle) }

        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(handle,
                                 "UPDATE codex_sessions SET record = ? WHERE task_id = ?",
                                 -1, &statement, nil) == SQLITE_OK,
              let statement else {
            throw NSError(domain: "CodexTaskStoreTests", code: 2)
        }
        defer { sqlite3_finalize(statement) }

        let data = try JSONEncoder().encode(record)
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        let bindResult = data.withUnsafeBytes { bytes in
            sqlite3_bind_blob(statement, 1, bytes.baseAddress, Int32(data.count), transient)
        }
        guard bindResult == SQLITE_OK,
              sqlite3_bind_text(statement, 2, taskID, -1, transient) == SQLITE_OK,
              sqlite3_step(statement) == SQLITE_DONE else {
            throw NSError(domain: "CodexTaskStoreTests", code: 3)
        }
    }

    func testCapabilityIsOffByDefaultAndDoesNotChangeConnectionRevision() {
        let name = "codex-config-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        defer { defaults.removePersistentDomain(forName: name) }
        let one = GullsConfig(profileID: "one", defaults: defaults, tokenStore: MemoryTokens())
        let two = GullsConfig(profileID: "two", defaults: defaults, tokenStore: MemoryTokens())
        XCTAssertFalse(one.codexEnabled)
        let revision = one.connectionRevision
        one.codexEnabled = true
        XCTAssertEqual(one.connectionRevision, revision)
        XCTAssertFalse(two.codexEnabled)
        XCTAssertTrue(GullsConfig(profileID: "one", defaults: defaults, tokenStore: MemoryTokens()).codexEnabled)
    }

    func testFolderIsOptionalAndSecretsStayOutOfHandoffAndLink() throws {
        let config = try config()
        var opened: URL?
        let store = CodexTaskStore(config: config, openURL: { opened = $0; return true }, copyHandoff: { _ in })
        let task = try create(store)
        let directory = taskDirectory(task, in: store)
        let requestData = try Data(contentsOf: directory.appendingPathComponent("request.json"))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: requestData) as? [String: Any])
        XCTAssertNil(object["working_directory"])
        XCTAssertNil(object["delivery_id"])
        XCTAssertEqual(task.request.profileID, config.profileID)
        let handoff = try String(contentsOf: directory.appendingPathComponent("handoff.md"))
        XCTAssertFalse(handoff.contains(config.token))
        XCTAssertTrue(handoff.contains("local-action request"))
        XCTAssertTrue(handoff.contains("codex result"))
        XCTAssertEqual((try FileManager.default.attributesOfItem(atPath: directory.path)[.posixPermissions] as? NSNumber)?.intValue, 0o700)
        XCTAssertEqual((try FileManager.default.attributesOfItem(atPath: directory.appendingPathComponent("request.json").path)[.posixPermissions] as? NSNumber)?.intValue, 0o600)
        try store.open(task)
        let components = try XCTUnwrap(opened.flatMap { URLComponents(url: $0, resolvingAgainstBaseURL: false) })
        XCTAssertEqual(components.scheme, "codex")
        XCTAssertEqual(components.host, "new")
        XCTAssertFalse(components.queryItems!.contains { $0.name == "path" })
        XCTAssertFalse(opened!.absoluteString.contains(config.token))
        XCTAssertFalse(components.queryItems!.contains { $0.value?.contains(task.request.goal) == true })
        XCTAssertEqual(CodexTaskStore(config: config).tasks.map(\.id), [task.id], "handoffs survive app restarts")
    }

    func testWorkingFolderIsTaskScopedAndURLEncoded() throws {
        let config = try config()
        let store = CodexTaskStore(config: config)
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("codex a & b # \(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let task = try create(store, folder: folder)
        let components = try XCTUnwrap(URLComponents(url: store.deepLink(for: task), resolvingAgainstBaseURL: false))
        XCTAssertEqual(components.queryItems?.first { $0.name == "path" }?.value, folder.resolvingSymlinksInPath().path)
        let next = try create(store)
        XCTAssertNil(next.request.workingDirectory, "a previous task must not become a Gull project binding")
        XCTAssertEqual(URL(fileURLWithPath: config.contextDir).resolvingSymlinksInPath().path,
                       store.tasksDirectory.deletingLastPathComponent().path)
        XCTAssertThrowsError(try create(store, folder: folder.appendingPathComponent("missing")))
    }

    func testMessageSnapshotAndDraftStayBoundToOriginalDelivery() throws {
        let config = try config()
        let store = CodexTaskStore(config: config)
        let task = try create(store, deliveryID: "delivery-one")
        let snapshot = try XCTUnwrap(task.request.contextPath)
        let original = URL(fileURLWithPath: config.contextDir).appendingPathComponent("delivery.md")
        try Data("Changed source after handoff".utf8).write(to: original)
        XCTAssertEqual(try String(contentsOfFile: snapshot), "Private owner guidance and untrusted message.")
        try writeResult(task, in: store)
        let ready = try XCTUnwrap(store.latestTask(for: "delivery-one"))
        XCTAssertEqual(try store.draft(for: ready, deliveryID: "delivery-one"), "A proposed reply, not a sent message.")
        XCTAssertThrowsError(try store.draft(for: ready, deliveryID: "delivery-two"))
        let stale = ready
        config.token = "replacement-connector-secret"
        XCTAssertThrowsError(try store.draft(for: stale, deliveryID: "delivery-one"))
        XCTAssertNil(store.latestTask(for: "delivery-one"))
        store.refresh()
        XCTAssertTrue(store.tasks.isEmpty)
    }

    func testAnotherGullCannotLoadOrApplyTaskEvenWithSharedContextDirectory() throws {
        let one = try config()
        let store = CodexTaskStore(config: one)
        let task = try create(store, deliveryID: "delivery-one")
        try writeResult(task, in: store)
        let ready = try XCTUnwrap(store.latestTask(for: "delivery-one"))
        let two = try config(profileID: "two", context: URL(fileURLWithPath: one.contextDir))
        let otherStore = CodexTaskStore(config: two)
        XCTAssertTrue(otherStore.tasks.isEmpty)
        XCTAssertThrowsError(try otherStore.draft(for: ready, deliveryID: "delivery-one"))
        XCTAssertThrowsError(try otherStore.open(ready))
    }

    func testInvalidIdentityDigestAndContentCannotBecomeDraft() throws {
        let store = CodexTaskStore(config: try config())
        let task = try create(store, deliveryID: "delivery-one")
        let mutations: [(inout [String: Any]) -> Void] = [
            { $0["profile_id"] = "another-profile" },
            { $0["gull_handle"] = "@another:gulls.ai" },
            { $0["connection_revision"] = "stale" },
            { $0["request_sha256"] = String(repeating: "0", count: 64) },
            { $0["content"] = "  \n" },
            { $0["content"] = String(repeating: "a", count: CodexTaskStore.maximumDraftBytes + 1) },
            { $0["codex_thread_id"] = "../another-thread" }
        ]
        for mutation in mutations {
            try writeResult(task, in: store, changing: mutation)
            let invalid = try XCTUnwrap(store.latestTask(for: "delivery-one"))
            XCTAssertNil(invalid.result)
            XCTAssertNotNil(invalid.resultError)
            XCTAssertThrowsError(try store.draft(for: invalid, deliveryID: "delivery-one"))
        }
    }

    func testReplacedRequestAndResultSymlinkCannotBeUsed() throws {
        let store = CodexTaskStore(config: try config())
        let task = try create(store, deliveryID: "delivery-one")
        try writeResult(task, in: store)
        let ready = try XCTUnwrap(store.latestTask(for: "delivery-one"))
        let directory = taskDirectory(task, in: store)
        let requestURL = directory.appendingPathComponent("request.json")
        var data = try Data(contentsOf: requestURL)
        data.append(Data("\n".utf8))
        try data.write(to: requestURL)
        XCTAssertThrowsError(try store.draft(for: ready, deliveryID: "delivery-one"), "even whitespace changes the exact request hash")
        try FileManager.default.removeItem(at: directory.appendingPathComponent("result.json"))
        try FileManager.default.createSymbolicLink(at: directory.appendingPathComponent("result.json"), withDestinationURL: requestURL)
        store.refresh()
        XCTAssertNil(store.latestTask(for: "delivery-one"))
        XCTAssertNotNil(store.lastError)
    }

    func testExecutionUpdatesPinExactRequestDigestWithoutReadingMessageSnapshot() throws {
        let config = try config()
        let store = CodexTaskStore(config: config)
        let task = try create(store, deliveryID: "delivery-one")
        let messageSnapshot = URL(fileURLWithPath: try XCTUnwrap(task.request.contextPath))
        try FileManager.default.removeItem(at: messageSnapshot)

        try store.updateExecution(CodexTaskExecution(status: .working), for: task)
        let requestURL = taskDirectory(task, in: store).appendingPathComponent("request.json")
        var requestData = try Data(contentsOf: requestURL)
        requestData.append(Data("\n".utf8))
        try requestData.write(to: requestURL)

        store.refresh()
        XCTAssertTrue(store.tasks.isEmpty, "A cached execution must not survive a request digest change")
        XCTAssertNotNil(store.lastError)
    }

    func testLiveDraftRequiresBoundedContentAndISOCompletionDate() throws {
        let store = CodexTaskStore(config: try config())
        let task = try create(store)

        var invalid = CodexTaskExecution(status: .draftReady, output: " \n", completedAt: "2026-10-21T09:00:00Z")
        XCTAssertThrowsError(try store.updateExecution(invalid, for: task))

        invalid.output = String(repeating: "x", count: CodexTaskStore.maximumDraftBytes + 1)
        XCTAssertThrowsError(try store.updateExecution(invalid, for: task))

        invalid.output = "A draft"
        invalid.completedAt = "not-a-date"
        XCTAssertThrowsError(try store.updateExecution(invalid, for: task))

        invalid.completedAt = "2026-10-21T09:00:00Z"
        XCTAssertNoThrow(try store.updateExecution(invalid, for: task))
        XCTAssertEqual(store.tasks.first?.result?.content, "A draft")
    }

    func testTamperedNativeResultNeverBecomesDraftEvenWithCachedDraftReadyExecution() throws {
        let store = CodexTaskStore(config: try config())
        let task = try create(store, deliveryID: "delivery-one")
        let routed = try store.selectRoute(.embedded, for: task)
        let threadID = UUID().uuidString.lowercased()
        let execution = CodexTaskExecution(status: .draftReady, output: "Original draft",
                                            codexThreadID: threadID, turnID: "turn-1",
                                            completedAt: "2026-10-21T09:00:00Z")
        try store.updateExecution(execution, for: routed)

        let resultURL = taskDirectory(task, in: store).appendingPathComponent("result.json")
        var tampered = try JSONSerialization.jsonObject(with: Data(contentsOf: resultURL)) as! [String: Any]
        tampered["content"] = "Tampered draft"
        try JSONSerialization.data(withJSONObject: tampered).write(to: resultURL)
        store.refresh()

        let refreshed = try XCTUnwrap(store.latestTask(for: "delivery-one"))
        XCTAssertNil(refreshed.result)
        XCTAssertNotNil(refreshed.resultError)
        XCTAssertThrowsError(try store.draft(for: refreshed, deliveryID: "delivery-one"))
    }

    func testDraftReadyExecutionRecoversImmutableResultAfterPublicationCrash() throws {
        let config = try config()
        let task: CodexTask
        do {
            let store = CodexTaskStore(config: config)
            task = try create(store, deliveryID: "delivery-one")
            let routed = try store.selectRoute(.embedded, for: task)
            let execution = CodexTaskExecution(status: .draftReady, output: "Recovered draft",
                                                codexThreadID: UUID().uuidString.lowercased(), turnID: "turn-1",
                                                completedAt: "2026-10-21T09:00:00Z")
            try store.updateExecution(execution, for: routed)
            try FileManager.default.removeItem(at: taskDirectory(task, in: store).appendingPathComponent("result.json"))
        }

        let restored = CodexTaskStore(config: config)
        let recovered = try XCTUnwrap(restored.latestTask(for: "delivery-one"))
        XCTAssertEqual(recovered.result?.content, "Recovered draft")
        XCTAssertNil(recovered.resultError)
        XCTAssertTrue(FileManager.default.fileExists(atPath: taskDirectory(task, in: restored)
            .appendingPathComponent("result.json").path))
    }

    func testPreparedPublicationIsRecoveredOnNextLoad() throws {
        let config = try config()
        let task: CodexTask
        do {
            let store = CodexTaskStore(config: config)
            task = try create(store, deliveryID: "delivery-one")
            var work = try XCTUnwrap(task.work)
            work.publication = .prepared
            let database = try CodexSessionDatabase(url: store.tasksDirectory.appendingPathComponent("sessions.sqlite3"))
            try database.saveWork(work)
        }

        let restored = CodexTaskStore(config: config)
        let recovered = try XCTUnwrap(restored.latestTask(for: "delivery-one"))
        XCTAssertEqual(recovered.work?.publication, .ready)
        XCTAssertNil(recovered.resultError)
    }

    func testTerminalDraftDispositionCannotBeReusedOrRedirected() throws {
        let store = CodexTaskStore(config: try config())
        let task = try create(store, deliveryID: "delivery-one")
        try writeResult(task, in: store)
        let ready = try XCTUnwrap(store.latestTask(for: "delivery-one"))

        XCTAssertEqual(try store.draft(for: ready, deliveryID: "delivery-one"), "A proposed reply, not a sent message.")
        try store.updateDraftDisposition(.sent, for: ready, deliveryID: "delivery-one")

        XCTAssertThrowsError(try store.updateDraftDisposition(.available, for: ready, deliveryID: "delivery-one"))
        XCTAssertThrowsError(try store.updateDraftDisposition(.used, for: ready, deliveryID: "delivery-one"))
        XCTAssertThrowsError(try store.draft(for: ready, deliveryID: "delivery-two"))
        XCTAssertThrowsError(try store.updateDraftDisposition(.discarded, for: ready, deliveryID: "delivery-two"))
    }

    func testImportedExternalResultCannotBeReplacedByAnotherValidResult() throws {
        let store = CodexTaskStore(config: try config())
        let task = try create(store, deliveryID: "delivery-one")
        try writeResult(task, in: store)
        let ready = try XCTUnwrap(store.latestTask(for: "delivery-one"))
        XCTAssertEqual(ready.result?.content, "A proposed reply, not a sent message.")

        let resultURL = taskDirectory(task, in: store).appendingPathComponent("result.json")
        var changed = try JSONSerialization.jsonObject(with: Data(contentsOf: resultURL)) as! [String: Any]
        changed["content"] = "A different but otherwise valid reply."
        try JSONSerialization.data(withJSONObject: changed).write(to: resultURL)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: resultURL.path)
        store.refresh()

        let rejected = try XCTUnwrap(store.latestTask(for: "delivery-one"))
        XCTAssertNil(rejected.result)
        XCTAssertTrue(rejected.resultError?.contains("changed") == true)
        XCTAssertThrowsError(try store.draft(for: rejected, deliveryID: "delivery-one"))
    }

    func testActiveSessionRestoresAsInterruptedAndClearsApprovalFields() throws {
        let config = try config()
        let first = CodexTaskStore(config: config)
        let task = try create(first)
        let active = CodexTaskExecution(status: .needsApproval, codexThreadID: UUID().uuidString,
                                        turnID: "turn-1", approvalID: "approval-1",
                                        approvalSummary: "Run a command", approvalDetails: "echo test")
        try first.updateExecution(active, for: task)

        let restored = CodexTaskStore(config: config)
        let execution = try XCTUnwrap(restored.tasks.first?.execution)
        XCTAssertEqual(execution.status, .interrupted)
        XCTAssertEqual(execution.error, "Gulls restarted while Codex was working. Continue when you are ready.")
        XCTAssertNil(execution.approvalID)
        XCTAssertNil(execution.approvalSummary)
        XCTAssertNil(execution.approvalDetails)
    }

    func testSessionDatabaseRejectsIdentityAndDigestMismatches() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("codex-sessions-\(UUID().uuidString).sqlite3")
        defer { try? FileManager.default.removeItem(at: url) }
        let database = try CodexSessionDatabase(url: url)
        let execution = CodexTaskExecution(status: .working)
        let valid = CodexSessionDatabase.Record(taskID: "task-1", profileID: "profile-1",
                                                connectionRevision: "revision-1",
                                                requestDigest: String(repeating: "a", count: 64), execution: execution)
        XCTAssertNoThrow(try database.save(valid))
        XCTAssertThrowsError(try database.save(.init(taskID: "task-1", profileID: "profile-1",
                                                     connectionRevision: "revision-1", requestDigest: "bad",
                                                     execution: execution)))

        // Simulate a tampered row whose SQLite key still points at task-1 but
        // whose signed record claims to belong to task-2. The read path must
        // reject that identity mismatch instead of attaching it to task-1.
        try replacePersistedSession(
            .init(taskID: "task-2", profileID: "profile-1",
                  connectionRevision: "revision-1",
                  requestDigest: String(repeating: "a", count: 64), execution: execution),
            forTaskID: "task-1", at: url
        )
        XCTAssertThrowsError(try database.record(for: "task-1"))
    }

    func testContinuationUsesExactCodexThreadAndDisabledCapabilityCannotLaunch() throws {
        let config = try config()
        var opened: URL?
        let store = CodexTaskStore(config: config, openURL: { opened = $0; return true })
        let task = try create(store)
        let thread = UUID().uuidString.lowercased()
        try writeResult(task, in: store) { $0["codex_thread_id"] = thread }
        let ready = try XCTUnwrap(store.tasks.first)
        try store.open(ready)
        XCTAssertEqual(opened?.absoluteString, "codex://threads/\(thread)")
        config.codexEnabled = false
        XCTAssertThrowsError(try store.open(ready))
        XCTAssertThrowsError(try create(store))
    }

    func testTaskRootSymlinkAndForeignContextAreRejected() throws {
        let config = try config()
        let store = CodexTaskStore(config: config)
        _ = try create(store)
        let foreign = FileManager.default.temporaryDirectory.appendingPathComponent("foreign-\(UUID().uuidString).md")
        try Data("foreign context".utf8).write(to: foreign)
        defer { try? FileManager.default.removeItem(at: foreign) }
        XCTAssertThrowsError(try store.create(goal: "Reply", workingDirectory: nil, deliveryID: "delivery",
                                            contextPath: foreign.path, cliExecutableURL: URL(fileURLWithPath: "/gulls")))
        let elsewhere = URL(fileURLWithPath: config.contextDir).appendingPathComponent("elsewhere")
        try FileManager.default.createDirectory(at: elsewhere, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try FileManager.default.removeItem(at: store.tasksDirectory)
        try FileManager.default.createSymbolicLink(at: store.tasksDirectory, withDestinationURL: elsewhere)
        XCTAssertThrowsError(try create(store))
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: elsewhere.path).isEmpty)
    }

    func testBundledCLICompletesExactSwiftTaskWithoutSending() throws {
        let config = try config()
        let store = CodexTaskStore(config: config)
        let task = try create(store, deliveryID: "delivery-one")
        _ = try store.selectRoute(.external, for: task)
        let cli = try XCTUnwrap(GullsCLI.bundled())
        let process = Process()
        process.executableURL = cli.executableURL
        process.arguments = [
            "--api-url", config.apiURL, "--agent-handle", config.agentHandle,
            "--context-dir", config.contextDir, "--json", "codex", "result",
            "--profile-id", config.profileID, "--connection-revision", config.connectionRevision,
            "--content-file", "-", task.id
        ]
        process.environment = ["PATH": "/usr/bin:/bin", "SEAGULL_AGENT_ENV_FILE": "/dev/null"]
        let input = Pipe(), output = Pipe(), errors = Pipe()
        process.standardInput = input
        process.standardOutput = output
        process.standardError = errors
        try process.run()
        try input.fileHandleForWriting.write(contentsOf: Data("A local Codex result.\n".utf8))
        try input.fileHandleForWriting.close()
        process.waitUntilExit()
        let errorText = String(data: errors.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        XCTAssertEqual(process.terminationStatus, 0, errorText)
        store.refresh()
        let ready = try XCTUnwrap(store.latestTask(for: "delivery-one"))
        XCTAssertEqual(try store.draft(for: ready, deliveryID: "delivery-one"), "A local Codex result.\n")
        XCTAssertNil(ready.resultError)
    }

    // MARK: - Task preparation source and failure boundaries

    private func preparationCLI(
        context: URL,
        deliveryID: String = "delivery-history",
        contextFailure: String? = nil,
        threadStartedMarker: URL? = nil
    ) throws -> GullsCLI {
        let url = context.appendingPathComponent("gulls-preparation-fixture")
        try FileManager.default.createDirectory(at: context, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        // Test messages are fixed, single-line fixture text, so a shell
        // single-quoted diagnostic keeps the generated script argument-safe.
        let failure = contextFailure.map { "printf '%s' '\($0)' >&2; exit 1" } ?? ""
        let threadMarker = threadStartedMarker.map { "touch \"\($0.path)\"" } ?? ""
        let script = """
        #!/bin/bash
        if [ "$1" = "--json" ]; then shift; fi
        command="$1"
        case "$command" in
          history)
            if [ "${2:-}" = "summary" ]; then
              printf '%s' '{"total_deliveries":1,"pending_deliveries":1,"distinct_threads":1,"distinct_senders":1,"daily_received":[],"relationships":[]}'
            else
              printf '%s' '{"items":[{"delivery":{"delivery_id":"\(deliveryID)","message_id":"message-\(deliveryID)","thread_id":"thread-\(deliveryID)","sender_agent_id":"agent_alice","recipient_agent_id":"agent_one","status":"delivered","created_at":"2026-10-24T09:00:00Z"},"message":{"message_id":"message-\(deliveryID)","thread_id":"thread-\(deliveryID)","sender_agent_id":"agent_alice","sender_handle":"@alice:gulls.ai","content_inline":"Please review the deploy notes.","created_at":"2026-10-24T09:00:00Z"},"current_message":{"content_inline":"Please review the deploy notes."}}],"total":1,"sync_complete":true}'
            fi
            ;;
          open)
            \(failure)
            mkdir -p "$SEAGULL_AGENT_CONTEXT_DIR"
            printf '%s' '# prepared context' > "$SEAGULL_AGENT_CONTEXT_DIR/\(deliveryID).md"
            chmod 600 "$SEAGULL_AGENT_CONTEXT_DIR/\(deliveryID).md"
            printf '%s' '{"context_path":"'"$SEAGULL_AGENT_CONTEXT_DIR/\(deliveryID).md"'","delivery":{"delivery_id":"\(deliveryID)","status":"delivered"}}'
            ;;
          thread)
            \(threadMarker)
            sleep 0.35
            printf '%s' '{"thread_id":"thread-\(deliveryID)","messages":[{"message_id":"message-\(deliveryID)","thread_id":"thread-\(deliveryID)","sender_handle":"@alice:gulls.ai","content_inline":"Please review the deploy notes.","created_at":"2026-10-24T09:00:00Z"}]}'
            ;;
          *)
            printf '%s' '{}'
            ;;
        esac
        """
        try script.write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        return GullsCLI(executableURL: url)
    }

    func testPrepareTaskUsesHistoryOnlySourceItem() async throws {
        let config = try config()
        let context = URL(fileURLWithPath: config.contextDir, isDirectory: true)
        let cli = try preparationCLI(context: context)
        let inbox = InboxStore(cli: cli, config: config, notifier: Notifier())
        await inbox.history.loadInitial()
        XCTAssertTrue(inbox.items.isEmpty)
        let item = try XCTUnwrap(inbox.mergedItems.first)
        XCTAssertNotNil(inbox.history.item(id: item.id))
        let store = CodexTaskStore(config: config)

        let task = try await store.prepareTask(
            goal: "Draft a reply to this message.", workingDirectory: nil, cli: cli,
            inbox: inbox, item: item, sourceProfileID: config.profileID,
            sourceConnectionRevision: config.connectionRevision, ownerRequestID: "owner-history"
        )

        XCTAssertEqual(task.request.profileID, config.profileID)
        XCTAssertEqual(task.request.connectionRevision, config.connectionRevision)
        XCTAssertEqual(task.request.deliveryID, item.id)
        XCTAssertEqual(task.request.threadID, item.delivery.threadId)
        XCTAssertNotNil(task.request.contextPath)
        XCTAssertEqual(store.tasks.count, 1)
        XCTAssertNil(task.execution, "preparation must not dispatch model work")
    }

    func testPrepareTaskRetainsContextFailureReasonAndLeavesStoreEmpty() async throws {
        let config = try config()
        let context = URL(fileURLWithPath: config.contextDir, isDirectory: true)
        let reason = "authenticated local runtime instructions are unavailable"
        let cli = try preparationCLI(context: context, contextFailure: reason)
        let inbox = InboxStore(cli: cli, config: config, notifier: Notifier())
        await inbox.history.loadInitial()
        let item = try XCTUnwrap(inbox.mergedItems.first)
        let store = CodexTaskStore(config: config)

        do {
            _ = try await store.prepareTask(
                goal: "Draft a reply.", workingDirectory: nil, cli: cli,
                inbox: inbox, item: item, sourceProfileID: config.profileID,
                sourceConnectionRevision: config.connectionRevision, ownerRequestID: "owner-failure"
            )
            XCTFail("context preparation should fail")
        } catch let error as CodexTaskPreparationError {
            guard case .contextUnavailable(let message) = error else {
                return XCTFail("unexpected preparation error: \(error)")
            }
            XCTAssertTrue(message.contains(reason))
        }
        XCTAssertTrue(store.tasks.isEmpty)
        XCTAssertNil(store.lastError)
        XCTAssertNil(inbox.actionFailure)
    }

    func testPrepareTaskRejectsWrongCapturedIdentityBeforeCLI() async throws {
        let config = try config()
        let context = URL(fileURLWithPath: config.contextDir, isDirectory: true)
        let cli = try preparationCLI(context: context)
        let inbox = InboxStore(cli: cli, config: config, notifier: Notifier())
        await inbox.history.loadInitial()
        let item = try XCTUnwrap(inbox.mergedItems.first)
        let store = CodexTaskStore(config: config)

        do {
            _ = try await store.prepareTask(
                goal: "Draft a reply.", workingDirectory: nil, cli: cli,
                inbox: inbox, item: item, sourceProfileID: "wrong-profile",
                sourceConnectionRevision: config.connectionRevision, ownerRequestID: "owner-identity"
            )
            XCTFail("wrong source profile should fail")
        } catch let error as CodexTaskPreparationError {
            guard case .connectionChanged = error else {
                return XCTFail("unexpected preparation error: \(error)")
            }
        }
        XCTAssertTrue(store.tasks.isEmpty)
    }

    func testPrepareTaskRejectsConfigurationChangeDuringThreadFetch() async throws {
        let config = try config()
        let context = URL(fileURLWithPath: config.contextDir, isDirectory: true)
        let marker = context.appendingPathComponent("thread-started")
        let cli = try preparationCLI(context: context, threadStartedMarker: marker)
        let inbox = InboxStore(cli: cli, config: config, notifier: Notifier())
        await inbox.history.loadInitial()
        let item = try XCTUnwrap(inbox.mergedItems.first)
        let store = CodexTaskStore(config: config)
        let revision = config.connectionRevision
        let task = Task {
            try await store.prepareTask(
                goal: "Draft a reply.", workingDirectory: nil, cli: cli,
                inbox: inbox, item: item, sourceProfileID: config.profileID,
                sourceConnectionRevision: revision, ownerRequestID: "owner-race"
            )
        }
        try await waitForFile(marker)
        config.apiURL = "https://changed.example.test"

        do {
            _ = try await task.value
            XCTFail("configuration changes during preparation should fail")
        } catch let error as CodexTaskPreparationError {
            guard case .connectionChanged = error else {
                return XCTFail("unexpected preparation error: \(error)")
            }
        }
        XCTAssertTrue(store.tasks.isEmpty)
    }

    func testPrepareTaskRejectsSourceDisappearingDuringThreadFetch() async throws {
        let config = try config()
        let context = URL(fileURLWithPath: config.contextDir, isDirectory: true)
        let marker = context.appendingPathComponent("thread-started")
        let cli = try preparationCLI(context: context, threadStartedMarker: marker)
        let inbox = InboxStore(cli: cli, config: config, notifier: Notifier())
        await inbox.history.loadInitial()
        let item = try XCTUnwrap(inbox.mergedItems.first)
        let store = CodexTaskStore(config: config)
        let task = Task {
            try await store.prepareTask(
                goal: "Draft a reply.", workingDirectory: nil, cli: cli,
                inbox: inbox, item: item, sourceProfileID: config.profileID,
                sourceConnectionRevision: config.connectionRevision, ownerRequestID: "owner-disappear"
            )
        }
        try await waitForFile(marker)
        inbox.items = []
        inbox.history.reset()

        do {
            _ = try await task.value
            XCTFail("source disappearance during preparation should fail")
        } catch let error as CodexTaskPreparationError {
            guard case .messageUnavailable = error else {
                return XCTFail("unexpected preparation error: \(error)")
            }
        }
        XCTAssertTrue(store.tasks.isEmpty)
    }

    private func waitForFile(_ url: URL) async throws {
        for _ in 0..<50 {
            if FileManager.default.fileExists(atPath: url.path) { return }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("Timed out waiting for fixture marker: \(url.lastPathComponent)")
    }
}
