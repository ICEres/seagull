import AppKit
import Foundation
import Observation

// Observable inbox state + the polling loop. Polls `inbox --json` and diffs
// by delivery_id against an app-private notified-set. Deliberately does NOT
// use `watch --once`: that returns no item data and mutates the CLI's
// seen-deliveries.json/context files, which would silently suppress a
// concurrently running `gulls watch`.
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

        func matches(_ status: String?) -> Bool {
            switch self {
            case .awaiting: return status == "delivered"
            case .replied: return status == "replied"
            case .acked: return status == "acked"
            case .ignored: return status == "ignored"
            case .all: return true
            }
        }
    }

    // Stream health, shown in the status menu. .off = no stream URL configured.
    enum StreamState: Equatable {
        case off, connecting, connected, down
    }

    private(set) var streamState: StreamState = .off

    private var pollTask: Task<Void, Never>?
    private var streamTask: Task<Void, Never>?
    private var streamTerminate: (@Sendable () -> Void)?
    private var pendingRefresh = false
    private var notifiedIDs: Set<String>
    private let notifiedStoreURL: URL

    var filteredItems: [InboxItem] {
        let query = searchText.trimmingCharacters(in: .whitespaces).lowercased()
        return items.filter { item in
            guard filter.matches(item.delivery.status) else { return false }
            guard !query.isEmpty else { return true }
            return item.senderDisplay.lowercased().contains(query)
                || (item.bodyText?.lowercased().contains(query) ?? false)
        }
    }

    // The number that matters: deliveries still waiting on a human decision.
    var awaitingCount: Int {
        items.filter { $0.delivery.status == "delivered" }.count
    }

    var selectedItem: InboxItem? {
        guard let selectedDeliveryID else { return nil }
        return items.first { $0.id == selectedDeliveryID }
    }

    init(cli: GullsCLI?, config: GullsConfig, notifier: Notifier) {
        self.cli = cli
        self.config = config
        self.notifier = notifier
        notifiedStoreURL = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Gulls/notified-deliveries.json")
        notifiedIDs = Self.loadNotifiedIDs(from: notifiedStoreURL)
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
            // Sends exactly the previewed draft text as a human-approved
            // reply — never a regenerated draft the user hasn't seen.
            Task { await self?.reply(to: deliveryID, content: draft) }
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
                notifyAboutNewItems(fetched)
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
        guard streamTask == nil, let cli else { return }
        let streamURL = config.streamURL.trimmingCharacters(in: .whitespaces)
        guard !streamURL.isEmpty, config.isConfigured else { return }

        streamState = .connecting
        streamTask = Task { [weak self] in
            var backoff: Double = 5
            while !Task.isCancelled {
                guard let self else { return }
                do {
                    let handle = try await cli.openStream(environment: self.config.cliEnvironment())
                    self.streamTerminate = handle.terminate
                    for try await line in handle.lines {
                        if Task.isCancelled { break }
                        await self.handleStreamLine(line)
                        backoff = 5
                    }
                } catch {
                    self.lastError = error.localizedDescription
                }
                self.streamTerminate = nil
                if Task.isCancelled { return }
                // Subprocess exit is unexpected (it reconnects internally);
                // restart it with backoff.
                self.streamState = .down
                try? await Task.sleep(for: .seconds(backoff))
                backoff = min(backoff * 2, 60)
                if Task.isCancelled { return }
                self.streamState = .connecting
            }
        }
    }

    func stopStreaming() {
        streamTask?.cancel()
        streamTask = nil
        streamTerminate?()
        streamTerminate = nil
        streamState = .off
    }

    private func handleStreamLine(_ line: Data) async {
        guard let parsed = try? JSONDecoder().decode(StreamLine.self, from: line) else { return }
        switch parsed.type {
        case "stream.connected":
            streamState = .connected
            // Reconnect catch-up: one poll covers anything missed while down.
            await refresh()
        case "stream.event":
            await refresh()
        case "stream.disconnected":
            streamState = .connecting
        default:
            break
        }
    }

    // MARK: - Badge & notifications

    private func updateBadge() {
        let count = awaitingCount
        NSApplication.shared.dockTile.badgeLabel = count > 0 ? String(count) : nil
    }

    // Deliveries decided anywhere (CLI, another machine) get their banners
    // withdrawn so notifications stay a trustworthy view of the queue.
    private func withdrawDecidedNotifications(_ fetched: [InboxItem]) {
        for item in fetched where item.delivery.status != "delivered" {
            notifier.withdraw(deliveryID: item.id)
        }
    }

    private func notifyAboutNewItems(_ fetched: [InboxItem]) {
        var changed = false
        // Only deliveries awaiting a decision are notification-worthy.
        for item in fetched where !notifiedIDs.contains(item.id) && item.delivery.status == "delivered" {
            notifiedIDs.insert(item.id)
            changed = true
            if !notificationsPaused {
                notifyWithDraftPreview(item)
            }
        }
        if changed {
            persistNotifiedIDs()
        }
    }

    // Best-effort: try to generate the rule-based draft so the banner can
    // preview it and offer "Send draft". Any failure degrades to a plain
    // notification — generation has no server-side side effects.
    private func notifyWithDraftPreview(_ item: InboxItem) {
        Task { [weak self] in
            guard let self else { return }
            var draft: String?
            if let result = try? await self.draftReply(for: item.id, approve: false),
               result.outcome == "draft_reply" {
                draft = result.draft
            }
            self.notifier.notifyNewDelivery(
                id: item.id,
                sender: item.senderDisplay,
                snippet: item.bodyText,
                draft: draft
            )
        }
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

    // MARK: - Notified-set persistence

    private static func loadNotifiedIDs(from url: URL) -> Set<String> {
        guard let data = try? Data(contentsOf: url),
              let ids = try? JSONDecoder().decode([String].self, from: data) else {
            return []
        }
        return Set(ids)
    }

    private func persistNotifiedIDs() {
        let url = notifiedStoreURL
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        if let data = try? JSONEncoder().encode(notifiedIDs.sorted()) {
            try? data.write(to: url, options: .atomic)
        }
    }
}
