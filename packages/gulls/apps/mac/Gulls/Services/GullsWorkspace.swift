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
    private(set) var codexTasks: [String: CodexTaskStore] = [:]
    private(set) var selectionRevision = 0
    private(set) var runtimeError: String?
    @ObservationIgnored var onOpenWorkspace: (() -> Void)?
    private var appliedRevisions: [String: String] = [:]
    private var runtimeRequested = false
    private var acceptingRuntimeEvents = false
    private var reconciliationTask: Task<Void, Never>?
    private var reconciliationGeneration = 0

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
            if let control = localControls.removeValue(forKey: id) {
                control.enabled = false
                control.stop()
            }
            codexTasks.removeValue(forKey: id)?.suspendExecution()
            appliedRevisions.removeValue(forKey: id)
        }
        for config in connections.profiles where inboxes[config.profileID] == nil {
            inboxes[config.profileID] = makeInbox(config)
        }
        for config in connections.profiles where localControls[config.profileID] == nil {
            localControls[config.profileID] = LocalControlStore(config: config, defaults: localControlDefaults)
        }
        for config in connections.profiles where codexTasks[config.profileID] == nil {
            codexTasks[config.profileID] = CodexTaskStore(config: config, localControl: localControls[config.profileID], replyCLI: cli)
        }
        routeNotifications()
    }

    func reconcile() async {
        let previous = reconciliationTask
        let generation = reconciliationGeneration
        let task = Task { [weak self] in
            await previous?.value
            guard let self, generation == self.reconciliationGeneration else { return }
            await self.applyConfiguration(generation: generation)
        }
        reconciliationTask = task
        await task.value
    }

    private func applyConfiguration(generation: Int) async {
        synchronizeProfiles()
        for config in connections.profiles {
            let revision = config.connectionRevision
            let storeRevision = inboxes[config.profileID]?.connectionRevision
            if storeRevision != revision
                || appliedRevisions[config.profileID].map({ $0 != revision }) == true {
                inboxes[config.profileID]?.suspendMonitoring()
                localControls[config.profileID]?.stop()
                codexTasks[config.profileID]?.suspendExecution()
                codexTasks[config.profileID] = CodexTaskStore(config: config, localControl: localControls[config.profileID], replyCLI: cli)
                inboxes[config.profileID] = makeInbox(config)
                routeNotifications()
            }
            appliedRevisions[config.profileID] = revision
        }

        let configured = connections.profiles.filter(\.isConfigured)
        if let cli, !configured.isEmpty || runtimeRequested {
            runtimeRequested = true
            acceptingRuntimeEvents = true
            for config in configured {
                guard let store = inboxes[config.profileID] else { continue }
                store.useResidentRuntime()
                if config.monitoringEnabled { store.startMonitoring() }
            }
            let key = configurationKey
            do {
                try await cli.startRuntime { [weak self] event in
                    Task { @MainActor in self?.receiveRuntimeEvent(event) }
                }
                guard generation == reconciliationGeneration else { return }
                try await cli.configureRuntime(configured.map {
                    RuntimeProfile(id: $0.profileID, revision: $0.connectionRevision,
                                   environment: $0.cliEnvironment(), pollInterval: max($0.pollInterval, 5),
                                   monitoring: $0.monitoringEnabled)
                })
                runtimeError = nil
            } catch let failure as GullsCLI.Failure {
                guard generation == reconciliationGeneration else { return }
                runtimeError = failure.localizedDescription
                // Runtime configuration validation reports profile-specific
                // events before returning exit code 2. Preserve those events
                // so a bad Gull does not make healthy Gulls look unavailable.
                if case .configuration = failure {
                    // The per-profile events are authoritative here.
                } else {
                    for config in configured {
                        inboxes[config.profileID]?.receiveRuntimeSnapshot(
                            nil, status: "unavailable", error: failure.localizedDescription, checkedAt: nil
                        )
                    }
                }
            } catch {
                guard generation == reconciliationGeneration else { return }
                runtimeError = error.localizedDescription
                for config in configured {
                    inboxes[config.profileID]?.receiveRuntimeSnapshot(
                        nil, status: "unavailable", error: error.localizedDescription, checkedAt: nil
                    )
                }
            }
            guard key == configurationKey, acceptingRuntimeEvents,
                  generation == reconciliationGeneration else { return }
        }

        for config in connections.profiles {
            guard let store = inboxes[config.profileID] else { continue }
            guard config.isConfigured, config.monitoringEnabled else {
                if !store.runtimeManaged { store.suspendMonitoring() }
                continue
            }
            if store.agent == nil { Task { await store.loadAgentProfile() } }
            store.startMonitoring()
        }
        updateBadge()
    }

    func setMonitoring(_ enabled: Bool, profileID: String) {
        guard let store = inboxes[profileID] else { return }
        if enabled { store.startMonitoring() } else { store.stopMonitoring() }
    }

    func stopAll(forTermination: Bool = false) {
        reconciliationGeneration &+= 1
        acceptingRuntimeEvents = false
        // Remember that a service was configured so the next reconciliation
        // sends an empty configuration if all profiles were removed asleep.
        for store in inboxes.values { store.suspendMonitoring() }
        for control in localControls.values { control.stop(forTermination: forTermination) }
        for tasks in codexTasks.values { tasks.suspendExecution(revokeReplies: false) }
        CodexExecutionCoordinator.shared.shutdown()
    }

    func refreshLocalActions() {
        for control in localControls.values { control.refresh() }
        for tasks in codexTasks.values { tasks.refresh() }
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
              store.mergedItems.contains(where: { $0.id == deliveryID }) else { return false }
        guard connections.select(profileID: profileID) != nil else { return false }
        store.selectedDeliveryID = deliveryID
        selectionRevision += 1
        onOpenWorkspace?()
        NSApp.activate()
        return true
    }

    func receiveRuntimeEvent(_ event: RuntimeEvent) {
        guard acceptingRuntimeEvents,
              let store = inboxes[event.profileID], store.isCurrent,
              event.revision == store.connectionRevision else { return }
        store.receiveRuntimeSnapshot(
            event.inbox?.items,
            status: event.status.rawValue,
            error: event.error,
            checkedAt: event.checkedAt.flatMap(GullsDates.parse),
            historyTotal: event.inbox?.historyTotal,
            historySyncComplete: event.inbox?.historySyncComplete,
            historyGeneration: event.inbox?.historyGeneration
        )
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
        inbox.beforeOwnerDecision = { [weak self] deliveryID in
            guard let self, let tasks = self.codexTasks[config.profileID] else {
                throw CodexTaskStore.Failure("The Gull connection is no longer available.")
            }
            try await tasks.prepareOwnerDecision(deliveryID: deliveryID)
        }
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
            $0.isCurrent && $0.mergedItems.contains { $0.id == deliveryID }
        }
    }

    private var dashboardProfiles: [DashboardProfileInput] {
        connections.profiles.compactMap { config in
            guard let store = inboxes[config.profileID] else { return nil }
            return DashboardProfileInput(
                profileID: config.profileID,
                handle: config.agentHandle,
                displayName: config.displayName.isEmpty ? nil : config.displayName,
                items: store.isCurrent ? store.mergedItems : []
            )
        }
    }
}
