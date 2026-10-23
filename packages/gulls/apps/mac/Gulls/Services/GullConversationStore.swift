import Foundation
import Observation

private struct PersistedConversationScope: Codable, Sendable {
    var messages: [String: [GullConversationMessage]]
    var cursors: [String: String]
    var pending: [String: [GullConversationStore.PendingOutgoing]]
    var pageStates: [String: GullConversationStore.PageState]? = nil
    var threadBindings: [String: String]? = nil
    var version: Int? = 2
}

private actor ConversationCachePersistence {
    let url: URL
    private var savedRevision = 0
    init(url: URL) { self.url = url }

    func load() -> [String: PersistedConversationScope] {
        guard let data = try? Data(contentsOf: url),
              let values = try? JSONDecoder().decode([String: PersistedConversationScope].self, from: data) else { return [:] }
        return values
    }

    func save(_ values: [String: PersistedConversationScope], revision: Int) -> Bool {
        guard revision > savedRevision else { return true }
        guard let data = try? JSONEncoder().encode(values) else { return false }
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: url, options: .atomic)
            savedRevision = revision
            return true
        } catch { return false }
    }
}

enum GullConversationError: Error, LocalizedError, Equatable {
    case unavailable
    case invalidRecipient
    case invalidMessage
    case staleSelection
    case conversationNotFound
    case pendingExpired
    case cacheUnavailable
    case invalidAcknowledgement
    case legacyPending
    case paginationLoop

    var errorDescription: String? {
        switch self {
        case .unavailable: return "The bundled Gulls CLI is unavailable."
        case .invalidRecipient: return "Choose a recipient before starting the conversation."
        case .invalidMessage: return "Enter a message before sending."
        case .staleSelection: return "The selected Gull connection changed. Reload it before sending."
        case .conversationNotFound: return "The conversation is no longer available."
        case .pendingExpired: return "This unsent message is older than the retry window. Review it and send again."
        case .cacheUnavailable: return "This message could not be saved locally. Check available disk space and try again."
        case .invalidAcknowledgement: return "The server response did not confirm this message's conversation. Review it before retrying."
        case .legacyPending: return "This older pending message has no saved request details. Review the conversation before sending it again."
        case .paginationLoop: return "Message sync could not advance. Your saved messages are available; try syncing again."
        }
    }
}

@MainActor
@Observable
final class GullConversationStore {
    private static let persistenceKey = "gull.startedConversations.v1"
    struct PageState: Codable, Sendable {
        var initialized = false
        var historyCursor: String?
        var headID: String?
        var catchup: Catchup?
        var needsHistoryRebuild = false
        var historyBoundaryID: String?
    }

    struct Catchup: Codable, Sendable {
        var cursor: String
        var anchorID: String?
        var candidateHeadID: String?
        var rebuilding: Bool
        var visitedCursors: Set<String> = []
    }

    struct PreparedSend: Codable, Equatable, Sendable {
        let senderProfileID: String
        let senderHandle: String
        let connectionRevision: String
        let recipientHandle: String
        let content: String
        let idempotencyKey: String
        let threadID: String?
    }

    struct PendingOutgoing: Codable, Equatable, Identifiable, Sendable {
        let id: String
        let conversationID: String
        let content: String
        let createdAt: Date
        var state: PendingState
        var attemptCount: Int
        var lastError: String?
        var preparedRequest: PreparedSend?
        var acknowledgedMessageID: String?

        enum PendingState: String, Codable { case queued, sending, unconfirmed, failed }

        init(id: String, conversationID: String, content: String, createdAt: Date,
             state: PendingState = .queued, attemptCount: Int = 0, lastError: String? = nil,
             preparedRequest: PreparedSend? = nil, acknowledgedMessageID: String? = nil) {
            self.id = id; self.conversationID = conversationID; self.content = content; self.createdAt = createdAt
            self.state = state; self.attemptCount = attemptCount; self.lastError = lastError
            self.preparedRequest = preparedRequest; self.acknowledgedMessageID = acknowledgedMessageID
        }

