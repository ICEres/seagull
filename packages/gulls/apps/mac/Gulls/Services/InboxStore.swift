import AppKit
import Foundation
import Observation

// Projects inbox snapshots and delivery actions into the native UI. Production
// workspaces receive snapshots from the shared resident runtime. Standalone
// previews and CLI fixtures retain the one-shot polling path.
@MainActor
@Observable
final class InboxStore {

    let cli: GullsCLI?
    let config: GullsConfig
    let notifier: Notifier
    /// Revision of the connection this store was created for. The mutable
    /// config can change before GullsWorkspace has replaced the store.
    let connectionRevision: String
    @ObservationIgnored var onUpdateBadge: (() -> Void)?

    var items: [InboxItem] = []
    var selectedDeliveryID: String?
    var agent: Agent?
    var lastError: String?
    var lastRefresh: Date?
    var isRefreshing = false
    var notificationsPaused = false
    // Banners are readable on a locked screen, so message and draft text are
    // shown there only when the owner asks for it.
    var showContentInNotifications = false
    var filter: InboxFilter = .awaiting
    var searchText = ""
    var monitoringEnabled: Bool {
        didSet {
            if config.monitoringEnabled != monitoringEnabled { config.monitoringEnabled = monitoringEnabled }
        }
    }

    var isMonitoring: Bool {
        monitoringEnabled && (runtimeManaged
            ? ["connecting", "connected", "reconnecting"].contains(runtimeStatus)
            : pollTask != nil || streamState != .off)
    }

    private(set) var runtimeManaged = false
    private(set) var runtimeStatus = "stopped"

    var monitoringStatusText: String {
        guard config.isConfigured else { return "Needs setup" }
        guard isCurrent else { return "Connection changed" }
        guard monitoringEnabled else { return "Monitoring paused" }
        guard runtimeManaged else { return isMonitoring ? "Monitoring" : "Ready" }
        switch runtimeStatus {
        case "connecting": return "Connecting"
        case "connected": return "Monitoring"
        case "reconnecting": return "Reconnecting"
        case "authorization_required": return "Reconnect required"
        case "paused": return "Monitoring paused"
        default: return "Service unavailable"
        }
    }

    var isCurrent: Bool { connectionRevision == config.connectionRevision }

    // The list is a decision queue first: default to what's waiting on you.
    enum InboxFilter: String, CaseIterable, Identifiable {
        case awaiting = "Awaiting decision"
        case replied = "Replied"
        case acked = "Acked"
        case ignored = "Ignored"
        case all = "All"

        var id: String { rawValue }

        func matches(_ status: DeliveryStatus?) -> Bool {
            switch self {
            case .awaiting: return status == .delivered
            case .replied: return status == .replied
            case .acked: return status == .acked
            case .ignored: return status == .ignored
            case .all: return true
            }
        }
    }

    // Stream health, shown in the status menu (mirrored from StreamController).
    private(set) var streamState: StreamController.State = .off

    private let streamController = StreamController()
    private var pollTask: Task<Void, Never>?
    private var pendingRefresh = false
    private var isLoadingAgentProfile = false
    private var requestedRuntimeNotifications = false
    private let notifiedStore: NotifiedSetStore
    private var hasSeededFirstRun: Bool
    // Sequential banner/draft pipeline; exposed so tests can await it.
    private(set) var pendingNotificationTask: Task<Void, Never>?
    private var notificationGeneration = 0

    var filteredItems: [InboxItem] {
        guard isCurrent else { return [] }
        let query = searchText.trimmingCharacters(in: .whitespaces).lowercased()
        return items.filter { item in
            guard filter.matches(item.delivery.statusValue) else { return false }
            guard !query.isEmpty else { return true }
            return item.senderDisplay.lowercased().contains(query)
                || (item.bodyText?.lowercased().contains(query) ?? false)
        }
    }

    // The number that matters: deliveries still waiting on a human decision.
    var awaitingCount: Int {
        guard isCurrent else { return 0 }
        return items.filter { $0.delivery.statusValue == .delivered }.count
    }

    var selectedItem: InboxItem? {
        guard isCurrent else { return nil }
        guard let selectedDeliveryID else { return nil }
        return items.first { $0.id == selectedDeliveryID }
    }

    init(
        cli: GullsCLI?,
        config: GullsConfig,
        notifier: Notifier,
        notifiedStore: NotifiedSetStore = NotifiedSetStore()
    ) {
        self.cli = cli
        self.config = config
        self.notifier = notifier
        self.connectionRevision = config.connectionRevision
        self.notifiedStore = notifiedStore
        hasSeededFirstRun = notifiedStore.existedOnDisk
        monitoringEnabled = config.monitoringEnabled

        notifier.onSelectDelivery = { [weak self] deliveryID in
            self?.selectedDeliveryID = deliveryID
            NSApp.activate()
        }
        notifier.onReply = { [weak self] deliveryID, text in
            Task { await self?.reply(to: deliveryID, content: text) }
        }
        notifier.onAck = { [weak self] deliveryID in
            Task { await self?.ack(deliveryID) }
        }
        streamController.onStateChange = { [weak self] state in
            self?.streamState = state
        }
        streamController.onWake = { [weak self] in
            await self?.refresh()
        }
        streamController.onError = { [weak self] message in
            self?.lastError = message
        }
    }

