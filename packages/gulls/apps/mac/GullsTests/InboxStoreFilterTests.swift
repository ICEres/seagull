import XCTest
@testable import Gulls

@MainActor
final class InboxStoreFilterTests: XCTestCase {

    private func makeStore() -> InboxStore {
        InboxStore(cli: nil, config: GullsConfig(defaults: UserDefaults(suiteName: "filter-tests")!), notifier: Notifier())
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
}
