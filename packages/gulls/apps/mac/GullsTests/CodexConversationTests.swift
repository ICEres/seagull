import CryptoKit
import Darwin
import Foundation
import SQLite3
import XCTest
@testable import Gulls

@MainActor
final class CodexConversationTests: XCTestCase {
    private final class MemoryTokens: GullsTokenStore {
        func token(for profileID: String) -> String? { nil }
        func legacyToken() -> String? { nil }
        func setToken(_ token: String, for profileID: String) -> Bool { true }
    }

    private var cleanup: [URL] = []

    override func tearDown() {
        for url in cleanup { try? FileManager.default.removeItem(at: url) }
        cleanup.removeAll()
    }

    func testSameConversationReusesContextButFolderChangesCreateContext() throws {
        let config = try makeConfig(profileID: "one")
        let store = CodexTaskStore(config: config)
        let source = try makeSource(in: config)
        let messages = [CodexContextMessage(id: "m-1", sender: "other", content: "Hello", createdAt: nil)]
        let first = try makeTask(store, source: source, threadID: "thread-1", sourceMessageID: "m-1",
                                 ownerRequestID: "request-1", messages: messages)
        let firstRouted = try store.selectRoute(.embedded, for: first)
        let second = try makeTask(store, source: source, threadID: "thread-1", sourceMessageID: "m-2",
                                  ownerRequestID: "request-2", messages: messages)
        let secondRouted = try store.selectRoute(.embedded, for: second)
        XCTAssertEqual(firstRouted.work?.conversationKey, secondRouted.work?.conversationKey)
        XCTAssertEqual(firstRouted.work?.contextID, secondRouted.work?.contextID)

        let folder = try makeDirectory("codex-folder")
        let changed = try makeTask(store, source: source, threadID: "thread-1", sourceMessageID: "m-3",
                                   ownerRequestID: "request-3", folder: folder, messages: messages)
        let changedRouted = try store.selectRoute(.embedded, for: changed)
        XCTAssertNotEqual(firstRouted.work?.contextID, changedRouted.work?.contextID)

        let removed = try makeTask(store, source: source, threadID: "thread-1", sourceMessageID: "m-4",
                                   ownerRequestID: "request-4", messages: messages)
        let removedRouted = try store.selectRoute(.embedded, for: removed)
        XCTAssertNotEqual(removedRouted.work?.contextID, firstRouted.work?.contextID)
        XCTAssertNotEqual(removedRouted.work?.contextID, changedRouted.work?.contextID)
    }

    func testConversationIdentityIsIsolatedByProfileAndServer() throws {
        let firstConfig = try makeConfig(profileID: "one", apiURL: "https://one.example.test")
        let secondConfig = try makeConfig(profileID: "two", apiURL: "https://two.example.test")
        let first = CodexTaskStore(config: firstConfig)
        let second = CodexTaskStore(config: secondConfig)
        let firstSource = try makeSource(in: firstConfig)
        let secondSource = try makeSource(in: secondConfig)

        let firstTask = try makeTask(first, source: firstSource, threadID: "same-thread",
                                     sourceMessageID: "m-1", ownerRequestID: "r-1")
        let secondTask = try makeTask(second, source: secondSource, threadID: "same-thread",
                                      sourceMessageID: "m-1", ownerRequestID: "r-1")
        let firstRouted = try first.selectRoute(.embedded, for: firstTask)
        let secondRouted = try second.selectRoute(.embedded, for: secondTask)

        XCTAssertNotEqual(firstRouted.work?.conversationKey, secondRouted.work?.conversationKey)
        XCTAssertTrue(first.hasConversation(threadID: "same-thread"))
        XCTAssertTrue(second.hasConversation(threadID: "same-thread"))
    }

