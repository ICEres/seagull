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
        let store = CodexTaskStore(config: config, openURL: { opened = $0; return true })
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
        XCTAssertNotNil(store.latestTask(for: "delivery-one")?.resultError)
        XCTAssertNil(store.latestTask(for: "delivery-one")?.result)
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
}
