import Darwin
import Foundation
import SQLite3

/// Private session routing only. Codex owns its full conversation history;
/// message transport and the owner's reviewed replies remain owned by Gulls.
final class CodexSessionDatabase {
    private static let maximumRecordBytes = 1024 * 1024

    struct Record: Codable {
        let taskID: String
        let profileID: String
        let connectionRevision: String
        let requestDigest: String
        var execution: CodexTaskExecution
    }

    let url: URL
    private var database: OpaquePointer?
    private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    init(url: URL) throws {
        self.url = url
        let descriptor = Darwin.open(url.path, O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { throw Failure("Could not open the private Codex session database.") }
        defer { Darwin.close(descriptor) }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == geteuid(), info.st_mode & 0o077 == 0 else {
            throw Failure("Codex sessions must use a private, regular database file.")
        }
        // Foundation canonicalizes /private/var back to /var on macOS. SQLite
        // NOFOLLOW also rejects parent aliases, so use the physical POSIX path.
        guard let physical = realpath(url.path, nil) else { throw Failure("Could not resolve the private session database.") }
        defer { free(physical) }
        guard sqlite3_open_v2(physical, &database, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX | SQLITE_OPEN_NOFOLLOW, nil) == SQLITE_OK else {
            let message = database.map { String(cString: sqlite3_errmsg($0)) } ?? "unknown error"
            sqlite3_close(database)
            database = nil
            throw Failure("Could not open the Codex session database: \(message)")
        }
        do {
            try execute("PRAGMA journal_mode=DELETE")
            let version = try scalar("PRAGMA user_version")
            guard version <= 2 else { throw Failure("This Codex database requires a newer version of Gulls.") }
            if version == 0 {
                let existing = try scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='codex_sessions'")
                if existing > 0, try scalar("SELECT COUNT(*) FROM codex_sessions") > 0 { try backupBeforeMigration() }
                try transaction {
                    try execute("CREATE TABLE IF NOT EXISTS codex_sessions (task_id TEXT PRIMARY KEY, record BLOB NOT NULL)")
                    try execute("CREATE TABLE IF NOT EXISTS codex_work (task_id TEXT PRIMARY KEY, deduplication_key TEXT UNIQUE NOT NULL, record BLOB NOT NULL)")
                    try execute("CREATE TABLE IF NOT EXISTS codex_contexts (context_id TEXT PRIMARY KEY, record BLOB NOT NULL)")
                    try execute("PRAGMA user_version=1")
                }
            }
            if version < 2 {
                if version == 1 { try backupBeforeMigration() }
                try transaction {
                    try execute("CREATE TABLE IF NOT EXISTS gull_reply_outbox (task_id TEXT PRIMARY KEY, publication_key TEXT UNIQUE NOT NULL, record BLOB NOT NULL)")
                    try execute("PRAGMA user_version=2")
                }
            }
        } catch {
            sqlite3_close(database)
            database = nil
            throw error
        }
    }

    deinit { sqlite3_close(database) }

    func record(for taskID: String) throws -> Record? {
        let statement = try prepare("SELECT record FROM codex_sessions WHERE task_id = ?")
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, taskID, -1, transient)
        let status = sqlite3_step(statement)
        if status == SQLITE_DONE { return nil }
        guard status == SQLITE_ROW, let bytes = sqlite3_column_blob(statement, 0) else {
            throw Failure("Could not read the Codex session.")
        }
        let size = Int(sqlite3_column_bytes(statement, 0))
        guard size <= Self.maximumRecordBytes else { throw Failure("The Codex session is too large.") }
        let record = try JSONDecoder().decode(Record.self, from: Data(bytes: bytes, count: size))
        try validate(record, expectedTaskID: taskID)
        return record
    }