    func testRepeatedOwnerActionReturnsTheSameImmutableTask() throws {
        let config = try makeConfig(profileID: "one")
        let store = CodexTaskStore(config: config)
        let source = try makeSource(in: config)
        let first = try makeTask(store, source: source, threadID: "thread-1", sourceMessageID: "m-1",
                                 ownerRequestID: "ui-action-1")
        let duplicate = try makeTask(store, source: source, threadID: "thread-1", sourceMessageID: "m-1",
                                     ownerRequestID: "ui-action-1")

        XCTAssertEqual(first.id, duplicate.id)
        XCTAssertEqual(store.tasks.filter { $0.id == first.id }.count, 1)
        XCTAssertEqual(first.work?.deduplicationKey, duplicate.work?.deduplicationKey)
    }

    func testRetryWithNewOwnerRequestIDDeduplicatesTheSameSource() throws {
        let config = try makeConfig(profileID: "one")
        let store = CodexTaskStore(config: config)
        let source = try makeSource(in: config)

        let first = try makeTask(store, source: source, threadID: "thread-1", sourceMessageID: "m-1",
                                 ownerRequestID: "request-1")
        let retry = try makeTask(store, source: source, threadID: "thread-1", sourceMessageID: "m-1",
                                 ownerRequestID: "request-2")

        XCTAssertEqual(first.id, retry.id)
        XCTAssertEqual(store.tasks.filter { $0.id == first.id }.count, 1)
    }

    func testMessageAndConversationSnapshotsRemainImmutable() throws {
        let config = try makeConfig(profileID: "one")
        let store = CodexTaskStore(config: config)
        let source = try makeSource(in: config, content: "Original source")
        let messages = [CodexContextMessage(id: "m-1", sender: "owner", content: "Original context", createdAt: nil)]
        let task = try makeTask(store, source: source, threadID: "thread-1", sourceMessageID: "m-1",
                                ownerRequestID: "r-1", messages: messages)
        try Data("Changed source".utf8).write(to: source)

        XCTAssertEqual(try String(contentsOf: URL(fileURLWithPath: task.request.contextPath!)), "Original source")
        let conversationURL = store.tasksDirectory.appendingPathComponent(task.id).appendingPathComponent("conversation.json")
        let snapshot = try JSONDecoder().decode([CodexContextMessage].self, from: Data(contentsOf: conversationURL))
        XCTAssertEqual(snapshot, messages)
    }

    func testExternalResultBeforeRouteSelectionIsRejected() throws {
        let config = try makeConfig(profileID: "one")
        let store = CodexTaskStore(config: config)
        let source = try makeSource(in: config)
        let task = try makeTask(store, source: source, threadID: "thread-1", sourceMessageID: "m-1",
                                ownerRequestID: "r-1")
        let requestData = try Data(contentsOf: store.tasksDirectory.appendingPathComponent(task.id).appendingPathComponent("request.json"))
        let digest = SHA256.hash(data: requestData).map { String(format: "%02x", $0) }.joined()
        let result: [String: Any] = [
            "version": 1,
            "task_id": task.id,
            "profile_id": task.request.profileID,
            "gull_handle": task.request.gullHandle,
            "connection_revision": task.request.connectionRevision,
            "request_sha256": digest,
            "content": "Early external draft",
            "completed_at": "2026-10-24T00:00:00Z"
        ]
        let resultURL = store.tasksDirectory.appendingPathComponent(task.id).appendingPathComponent("result.json")
        try JSONSerialization.data(withJSONObject: result).write(to: resultURL)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: resultURL.path)
        store.refresh()