    // MARK: - Refresh & polling

    func refresh() async {
        guard let cli, config.isConfigured, isCurrent else { return }
        // Coalesce instead of dropping: a wake-up arriving mid-refresh marks a
        // pending re-run, so no event is silently lost.
        if isRefreshing {
            pendingRefresh = true
            return
        }
        isRefreshing = true
        defer { isRefreshing = false }
        repeat {
            pendingRefresh = false
            let generation = notificationGeneration
            let revision = config.connectionRevision
            do {
                if runtimeManaged {
                    try await cli.refreshRuntime(profileID: config.profileID)
                    continue
                }
                let fetched = try await cli.inbox(limit: 100, environment: config.cliEnvironment())
                guard !Task.isCancelled, generation == notificationGeneration,
                      revision == config.connectionRevision, revision == connectionRevision else { return }
                acceptSnapshot(fetched, checkedAt: Date())
            } catch {
                guard !Task.isCancelled, generation == notificationGeneration,
                      revision == config.connectionRevision, revision == connectionRevision else { return }
                lastError = error.localizedDescription
            }
        } while pendingRefresh
    }

    func loadAgentProfile() async {
        guard let cli, config.isConfigured, isCurrent, !isLoadingAgentProfile else { return }
        isLoadingAgentProfile = true
        defer { isLoadingAgentProfile = false }
        let fetched = try? await cli.whoami(environment: config.cliEnvironment())
        guard isCurrent, !Task.isCancelled else { return }
        agent = fetched
    }

