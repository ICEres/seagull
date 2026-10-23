import Foundation
import SQLite3

/// Small durable cache used by the mobile client. The actor owns the SQLite
/// connection so reads and writes never run on the main actor.
actor MobileLocalDatabase {
    struct Entry: Equatable, Sendable {
        let id: String
        let data: Data
        let sortKey: Double
    }

    struct Batch: Sendable {
        let scope: String
        let bucket: String
        let entries: [Entry]
        let replacing: Bool

        init(scope: String, bucket: String, entries: [Entry], replacing: Bool = false) {
            self.scope = scope
            self.bucket = bucket
            self.entries = entries
            self.replacing = replacing
        }
    }

    enum Failure: Error, LocalizedError, Equatable {
        case invalidScope
        case invalidBucket
        case invalidIdentifier
        case open(String)
        case query(String)
        case transaction(String)

        var errorDescription: String? {
            switch self {
            case .invalidScope: return "The cache scope is invalid."
            case .invalidBucket: return "The cache bucket is invalid."
            case .invalidIdentifier: return "The cache entry identifier is invalid."
            case let .open(message), let .query(message), let .transaction(message): return message
            }
        }
    }

    let url: URL
    private var database: OpaquePointer?
    private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    init(url: URL = MobileLocalDatabase.defaultURL()) {
        self.url = url
    }

    deinit {
        sqlite3_close(database)
    }

    func read(scope: String, bucket: String, limit: Int = 1000) throws -> [Entry] {
        try validate(scope: scope, bucket: bucket)
        guard limit > 0 else { return [] }
        let statement = try prepare("SELECT id, data, sort_key FROM mobile_cache_entries WHERE scope = ? AND bucket = ? ORDER BY sort_key DESC, id ASC LIMIT ?")
        defer { sqlite3_finalize(statement) }
        try bind(scope, to: statement, index: 1)
        try bind(bucket, to: statement, index: 2)
        guard sqlite3_bind_int64(statement, 3, sqlite3_int64(limit)) == SQLITE_OK else {
            throw queryFailure("Could not bind the mobile cache limit.")
        }

        var entries: [Entry] = []
        while true {
            let status = sqlite3_step(statement)
            if status == SQLITE_DONE { return entries }
            guard status == SQLITE_ROW else { throw queryFailure("Could not read the mobile cache.") }
            guard let idBytes = sqlite3_column_text(statement, 0) else {
                throw queryFailure("The mobile cache contains an invalid entry.")
            }
            let id = String(cString: idBytes)
            let size = Int(sqlite3_column_bytes(statement, 1))
            let data: Data
            if size == 0 {
                data = Data()
            } else {
                guard let dataBytes = sqlite3_column_blob(statement, 1) else {
                    throw queryFailure("The mobile cache contains an invalid entry.")
                }
                data = Data(bytes: dataBytes, count: size)
            }
            entries.append(Entry(id: id, data: data, sortKey: sqlite3_column_double(statement, 2)))
        }
    }

    func entry(scope: String, bucket: String, id: String) throws -> Entry? {
        try validate(scope: scope, bucket: bucket)
        guard !id.isEmpty else { throw Failure.invalidIdentifier }
        let statement = try prepare("SELECT data, sort_key FROM mobile_cache_entries WHERE scope = ? AND bucket = ? AND id = ?")
        defer { sqlite3_finalize(statement) }
        try bind(scope, to: statement, index: 1)
        try bind(bucket, to: statement, index: 2)
        try bind(id, to: statement, index: 3)
        let status = sqlite3_step(statement)
        if status == SQLITE_DONE { return nil }
        guard status == SQLITE_ROW else { throw queryFailure("Could not read the mobile cache entry.") }
        let size = Int(sqlite3_column_bytes(statement, 0))
        let data: Data
        if size == 0 {
            data = Data()
        } else {
            guard let bytes = sqlite3_column_blob(statement, 0) else {
                throw queryFailure("The mobile cache contains an invalid entry.")
            }
            data = Data(bytes: bytes, count: size)
        }
        return Entry(id: id, data: data, sortKey: sqlite3_column_double(statement, 1))
    }

    func write(scope: String, bucket: String, entries: [Entry], replacing: Bool = false) throws {
        try write(batches: [Batch(scope: scope, bucket: bucket, entries: entries, replacing: replacing)])
    }

    /// Writes multiple cache buckets under one SQLite transaction. This is used
    /// for a page response so its rows and continuation state cannot diverge
    /// after a termination or storage error.
    func write(batches: [Batch]) throws {
        guard !batches.isEmpty else { return }
        for batch in batches {
            try validate(scope: batch.scope, bucket: batch.bucket)
            for entry in batch.entries where entry.id.isEmpty { throw Failure.invalidIdentifier }
        }
        try ensureDatabase()
        try execute("BEGIN IMMEDIATE")
        do {
            let upsertSQL = "INSERT INTO mobile_cache_entries(scope, bucket, id, data, sort_key) VALUES (?, ?, ?, ?, ?) ON CONFLICT(scope, bucket, id) DO UPDATE SET data = excluded.data, sort_key = excluded.sort_key"
            for batch in batches {
                if batch.replacing {
                    let statement = try prepare("DELETE FROM mobile_cache_entries WHERE scope = ? AND bucket = ?")
                    defer { sqlite3_finalize(statement) }
                    try bind(batch.scope, to: statement, index: 1)
                    try bind(batch.bucket, to: statement, index: 2)
                    guard sqlite3_step(statement) == SQLITE_DONE else { throw transactionFailure("Could not replace the mobile cache bucket.") }
                }
                for entry in batch.entries {
                    let statement = try prepare(upsertSQL)
                    defer { sqlite3_finalize(statement) }
                    try bind(batch.scope, to: statement, index: 1)
                    try bind(batch.bucket, to: statement, index: 2)
                    try bind(entry.id, to: statement, index: 3)
                    let dataStatus: Int32 = entry.data.isEmpty
                        ? sqlite3_bind_zeroblob(statement, 4, 0)
                        : entry.data.withUnsafeBytes { bytes in
                            sqlite3_bind_blob(statement, 4, bytes.baseAddress, Int32(entry.data.count), transient)
                        }
                    guard dataStatus == SQLITE_OK else { throw transactionFailure("Could not bind the mobile cache entry data.") }
                    guard sqlite3_bind_double(statement, 5, entry.sortKey) == SQLITE_OK else {
                        throw transactionFailure("Could not bind the mobile cache entry sort key.")
                    }
                    guard sqlite3_step(statement) == SQLITE_DONE else { throw transactionFailure("Could not write the mobile cache entry.") }
                }
            }
            try execute("COMMIT")
        } catch {
            _ = sqlite3_exec(database, "ROLLBACK", nil, nil, nil)
            throw error
        }
    }

    func remove(scope: String, bucket: String, id: String) throws {
        try validate(scope: scope, bucket: bucket)
        guard !id.isEmpty else { throw Failure.invalidIdentifier }
        let statement = try prepare("DELETE FROM mobile_cache_entries WHERE scope = ? AND bucket = ? AND id = ?")
        defer { sqlite3_finalize(statement) }
        try bind(scope, to: statement, index: 1)
        try bind(bucket, to: statement, index: 2)
        try bind(id, to: statement, index: 3)
        guard sqlite3_step(statement) == SQLITE_DONE else { throw queryFailure("Could not delete the mobile cache entry.") }
    }

    func remove(scope: String) throws {
        guard !scope.isEmpty else { throw Failure.invalidScope }
        let statement = try prepare("DELETE FROM mobile_cache_entries WHERE scope = ?")
        defer { sqlite3_finalize(statement) }
        try bind(scope, to: statement, index: 1)
        guard sqlite3_step(statement) == SQLITE_DONE else { throw queryFailure("Could not delete the mobile cache scope.") }
    }

    private func ensureDatabase() throws {
        guard database == nil else { return }
        var directory = url.deletingLastPathComponent()
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            try directory.setResourceValues(values)
            try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: directory.path)
        } catch {
            throw Failure.open("Could not prepare the mobile cache directory: \(error.localizedDescription)")
        }

        var handle: OpaquePointer?
        let status = sqlite3_open_v2(url.path, &handle, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX, nil)
        guard status == SQLITE_OK, let handle else {
            let message = handle.map { String(cString: sqlite3_errmsg($0)) } ?? "unknown error"
            sqlite3_close(handle)
            throw Failure.open("Could not open the mobile cache: \(message)")
        }
        database = handle
        do {
            try execute("PRAGMA journal_mode = WAL")
            try execute("PRAGMA synchronous = FULL")
            try execute("PRAGMA user_version = 1")
            try execute("CREATE TABLE IF NOT EXISTS mobile_cache_entries (scope TEXT NOT NULL, bucket TEXT NOT NULL, id TEXT NOT NULL, data BLOB NOT NULL, sort_key REAL NOT NULL, PRIMARY KEY (scope, bucket, id))")
            try execute("CREATE INDEX IF NOT EXISTS mobile_cache_entries_order ON mobile_cache_entries(scope, bucket, sort_key DESC, id ASC)")
            try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: url.path)
        } catch {
            sqlite3_close(database)
            database = nil
            throw error
        }
    }

    private func prepare(_ sql: String) throws -> OpaquePointer? {
        try ensureDatabase()
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, sql, -1, &statement, nil) == SQLITE_OK else {
            throw queryFailure("Could not prepare the mobile cache query.")
        }
        return statement
    }

    private func execute(_ sql: String) throws {
        guard sqlite3_exec(database, sql, nil, nil, nil) == SQLITE_OK else {
            throw queryFailure("Could not update the mobile cache schema.")
        }
    }

    private func bind(_ value: String, to statement: OpaquePointer?, index: Int32) throws {
        guard sqlite3_bind_text(statement, index, value, -1, transient) == SQLITE_OK else {
            throw queryFailure("Could not bind the mobile cache value.")
        }
    }

    private func validate(scope: String, bucket: String) throws {
        guard !scope.isEmpty else { throw Failure.invalidScope }
        guard !bucket.isEmpty else { throw Failure.invalidBucket }
    }

    private func queryFailure(_ fallback: String) -> Failure {
        Failure.query(database.map { "\(fallback) (\(String(cString: sqlite3_errmsg($0))))" } ?? fallback)
    }

    private func transactionFailure(_ fallback: String) -> Failure {
        Failure.transaction(database.map { "\(fallback) (\(String(cString: sqlite3_errmsg($0))))" } ?? fallback)
    }

    private static func defaultURL() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent("Gulls", isDirectory: true).appendingPathComponent("mobile.sqlite")
    }
}
