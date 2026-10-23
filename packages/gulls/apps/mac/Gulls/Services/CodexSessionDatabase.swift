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
            try execute("CREATE TABLE IF NOT EXISTS codex_sessions (task_id TEXT PRIMARY KEY, record BLOB NOT NULL)")
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

    private struct Failure: LocalizedError {
        let message: String
        init(_ message: String) { self.message = message }
        var errorDescription: String? { message }
    }
}
