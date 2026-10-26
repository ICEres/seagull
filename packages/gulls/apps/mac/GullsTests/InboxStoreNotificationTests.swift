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

    private final class MemoryTokenStore: GullsTokenStore {
        func token(for profileID: String) -> String? { nil }
        func legacyToken() -> String? { nil }
        @discardableResult
        func setToken(_ token: String, for profileID: String) -> Bool { true }
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

    private func makeStore(
        notifier: Notifier,
        notifiedFile: URL,
        inboxDelay: TimeInterval = 0,
        inboxStarted: URL? = nil
    ) throws -> InboxStore {
        let binary = tmp.appendingPathComponent("gulls")
        let startMarker = inboxStarted.map { "touch \"\($0.path)\"" } ?? ":"
        let script = """
        #!/bin/bash
        case "$2" in
        inbox) \(startMarker); sleep \(inboxDelay); cat "\(tmp.appendingPathComponent("inbox.json").path)" ;;
        draft-reply) printf '{"outcome":"no_response_rules","draft_sent":false,"delivery_decision_submitted":false}' ;;
        *) printf '{}' ;;
        esac
        """
        try script.write(to: binary, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)

        let config = GullsConfig(defaults: defaults, tokenStore: MemoryTokenStore())
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

    private func makeFailingStore() throws -> InboxStore {
        let binary = tmp.appendingPathComponent("failing-gulls")
        let script = """
        #!/bin/bash
        printf 'fixture failure' >&2
        exit 1
        """
        try script.write(to: binary, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)

        let config = GullsConfig(defaults: defaults, tokenStore: MemoryTokenStore())
        config.apiURL = "http://localhost:1"
        config.agentHandle = "@test:gulls.ai"
        config.contextDir = tmp.appendingPathComponent("context").path

        return InboxStore(
            cli: GullsCLI(executableURL: binary),
            config: config,
            notifier: RecordingNotifier(),
            notifiedStore: NotifiedSetStore(url: tmp.appendingPathComponent("failing-notified.json"))
        )
    }

    private func makeContextStore(
        openDelay: TimeInterval = 0,
        openStarted: URL? = nil,
        openOutput: String = "{\"context_path\":\"/tmp/context.md\"}",
        openExitCode: Int = 0,
        configured: Bool = true,
        cli: GullsCLI? = nil
    ) throws -> InboxStore {
        let binary = tmp.appendingPathComponent("context-gulls")
        let startMarker = openStarted.map { "touch \"\($0.path)\"" } ?? ":"
        let script = """
        #!/bin/bash
        case "$2" in
        open) \(startMarker); sleep \(openDelay); if [ \(openExitCode) -ne 0 ]; then printf '%s' '\(openOutput)' >&2; else printf '%s' '\(openOutput)'; fi; exit \(openExitCode) ;;
        *) printf '{}' ;;
        esac
        """
        try script.write(to: binary, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)

        let config = GullsConfig(defaults: defaults, tokenStore: MemoryTokenStore())
        config.apiURL = configured ? "http://localhost:1" : ""
        config.agentHandle = configured ? "@test:gulls.ai" : ""
        config.contextDir = tmp.appendingPathComponent("context").path

        return InboxStore(
            cli: cli ?? GullsCLI(executableURL: binary),
            config: config,
            notifier: RecordingNotifier(),
            notifiedStore: NotifiedSetStore(url: tmp.appendingPathComponent("context-notified.json"))
        )
    }

    func testUserActionFailureIsAlertableButBackgroundRefreshFailureIsNot() async throws {
        let actionStore = try makeFailingStore()
        await actionStore.ack("delivery-1")

        XCTAssertEqual(actionStore.actionFailure?.title, "Couldn’t acknowledge message")
        XCTAssertEqual(actionStore.actionFailure?.message, "fixture failure")
        XCTAssertEqual(actionStore.lastError, "fixture failure")

        let refreshStore = try makeFailingStore()
        await refreshStore.refresh()

        XCTAssertNil(refreshStore.actionFailure)
        XCTAssertEqual(refreshStore.lastError, "fixture failure")
    }

    func testPrepareContextFileReturnsCLIErrorWithoutActionFailure() async throws {
        let store = try makeContextStore(openOutput: "fixture context failure", openExitCode: 1)

        do {
            _ = try await store.prepareContextFile(for: "delivery-1")
            XCTFail("expected context preparation to fail")
        } catch {
            XCTAssertEqual(error.localizedDescription, "fixture context failure")
        }

        XCTAssertNil(store.actionFailure)
    }

    func testPrepareContextFileReturnsCLIResult() async throws {
        let store = try makeContextStore(openOutput: "{\"context_path\":\"/tmp/delivery-1.md\"}")

        let result = try await store.prepareContextFile(for: "delivery-1")

        XCTAssertEqual(result.contextPath, "/tmp/delivery-1.md")
        XCTAssertNil(store.actionFailure)
    }

    func testPrepareContextFileRejectsResultAfterConnectionChanges() async throws {
        let started = tmp.appendingPathComponent("context-started")
        let store = try makeContextStore(openDelay: 0.25, openStarted: started)
        let task = Task { try await store.prepareContextFile(for: "delivery-1") }

        while !FileManager.default.fileExists(atPath: started.path) {
            try await Task.sleep(for: .milliseconds(10))
        }
        store.config.apiURL = "http://localhost:2"

        do {
            _ = try await task.value
            XCTFail("expected stale context result to be rejected")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("connection changed"))
        }
        XCTAssertNil(store.actionFailure)
    }

    func testPrepareContextFileReportsMissingCLIAndConfiguration() async throws {
        let configured = try makeContextStore()
        let missingCLI = InboxStore(
            cli: nil,
            config: configured.config,
            notifier: RecordingNotifier(),
            notifiedStore: NotifiedSetStore(url: tmp.appendingPathComponent("missing-cli.json"))
        )
        do {
            _ = try await missingCLI.prepareContextFile(for: "delivery-1")
            XCTFail("expected missing CLI failure")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("bundled gulls binary is missing"))
        }

        let unconfigured = try makeContextStore(configured: false)
        do {
            _ = try await unconfigured.prepareContextFile(for: "delivery-1")
            XCTFail("expected missing configuration failure")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("connection is not configured"))
        }
    }

    func testSuspendingDuringRefreshDiscardsStaleItemsAndNotifications() async throws {
        let notifier = RecordingNotifier()
        let notifiedFile = tmp.appendingPathComponent("notified.json")
        try Data("[]".utf8).write(to: notifiedFile)
        try writeInbox([("stale_delivery", "delivered")])
        let inboxStarted = tmp.appendingPathComponent("inbox-started")
        let store = try makeStore(
            notifier: notifier,
            notifiedFile: notifiedFile,
            inboxDelay: 0.25,
            inboxStarted: inboxStarted
        )

        let refreshTask = Task { await store.refresh() }
        while !FileManager.default.fileExists(atPath: inboxStarted.path) {
            try await Task.sleep(for: .milliseconds(10))
        }
        store.suspendMonitoring()
        await refreshTask.value
        await store.pendingNotificationTask?.value

        XCTAssertTrue(store.items.isEmpty, "a refresh completed after suspension must not publish stale items")
        XCTAssertTrue(notifier.notified.isEmpty, "a suspended refresh must not enqueue notifications")
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

    func testResidentSnapshotsSeedSilentlyAndNotifyOnlyNewDeliveries() async throws {
        let notifier = RecordingNotifier()
        let store = try makeStore(notifier: notifier, notifiedFile: tmp.appendingPathComponent("resident-notified.json"))
        store.useResidentRuntime()
        let existing = try runtimeItems([("existing", "delivered")])
        store.receiveRuntimeSnapshot(existing, status: "connected", error: nil, checkedAt: Date())
        await store.pendingNotificationTask?.value
        XCTAssertTrue(notifier.notified.isEmpty)

        let updated = try runtimeItems([("existing", "delivered"), ("new", "delivered")])
        store.receiveRuntimeSnapshot(updated, status: "connected", error: nil, checkedAt: Date())
        await store.pendingNotificationTask?.value
        store.receiveRuntimeSnapshot(updated, status: "connected", error: nil, checkedAt: Date())
        await store.pendingNotificationTask?.value

        XCTAssertEqual(store.items.map(\.id), ["existing", "new"])
        XCTAssertEqual(notifier.notified, ["new"])
        XCTAssertTrue(store.isMonitoring)
    }

    func testResidentSnapshotsAfterPauseOrShutdownDoNotNotify() async throws {
        let notifier = RecordingNotifier()
        let store = try makeStore(notifier: notifier, notifiedFile: tmp.appendingPathComponent("resident-paused.json"))
        store.useResidentRuntime()
        store.stopMonitoring()
        let late = try runtimeItems([("late", "delivered")])
        store.receiveRuntimeSnapshot(late, status: "connected", error: nil, checkedAt: Date())
        XCTAssertTrue(store.items.isEmpty)
        XCTAssertFalse(store.isMonitoring)

        store.monitoringEnabled = true
        store.suspendMonitoring()
        store.receiveRuntimeSnapshot(late, status: "connected", error: nil, checkedAt: Date())
        XCTAssertTrue(store.items.isEmpty)
        XCTAssertTrue(notifier.notified.isEmpty)
    }

    func testResidentOfflineCacheDoesNotAnnounceOldMessages() async throws {
        let notifier = RecordingNotifier()
        let store = try makeStore(notifier: notifier, notifiedFile: tmp.appendingPathComponent("resident-cache.json"))
        store.useResidentRuntime()
        let cached = try runtimeItems([("cached", "delivered")])
        store.receiveRuntimeSnapshot(cached, status: "reconnecting", error: "Offline", checkedAt: nil)

        XCTAssertEqual(store.items.map(\.id), ["cached"])
        XCTAssertEqual(store.lastError, "Offline")
        XCTAssertTrue(notifier.notified.isEmpty)

        store.config.apiURL = "http://localhost:2"
        store.receiveRuntimeSnapshot([], status: "connected", error: nil, checkedAt: Date())
        XCTAssertEqual(store.items.map(\.id), ["cached"], "a replaced connection must ignore late snapshots")
    }

    func testResidentManualSnapshotWhilePausedDoesNotResumeOrNotify() async throws {
        let notifier = RecordingNotifier()
        let store = try makeStore(notifier: notifier, notifiedFile: tmp.appendingPathComponent("resident-manual.json"))
        store.useResidentRuntime()
        store.stopMonitoring()
        store.suspendMonitoring()
        store.useResidentRuntime()
        let fetched = try runtimeItems([("manual", "delivered")])

        store.receiveRuntimeSnapshot(fetched, status: "paused", error: nil, checkedAt: Date())

        XCTAssertEqual(store.items.map(\.id), ["manual"])
        XCTAssertFalse(store.isMonitoring)
        XCTAssertFalse(store.config.monitoringEnabled)
        XCTAssertTrue(notifier.notified.isEmpty)
    }

    func testUnavailableResidentServiceIsNotShownAsMonitoring() throws {
        let store = try makeStore(notifier: RecordingNotifier(), notifiedFile: tmp.appendingPathComponent("resident-unavailable.json"))
        store.useResidentRuntime()
        store.receiveRuntimeSnapshot(nil, status: "unavailable", error: "Service stopped", checkedAt: nil)

        XCTAssertFalse(store.isMonitoring)
        XCTAssertTrue(store.config.monitoringEnabled, "the desired monitoring preference must survive a service failure")
        XCTAssertEqual(store.monitoringStatusText, "Service unavailable")
    }

    private func runtimeItems(_ items: [(String, String)]) throws -> [InboxItem] {
        try items.map { id, status in
            try JSONDecoder().decode(InboxItem.self, from: Data("""
            {"delivery":{"delivery_id":"\(id)","status":"\(status)"}}
            """.utf8))
        }
    }
}
