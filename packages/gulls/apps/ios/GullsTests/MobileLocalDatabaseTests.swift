import Foundation
import XCTest
@testable import GullsIOS

final class MobileLocalDatabaseTests: XCTestCase {
    func testPersistsAcrossReopenedActors() async throws {
        let url = try temporaryURL()
        let first = MobileLocalDatabase(url: url)
        try await first.write(scope: "account-1|server-a", bucket: "messages", entries: [entry("m1", "hello", 1)])
        let second = MobileLocalDatabase(url: url)
        let values = try await second.read(scope: "account-1|server-a", bucket: "messages")
        XCTAssertEqual(values, [entry("m1", "hello", 1)])
    }

    func testScopesAreIsolatedByAccountAndServer() async throws {
        let db = MobileLocalDatabase(url: try temporaryURL())
        try await db.write(scope: "account-1|server-a", bucket: "messages", entries: [entry("same", "one", 1)])
        try await db.write(scope: "account-2|server-a", bucket: "messages", entries: [entry("same", "two", 1)])
        try await db.write(scope: "account-1|server-b", bucket: "messages", entries: [entry("same", "three", 1)])
        let first = try await db.read(scope: "account-1|server-a", bucket: "messages")
        let second = try await db.read(scope: "account-2|server-a", bucket: "messages")
        let third = try await db.read(scope: "account-1|server-b", bucket: "messages")
        XCTAssertEqual(first.first?.data, Data("one".utf8))
        XCTAssertEqual(second.first?.data, Data("two".utf8))
        XCTAssertEqual(third.first?.data, Data("three".utf8))
    }

    func testReplacingBucketIsAtomicAndUpsertUpdatesExistingID() async throws {
        let db = MobileLocalDatabase(url: try temporaryURL())
        try await db.write(scope: "scope", bucket: "messages", entries: [entry("old", "old", 1), entry("same", "before", 2)])
        try await db.write(scope: "scope", bucket: "messages", entries: [entry("same", "after", 4), entry("new", "new", 3)])
        let merged = try await db.read(scope: "scope", bucket: "messages")
        XCTAssertEqual(merged.map(\.id), ["same", "new", "old"])
        try await db.write(scope: "scope", bucket: "messages", entries: [entry("replacement", "only", 5)], replacing: true)
        let replaced = try await db.read(scope: "scope", bucket: "messages")
        XCTAssertEqual(replaced.map(\.id), ["replacement"])
        try await db.write(scope: "scope", bucket: "messages", entries: [], replacing: true)
        let emptied = try await db.read(scope: "scope", bucket: "messages")
        XCTAssertTrue(emptied.isEmpty)
    }

    func testBatchWriteKeepsPageRowsAndContinuationInOneCommit() async throws {
        let db = MobileLocalDatabase(url: try temporaryURL())
        let rows = [entry("row-1", "message", 2)]
        let page = entry("inbox", #"{"version":2,"historyCursor":"cursor-1","historyCursorVerified":true}"#, 1)
        try await db.write(batches: [
            .init(scope: "scope", bucket: "inbox:@mine:gulls.ai", entries: rows),
            .init(scope: "scope", bucket: "inbox-pages", entries: [page])
        ])

        let storedRow = try await db.entry(scope: "scope", bucket: "inbox:@mine:gulls.ai", id: "row-1")
        let storedPage = try await db.entry(scope: "scope", bucket: "inbox-pages", id: "inbox")
        XCTAssertEqual(storedRow?.data, Data("message".utf8))
        XCTAssertEqual(storedPage?.data, page.data)
    }

    func testReadsNewestFirstWithStableIDTieBreakAndLimit() async throws {
        let db = MobileLocalDatabase(url: try temporaryURL())
        try await db.write(scope: "scope", bucket: "messages", entries: [entry("b", "b", 2), entry("a", "a", 2), entry("c", "c", 3), entry("d", "d", 1)])
        let values = try await db.read(scope: "scope", bucket: "messages", limit: 3)
        XCTAssertEqual(values.map(\.id), ["c", "a", "b"])
    }

    func testPreservesEmptyDataAsAnEmptyBlob() async throws {
        let db = MobileLocalDatabase(url: try temporaryURL())
        try await db.write(scope: "scope", bucket: "messages", entries: [MobileLocalDatabase.Entry(id: "empty", data: Data(), sortKey: 1)])
        let values = try await db.read(scope: "scope", bucket: "messages")
        XCTAssertEqual(values.first?.data, Data())
        let lookedUp = try await db.entry(scope: "scope", bucket: "messages", id: "empty")
        XCTAssertEqual(lookedUp, MobileLocalDatabase.Entry(id: "empty", data: Data(), sortKey: 1))
    }

    func testInvalidReplacementBatchLeavesExistingBucketUnchanged() async throws {
        let db = MobileLocalDatabase(url: try temporaryURL())
        try await db.write(scope: "scope", bucket: "messages", entries: [entry("existing", "keep", 1)])
        do {
            try await db.write(scope: "scope", bucket: "messages", entries: [entry("replacement", "new", 2), entry("", "invalid", 3)], replacing: true)
            XCTFail("Expected invalid replacement entry to throw")
        } catch {
            // The existing bucket must remain intact after validation failure.
        }
        let values = try await db.read(scope: "scope", bucket: "messages")
        XCTAssertEqual(values, [entry("existing", "keep", 1)])
    }

    func testDeletionOnlyTouchesRequestedScope() async throws {
        let db = MobileLocalDatabase(url: try temporaryURL())
        try await db.write(scope: "one", bucket: "messages", entries: [entry("id", "one", 1)])
        try await db.write(scope: "two", bucket: "messages", entries: [entry("id", "two", 1)])
        try await db.remove(scope: "one", bucket: "messages", id: "id")
        let one = try await db.read(scope: "one", bucket: "messages")
        let two = try await db.read(scope: "two", bucket: "messages")
        XCTAssertTrue(one.isEmpty)
        XCTAssertFalse(two.isEmpty)
        try await db.remove(scope: "two")
        let removed = try await db.read(scope: "two", bucket: "messages")
        XCTAssertTrue(removed.isEmpty)
    }

    func testEntryLookupIsScopedByFullPrimaryKey() async throws {
        let db = MobileLocalDatabase(url: try temporaryURL())
        try await db.write(scope: "one", bucket: "messages", entries: [entry("same", "one", 1)])
        try await db.write(scope: "two", bucket: "messages", entries: [entry("same", "two", 2)])
        let one = try await db.entry(scope: "one", bucket: "messages", id: "same")
        let two = try await db.entry(scope: "two", bucket: "messages", id: "same")
        let missing = try await db.entry(scope: "one", bucket: "other", id: "same")
        XCTAssertEqual(one?.data, Data("one".utf8))
        XCTAssertEqual(two?.data, Data("two".utf8))
        XCTAssertNil(missing)
    }

    private func entry(_ id: String, _ value: String, _ sortKey: Double) -> MobileLocalDatabase.Entry {
        MobileLocalDatabase.Entry(id: id, data: Data(value.utf8), sortKey: sortKey)
    }

    private func temporaryURL() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("gulls-mobile-db-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent("mobile.sqlite")
    }
}
