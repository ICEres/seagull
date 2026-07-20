import XCTest
@testable import Gulls

// Drives InboxStore.refresh() end to end against a fake gulls binary and a
// recording Notifier: notify-once diffing, first-run silent seeding, and
// withdrawal of deliveries decided elsewhere. The fake binary serves whatever
// inbox JSON the test last wrote, so refreshes see the queue "change".
@MainActor
final class InboxStoreNotificationTests: XCTestCase {

    private var tmp: URL!
    private var suiteName: String!
    private var defaults: UserDefaults!

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("InboxStoreNotificationTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
        suiteName = "inbox-notification-tests-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)!
    }

    override func tearDownWithError() throws {
        defaults.removePersistentDomain(forName: suiteName)
        try? FileManager.default.removeItem(at: tmp)
    }

    // Records instead of talking to UNUserNotificationCenter.
    private final class RecordingNotifier: Notifier {
        var notified: [String] = []
        var withdrawn: [String] = []

        override func notifyNewDelivery(id: String, sender: String, snippet: String?, draft: String?) {
            notified.append(id)
        }

        override func withdraw(deliveryIDs: [String]) {
            withdrawn.append(contentsOf: deliveryIDs)
        }
    }

    private func writeInbox(_ items: [(id: String, status: String)]) throws {
        let itemsJSON = items.map { item in
            """
            {"delivery": {"delivery_id": "\(item.id)", "status": "\(item.status)"},
             "message": {"sender_agent_id": "agent_test", "content_inline": "hello"}}
            """
        }.joined(separator: ",")
        try Data("{\"items\": [\(itemsJSON)]}".utf8)
            .write(to: tmp.appendingPathComponent("inbox.json"))
    }

    private func makeStore(notifier: Notifier, notifiedFile: URL) throws -> InboxStore {
        let binary = tmp.appendingPathComponent("gulls")
        let script = """
        #!/bin/bash
        case "$2" in
        inbox) cat "\(tmp.appendingPathComponent("inbox.json").path)" ;;
        draft-reply) printf '{"outcome":"no_response_rules","draft_sent":false,"delivery_decision_submitted":false}' ;;
        *) printf '{}' ;;
        esac
        """
        try script.write(to: binary, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)

        let config = GullsConfig(defaults: defaults)
        config.apiURL = "http://localhost:1"
        config.agentHandle = "@test:gulls.ai"
        config.contextDir = tmp.appendingPathComponent("context").path

        return InboxStore(
            cli: GullsCLI(executableURL: binary),
            config: config,
            notifier: notifier,
            notifiedStore: NotifiedSetStore(url: notifiedFile)
        )
    }

    private func refreshAndSettle(_ store: InboxStore) async {
        await store.refresh()
        await store.pendingNotificationTask?.value
    }

    func testFirstRunSeedsExistingQueueWithoutBanners() async throws {
        let notifier = RecordingNotifier()
        let notifiedFile = tmp.appendingPathComponent("notified.json") // absent → first run
        try writeInbox([("delivery_1", "delivered"), ("delivery_2", "delivered")])
        let store = try makeStore(notifier: notifier, notifiedFile: notifiedFile)

        await refreshAndSettle(store)
        XCTAssertEqual(store.items.count, 2)
        XCTAssertEqual(notifier.notified, [], "pre-existing queue must seed silently")

        // A delivery arriving after the seed does banner.
        try writeInbox([
            ("delivery_1", "delivered"), ("delivery_2", "delivered"), ("delivery_3", "delivered"),
        ])
        await refreshAndSettle(store)
        XCTAssertEqual(notifier.notified, ["delivery_3"])
    }

    func testNotifiesOncePerDeliveryAcrossRefreshes() async throws {
        let notifier = RecordingNotifier()
        let notifiedFile = tmp.appendingPathComponent("notified.json")
        try Data("[]".utf8).write(to: notifiedFile) // file exists → not a first run
        try writeInbox([("delivery_1", "delivered"), ("delivery_2", "delivered")])
        let store = try makeStore(notifier: notifier, notifiedFile: notifiedFile)

        await refreshAndSettle(store)
        XCTAssertEqual(notifier.notified, ["delivery_1", "delivery_2"])

        await refreshAndSettle(store)
        XCTAssertEqual(notifier.notified.count, 2, "already-notified deliveries must not re-banner")
    }

    func testOnlyAwaitingDeliveriesNotify() async throws {
        let notifier = RecordingNotifier()
        let notifiedFile = tmp.appendingPathComponent("notified.json")
        try Data("[]".utf8).write(to: notifiedFile)
        try writeInbox([("delivery_1", "delivered"), ("delivery_2", "replied")])
        let store = try makeStore(notifier: notifier, notifiedFile: notifiedFile)

        await refreshAndSettle(store)
        XCTAssertEqual(notifier.notified, ["delivery_1"])
    }

    func testWithdrawsDeliveriesDecidedElsewhere() async throws {
        let notifier = RecordingNotifier()
        let notifiedFile = tmp.appendingPathComponent("notified.json")
        try Data("[]".utf8).write(to: notifiedFile)
        try writeInbox([("delivery_1", "delivered")])
        let store = try makeStore(notifier: notifier, notifiedFile: notifiedFile)
        await refreshAndSettle(store)
        XCTAssertEqual(notifier.withdrawn, [])

        // Decided in the CLI / on another machine: banner must be withdrawn.
        try writeInbox([("delivery_1", "replied")])
        await refreshAndSettle(store)
        XCTAssertEqual(notifier.withdrawn, ["delivery_1"])
    }

    func testPausedNotificationsStillMarkAsSeen() async throws {
        let notifier = RecordingNotifier()
        let notifiedFile = tmp.appendingPathComponent("notified.json")
        try Data("[]".utf8).write(to: notifiedFile)
        try writeInbox([("delivery_1", "delivered")])
        let store = try makeStore(notifier: notifier, notifiedFile: notifiedFile)
        store.notificationsPaused = true

        await refreshAndSettle(store)
        XCTAssertEqual(notifier.notified, [])

        // Unpausing must not retroactively banner what arrived while paused.
        store.notificationsPaused = false
        await refreshAndSettle(store)
        XCTAssertEqual(notifier.notified, [])
    }
}