    func save(_ record: Record) throws {
        try validate(record, expectedTaskID: record.taskID)
        let data = try JSONEncoder().encode(record)
        guard data.count <= Self.maximumRecordBytes else { throw Failure("The Codex session is too large.") }
        let statement = try prepare("INSERT INTO codex_sessions(task_id, record) VALUES (?, ?) ON CONFLICT(task_id) DO UPDATE SET record = excluded.record")
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, record.taskID, -1, transient)
        _ = data.withUnsafeBytes { sqlite3_bind_blob(statement, 2, $0.baseAddress, Int32(data.count), transient) }
        guard sqlite3_step(statement) == SQLITE_DONE else { throw Failure("Could not save the Codex session.") }
    }

    func work(for taskID: String) throws -> CodexWorkRecord? {
        let values: [CodexWorkRecord] = try records("SELECT record FROM codex_work WHERE task_id = ?", key: taskID)
        if let work = values.first { try validate(work) }
        return values.first
    }

    func work(forDeduplicationKey key: String) throws -> CodexWorkRecord? {
        let values: [CodexWorkRecord] = try records("SELECT record FROM codex_work WHERE deduplication_key = ?", key: key)
        if let work = values.first { try validate(work) }
        return values.first
    }

    func allWork() throws -> [CodexWorkRecord] {
        let records: [CodexWorkRecord] = try records("SELECT record FROM codex_work ORDER BY rowid")
        for record in records { try validate(record) }
        return records
    }

    func saveWork(_ work: CodexWorkRecord) throws {
        try validate(work)
        let data = try encoded(work)
        let statement = try prepare("INSERT INTO codex_work(task_id,deduplication_key,record) VALUES (?,?,?) ON CONFLICT(task_id) DO UPDATE SET record=excluded.record")
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, work.taskID, -1, transient)
        sqlite3_bind_text(statement, 2, work.deduplicationKey, -1, transient)
        _ = data.withUnsafeBytes { sqlite3_bind_blob(statement, 3, $0.baseAddress, Int32(data.count), transient) }
        guard sqlite3_step(statement) == SQLITE_DONE else { throw Failure("This Codex request is already queued or could not be saved.") }
    }

    func contexts() throws -> [CodexConversationContext] {
        try records("SELECT record FROM codex_contexts ORDER BY rowid")
    }

    func saveContext(_ context: CodexConversationContext) throws {
        guard UUID(uuidString: context.id) != nil, !context.conversationKey.isEmpty,
              !context.profileID.isEmpty, !context.connectionRevision.isEmpty,
              context.codexThreadID.map({ UUID(uuidString: $0) != nil }) ?? true else {
            throw Failure("Invalid Codex conversation context.")
        }
        let data = try encoded(context)
        let statement = try prepare("INSERT INTO codex_contexts(context_id,record) VALUES (?,?) ON CONFLICT(context_id) DO UPDATE SET record=excluded.record")
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, context.id, -1, transient)
        _ = data.withUnsafeBytes { sqlite3_bind_blob(statement, 2, $0.baseAddress, Int32(data.count), transient) }
        guard sqlite3_step(statement) == SQLITE_DONE else { throw Failure("Could not save the Codex conversation context.") }
    }

    func transaction(_ operation: () throws -> Void) throws {
        try execute("BEGIN IMMEDIATE")
        do {
            try operation()
            try execute("COMMIT")
        } catch {
            try? execute("ROLLBACK")
            throw error
        }
    }

    func reply(for taskID: String) throws -> GullReplyPublication? {
        let values: [GullReplyPublication] = try records("SELECT record FROM gull_reply_outbox WHERE task_id = ?", key: taskID)
        return values.first
    }

    func saveReply(_ reply: GullReplyPublication) throws {
        guard UUID(uuidString: reply.taskID) != nil, UUID(uuidString: reply.publicationKey) != nil,
              !reply.profileID.isEmpty, !reply.connectionRevision.isEmpty, !reply.deliveryID.isEmpty,
              reply.requestDigest.count == 64,
              reply.content.map({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && $0.utf8.count <= 128 * 1024 }) ?? true,
              reply.status != .sent || reply.messageID?.isEmpty == false else {
            throw Failure("Invalid delegated reply record.")
        }
        let data = try encoded(reply)
        let statement = try prepare("INSERT INTO gull_reply_outbox(task_id,publication_key,record) VALUES (?,?,?) ON CONFLICT(task_id) DO UPDATE SET record=excluded.record")
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, reply.taskID, -1, transient)
        sqlite3_bind_text(statement, 2, reply.publicationKey, -1, transient)
        _ = data.withUnsafeBytes { sqlite3_bind_blob(statement, 3, $0.baseAddress, Int32(data.count), transient) }
        guard sqlite3_step(statement) == SQLITE_DONE else { throw Failure("Could not save the delegated reply.") }
    }

    private func records<T: Decodable>(_ sql: String, key: String? = nil) throws -> [T] {
        let statement = try prepare(sql)
        defer { sqlite3_finalize(statement) }
        if let key { sqlite3_bind_text(statement, 1, key, -1, transient) }
        var values: [T] = []
        while true {
            let status = sqlite3_step(statement)
            if status == SQLITE_DONE { return values }
            guard status == SQLITE_ROW, let bytes = sqlite3_column_blob(statement, 0) else {
                throw Failure("Could not read private Codex metadata.")
            }
            let size = Int(sqlite3_column_bytes(statement, 0))
            guard size > 0, size <= Self.maximumRecordBytes else { throw Failure("The Codex record is too large.") }
            values.append(try JSONDecoder().decode(T.self, from: Data(bytes: bytes, count: size)))
        }
    }

    private func encoded<T: Encodable>(_ value: T) throws -> Data {
        let data = try JSONEncoder().encode(value)
        guard data.count <= Self.maximumRecordBytes else { throw Failure("The Codex record is too large.") }
        return data
    }

    private func scalar(_ sql: String) throws -> Int {
        let statement = try prepare(sql)
        defer { sqlite3_finalize(statement) }
        guard sqlite3_step(statement) == SQLITE_ROW else { throw Failure("Could not read the Codex database version.") }
        return Int(sqlite3_column_int(statement, 0))
    }

    private func backupBeforeMigration() throws {
        let backupURL = url.deletingLastPathComponent().appendingPathComponent("sessions-before-conversations-\(UUID().uuidString.lowercased()).sqlite3")
        let descriptor = Darwin.open(backupURL.path, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { throw Failure("Could not prepare a private Codex migration backup.") }
        Darwin.close(descriptor)
        var destination: OpaquePointer?
        var succeeded = false
        defer {
            sqlite3_close(destination)
            if !succeeded { try? FileManager.default.removeItem(at: backupURL) }
        }
        guard sqlite3_open_v2(backupURL.path, &destination, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK,
              let backup = sqlite3_backup_init(destination, "main", database, "main") else {
            throw Failure("Could not create the Codex migration backup.")
        }
        let status = sqlite3_backup_step(backup, -1)
        let finish = sqlite3_backup_finish(backup)
        guard status == SQLITE_DONE, finish == SQLITE_OK else { throw Failure("Could not complete the Codex migration backup.") }
        succeeded = true
    }

    private func execute(_ sql: String) throws {
        guard sqlite3_exec(database, sql, nil, nil, nil) == SQLITE_OK else {
            throw Failure("Could not prepare the Codex session database.")
        }
    }

    private func prepare(_ sql: String) throws -> OpaquePointer? {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, sql, -1, &statement, nil) == SQLITE_OK else {
            throw Failure("Could not prepare the Codex session query.")
        }
        return statement
    }

    private func validate(_ record: Record, expectedTaskID: String) throws {
        guard !expectedTaskID.isEmpty, record.taskID == expectedTaskID,
              !record.profileID.isEmpty, record.profileID.utf8.count <= 256,
              !record.connectionRevision.isEmpty, record.connectionRevision.utf8.count <= 256,
              record.requestDigest.count == 64,
              record.requestDigest.allSatisfy({ $0.isHexDigit }) else {
            throw Failure("The Codex session identity does not match its task.")
        }
    }

    private func validate(_ work: CodexWorkRecord) throws {
        guard UUID(uuidString: work.taskID) != nil, !work.profileID.isEmpty,
              !work.connectionRevision.isEmpty, work.requestDigest.count == 64,
              work.requestDigest.allSatisfy({ $0.isHexDigit }), !work.deduplicationKey.isEmpty else {
            throw Failure("Invalid private Codex work metadata.")
        }
    }

    private struct Failure: LocalizedError {
        let message: String
        init(_ message: String) { self.message = message }
        var errorDescription: String? { message }
    }
}
