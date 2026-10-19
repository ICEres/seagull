import AppKit
import Foundation
import Observation

@MainActor
@Observable
final class GullsWorkspace {
    let connections: LocalConnectionsStore
    let cli: GullsCLI?
    let pairingSession: URLSession
    private let notifier: Notifier
    private let notifiedDirectory: URL?
    private let localControlDefaults: UserDefaults
    private(set) var inboxes: [String: InboxStore] = [:]
    private(set) var localControls: [String: LocalControlStore] = [:]
    private(set) var selectionRevision = 0
    private var appliedRevisions: [String: String] = [:]

    init(connections: LocalConnectionsStore, cli: GullsCLI?, notifier: Notifier,
         notifiedDirectory: URL? = nil, pairingSession: URLSession = .shared,
         localControlDefaults: UserDefaults = .standard) {
        self.connections = connections
        self.cli = cli
        self.notifier = notifier
        self.notifiedDirectory = notifiedDirectory
        self.pairingSession = pairingSession
        self.localControlDefaults = localControlDefaults
        synchronizeProfiles()
    }

    var selectedStore: InboxStore {
        inboxes[connections.selectedProfileID] ?? inboxes[GullsConfig.defaultProfileID]!
    }

    var configurationKey: [String] {
        connections.profiles.map {
            "\($0.profileID):\($0.connectionRevision):\($0.monitoringEnabled)"
        }
    }

    var awaitingCount: Int { inboxes.values.reduce(0) { $0 + $1.awaitingCount } }

    /// Number of work conversations that currently need owner attention.
    /// Multiple pending deliveries in one thread count as one conversation.
    var attentionCount: Int {
        DashboardProjector.makeSnapshot(from: dashboardProfiles).needsAttention.count
            + localControls.values.reduce(0) { $0 + $1.pendingRequests.count }
    }

    func synchronizeProfiles() {
        let ids = Set(connections.profiles.map(\.profileID))
        for id in Array(inboxes.keys) where !ids.contains(id) {
            inboxes.removeValue(forKey: id)?.suspendMonitoring()
            localControls.removeValue(forKey: id)?.stop()
            appliedRevisions.removeValue(forKey: id)
        }
        for config in connections.profiles where inboxes[config.profileID] == nil {
            inboxes[config.profileID] = makeInbox(config)
        }
        for config in connections.profiles where localControls[config.profileID] == nil {
            localControls[config.profileID] = LocalControlStore(config: config, defaults: localControlDefaults)
        }
        routeNotifications()
    }

    func reconcile() async {
        synchronizeProfiles()
        for config in connections.profiles {
            let revision = config.connectionRevision
            let storeRevision = inboxes[config.profileID]?.connectionRevision
            if storeRevision != revision
                || appliedRevisions[config.profileID].map({ $0 != revision }) == true {
                inboxes[config.profileID]?.suspendMonitoring()
                inboxes[config.profileID] = makeInbox(config)
                routeNotifications()
            }
            appliedRevisions[config.profileID] = revision
            guard let store = inboxes[config.profileID] else { continue }
            guard config.isConfigured, config.monitoringEnabled else {
                store.suspendMonitoring()
                continue
            }
            if store.agent == nil { await store.loadAgentProfile() }
            guard !Task.isCancelled else { return }
            guard config.connectionRevision == revision,
                  connections.profiles.contains(where: { $0.profileID == config.profileID }) else { continue }
            store.startMonitoring()
        }
        updateBadge()
    }

    func setMonitoring(_ enabled: Bool, profileID: String) {
        guard let store = inboxes[profileID] else { return }
        if enabled { store.startMonitoring() } else { store.stopMonitoring() }
    }

    func stopAll() {
        for store in inboxes.values { store.suspendMonitoring() }
        for control in localControls.values { control.stop() }
    }

    func refreshLocalActions() {
        for control in localControls.values { control.refresh() }
    }

    func updateBadge() {
        NSApp.dockTile.badgeLabel = attentionCount > 0 ? String(attentionCount) : nil
    }

    /// Select a delivery in a specific owned Gull's inbox.
    ///
    /// Selection is revisioned so repeated notifications for the same delivery
    /// still produce a distinct observable navigation event.
    @discardableResult
    func selectDelivery(profileID: String, deliveryID: String) -> Bool {
        guard let store = inboxes[profileID],
              store.isCurrent,
              store.items.contains(where: { $0.id == deliveryID }) else { return false }
        guard connections.select(profileID: profileID) != nil else { return false }
        store.selectedDeliveryID = deliveryID
        selectionRevision += 1
        NSApp.activate()
        return true
    }

    private func makeInbox(_ config: GullsConfig) -> InboxStore {
        let notifiedURL: URL
        if let notifiedDirectory {
            notifiedURL = notifiedDirectory.appendingPathComponent("\(config.profileID).json")
        } else {
            notifiedURL = config.profileID == GullsConfig.defaultProfileID
                ? NotifiedSetStore.defaultURL
                : config.cliEnvironment().contextDir.appendingPathComponent("mac-notified-deliveries.json")
        }
        let inbox = InboxStore(cli: cli, config: config, notifier: notifier,
                               notifiedStore: NotifiedSetStore(url: notifiedURL))
        inbox.onUpdateBadge = { [weak self] in self?.updateBadge() }
        return inbox
    }

    private func routeNotifications() {
        notifier.onSelectDelivery = { [weak self] id in
            guard let self, let store = self.inbox(containing: id) else { return }
            _ = self.selectDelivery(profileID: store.config.profileID, deliveryID: id)
        }
        notifier.onReply = { [weak self] id, text in
            guard let store = self?.inbox(containing: id) else { return }
            Task { await store.reply(to: id, content: text) }
        }
        notifier.onAck = { [weak self] id in
            guard let store = self?.inbox(containing: id) else { return }
            Task { await store.ack(id) }
        }
    }

    private func inbox(containing deliveryID: String) -> InboxStore? {
        inboxes.values.first {
            $0.isCurrent && $0.items.contains { $0.id == deliveryID }
        }
    }

    private var dashboardProfiles: [DashboardProfileInput] {
        connections.profiles.compactMap { config in
            guard let store = inboxes[config.profileID] else { return nil }
            return DashboardProfileInput(
                profileID: config.profileID,
                handle: config.agentHandle,
                displayName: config.displayName.isEmpty ? nil : config.displayName,
                items: store.isCurrent ? store.items : []
            )
        }
    }
}
