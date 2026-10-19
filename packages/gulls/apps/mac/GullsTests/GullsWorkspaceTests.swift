import XCTest
@testable import Gulls

@MainActor
final class GullsWorkspaceTests: XCTestCase {
    private final class MemoryTokenStore: GullsTokenStore {
        var values: [String: String] = [:]
        func token(for profileID: String) -> String? { values[profileID] }
        func legacyToken() -> String? { nil }
        @discardableResult
        func setToken(_ token: String, for profileID: String) -> Bool {
            values[profileID] = token
            return true
        }
    }

    private final class RecordingNotifier: Notifier {
        var notified: [String] = []
        override func notifyNewDelivery(id: String, sender: String, snippet: String?, draft: String?) {
            notified.append(id)
        }
    }

    private func suite() -> UserDefaults {
        let name = "workspace-tests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        return defaults
    }

    private func item(_ id: String, status: String = "delivered", threadID: String? = nil) throws -> InboxItem {
        let threadField = threadID.map { ", \"thread_id\": \"\($0)\"" } ?? ""
        let raw = """
        {"delivery":{"delivery_id":"\(id)","status":"\(status)"\(threadField)},"message":{"sender_agent_id":"sender"}}
        """
        return try JSONDecoder().decode(InboxItem.self, from: Data(raw.utf8))
    }

    private func writeLocalRequest(for config: GullsConfig, id: String = UUID().uuidString) throws {
        let base = URL(fileURLWithPath: config.contextDir)
            .appendingPathComponent("local-actions", isDirectory: true)
            .appendingPathComponent("requests", isDirectory: true)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        let request = LocalActionRequest(
            requestID: id,
            gullHandle: config.agentHandle,
            kind: .readFile,
            createdAt: "2026-10-18T00:00:00Z",
            path: "/tmp/example.txt"
        )
        try JSONEncoder().encode(request)
            .write(to: base.appendingPathComponent("\(id).json"))
    }