        let refreshed = try XCTUnwrap(store.tasks.first { $0.id == task.id })
        XCTAssertNil(refreshed.result)
        XCTAssertTrue(refreshed.resultError?.contains("route") == true)
    }

    func testDatabaseMigratesLegacySessionsAndRejectsUnknownSchema() throws {
        let url = try makeDatabaseURL()
        try createLegacyDatabase(at: url)
        let database = try CodexSessionDatabase(url: url)
        let record = try XCTUnwrap(database.record(for: "legacy-task"))
        XCTAssertEqual(record.profileID, "profile-1")
        let backups = try FileManager.default.contentsOfDirectory(at: url.deletingLastPathComponent(),
                                                                    includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("sessions-before-conversations-") }
        XCTAssertEqual(backups.count, 1)

        let unknownURL = try makeDatabaseURL()
        try executeSQLite("PRAGMA user_version=3", at: unknownURL)
        XCTAssertThrowsError(try CodexSessionDatabase(url: unknownURL))
    }

    private func makeConfig(profileID: String, apiURL: String = "https://messages.example.test") throws -> GullsConfig {
        let suite = "codex-conversation-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
        let config = GullsConfig(profileID: profileID, defaults: defaults, tokenStore: MemoryTokens())
        config.apiURL = apiURL
        config.agentHandle = "@\(profileID):gulls.ai"
        config.contextDir = try makeDirectory("codex-context").path
        config.token = "test-token"
        config.codexEnabled = true
        return config
    }

    private func makeTask(
        _ store: CodexTaskStore,
        source: URL,
        threadID: String,
        sourceMessageID: String,
        ownerRequestID: String,
        folder: URL? = nil,
        messages: [CodexContextMessage] = []
    ) throws -> CodexTask {
        try store.create(
            goal: "Draft a private reply.",
            workingDirectory: folder,
            deliveryID: sourceMessageID,
            threadID: threadID,
            contextPath: source.path,
            sourceMessageID: sourceMessageID,
            ownerRequestID: ownerRequestID,
            conversationMessages: messages,
            cliExecutableURL: URL(fileURLWithPath: "/Applications/Gulls.app/Contents/Resources/gulls")
        )
    }

    private func makeSource(in config: GullsConfig, content: String = "Original source") throws -> URL {
        let base = URL(fileURLWithPath: config.contextDir, isDirectory: true)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let source = base.appendingPathComponent("message-\(UUID().uuidString).md")
        try Data(content.utf8).write(to: source)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: source.path)
        return source
    }

    private func makeDirectory(_ prefix: String) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(prefix)-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        cleanup.append(url)
        return url
    }

    private func makeDatabaseURL() throws -> URL {
        let directory = try makeDirectory("codex-database")
        return directory.appendingPathComponent("sessions.sqlite3")
    }

    private func executeSQLite(_ sql: String, at url: URL) throws {
        var handle: OpaquePointer?
        guard sqlite3_open_v2(url.path, &handle, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE, nil) == SQLITE_OK else {
            throw XCTSkip("SQLite fixture could not be created.")
        }
        defer { sqlite3_close(handle) }
        guard sqlite3_exec(handle, sql, nil, nil, nil) == SQLITE_OK else {
            throw XCTSkip("SQLite fixture could not be written.")
        }
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }

    private func createLegacyDatabase(at url: URL) throws {
        try executeSQLite("CREATE TABLE codex_sessions (task_id TEXT PRIMARY KEY, record BLOB NOT NULL)", at: url)
        let execution = CodexTaskExecution(status: .working)
        let record = CodexSessionDatabase.Record(
            taskID: "legacy-task",
            profileID: "profile-1",
            connectionRevision: "revision-1",
            requestDigest: String(repeating: "a", count: 64),
            execution: execution
        )
        let data = try JSONEncoder().encode(record)
        var handle: OpaquePointer?
        guard sqlite3_open_v2(url.path, &handle, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK else {
            throw XCTSkip("SQLite fixture could not be reopened.")
        }
        defer { sqlite3_close(handle) }
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(handle, "INSERT INTO codex_sessions(task_id,record) VALUES (?,?)", -1, &statement, nil) == SQLITE_OK else {
            throw XCTSkip("SQLite fixture statement could not be prepared.")
        }
        defer { sqlite3_finalize(statement) }
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        sqlite3_bind_text(statement, 1, record.taskID, -1, transient)
        _ = data.withUnsafeBytes { sqlite3_bind_blob(statement, 2, $0.baseAddress, Int32(data.count), transient) }
        guard sqlite3_step(statement) == SQLITE_DONE else { throw XCTSkip("SQLite fixture row could not be inserted.") }
    }
}
