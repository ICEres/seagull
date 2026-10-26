import XCTest
@testable import Gulls

@MainActor
final class InboxStoreFilterTests: XCTestCase {

    private var tmp: URL!
    private var suiteName: String!
    private var defaults: UserDefaults!

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("InboxStoreFilterTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
        suiteName = "filter-tests-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)!
    }

    override func tearDownWithError() throws {
        defaults.removePersistentDomain(forName: suiteName)
        try? FileManager.default.removeItem(at: tmp)
    }

    private func makeStore() -> InboxStore {
        InboxStore(
            cli: nil,
            config: GullsConfig(defaults: defaults),
            notifier: Notifier(),
            notifiedStore: NotifiedSetStore(url: tmp.appendingPathComponent("notified.json"))
        )
    }

    private func item(_ id: String, status: String, sender: String = "agent_alice", body: String = "hello") throws -> InboxItem {
        let json = """
        {"delivery": {"delivery_id": "\(id)", "status": "\(status)"},
         "message": {"sender_agent_id": "\(sender)", "content_inline": "\(body)"},
         "current_message": {"content_inline": "\(body)"}}
        """
        return try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    func testDefaultFilterIsDecisionQueue() throws {
        let store = makeStore()
        store.items = [
            try item("d1", status: "delivered"),
            try item("d2", status: "replied"),
            try item("d3", status: "delivered"),
            try item("d4", status: "acked"),
        ]

        XCTAssertEqual(store.filter, .awaiting)
        XCTAssertEqual(store.filteredItems.map(\.id), ["d1", "d3"])
        XCTAssertEqual(store.awaitingCount, 2)
    }

    func testFilterByStatusAndAll() throws {
        let store = makeStore()
        store.items = [
            try item("d1", status: "delivered"),
            try item("d2", status: "replied"),
            try item("d3", status: "ignored"),
        ]

        store.filter = .replied
        XCTAssertEqual(store.filteredItems.map(\.id), ["d2"])
        store.filter = .all
        XCTAssertEqual(store.filteredItems.count, 3)
    }

    func testUnknownStatusOnlyAppearsUnderAll() throws {
        // The hub may grow states this build doesn't know; they must not be
        // mistaken for any known state, but "All" still shows them.
        let store = makeStore()
        store.items = [
            try item("d1", status: "delivered"),
            try item("d2", status: "quarantined"),
        ]

        XCTAssertEqual(store.filteredItems.map(\.id), ["d1"])
        XCTAssertEqual(store.awaitingCount, 1)
        store.filter = .all
        XCTAssertEqual(store.filteredItems.count, 2)
    }

    func testSearchMatchesSenderAndBodyCaseInsensitively() throws {
        let store = makeStore()
        store.filter = .all
        store.items = [
            try item("d1", status: "delivered", sender: "agent_alice", body: "Deploy notes ready"),
            try item("d2", status: "delivered", sender: "agent_bob", body: "lunch?"),
        ]

        store.searchText = "DEPLOY"
        XCTAssertEqual(store.filteredItems.map(\.id), ["d1"])
        store.searchText = "bob"
        XCTAssertEqual(store.filteredItems.map(\.id), ["d2"])
        store.searchText = "nothing"
        XCTAssertEqual(store.filteredItems.count, 0)
    }

    func testReadableNameKeepsFullSenderIdentitySearchable() throws {
        let store = makeStore()
        store.items = [try JSONDecoder().decode(InboxItem.self, from: Data(#"{"delivery":{"delivery_id":"named","status":"delivered","sender_agent_id":"agent_fbe74eac41164338a1084be3882c2a2f"},"message":{"sender_handle":"@atlas:remote.example","sender_display_name":"Atlas"}}"#.utf8))]

        for query in ["Atlas", "@atlas:remote.example", "agent_fbe74eac41164338a1084be3882c2a2f"] {
            store.searchText = query
            XCTAssertEqual(store.filteredItems.map(\.id), ["named"], query)
        }
    }
}
