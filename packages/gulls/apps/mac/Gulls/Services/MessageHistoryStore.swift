import Foundation
import Observation

/// Reads the runtime's durable message history. The Mac never opens the
/// SQLite file directly; the runtime owns migrations, caching and sync.
@MainActor
@Observable
final class MessageHistoryStore {
    enum Failure: Error, LocalizedError {
        case staleConnection

        var errorDescription: String? {
            switch self {
            case .staleConnection: return "This Gull connection changed. Reload its history."
            }
        }
    }

    let cli: GullsCLI?
    let config: GullsConfig
    let connectionRevision: String

    private(set) var items: [InboxItem] = []
    private(set) var nextCursor: String?
    private(set) var total: Int?
    private(set) var syncComplete = false
    private(set) var isLoading = false
    private(set) var lastError: String?
    private(set) var summary: MessageHistorySummary?
    private(set) var isLoadingSummary = false

    private var loadedQuery = ""
    private var loadedStatus: String?
    private var loadedThreadID: String?
    private var requestedQuery = ""
    private var requestedStatus: String?
    private var hasLoadedFirstPage = false
    private var generation = 0
    private var searchTask: Task<Void, Never>?
    private var pendingRequest: (query: String, status: String?, generation: Int)?
    private var pendingRefresh = false

    init(cli: GullsCLI?, config: GullsConfig) {
        self.cli = cli
        self.config = config
        self.connectionRevision = config.connectionRevision
    }

    var isCurrent: Bool { config.connectionRevision == connectionRevision }

    func hasLoaded(query: String, status: String?) -> Bool {
        loadedQuery.caseInsensitiveCompare(query.trimmingCharacters(in: .whitespacesAndNewlines)) == .orderedSame
            && loadedStatus == status
    }

    func loadInitial() async {
        guard isCurrent, !hasLoadedFirstPage else { return }
        await load(query: loadedQuery, status: loadedStatus, threadID: nil, reset: true)
        await loadSummary()
    }

    /// Debounced search entry point used by the Messages list.
    func search(query: String, status: String?) {
        let normalized = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard normalized != requestedQuery || status != requestedStatus else { return }
        requestedQuery = normalized
        requestedStatus = status
        generation &+= 1
        searchTask?.cancel()
        let generation = generation
        searchTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(180))
            guard !Task.isCancelled, let self else { return }
            self.request(query: normalized, status: status, generation: generation, reset: true)
        }
    }

    /// Called when the runtime imports more durable history. The first page
    /// is refreshed and merged with already loaded pages, so scrolling/search
    /// does not jump backwards or discard older cached rows.
    func refreshCurrent() {
        guard hasLoadedFirstPage else { return }
        // A debounced search is authoritative. Do not invalidate it by
        // refreshing the previous query when a runtime import arrives.
        guard requestedQuery == loadedQuery, requestedStatus == loadedStatus else {
            pendingRefresh = true
            return
        }
        if isLoading {
            pendingRefresh = true
            return
        }
        generation &+= 1
        request(query: loadedQuery, status: loadedStatus, generation: generation,
                reset: false, preservePages: true)
    }

    func noteRuntimeMetadata(total: Int?, syncComplete: Bool?, generation: Int?) {
        if let total { self.total = total }
        if let syncComplete { self.syncComplete = syncComplete }
        guard let generation else { return }
        guard generation != runtimeGeneration else { return }
        runtimeGeneration = generation
        refreshCurrent()
        Task { await loadSummary() }
    }

    func loadMore() async {
        guard isCurrent, !isLoading, let nextCursor, !nextCursor.isEmpty else { return }
        await load(query: loadedQuery, status: loadedStatus, threadID: loadedThreadID,
                   cursor: nextCursor, reset: false)
    }

    func item(id: String) -> InboxItem? {
        items.first { $0.id == id }
    }

    func reset() {
        searchTask?.cancel()
        generation &+= 1
        pendingRequest = nil
        pendingRefresh = false
        items = []
        nextCursor = nil
        total = nil
        syncComplete = false
        lastError = nil
        summary = nil
        loadedQuery = ""
        loadedStatus = nil
        loadedThreadID = nil
        requestedQuery = ""
        requestedStatus = nil
        hasLoadedFirstPage = false
    }

    private var runtimeGeneration: Int?

    func loadSummary() async {
        guard isCurrent, let cli, !isLoadingSummary else { return }
        isLoadingSummary = true
        defer { isLoadingSummary = false }
        do {
            let result = try await cli.historySummary(days: 7, environment: config.cliEnvironment())
            guard isCurrent, !Task.isCancelled else { return }
            summary = result
        } catch {
            // Preserve the last good summary while offline.
        }
    }

    private func request(query: String, status: String?, generation: Int,
                         reset: Bool, preservePages: Bool = false) {
        guard generation == self.generation, isCurrent else { return }
        if isLoading {
            pendingRequest = (query, status, generation)
            if preservePages { pendingRefresh = true }
            return
        }
        Task { [weak self] in
            await self?.load(query: query, status: status, threadID: nil,
                             reset: reset, preservePages: preservePages,
                             expectedGeneration: generation)
        }
    }

    private func load(query: String, status: String?, threadID: String?, cursor: String? = nil,
                      reset: Bool, preservePages: Bool = false,
                      expectedGeneration: Int? = nil) async {
        guard isCurrent, let cli else { return }
        guard expectedGeneration == nil || expectedGeneration == generation else { return }
        if isLoading { return }
        isLoading = true
        defer {
            isLoading = false
            if let pendingRequest {
                self.pendingRequest = nil
                request(query: pendingRequest.query, status: pendingRequest.status,
                        generation: pendingRequest.generation, reset: true)
            } else if pendingRefresh {
                pendingRefresh = false
                refreshCurrent()
            }
        }
        let requestGeneration = generation
        let requestRevision = connectionRevision
        let previousCursor = nextCursor
        let previousFirstID = items.first?.id
        do {
            let page = try await cli.history(limit: 50, cursor: cursor, query: query,
                                             status: status, threadID: threadID,
                                             environment: config.cliEnvironment())
            guard !Task.isCancelled, requestGeneration == generation,
                  requestRevision == config.connectionRevision, isCurrent else { return }
            if reset {
                items = page.items
            } else if preservePages {
                let pageIDs = Set(page.items.map(\.id))
                items = page.items + items.filter { !pageIDs.contains($0.id) }
            } else {
                let existing = Set(items.map(\.id))
                items.append(contentsOf: page.items.filter { !existing.contains($0.id) })
            }
            let pageCursor: String? = {
                guard let cursor = page.nextCursor?.trimmingCharacters(in: .whitespacesAndNewlines),
                      !cursor.isEmpty else { return nil }
                return cursor
            }()
            if preservePages, previousFirstID == page.items.first?.id {
                // If the refreshed head is unchanged, the existing boundary still
                // points at the next unread page. Keep it so loaded older rows remain reachable.
                nextCursor = previousCursor ?? pageCursor
            } else {
                // A moved head may have inserted rows before the old boundary.
                // Walk from the refreshed page cursor until that gap is consumed.
                nextCursor = pageCursor
            }
            total = page.total
            syncComplete = page.syncComplete ?? false
            loadedQuery = query
            loadedStatus = status
            loadedThreadID = threadID
            hasLoadedFirstPage = true
            lastError = nil
        } catch {
            guard !Task.isCancelled, requestGeneration == generation else { return }
            lastError = error.localizedDescription
        }
    }
}
