import XCTest
@testable import Gulls

@MainActor
final class MessageHistoryStoreTests: XCTestCase {
    private var tmp: URL!
    private var suiteName = ""

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory.appendingPathComponent("history-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tmp)
    }
    func testDecodesPagedHistoryContract() throws {
        let data = Data(#"""
        {
          "items": [
            {"delivery": {"delivery_id": "d1", "status": "replied"},
             "message": {"sender_handle": "@alice:gulls.ai", "content_inline": "hello"}}
          ],
          "next_cursor": "opaque-2",
          "total": 101,
          "sync_complete": false
        }
        """#.utf8)

        let response = try JSONDecoder().decode(MessageHistoryResponse.self, from: data)
        XCTAssertEqual(response.items.map(\.id), ["d1"])
        XCTAssertEqual(response.nextCursor, "opaque-2")
        XCTAssertEqual(response.total, 101)
        XCTAssertFalse(response.syncComplete ?? true)
    }

    func testDecodesOlderRuntimeEnvelopeWithoutOptionalFields() throws {
        let data = Data(#"{"items": []}"#.utf8)
        let response = try JSONDecoder().decode(MessageHistoryResponse.self, from: data)
        XCTAssertTrue(response.items.isEmpty)
        XCTAssertNil(response.nextCursor)
        XCTAssertNil(response.total)
        XCTAssertNil(response.syncComplete)
    }

    func testAggregatesHistorySummariesForDashboard() throws {
        let data = Data(#"""
        {
          "total_deliveries": 4, "pending_deliveries": 1,
          "distinct_threads": 2, "distinct_senders": 2,
          "daily_received": [{"day":"2026-10-21","count":4}],
          "relationships": [{"sender":"@alice:gulls.ai","count":3},{"sender":"@cedar:gulls.ai","count":1}],
          "sync_complete": true
        }
        """#.utf8)
        let first = try JSONDecoder().decode(MessageHistorySummary.self, from: data)
        let second = MessageHistorySummary(
            totalDeliveries: 1, pendingDeliveries: 0, distinctThreads: 1,
            distinctSenders: 1,
            dailyReceived: [MessageHistoryDailyCount(day: "2026-10-21", count: 1)],
            relationships: [MessageHistoryRelationshipCount(sender: "@alice:gulls.ai", count: 1)],
            syncComplete: false
        )
        let result = try XCTUnwrap(MessageHistorySummary.aggregate([first, second]))
        XCTAssertEqual(result.totalDeliveries, 5)
        XCTAssertEqual(result.distinctThreads, 3)
        XCTAssertEqual(result.distinctSenders, 2)
        XCTAssertEqual(result.relationships.first(where: { $0.sender == "@alice:gulls.ai" })?.count, 4)
        XCTAssertEqual(result.dailyReceived.first?.count, 5)
        XCTAssertFalse(result.syncComplete ?? true)
    }

    func testLatestDebouncedSearchWins() async throws {
        let binary = tmp.appendingPathComponent("gulls")
        try """
        #!/bin/bash
        if [[ "$*" == *"history summary"* ]]; then
          printf '{"total_deliveries":0,"pending_deliveries":0,"distinct_threads":0,"distinct_senders":0,"daily_received":[],"relationships":[],"sync_complete":true}'
          exit 0
        fi
        query=""
        previous=""
        while [ "$#" -gt 0 ]; do
          if [ "$1" = "--query" ]; then query="$2"; shift 2; continue; fi
          shift
        done
        if [ "$query" = "first" ]; then sleep 0.2; fi
        printf '{"items":[{"delivery":{"delivery_id":"%s","status":"replied"},"message":{"content_inline":"%s"}}],"next_cursor":"","sync_complete":true}' "$query" "$query"
        """.write(to: binary, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)

        suiteName = "history-store-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        let config = GullsConfig(defaults: defaults)
        config.apiURL = "https://api.example.test"
        config.agentHandle = "@me:gulls.ai"
        let store = MessageHistoryStore(cli: GullsCLI(executableURL: binary), config: config)

        store.search(query: "first", status: nil)
        store.search(query: "second", status: nil)
        try await Task.sleep(for: .milliseconds(700))

        XCTAssertEqual(store.items.map(\.id), ["second"])
        defaults.removePersistentDomain(forName: suiteName)
    }

    func testRuntimeRefreshKeepsOlderPageCursor() async throws {
        let binary = tmp.appendingPathComponent("gulls")
        let countFile = tmp.appendingPathComponent("calls")
        try """
        #!/bin/bash
        if [[ "$*" == *"history summary"* ]]; then
          printf '{"total_deliveries":0,"pending_deliveries":0,"distinct_threads":0,"distinct_senders":0,"daily_received":[],"relationships":[],"sync_complete":true}'
          exit 0
        fi
        count=$(($(cat "\(countFile.path)" 2>/dev/null || echo 0) + 1)); echo "$count" > "\(countFile.path)"
        case "$count" in
          1) printf '{"items":[{"delivery":{"delivery_id":"newest","status":"replied"}}],"next_cursor":"cursor-1","sync_complete":false}' ;;
          2) printf '{"items":[{"delivery":{"delivery_id":"older-1","status":"replied"}}],"next_cursor":"cursor-2","sync_complete":false}' ;;
          3) printf '{"items":[{"delivery":{"delivery_id":"newest","status":"replied"}}],"next_cursor":"cursor-refresh","sync_complete":false}' ;;
          *) printf '{"items":[{"delivery":{"delivery_id":"older-2","status":"replied"}}],"next_cursor":"","sync_complete":true}' ;;
        esac
        """.write(to: binary, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)

        suiteName = "history-cursor-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        let config = GullsConfig(defaults: defaults)
        config.apiURL = "https://api.example.test"
        config.agentHandle = "@me:gulls.ai"
        let store = MessageHistoryStore(cli: GullsCLI(executableURL: binary), config: config)

        await store.loadInitial()
        await store.loadMore()
        store.noteRuntimeMetadata(total: 4, syncComplete: false, generation: 1)
        try await Task.sleep(for: .milliseconds(250))
        XCTAssertEqual(store.nextCursor, "cursor-2")
        await store.loadMore()

        XCTAssertEqual(store.items.map(\.id), ["newest", "older-1", "older-2"])
        defaults.removePersistentDomain(forName: suiteName)
    }

    func testBackgroundRefreshDoesNotCancelPendingSearch() async throws {
        let binary = tmp.appendingPathComponent("gulls")
        try """
        #!/bin/bash
        if [[ "$*" == *"history summary"* ]]; then
          printf '{"total_deliveries":0,"pending_deliveries":0,"distinct_threads":0,"distinct_senders":0,"daily_received":[],"relationships":[],"sync_complete":true}'
          exit 0
        fi
        query=""
        while [ "$#" -gt 0 ]; do
          if [ "$1" = "--query" ]; then query="$2"; shift 2; continue; fi
          shift
        done
        printf '{"items":[{"delivery":{"delivery_id":"%s","status":"replied"}}],"next_cursor":"","sync_complete":true}' "${query:-initial}"
        """.write(to: binary, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)

        suiteName = "history-refresh-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        let config = GullsConfig(defaults: defaults)
        config.apiURL = "https://api.example.test"
        config.agentHandle = "@me:gulls.ai"
        let store = MessageHistoryStore(cli: GullsCLI(executableURL: binary), config: config)
        await store.loadInitial()

        store.search(query: "needle", status: nil)
        store.noteRuntimeMetadata(total: 2, syncComplete: false, generation: 2)
        try await Task.sleep(for: .milliseconds(450))

        XCTAssertEqual(store.items.map(\.id), ["needle"])
        defaults.removePersistentDomain(forName: suiteName)
    }
}
