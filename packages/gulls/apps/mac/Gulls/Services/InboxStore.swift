import AppKit
import Foundation
import Observation

// Observable inbox state, delivery actions, and the polling loop. Polls
// `inbox --json` and diffs by delivery_id against the app-private
// NotifiedSetStore. Deliberately does NOT use `watch --once`: that returns no
// item data and mutates the CLI's seen-deliveries.json/context files, which
// would silently suppress a concurrently running `gulls watch`.
//
// Stream lifecycle lives in StreamController; notified-set persistence lives
// in NotifiedSetStore. This class owns state, the poll loop, and the
// notification diffing between them.
@MainActor
@Observable
final class InboxStore {

    let cli: GullsCLI?
    let config: GullsConfig
    let notifier: Notifier

    var items: [InboxItem] = []
    var selectedDeliveryID: String?
    var agent: Agent?
    var lastError: String?
    var lastRefresh: Date?
    var isRefreshing = false
    var notificationsPaused = false
    var filter: InboxFilter = .awaiting
    var searchText = ""

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
    private let notifiedStore: NotifiedSetStore
    private var hasSeededFirstRun: Bool
    // Sequential banner/draft pipeline; exposed so tests can await it.
    private(set) var pendingNotificationTask: Task<Void, Never>?

    var filteredItems: [InboxItem] {
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
        items.filter { $0.delivery.statusValue == .delivered }.count
    }

    var selectedItem: InboxItem? {
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
        self.notifiedStore = notifiedStore
        hasSeededFirstRun = notifiedStore.existedOnDisk

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
        notifier.onSendDraft = { [weak self] deliveryID, draft in
            // Sends exactly the draft text carried by the notification — the
            // full generated draft, never a regenerated one.
            Task { await self?.reply(to: deliveryID, content: draft) }
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
        guard let cli, config.isConfigured else { return }
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
            do {
                let fetched = try await cli.inbox(limit: 100, environment: config.cliEnvironment())
                items = fetched
                lastRefresh = Date()
                lastError = nil
                updateBadge()
                withdrawDecidedNotifications(fetched)
                if hasSeededFirstRun {
                    notifyAboutNewItems(fetched)
                } else {
                    // First run: mark the pre-existing queue as known instead
                    // of bannering every old delivery at once. Banners are for
                    // deliveries that arrive from here on.
                    notifiedStore.seed(
                        fetched.filter { $0.delivery.statusValue == .delivered }.map(\.id)
                    )
                    hasSeededFirstRun = true
                }
            } catch {
                lastError = error.localizedDescription
            }
        } while pendingRefresh
    }

    func loadAgentProfile() async {
        guard let cli, config.isConfigured else { return }
        agent = try? await cli.whoami(environment: config.cliEnvironment())
    }

    func startPolling() {
        guard pollTask == nil, cli != nil else { return }
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

    // While the stream is healthy, polling is only the safety net — stretch it.
    private var currentPollInterval: Double {
        let base = max(config.pollInterval, 5)
        return streamState == .connected ? max(base, 90) : base
    }

    // MARK: - Streaming (push = wake-up, poll = truth)

    func startStreaming() {
        guard let cli else { return }
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
        let count = awaitingCount
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
        pendingNotificationTask = Task { [weak self] in
            await previous?.value
            for item in newItems {
                guard let self else { return }
                await self.postNotification(for: item)
            }
        }
    }

    // Best-effort: try to generate the rule-based draft so the banner can
    // preview it and offer "Send draft". Any failure degrades to a plain
    // notification — generation has no server-side side effects.
    private func postNotification(for item: InboxItem) async {
        var draft: String?
        if let result = try? await draftReply(for: item.id, approve: false),
           result.outcome == "draft_reply" {
            draft = result.draft
        }
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

    func draftReply(for deliveryID: String, approve: Bool) async throws -> DraftReplyResult {
        guard let cli else { throw GullsCLI.Failure.launch("bundled gulls binary is missing") }
        let result = try await cli.draftReply(id: deliveryID, approve: approve, environment: config.cliEnvironment())
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
        guard let cli else { return nil }
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