        private enum CodingKeys: String, CodingKey {
            case id, conversationID, content, createdAt, state, attemptCount, lastError, preparedRequest, acknowledgedMessageID
        }
        init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            id = try values.decode(String.self, forKey: .id)
            conversationID = try values.decode(String.self, forKey: .conversationID)
            content = try values.decode(String.self, forKey: .content)
            createdAt = try values.decode(Date.self, forKey: .createdAt)
            state = try values.decodeIfPresent(PendingState.self, forKey: .state) ?? .queued
            attemptCount = try values.decodeIfPresent(Int.self, forKey: .attemptCount) ?? 0
            lastError = try values.decodeIfPresent(String.self, forKey: .lastError)
            preparedRequest = try values.decodeIfPresent(PreparedSend.self, forKey: .preparedRequest)
            acknowledgedMessageID = try values.decodeIfPresent(String.self, forKey: .acknowledgedMessageID)
        }
    }

    private let defaults: UserDefaults
    private let cli: GullsCLI?
    private(set) var activeScope: String?
    private(set) var conversations: [GullConversation] = []
    private(set) var messagesByConversationID: [String: [GullConversationMessage]] = [:]
    private(set) var nextCursorByConversationID: [String: String] = [:]
    private(set) var pendingByConversationID: [String: [PendingOutgoing]] = [:]
    private var scopeGeneration = 0
    private let cacheURL: URL
    private let cachePersistence: ConversationCachePersistence
    private var cachedScopes: [String: PersistedConversationScope] = [:]
    private let cacheHydration: Task<[String: PersistedConversationScope], Never>
    private var hydrationApplied = false
    private var appliedHydrationGeneration: Int?
    private var loadingConversationIDs: Set<String> = []
    private var pageStates: [String: PageState] = [:]
    private var threadBindings: [String: String] = [:]
    private var durablePendingIDs: Set<String> = []
    private var sendWorkers: [String: (id: UUID, task: Task<[GullConversationMessage], Error>)] = [:]
    private var pageWorkers: [String: (id: UUID, task: Task<[GullConversationMessage], Error>)] = [:]
    private var cacheRevision = 0

    init(cli: GullsCLI?, defaults: UserDefaults = .standard, cacheURL: URL? = nil) {
        self.cli = cli
        self.defaults = defaults
        self.cacheURL = cacheURL ?? Self.defaultCacheURL()
        let persistence = ConversationCachePersistence(url: self.cacheURL)
        self.cachePersistence = persistence
        self.cacheHydration = Task { await persistence.load() }
    }

    func activate(scope: String?) {
        for worker in sendWorkers.values { worker.task.cancel() }
        for worker in pageWorkers.values { worker.task.cancel() }
        sendWorkers.removeAll()
        pageWorkers.removeAll()
        scopeGeneration &+= 1
        activeScope = normalizedScope(scope)
        loadingConversationIDs.removeAll()
        conversations = loadPersisted()[activeScope ?? ""] ?? []
        messagesByConversationID = [:]
        nextCursorByConversationID = [:]
        pendingByConversationID = [:]
        pageStates = [:]
        threadBindings = [:]
        durablePendingIDs = []
        appliedHydrationGeneration = nil
        let generation = scopeGeneration
        Task { @MainActor [weak self] in
            guard let self else { return }
            let values = await self.hydrateCacheIfNeeded()
            guard generation == self.scopeGeneration else { return }
            guard self.appliedHydrationGeneration != generation else { return }
            self.applyCachedScope(values[self.activeScope ?? ""])
            self.appliedHydrationGeneration = generation
        }
    }

    func waitForCacheHydration() async {
        let generation = scopeGeneration
        let values = await hydrateCacheIfNeeded()
        guard generation == scopeGeneration else { return }
        if appliedHydrationGeneration != scopeGeneration {
            applyCachedScope(values[activeScope ?? ""])
            appliedHydrationGeneration = scopeGeneration
        }
    }

    func flushCache() async { _ = await persistCacheAndWait() }

    private func applyCachedScope(_ cached: PersistedConversationScope?) {
        let cachedMessages = cached?.messages ?? [:]
        var hydratedMessages = cachedMessages
        for (conversationID, current) in messagesByConversationID {
            hydratedMessages[conversationID] = merge(cachedMessages[conversationID] ?? [], with: current)
        }
        messagesByConversationID = hydratedMessages

        var restoredPages = cached?.pageStates ?? [:]
        if cached?.version != 2 {
            // Legacy cursors may already skip a truncated or disconnected range.
            for id in cachedMessages.keys {
                var page = PageState()
                page.needsHistoryRebuild = true
                restoredPages[id] = page
            }
        }
        pageStates.merge(restoredPages) { current, _ in current }
        nextCursorByConversationID = pageStates.compactMapValues(\.historyCursor)
        threadBindings.merge(cached?.threadBindings ?? [:]) { current, _ in current }
        for index in conversations.indices {
            if let threadID = threadBindings[conversations[index].id] { conversations[index].threadID = threadID }
        }

        let cachedPending = cached?.pending.mapValues { $0.map { pending in
            var pending = pending
            if pending.state == .sending || (pending.state == .queued &&
                (pending.attemptCount > 0 || pending.preparedRequest != nil)) {
                pending.state = .unconfirmed
            }
            if pending.attemptCount > 0, pending.preparedRequest == nil {
                pending.state = .unconfirmed
                pending.lastError = GullConversationError.legacyPending.localizedDescription
            }
            return pending
        }} ?? [:]
        var hydratedPending = cachedPending
        for (conversationID, current) in pendingByConversationID {
            let currentIDs = Set(current.map(\.id))
            hydratedPending[conversationID] = (cachedPending[conversationID] ?? []).filter { !currentIDs.contains($0.id) } + current
        }
        pendingByConversationID = hydratedPending
        durablePendingIDs.formUnion(cachedPending.values.flatMap { $0 }.map(\.id))
    }

    private func hydrateCacheIfNeeded() async -> [String: PersistedConversationScope] {
        let values = await cacheHydration.value
        if !hydrationApplied {
            cachedScopes = values
            hydrationApplied = true
        }
        return cachedScopes
    }

    func messages(for conversationID: String) -> [GullConversationMessage] {
        messagesByConversationID[conversationID] ?? []
    }

    var hasPendingMessages: Bool { pendingByConversationID.values.contains { !$0.isEmpty } }

    func pendingMessages(for conversationID: String) -> [String] {
        pendingByConversationID[conversationID, default: []].map(\.id)
    }

    func pendingMessage(_ id: String) -> PendingOutgoing? {
        pendingByConversationID.values.flatMap { $0 }.first { $0.id == id || $0.acknowledgedMessageID == id }
    }

    func sendQueued(environment: GullsCLI.Environment) async {
        let generation = scopeGeneration
        await waitForCacheHydration()
        guard generation == scopeGeneration else { return }
        for conversation in conversations where matches(conversation, environment: environment) {
            guard generation == scopeGeneration else { return }
            guard pendingByConversationID[conversation.id]?.first?.state == .queued else { continue }
            _ = try? await drain(conversation.id, environment: environment)
        }
    }

    @discardableResult
    func start(recipientHandle: String, recipientName: String? = nil, recipientAgentID: String? = nil,
               sender: GullConversationSender, scope: String? = nil) throws -> GullConversation {
        guard let recipient = SavedGull.canonicalHandle(recipientHandle) else {
            throw GullConversationError.invalidRecipient
        }
        let resolvedScope = normalizedScope(scope ?? activeScope)
        guard resolvedScope != nil else { throw GullConversationError.unavailable }
        if activeScope != resolvedScope { activate(scope: resolvedScope) }

        if let existingIndex = conversations.firstIndex(where: {
            $0.recipientHandle == recipient && $0.senderProfileID == sender.id
                && $0.connectionRevision == sender.connectionRevision
        }) {
            var existing = conversations[existingIndex]
            var changed = false
            if existing.recipientAgentID == nil, let recipientAgentID {
                existing.recipientAgentID = recipientAgentID
                changed = true
            }
            if existing.recipientName == nil, let recipientName {
                existing.recipientName = recipientName
                changed = true
            }
            if existing.senderAgentID == nil, let senderAgentID = sender.agentID {
                existing.senderAgentID = senderAgentID
                changed = true
            }
            if changed {
                existing.updatedAt = Date()
                conversations[existingIndex] = existing
                persist()
            }
            return existing
        }

        let now = Date()
        let conversation = GullConversation(
            id: UUID().uuidString,
            recipientHandle: recipient,
            recipientAgentID: recipientAgentID,
            recipientName: recipientName,
            senderProfileID: sender.id,
            senderHandle: sender.handle,
            senderAgentID: sender.agentID,
            connectionRevision: sender.connectionRevision,
            threadID: nil,
            createdAt: now,
            updatedAt: now
        )
        conversations.insert(conversation, at: 0)
        persist()
        return conversation
    }

    @discardableResult
    func open(_ conversationID: String, environment: GullsCLI.Environment) async throws -> [GullConversationMessage] {
        guard let conversation = self.conversation(conversationID) else { throw GullConversationError.conversationNotFound }
        guard matches(conversation, environment: environment) else { throw GullConversationError.staleSelection }
        guard let threadID = conversation.threadID else {
            persistCache()
            return messages(for: conversationID)
        }
        let cached = messages(for: conversationID)
        if !cached.isEmpty {
            guard loadingConversationIDs.insert(conversationID).inserted else { return cached }
            Task { [weak self] in
                guard let self else { return }
                defer { loadingConversationIDs.remove(conversationID) }
                _ = try? await self.load(conversationID, threadID: threadID, environment: environment)
            }
            return cached
        }
        return try await load(conversationID, threadID: threadID, environment: environment)
    }

    @discardableResult
    func load(_ conversationID: String, threadID: String, environment: GullsCLI.Environment) async throws -> [GullConversationMessage] {
        try await schedulePage(conversationID, threadID: threadID, older: false, environment: environment)
    }

    func hasMoreMessages(for conversationID: String) -> Bool {
        guard conversation(conversationID)?.threadID != nil else { return false }
        let page = pageStates[conversationID] ?? PageState()
        return !page.initialized || page.needsHistoryRebuild || page.catchup != nil || page.historyCursor != nil
    }

    @discardableResult
    func loadMore(_ conversationID: String, environment: GullsCLI.Environment) async throws -> [GullConversationMessage] {
        let generation = scopeGeneration
        await waitForCacheHydration()
        try validate(conversationID, environment: environment, generation: generation)
        guard let current = conversation(conversationID), matches(current, environment: environment) else {
            throw GullConversationError.staleSelection
        }
        guard let threadID = current.threadID else { return messages(for: conversationID) }
        return try await schedulePage(conversationID, threadID: threadID, older: true, environment: environment)
    }

    private func schedulePage(_ id: String, threadID: String, older: Bool,
                              environment: GullsCLI.Environment) async throws -> [GullConversationMessage] {
        let generation = scopeGeneration
        let previous = pageWorkers[id]?.task
        let token = UUID()
        let task = Task { @MainActor in
            _ = try? await previous?.value
            try self.validate(id, environment: environment, generation: generation)
            await self.waitForCacheHydration()
            try self.validate(id, environment: environment, generation: generation)
            return try await self.fetchPages(id, threadID: threadID, older: older, environment: environment, generation: generation)
        }
        pageWorkers[id] = (token, task)
        defer { if pageWorkers[id]?.id == token { pageWorkers.removeValue(forKey: id) } }
        return try await task.value
    }

    private func fetchPages(_ id: String, threadID: String, older: Bool, environment: GullsCLI.Environment,
                            generation: Int) async throws -> [GullConversationMessage] {
        guard let cli else { throw GullConversationError.unavailable }
        var page = pageStates[id] ?? PageState()
        var budget = 2
        // A pending catch-up owns its chain until the old head is reached.
        if page.catchup == nil {
            if older, page.initialized, !page.needsHistoryRebuild {
                guard let cursor = page.historyCursor else { return messages(for: id) }
                let result = try await cli.thread(id: threadID, limit: 100, cursor: cursor, environment: environment)
                try validate(id, environment: environment, generation: generation)
                guard result.nextCursor != cursor else { throw GullConversationError.paginationLoop }
                try mergePage(result, into: id, threadID: threadID)
                page.historyCursor = normalizedScope(result.nextCursor)
                try await savePage(page, id: id, environment: environment, generation: generation)
                return messages(for: id)
            }
            let result = try await cli.thread(id: threadID, limit: 100, environment: environment)
            try validate(id, environment: environment, generation: generation)
            try mergePage(result, into: id, threadID: threadID)
            budget -= 1
            let newHead = result.messages.last?.id
            let ids = Set(result.messages.map(\.id))
            let next = normalizedScope(result.nextCursor)
            if page.needsHistoryRebuild {
                let reachedBoundary = page.historyBoundaryID.map { ids.contains($0) } ?? false
                if reachedBoundary || next == nil {
                    page = PageState(initialized: true, historyCursor: next, headID: newHead)
                } else if let next {
                    page.catchup = Catchup(cursor: next, anchorID: page.historyBoundaryID,
                                           candidateHeadID: newHead, rebuilding: true)
                }
            } else if !page.initialized || page.headID == nil {
                page.initialized = true
                page.historyCursor = next
                page.headID = newHead
            } else if let anchor = page.headID, !ids.contains(anchor), let next {
                page.catchup = Catchup(cursor: next, anchorID: anchor, candidateHeadID: newHead, rebuilding: false)
            } else {
                page.headID = newHead
            }
            try await savePage(page, id: id, environment: environment, generation: generation)
        }
        while budget > 0, var catchup = page.catchup {
            guard !catchup.visitedCursors.contains(catchup.cursor) else { throw GullConversationError.paginationLoop }
            let cursor = catchup.cursor
            let result = try await cli.thread(id: threadID, limit: 100, cursor: cursor, environment: environment)
            try validate(id, environment: environment, generation: generation)
            let next = normalizedScope(result.nextCursor)
            guard next != cursor, next.map({ !catchup.visitedCursors.contains($0) }) ?? true else {
                throw GullConversationError.paginationLoop
            }
            try mergePage(result, into: id, threadID: threadID)
            let reachedAnchor = catchup.anchorID.map { anchor in result.messages.contains { $0.id == anchor } } ?? false
            if reachedAnchor || next == nil {
                if catchup.rebuilding {
                    page.historyCursor = next
                    page.initialized = true
                    page.needsHistoryRebuild = false
                    page.historyBoundaryID = nil
                }
                page.headID = catchup.candidateHeadID
                page.catchup = nil
            } else if let next {
                catchup.visitedCursors.insert(cursor)
                catchup.cursor = next
                page.catchup = catchup
            }
            try await savePage(page, id: id, environment: environment, generation: generation)
            budget -= 1
        }
        return messages(for: id)
    }

    private func mergePage(_ result: GullThreadResult, into id: String, threadID: String) throws {
        guard result.threadID == threadID, let current = conversation(id),
              current.threadID == nil || current.threadID == threadID else { throw GullConversationError.staleSelection }
        let incoming = result.messages.compactMap { Self.mapMessage($0, conversation: current) }
        messagesByConversationID[id] = merge(incoming, with: messages(for: id))
        threadBindings[id] = threadID
        if current.threadID == nil { updateConversation(id) { $0.threadID = threadID } }
    }

    private func savePage(_ page: PageState, id: String, environment: GullsCLI.Environment, generation: Int) async throws {
        pageStates[id] = page
        nextCursorByConversationID[id] = page.historyCursor
        let saved = await persistCacheAndWait()
        try validate(id, environment: environment, generation: generation)
        guard saved else { throw GullConversationError.cacheUnavailable }
    }

    @discardableResult
    func send(_ conversationID: String, content: String, environment: GullsCLI.Environment,
              onEnqueued: (() -> Void)? = nil, pendingID: String? = nil) async throws -> [GullConversationMessage] {
        let text = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw GullConversationError.invalidMessage }
        let generation = scopeGeneration
        try validate(conversationID, environment: environment, generation: generation)
        await waitForCacheHydration()
        try validate(conversationID, environment: environment, generation: generation)
        guard let conversation = conversation(conversationID) else { throw GullConversationError.conversationNotFound }
        if let pendingID {
            guard let index = pendingByConversationID[conversationID]?.firstIndex(where: { $0.id == pendingID }),
                  pendingByConversationID[conversationID]?[index].content == text else { throw GullConversationError.invalidMessage }
            // A duplicate Retry click joins the worker already sending this request.
            if pendingByConversationID[conversationID]?[index].state == .sending {
                return try await drain(conversationID, environment: environment)
            }
            if let item = pendingByConversationID[conversationID]?[index], item.attemptCount > 0, item.preparedRequest == nil {
                throw GullConversationError.legacyPending
            }
            pendingByConversationID[conversationID]?[index].state = .queued
            pendingByConversationID[conversationID]?[index].lastError = nil
            let saved = await persistCacheAndWait()
            try validate(conversationID, environment: environment, generation: generation)
            guard saved else { throw GullConversationError.cacheUnavailable }
            durablePendingIDs.insert(pendingID)
        } else {
            let pending = PendingOutgoing(id: UUID().uuidString, conversationID: conversationID, content: text, createdAt: Date())
            pendingByConversationID[conversationID, default: []].append(pending)
            let optimistic = GullConversationMessage(id: pending.id, threadID: conversation.threadID,
                senderHandle: conversation.senderHandle, senderAgentID: conversation.senderAgentID, content: text, createdAt: pending.createdAt)
            messagesByConversationID[conversationID] = merge(messages(for: conversationID), with: [optimistic])
            let saved = await persistCacheAndWait()
            try validate(conversationID, environment: environment, generation: generation)
            guard saved else {
                pendingByConversationID[conversationID]?.removeAll { $0.id == pending.id }
                messagesByConversationID[conversationID]?.removeAll { $0.id == pending.id }
                throw GullConversationError.cacheUnavailable
            }
            durablePendingIDs.insert(pending.id)
            onEnqueued?()
        }
        return try await drain(conversationID, environment: environment)
    }

    private func drain(_ id: String, environment: GullsCLI.Environment) async throws -> [GullConversationMessage] {
        if let worker = sendWorkers[id] { return try await worker.task.value }
        let token = UUID()
        let generation = scopeGeneration
        let task = Task { @MainActor in
            defer { if self.sendWorkers[id]?.id == token { self.sendWorkers.removeValue(forKey: id) } }
            try self.validate(id, environment: environment, generation: generation)
            while let item = self.pendingByConversationID[id]?.first {
                guard item.state == .queued, self.durablePendingIDs.contains(item.id) else { break }
                try await self.dispatch(item, environment: environment, generation: generation)
            }
            return self.messages(for: id)
        }
        sendWorkers[id] = (token, task)
        return try await task.value
    }

    private func dispatch(_ pending: PendingOutgoing, environment: GullsCLI.Environment, generation: Int) async throws {
        let id = pending.conversationID
        try validate(id, environment: environment, generation: generation)
        guard let cli else { throw GullConversationError.unavailable }
        guard Date().timeIntervalSince(pending.createdAt) < 6 * 24 * 60 * 60 else {
            markPending(pending.id, error: GullConversationError.pendingExpired.localizedDescription)
            throw GullConversationError.pendingExpired
        }
        guard let current = conversation(id), let index = pendingByConversationID[id]?.firstIndex(where: { $0.id == pending.id }) else {
            throw GullConversationError.conversationNotFound
        }
        let request = pending.preparedRequest ?? PreparedSend(senderProfileID: current.senderProfileID,
            senderHandle: current.senderHandle, connectionRevision: current.connectionRevision,
            recipientHandle: current.recipientHandle, content: pending.content, idempotencyKey: pending.id,
            threadID: threadBindings[id] ?? current.threadID)
        guard request.senderProfileID == environment.profileID, request.senderHandle == environment.agentHandle,
              request.connectionRevision == environment.connectionRevision else { throw GullConversationError.staleSelection }
        pendingByConversationID[id]?[index].preparedRequest = request
        pendingByConversationID[id]?[index].state = .sending
        pendingByConversationID[id]?[index].attemptCount += 1
        let preparedSaved = await persistCacheAndWait()
        try validate(id, environment: environment, generation: generation)
        guard preparedSaved else {
            markPending(pending.id, error: GullConversationError.cacheUnavailable.localizedDescription)
            throw GullConversationError.cacheUnavailable
        }
        let result: GullPostResult
        do {
            result = try await cli.post(to: request.recipientHandle, content: request.content,
                threadID: request.threadID, idempotencyKey: request.idempotencyKey, environment: environment)
        } catch {
            try validate(id, environment: environment, generation: generation)
            let rejected: Bool
            if case GullsCLI.Failure.rejected = error { rejected = true } else { rejected = false }
            markPending(pending.id, error: error.localizedDescription, rejected: rejected)
            throw error
        }
        try validate(id, environment: environment, generation: generation)
        guard let threadID = normalizedScope(result.threadID), let confirmedID = normalizedScope(result.messageID),
              request.threadID == nil || request.threadID == threadID,
              threadBindings[id] == nil || threadBindings[id] == threadID else {
            markPending(pending.id, error: GullConversationError.invalidAcknowledgement.localizedDescription)
            throw GullConversationError.invalidAcknowledgement
        }
        threadBindings[id] = threadID
        updateConversation(id) { $0.threadID = threadID; $0.updatedAt = Date() }
        if let index = pendingByConversationID[id]?.firstIndex(where: { $0.id == pending.id }) {
            pendingByConversationID[id]?[index].acknowledgedMessageID = confirmedID
        }
        var visible = messages(for: id).filter { $0.id != pending.id && $0.id != confirmedID && $0.id != pending.acknowledgedMessageID }
        visible.append(GullConversationMessage(id: confirmedID, threadID: threadID, senderHandle: request.senderHandle,
            senderAgentID: current.senderAgentID, content: request.content, createdAt: pending.createdAt))
        messagesByConversationID[id] = merge(visible, with: [])
        // The binding and original prepared request survive a crash together.
        let acknowledgementSaved = await persistCacheAndWait()
        try validate(id, environment: environment, generation: generation)
        guard acknowledgementSaved else {
            markPending(pending.id, error: "The sent message could not be confirmed locally.")
            throw GullConversationError.cacheUnavailable
        }
        let confirmedPending = pendingByConversationID[id]?.first { $0.id == pending.id }
        pendingByConversationID[id]?.removeAll { $0.id == pending.id }
        let removalSaved = await persistCacheAndWait()
        try validate(id, environment: environment, generation: generation)
        guard removalSaved else {
            if var restored = confirmedPending {
                restored.state = .unconfirmed
                restored.lastError = "The sent message could not be confirmed locally."
                pendingByConversationID[id, default: []].insert(restored, at: 0)
            }
            throw GullConversationError.cacheUnavailable
        }
        durablePendingIDs.remove(pending.id)
        // Refresh is independent of queue ordering and never changes the prepared request.
        _ = try? await load(id, threadID: threadID, environment: environment)
        try validate(id, environment: environment, generation: generation)
    }

    private func validate(_ id: String, environment: GullsCLI.Environment, generation: Int) throws {
        guard generation == scopeGeneration, !Task.isCancelled,
              let current = conversation(id), matches(current, environment: environment) else {
            throw GullConversationError.staleSelection
        }
    }

    func remove(_ conversationID: String) {
        sendWorkers.removeValue(forKey: conversationID)?.task.cancel()
        pageWorkers.removeValue(forKey: conversationID)?.task.cancel()
        for pending in pendingByConversationID[conversationID] ?? [] { durablePendingIDs.remove(pending.id) }
        conversations.removeAll { $0.id == conversationID }
        messagesByConversationID.removeValue(forKey: conversationID)
        nextCursorByConversationID.removeValue(forKey: conversationID)
        pendingByConversationID.removeValue(forKey: conversationID)
        pageStates.removeValue(forKey: conversationID)
        threadBindings.removeValue(forKey: conversationID)
        persist()
        persistCache()
    }

    func retryPending(_ pendingID: String, environment: GullsCLI.Environment) async throws -> [GullConversationMessage] {
        guard let item = pendingByConversationID.values.flatMap({ $0 }).first(where: { $0.id == pendingID }) else {
            return []
        }
        guard Date().timeIntervalSince(item.createdAt) < 6 * 24 * 60 * 60 else {
            throw GullConversationError.pendingExpired
        }
        return try await send(item.conversationID, content: item.content, environment: environment, pendingID: item.id)
    }

    private func conversation(_ id: String) -> GullConversation? {
        conversations.first { $0.id == id }
    }

    private func matches(_ conversation: GullConversation, environment: GullsCLI.Environment) -> Bool {
        conversation.senderProfileID == environment.profileID
            && conversation.connectionRevision == environment.connectionRevision
            && conversation.senderHandle == environment.agentHandle
    }

    private func updateConversation(_ id: String, _ change: (inout GullConversation) -> Void) {
        guard let index = conversations.firstIndex(where: { $0.id == id }) else { return }
        change(&conversations[index])
        persist()
    }

    private func normalizedScope(_ value: String?) -> String? {
        let result = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return result.isEmpty ? nil : result
    }

    private func persist() {
        var values = loadPersisted()
        values[activeScope ?? ""] = conversations
        guard let data = try? JSONEncoder().encode(values) else { return }
        defaults.set(data, forKey: Self.persistenceKey)
    }

    @discardableResult
    private func persistCache() -> Bool {
        guard activeScope != nil else { return false }
        let generation = scopeGeneration
        Task { @MainActor [weak self] in
            guard let self, self.scopeGeneration == generation else { return }
            _ = await self.persistCacheAndWait()
        }
        return true
    }

    @discardableResult
    private func persistCacheAndWait() async -> Bool {
        let generation = scopeGeneration
        guard let scope = activeScope else { return false }
        let hydrated = await hydrateCacheIfNeeded()
        guard scopeGeneration == generation, activeScope == scope else { return false }
        if appliedHydrationGeneration != generation {
            applyCachedScope(hydrated[scope])
            appliedHydrationGeneration = generation
        }
        var warmMessages: [String: [GullConversationMessage]] = [:]
        var savedPages = pageStates
        for (id, messages) in messagesByConversationID {
            let pendingIDs = Set((pendingByConversationID[id] ?? []).flatMap { [$0.id, $0.acknowledgedMessageID].compactMap { $0 } })
            let confirmed = messages.filter { !pendingIDs.contains($0.id) }
            let warm = Array(confirmed.suffix(500))
            warmMessages[id] = merge(warm, with: messages.filter { pendingIDs.contains($0.id) })
            if confirmed.count > warm.count {
                var page = savedPages[id] ?? PageState()
                page.needsHistoryRebuild = true
                page.historyBoundaryID = warm.first?.id
                page.historyCursor = nil
                page.catchup = nil
                savedPages[id] = page
            }
        }
        cachedScopes[scope] = PersistedConversationScope(messages: warmMessages,
            cursors: savedPages.compactMapValues(\.historyCursor), pending: pendingByConversationID,
            pageStates: savedPages, threadBindings: threadBindings)
        cacheRevision += 1
        return await cachePersistence.save(cachedScopes, revision: cacheRevision)
    }

    private func markPending(_ id: String, error: String, rejected: Bool = false) {
        for conversationID in pendingByConversationID.keys {
            guard let index = pendingByConversationID[conversationID]?.firstIndex(where: { $0.id == id }) else { continue }
            pendingByConversationID[conversationID]?[index].lastError = error
            pendingByConversationID[conversationID]?[index].state = rejected ? .failed : .unconfirmed
            persistCache()
            return
        }
    }

    private func merge(_ lhs: [GullConversationMessage], with rhs: [GullConversationMessage]) -> [GullConversationMessage] {
        var seen = Set<String>()
        return Array((lhs + rhs).filter { seen.insert($0.id).inserted }.sorted {
            let left = $0.createdAt ?? .distantPast, right = $1.createdAt ?? .distantPast
            return left == right ? $0.id < $1.id : left < right
        })
    }

    private static func defaultCacheURL() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent("Gulls/conversation-cache.json")
    }

    private func loadPersisted() -> [String: [GullConversation]] {
        guard let data = defaults.data(forKey: Self.persistenceKey),
              let values = try? JSONDecoder().decode([String: [GullConversation]].self, from: data) else { return [:] }
        return values
    }

    private static func mapMessage(_ message: GullThreadMessage, conversation: GullConversation) -> GullConversationMessage? {
        guard let content = message.contentInline?.trimmingCharacters(in: .whitespacesAndNewlines), !content.isEmpty else { return nil }
        let resolvedHandle: String?
        if let messageAgentID = message.senderAgentID?.trimmingCharacters(in: .whitespacesAndNewlines),
           !messageAgentID.isEmpty,
           let senderAgentID = conversation.senderAgentID,
           messageAgentID == senderAgentID {
            resolvedHandle = conversation.senderHandle
        } else if let messageAgentID = message.senderAgentID?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !messageAgentID.isEmpty,
                  let recipientAgentID = conversation.recipientAgentID,
                  messageAgentID == recipientAgentID {
            resolvedHandle = conversation.recipientHandle
        } else {
            resolvedHandle = message.senderHandle
        }
        return GullConversationMessage(
            id: message.messageID,
            threadID: message.threadID,
            senderHandle: resolvedHandle,
            senderAgentID: message.senderAgentID,
            content: content,
            createdAt: message.createdAt.flatMap(GullsDates.parse)
        )
    }
}