    func testCreatesOneInboxPerOwnedProfileAndRoutesSelection() throws {
        let defaults = suite()
        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: MemoryTokenStore())
        let second = connections.add(displayName: "Second")
        let notifier = RecordingNotifier()
        let workspace = GullsWorkspace(
            connections: connections,
            cli: nil,
            notifier: notifier,
            notifiedDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString),
            localControlDefaults: defaults
        )

        XCTAssertEqual(workspace.inboxes.count, 2)
        workspace.inboxes[GullsConfig.defaultProfileID]!.items = [try item("default-delivery")]
        workspace.inboxes[second.profileID]!.items = [try item("second-delivery")]
        notifier.onSelectDelivery?("second-delivery")

        XCTAssertEqual(connections.selectedProfileID, second.profileID)
        XCTAssertEqual(workspace.selectedStore.selectedDeliveryID, "second-delivery")
        XCTAssertEqual(workspace.selectionRevision, 1)
    }

    func testRepeatedSelectionIncrementsRevision() throws {
        let defaults = suite()
        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: MemoryTokenStore())
        let notifier = RecordingNotifier()
        let workspace = GullsWorkspace(
            connections: connections,
            cli: nil,
            notifier: notifier,
            notifiedDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString),
            localControlDefaults: defaults
        )
        workspace.inboxes[GullsConfig.defaultProfileID]!.items = [try item("delivery")]

        XCTAssertTrue(workspace.selectDelivery(profileID: GullsConfig.defaultProfileID, deliveryID: "delivery"))
        XCTAssertTrue(workspace.selectDelivery(profileID: GullsConfig.defaultProfileID, deliveryID: "delivery"))
        XCTAssertEqual(workspace.selectionRevision, 2)
        XCTAssertEqual(workspace.selectedStore.selectedDeliveryID, "delivery")
    }

    func testInvalidSelectionLeavesStateUnchanged() throws {
        let defaults = suite()
        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: MemoryTokenStore())
        let second = connections.add(displayName: "Second")
        let workspace = GullsWorkspace(
            connections: connections,
            cli: nil,
            notifier: RecordingNotifier(),
            notifiedDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString),
            localControlDefaults: defaults
        )
        workspace.inboxes[second.profileID]!.items = [try item("valid")]
        XCTAssertTrue(workspace.selectDelivery(profileID: second.profileID, deliveryID: "valid"))
        let selectedProfile = connections.selectedProfileID
        let selectedDelivery = workspace.selectedStore.selectedDeliveryID
        let revision = workspace.selectionRevision

        XCTAssertFalse(workspace.selectDelivery(profileID: "missing", deliveryID: "valid"))
        XCTAssertFalse(workspace.selectDelivery(profileID: second.profileID, deliveryID: "missing"))
        XCTAssertEqual(connections.selectedProfileID, selectedProfile)
        XCTAssertEqual(workspace.selectedStore.selectedDeliveryID, selectedDelivery)
        XCTAssertEqual(workspace.selectionRevision, revision)
    }

    func testAttentionBadgeCountsConversationsAndKeepsUnknownAndFailedActionable() throws {
        let defaults = suite()
        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: MemoryTokenStore())
        let workspace = GullsWorkspace(
            connections: connections,
            cli: nil,
            notifier: RecordingNotifier(),
            notifiedDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString),
            localControlDefaults: defaults
        )
        workspace.inboxes[GullsConfig.defaultProfileID]!.items = [
            try item("pending-1", status: "delivered", threadID: "shared-thread"),
            try item("pending-2", status: "pending_action", threadID: "shared-thread"),
            try item("failed", status: "failed", threadID: "failed-thread"),
            try item("unknown", status: "future_state", threadID: "unknown-thread")
        ]

        XCTAssertEqual(workspace.awaitingCount, 1)
        XCTAssertEqual(workspace.attentionCount, 3)
    }

    func testConfigurationRevisionRecreatesStoreAndClearsOldItems() async throws {
        let defaults = suite()
        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: MemoryTokenStore())
        let config = connections.selectedConfig!
        config.apiURL = "https://api.example.test"
        config.agentHandle = "@default:gulls.ai"
        let workspace = GullsWorkspace(
            connections: connections,
            cli: nil,
            notifier: RecordingNotifier(),
            notifiedDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString),
            localControlDefaults: defaults
        )
        let original = workspace.inboxes[config.profileID]!
        original.items = [try item("stale-delivery")]
        await workspace.reconcile()
        config.apiURL = "https://api-2.example.test"
        await workspace.reconcile()

        XCTAssertFalse(original === workspace.inboxes[config.profileID])
        XCTAssertTrue(workspace.inboxes[config.profileID]!.items.isEmpty)
    }

    func testChangedConfigBeforeFirstReconcileRejectsStaleSelection() async throws {
        let defaults = suite()
        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: MemoryTokenStore())
        let config = connections.selectedConfig!
        config.apiURL = "https://api.example.test"
        config.agentHandle = "@default:gulls.ai"
        let workspace = GullsWorkspace(
            connections: connections,
            cli: nil,
            notifier: RecordingNotifier(),
            notifiedDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString),
            localControlDefaults: defaults
        )
        let original = workspace.inboxes[config.profileID]!
        original.items = [try item("stale-before-reconcile")]

        config.apiURL = "https://api-changed.example.test"

        XCTAssertFalse(workspace.selectDelivery(profileID: config.profileID, deliveryID: "stale-before-reconcile"))
        XCTAssertNil(original.selectedItem)
        XCTAssertEqual(workspace.attentionCount, 0, "stale rows must not remain in the dashboard projection")

        await workspace.reconcile()
        XCTAssertFalse(original === workspace.inboxes[config.profileID])
        XCTAssertTrue(workspace.inboxes[config.profileID]!.items.isEmpty)
    }

    func testAttentionCountGroupsThreadsAndExcludesRemovedProfileLocalRequests() throws {
        let defaults = suite()
        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: MemoryTokenStore())
        let first = connections.selectedConfig!
        first.apiURL = "https://api-one.example.test"
        first.agentHandle = "@one:gulls.ai"
        first.contextDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("gulls-one-\(UUID().uuidString)").path
        let second = connections.add(displayName: "Second")
        second.apiURL = "https://api-two.example.test"
        second.agentHandle = "@two:gulls.ai"
        second.contextDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("gulls-two-\(UUID().uuidString)").path

        let workspace = GullsWorkspace(
            connections: connections,
            cli: nil,
            notifier: RecordingNotifier(),
            notifiedDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString),
            localControlDefaults: defaults
        )
        workspace.inboxes[first.profileID]!.items = [
            try item("thread-one-a", threadID: "shared-thread"),
            try item("thread-one-b", threadID: "shared-thread")
        ]
        try writeLocalRequest(for: first)
        try writeLocalRequest(for: second)
        workspace.refreshLocalActions()

        XCTAssertEqual(workspace.attentionCount, 3, "one grouped conversation plus two local requests")

        XCTAssertTrue(connections.remove(profileID: second.profileID))
        workspace.synchronizeProfiles()
        XCTAssertEqual(workspace.attentionCount, 2, "removing one profile removes its local request from the count")
    }

    func testStopAllSuspendsTransportsWithoutDisablingDesiredMonitoring() async {
        let defaults = suite()
        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: MemoryTokenStore())
        let config = connections.selectedConfig!
        config.apiURL = "https://api.example.test"
        config.agentHandle = "@default:gulls.ai"
        config.monitoringEnabled = true
        let workspace = GullsWorkspace(connections: connections, cli: nil, notifier: RecordingNotifier(), localControlDefaults: defaults)

        await workspace.reconcile()
        workspace.stopAll()
        XCTAssertTrue(config.monitoringEnabled)
        XCTAssertFalse(workspace.inboxes[config.profileID]!.isMonitoring)
    }
}