    func startPolling() {
        guard !runtimeManaged, isCurrent, pollTask == nil, cli != nil else { return }
        // Authorization must not gate the poll loop: the system prompt stays
        // open until the user answers, and polling should run regardless.
        Task { [notifier] in
            _ = await notifier.requestAuthorization()
        }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                let interval = self?.currentPollInterval ?? GullsConfig.defaultPollInterval
                try? await Task.sleep(for: .seconds(interval))
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    // Starts both local inbox monitoring paths. Monitoring only reads the
    // inbox and may notify the owner; it does not enable AI replies.
    func startMonitoring() {
        guard isCurrent else { return }
        if !monitoringEnabled { monitoringEnabled = true }
        if runtimeManaged {
            if runtimeStatus == "paused" || runtimeStatus == "stopped" { runtimeStatus = "connecting" }
            if !requestedRuntimeNotifications {
                requestedRuntimeNotifications = true
                Task { [notifier] in _ = await notifier.requestAuthorization() }
            }
            return
        }
        startPolling()
        startStreaming()
    }

    func stopMonitoring() {
        if monitoringEnabled { monitoringEnabled = false }
        stopPolling()
        stopStreaming()
        if runtimeManaged { runtimeStatus = "paused" }
        cancelNotificationPipeline()
    }

    // Stops transports for quit/reconfiguration while preserving the user's
    // desired monitoring setting for the next matching configuration.
    func suspendMonitoring() {
        stopPolling()
        stopStreaming()
        if runtimeManaged { runtimeStatus = "stopped" }
        cancelNotificationPipeline()
    }

    func useResidentRuntime() {
        if !runtimeManaged {
            stopPolling()
            stopStreaming()
            runtimeManaged = true
        }
        if runtimeStatus == "stopped" {
            runtimeStatus = monitoringEnabled ? "connecting" : "paused"
        }
    }

    func receiveRuntimeSnapshot(
        _ fetched: [InboxItem]?, status: String, error: String?, checkedAt: Date?
    ) {
        guard runtimeManaged, isCurrent, runtimeStatus != "stopped",
              monitoringEnabled || status == "paused" else { return }
        runtimeStatus = status
        lastError = error
        guard let fetched else { return }
        if status == "connected" {
            acceptSnapshot(fetched, checkedAt: checkedAt)
        } else {
            // A durable snapshot is useful offline, but only fresh successful
            // checks may seed or generate new-message notifications.
            items = fetched
            lastRefresh = checkedAt
            updateBadge()
        }
    }

    private func acceptSnapshot(_ fetched: [InboxItem], checkedAt: Date?) {
        items = fetched
        lastRefresh = checkedAt
        lastError = nil
        updateBadge()
        withdrawDecidedNotifications(fetched)
        if hasSeededFirstRun {
            notifyAboutNewItems(fetched)
        } else {
            notifiedStore.seed(fetched.filter { $0.delivery.statusValue == .delivered }.map(\.id))
            hasSeededFirstRun = true
        }
    }

    private func cancelNotificationPipeline() {
        notificationGeneration &+= 1
        pendingNotificationTask?.cancel()
        pendingNotificationTask = nil
    }

    // While the stream is healthy, polling is only the safety net — stretch it.
    private var currentPollInterval: Double {
        let base = max(config.pollInterval, 5)
        return streamState == .connected ? max(base, 90) : base
    }

    // MARK: - Streaming (push = wake-up, poll = truth)

    func startStreaming() {
        guard !runtimeManaged, isCurrent, let cli else { return }
        let streamURL = config.streamURL.trimmingCharacters(in: .whitespaces)
        guard !streamURL.isEmpty, config.isConfigured else { return }
        streamController.start(cli: cli) { [config] in
            config.cliEnvironment()
        }
    }

    func stopStreaming() {
        streamController.stop()
    }

    // MARK: - Badge & notifications

    private func updateBadge() {
        guard isCurrent else { return }
        if let onUpdateBadge {
            onUpdateBadge()
            return
        }
        let count = DashboardProjector.makeSnapshot(from: [DashboardProfileInput(
            profileID: config.profileID, handle: config.agentHandle,
            displayName: config.displayName, items: items
        )]).needsAttention.count
        NSApplication.shared.dockTile.badgeLabel = count > 0 ? String(count) : nil
    }

    // Deliveries decided anywhere (CLI, another machine) get their banners
    // withdrawn so notifications stay a trustworthy view of the queue.
    private func withdrawDecidedNotifications(_ fetched: [InboxItem]) {
        let decided = fetched
            .filter { $0.delivery.statusValue != .delivered }
            .map(\.id)
        notifier.withdraw(deliveryIDs: decided)
    }

    private func notifyAboutNewItems(_ fetched: [InboxItem]) {
        // Only deliveries awaiting a decision are notification-worthy.
        let newItems = fetched.filter {
            $0.delivery.statusValue == .delivered && !notifiedStore.contains($0.id)
        }
        guard !newItems.isEmpty else { return }
        notifiedStore.insert(newItems.map(\.id))
        guard !notificationsPaused else { return }

        // One sequential pipeline instead of a task per item: draft-preview
        // generation shells out to the CLI, and a burst of new deliveries
        // must not fan out into a burst of subprocesses. Chained on any
        // still-running pipeline so banners keep arrival order.
        let previous = pendingNotificationTask
        let generation = notificationGeneration
        pendingNotificationTask = Task { [weak self] in
            await previous?.value
            guard !Task.isCancelled, let self, self.notificationGeneration == generation else { return }
            for item in newItems {
                guard !Task.isCancelled, self.notificationGeneration == generation else { return }
                await self.postNotification(for: item)
            }
        }
    }

    // Best-effort: generate the rule-based draft only to learn whether one
    // exists, so the banner can offer "Review draft". The text is not passed
    // to the notification. Any failure degrades to a plain notification —
    // generation has no server-side side effects.
    private func postNotification(for item: InboxItem) async {
        guard !Task.isCancelled else { return }
        var draft: String?
        if let result = try? await draftReply(for: item.id, approve: false),
           result.outcome == "draft_reply" {
            draft = result.draft
        }
        guard !Task.isCancelled else { return }
        notifier.showsContentPreview = showContentInNotifications
        notifier.notifyNewDelivery(
            id: item.id,
            sender: item.senderDisplay,
            snippet: item.bodyText,
            draft: draft
        )
    }

    // MARK: - Delivery actions

    @discardableResult
    func reply(to deliveryID: String, content: String) async -> DecisionResult? {
        await performAction { cli, environment in
            try await cli.reply(id: deliveryID, content: content, environment: environment)
        }
    }

    func ack(_ deliveryID: String) async {
        _ = await performAction { cli, environment in
            try await cli.ack(id: deliveryID, environment: environment)
        }
    }

    @discardableResult
    func ignore(_ deliveryID: String) async -> DecisionResult? {
        await performAction { cli, environment in
            try await cli.ignore(id: deliveryID, environment: environment)
        }
    }

    func draftReply(
        for deliveryID: String,
        approve: Bool,
        expectDraft: String? = nil
    ) async throws -> DraftReplyResult {
        guard isCurrent else {
            throw GullsCLI.Failure.configuration("connection changed; refresh the Gull before acting")
        }
        guard let cli else { throw GullsCLI.Failure.launch("bundled gulls binary is missing") }
        let result = try await cli.draftReply(
            id: deliveryID,
            approve: approve,
            expectDraft: expectDraft,
            environment: config.cliEnvironment()
        )
        if approve {
            await refresh()
        }
        return result
    }

    @discardableResult
    func writeContextFile(for deliveryID: String) async -> OpenResult? {
        await performAction(refreshAfter: false) { cli, environment in
            try await cli.openDelivery(id: deliveryID, environment: environment)
        }
    }

    private func performAction<T>(
        refreshAfter: Bool = true,
        _ action: (GullsCLI, GullsCLI.Environment) async throws -> T
    ) async -> T? {
        guard isCurrent, let cli else { return nil }
        do {
            let result = try await action(cli, config.cliEnvironment())
            lastError = nil
            if refreshAfter {
                await refresh()
            }
            return result
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }
}
