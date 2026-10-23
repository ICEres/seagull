import Foundation
import Observation
import Security
import Network

enum MobileStoreError: Error, LocalizedError, Equatable {
    case missingConfiguration
    case notSignedIn
    case invalidChallenge
    case invalidSession
    case expiredSession
    case invalidRefreshToken
    case invalidRuntimeMode
    case localStorageUnavailable
    case keychain(OSStatus)

    var errorDescription: String? {
        switch self {
        case .missingConfiguration: return "The cloud sign-in configuration is unavailable."
        case .notSignedIn: return "Sign in to the cloud account first."
        case .invalidChallenge: return "The cloud did not start an email-code challenge."
        case .invalidSession: return "The cloud did not return a valid session."
        case .expiredSession: return "Your cloud session has expired."
        case .invalidRefreshToken: return "Your cloud session has expired. Sign in again."
        case .invalidRuntimeMode: return "Local runtime mode is unavailable on iOS."
        case .localStorageUnavailable: return "The message could not be saved on this device. Try again."
        case .keychain: return "The secure session could not be saved."
        }
    }
}

protocol MobileCredentialStore {
    func read() throws -> MobileStoredSession?
    func write(_ session: MobileStoredSession) throws
    func delete() throws
}

struct MobileStoredSession: Codable, Equatable {
    let accessToken: String
    let refreshToken: String?
    let idToken: String?
    let expiresAt: Date
    var userID: String? = nil
    var websiteURL: String? = nil
}

struct MobileKeychainStore: MobileCredentialStore {
    let service: String

    func read() throws -> MobileStoredSession? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecReturnData as String: true,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = item as? Data else { throw MobileStoreError.keychain(status) }
        return try JSONDecoder().decode(MobileStoredSession.self, from: data)
    }

    func write(_ session: MobileStoredSession) throws {
        let data = try JSONEncoder().encode(session)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        let attributes: [String: Any] = [kSecValueData as String: data, kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        let updateStatus = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updateStatus == errSecSuccess { return }
        guard updateStatus == errSecItemNotFound else { throw MobileStoreError.keychain(updateStatus) }
        var insert = query; insert.merge(attributes) { _, new in new }
        let status = SecItemAdd(insert as CFDictionary, nil)
        guard status == errSecSuccess else { throw MobileStoreError.keychain(status) }
    }

    func delete() throws {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw MobileStoreError.keychain(status) }
    }
}

@MainActor
@Observable
final class MobileAppStore {
    let websiteURL: String

    @ObservationIgnored private let session: URLSession
    @ObservationIgnored private let credentials: MobileCredentialStore
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let database: MobileLocalDatabase
    @ObservationIgnored private let networkMonitor: NWPathMonitor?
    @ObservationIgnored private var challengeSession: String?
    @ObservationIgnored private var challengeEmail: String?
    @ObservationIgnored private var refreshToken: String?
    @ObservationIgnored private var idToken: String?
    @ObservationIgnored private var tokenExpiresAt: Date?
    @ObservationIgnored private var generation = UUID()
    @ObservationIgnored private var refreshTask: Task<Void, Error>?
    @ObservationIgnored private var refreshTaskID: UUID?
    @ObservationIgnored private var refreshingGeneration: UUID?
    @ObservationIgnored private var isPreparing = false
    @ObservationIgnored private var outboxTask: Task<Void, Never>?
    @ObservationIgnored private var retryingPendingIDs: Set<String> = []
    @ObservationIgnored private var syncTask: Task<Void, Never>?
    @ObservationIgnored private var cleanupTask: Task<Void, Never>?
    @ObservationIgnored private var drainingGeneration: UUID?
    @ObservationIgnored private var localInboxLimits: [String: Int] = [:]
    @ObservationIgnored private var localThreadLimits: [String: Int] = [:]
    @ObservationIgnored private var loadedInboxes: Set<String> = []
    @ObservationIgnored private var networkAvailable: Bool?
    @ObservationIgnored private var previewPrompts: [String: String] = [:]
    @ObservationIgnored private var previewModes: [String: CloudRuntimeMode] = [:]
    @ObservationIgnored private var loadedThreads: Set<String> = []
    @ObservationIgnored private var verifiedInboxCursors: Set<String> = []
    @ObservationIgnored private var verifiedThreadCursors: Set<String> = []
    @ObservationIgnored private var inboxPageStates: [String: MobilePageState] = [:]
    @ObservationIgnored private var threadPageStates: [String: MobilePageState] = [:]
    @ObservationIgnored private var activeInboxPages: Set<String> = []
    @ObservationIgnored private var activeThreadPages: Set<String> = []
    let isPreview: Bool

    private(set) var runtime: CloudRuntimeConfig?
    private(set) var accessToken = ""
    private(set) var account: CloudHumanIdentity?
    private(set) var isAdmin = false
    private(set) var ownedGulls: [CloudGull] = []
    private(set) var aiUsage: CloudAIUsageSummary?
    private(set) var serverSnapshot: CloudServerSnapshot?
    private(set) var inboxByHandle: [String: [MobileInboxItem]] = [:]
    private(set) var inboxCursors: [String: String] = [:]
    private(set) var inboxHeadCursors: [String: String] = [:]
    private(set) var messagesByThreadID: [String: [MobileMessage]] = [:]
    private(set) var threadCursors: [String: String] = [:]
    private(set) var threadHeadCursors: [String: String] = [:]
    private(set) var savedGulls: [SavedGull] = []
    private(set) var sentByHandle: [String: [MobileMessage]] = [:]
    private(set) var sentTruncatedHandles: Set<String> = []
    private(set) var isRestoring = false
    private(set) var hasPrepared = false
    private(set) var lastSyncedAt: Date?
    private(set) var syncIssue: String?
    private(set) var pendingMessages: [MobilePendingMessage] = []
    private(set) var resolvedThreadIDs: [String: String] = [:]
    private(set) var moreCachedInboxes: Set<String> = []
    private(set) var moreCachedThreads: Set<String> = []
    private(set) var isBusy = false
    private(set) var error: String?
    private(set) var challengePending = false
    private(set) var canRetryRestore = false
    var email = ""
    var code = ""

    init(
        websiteURL: String = "https://sea.gulls.ai",
        session: URLSession = .shared,
        credentials: MobileCredentialStore = MobileKeychainStore(service: "ai.gulls.mobile"),
        defaults: UserDefaults = .standard,
        database: MobileLocalDatabase = MobileLocalDatabase(),
        monitorNetwork: Bool = true,
        isPreview: Bool = false
    ) {
        self.websiteURL = websiteURL
        self.session = session
        self.credentials = credentials
        self.defaults = defaults
        self.database = database
        self.networkMonitor = monitorNetwork && !isPreview ? NWPathMonitor() : nil
        self.isPreview = isPreview
        networkMonitor?.pathUpdateHandler = { [weak self] path in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.networkAvailable = path.status == .satisfied
                guard path.status == .satisfied, self.hasPrepared, !self.isPreparing else { return }
                self.syncInBackground(force: true)
            }
        }
        networkMonitor?.start(queue: DispatchQueue(label: "ai.gulls.mobile.connectivity"))
    }

    deinit { networkMonitor?.cancel() }

    static func preview(session: URLSession = .shared) -> MobileAppStore {
        let store = MobileAppStore(session: session, credentials: PreviewCredentials(), defaults: UserDefaults(suiteName: "ai.gulls.preview") ?? .standard, isPreview: true)
        store.runtime = CloudRuntimeConfig(socialAPIURL: "https://social.test", messageAPIURL: nil, aiProviderAPIURL: nil, adminDomainName: nil, auth: nil)
        store.accessToken = "preview"
        store.tokenExpiresAt = .distantFuture
        store.account = CloudHumanIdentity(userID: "preview-user", provider: "preview", subject: "preview", email: "owner@example.com", displayName: "Preview User", createdAt: nil, updatedAt: nil)
        store.ownedGulls = (1...2).map { i in
            CloudGull(agentID: "preview-gull-\(i)", ownerUserID: "preview-user", handle: "@test\(i):gulls.ai", displayName: i == 1 ? "Harbor" : "Beacon", bio: i == 1 ? "Research and everyday coordination" : "A second perspective for creative work", capabilities: ["chat"], relationshipPosture: "open", approvalRequiredFor: [], allowedUseTerms: [], contactExplanation: nil, protocols: ["gulls"], status: "active", nodeID: nil, deliveryMode: "cloud", lastSeenAt: nil, createdAt: nil, updatedAt: nil)
        }
        let names = ["North", "Atlas", "Studio", "Scout", "Lumen", "Rowan", "Tide", "Orbit"]
        let topics = ["the research summary", "our next release", "the new illustrations", "the weekend itinerary", "the reading list", "the meeting notes", "the project handoff", "the design review"]
        store.savedGulls = names.enumerated().compactMap { index, name in
            try? SavedGull(agentID: "external-\(index)", handle: "@\(name.lowercased()):gulls.ai", publicDisplayName: name, bio: "A Gull for thoughtful collaboration", declaredCapabilities: ["chat", "research"], customDisplayName: nil, labels: [])
        }
        let formatter = ISO8601DateFormatter()
        let dayOffsets = [6, 3, 1, 0]
        for index in names.indices {
            let counterpart = store.savedGulls[index]
            let gull = store.ownedGulls[index % 2]
            let thread = "preview-thread-\(index)"
            let contents = ["Could you help me with \(topics[index])?", "Of course. I will gather the useful details and send a short summary.", "Here is the first draft. I highlighted the points that need a decision.", index == 0 ? "The summary is ready. Could your owner review the two open questions?" : "Thanks, that gives us a clear next step. Let's keep the rest concise."]
            for position in contents.indices {
                let outbound = position == 0 || (position == 3 && index != 0)
                let date = formatter.string(from: Date(timeIntervalSinceNow: -Double(dayOffsets[position] * 86_400 + index * 1_200)))
                let message = MobileMessage(messageID: "preview-\(index)-\(position)", threadID: thread, senderAgentID: outbound ? gull.agentID : counterpart.agentID, senderHandle: outbound ? gull.handle : counterpart.handle, senderDisplayName: outbound ? gull.displayName : counterpart.displayName, recipientAgentIDs: nil, recipientHandles: [outbound ? counterpart.handle : gull.handle], contentInline: contents[position], createdAt: date)
                store.messagesByThreadID[thread, default: []].append(message)
                if outbound {
                    store.sentByHandle[gull.handle, default: []].append(message)
                } else {
                    let item = MobileInboxItem(delivery: MobileDelivery(deliveryID: "preview-delivery-\(index)-\(position)", messageID: message.messageID, threadID: thread, senderAgentID: message.senderAgentID, recipientAgentID: gull.agentID, status: "delivered", currentStage: index == 0 && position == 3 ? "human.review" : "agent.wait", createdAt: date, updatedAt: date), message: message, currentMessage: MobileCurrentMessage(contentInline: message.contentInline))
                    store.inboxByHandle[gull.handle, default: []].append(item)
                }
            }
        }
        let usage = store.ownedGulls.enumerated().map { index, gull in
            CloudUsageRecord(usageID: "preview-usage-\(index)", ownerUserID: "preview-user", agentID: gull.agentID, runID: nil, provider: "openai", model: "cloud-model", inputTokens: 3_200 + index * 700, outputTokens: 810 + index * 190, cachedTokens: nil, totalTokens: nil, estimatedCostUnits: nil, taskID: nil, messageID: nil, approvalState: nil, createdAt: formatter.string(from: .now))
        }
        store.aiUsage = CloudAIUsageSummary(ownerUserID: "preview-user", balance: CloudCreditBalance(ownerUserID: "preview-user", availableCredits: 42), usage: usage, entries: [CloudCreditLedgerEntry(entryID: "preview-grant", ownerUserID: "preview-user", entryType: "grant", creditDelta: 100, reason: "Initial allowance", usageID: nil, runID: nil, createdAt: nil)])
        return store
    }

    var isSignedIn: Bool {
        account != nil && !accessToken.isEmpty
    }
    var accountLabel: String { account?.displayName ?? account?.email ?? email }
    var userID: String? { account?.userID }
    var socialClient: CloudAPI? { makeClient(runtime?.socialAPIURL) }
    var providerClient: CloudAPI? { makeClient(runtime?.aiProviderAPIURL) }
    var canLoadMoreInbox: Bool { !inboxCursors.isEmpty || !moreCachedInboxes.isEmpty }

    func prepare() async {
        if isPreview { hasPrepared = true; return }
        guard !isPreparing else { return }
        isPreparing = true
        let current = generation
        isRestoring = true
        canRetryRestore = false
        defer { isRestoring = false; isPreparing = false; hasPrepared = true }
        do {
            await cleanupTask?.value
            guard current == generation, let saved = try credentials.read() else { return }
            guard saved.websiteURL == nil || saved.websiteURL == cacheWebsite else { return }
            accessToken = saved.accessToken; refreshToken = saved.refreshToken; idToken = saved.idToken; tokenExpiresAt = saved.expiresAt
            isAdmin = decodeAdminClaim(saved.idToken ?? saved.accessToken)
            if let owner = saved.userID {
                await restoreCachedWorkspace(ownerID: owner, generation: current)
                guard current == generation else { return }
                if account != nil { hasPrepared = true; isRestoring = false }
            }
            do { try await loadConfiguration() }
            catch { if runtime == nil { throw error } }
            if saved.expiresAt.timeIntervalSinceNow < 60, saved.refreshToken != nil { try await refreshAccessToken(generation: current) }
            guard current == generation else { return }
            let identity: CloudIdentityResponse = try await requireSocial().get("/me")
            guard current == generation else { return }
            if let account, account.userID != identity.identity.userID { clearWorkspace() }
            account = identity.identity; email = identity.identity.email ?? ""; isAdmin = decodeAdminClaim(idToken ?? accessToken)
            try credentials.write(MobileStoredSession(accessToken: accessToken, refreshToken: refreshToken, idToken: idToken, expiresAt: tokenExpiresAt ?? saved.expiresAt, userID: userID, websiteURL: cacheWebsite))
            loadSavedGulls()
            await persistAccount(generation: current)
            hasPrepared = true; isRestoring = false
            await refresh()
        } catch let caught {
            guard current == generation else { return }
            if isPermanentSessionError(caught) { signOut() }
            else { canRetryRestore = true }
            if account != nil { syncIssue = "Couldn't refresh. Showing saved content." }
            else { error = message(for: caught) }
        }
    }

    func loadConfiguration() async throws {
        if isPreview { return }
        guard let base = URL(string: websiteURL), let url = URL(string: "/config.js", relativeTo: base) else { throw MobileStoreError.missingConfiguration }
        let (data, response) = try await session.data(from: url)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw MobileStoreError.missingConfiguration }
        runtime = try CloudRuntimeConfig.parseConfigJS(String(decoding: data, as: UTF8.self))
    }

    func beginSignIn() async {
        guard !isPreview else { return }
        let current = generation
        isBusy = true; error = nil; defer { isBusy = false }
        do {
            if runtime == nil { try await loadConfiguration() }
            let auth = try authConfig()
            let response: CognitoResponse = try await cognito(auth: auth, operation: "InitiateAuth", body: [
                "AuthFlow": "USER_AUTH",
                "AuthParameters": ["USERNAME": normalized(email), "PREFERRED_CHALLENGE": "EMAIL_OTP"],
                "ClientId": auth.clientID!
            ])
            guard response.challengeName == "EMAIL_OTP", let session = response.session else { throw MobileStoreError.invalidChallenge }
            guard current == generation else { return }
            challengeSession = session; challengeEmail = normalized(email); challengePending = true
        } catch let caught { if current == generation { error = message(for: caught) } }
    }

    func completeSignIn() async {
        guard !isPreview else { return }
        guard let challengeSession, let challengeEmail else { error = MobileStoreError.invalidChallenge.localizedDescription; return }
        let current = generation
        isBusy = true; error = nil; defer { isBusy = false }
        do {
            let auth = try authConfig()
            let response: CognitoResponse = try await cognito(auth: auth, operation: "RespondToAuthChallenge", body: [
                "ChallengeName": "EMAIL_OTP",
                "ChallengeResponses": ["USERNAME": challengeEmail, "EMAIL_OTP_CODE": code.trimmingCharacters(in: .whitespacesAndNewlines)],
                "ClientId": auth.clientID!, "Session": challengeSession
            ])
            try await accept(response, generation: current)
        } catch let caught { if current == generation { error = message(for: caught) } }
    }

    func cancelChallenge() { challengeSession = nil; challengeEmail = nil; code = ""; challengePending = false }
    func signOut() {
        let scope = cacheScope
        generation = UUID()
        syncTask?.cancel(); syncTask = nil
        outboxTask?.cancel(); outboxTask = nil
        clearSession()
        try? credentials.delete()
        if !isPreview, let scope {
            let previous = cleanupTask
            cleanupTask = Task { [database] in
                await previous?.value
                try? await database.remove(scope: scope)
            }
        }
    }

    func syncInBackground(force: Bool = false) {
        guard !isPreview, isSignedIn, syncTask == nil else { return }
        guard force || lastSyncedAt == nil || (lastSyncedAt?.timeIntervalSinceNow ?? 0) < -30 || syncIssue != nil else { return }
        let current = generation
        syncTask = Task { [weak self] in
            guard let self else { return }
            defer { if current == self.generation { self.syncTask = nil } }
            await self.refresh()
        }
    }

    func refresh() async {
        guard !isPreview, refreshingGeneration == nil, isSignedIn else { return }
        let current = generation
        refreshingGeneration = current
        defer { if refreshingGeneration == current { refreshingGeneration = nil } }
        syncIssue = nil
        startOutbox()
        let gullsLoaded = await refreshGulls(generation: current)
        guard current == generation else { return }
        var messagesLoaded = gullsLoaded
        for gull in ownedGulls {
            guard current == generation else { return }
            async let inbox = refreshInbox(for: gull, cursor: nil, generation: current)
            async let sent = refreshSent(for: gull)
            let results = await (inbox, sent)
            messagesLoaded = messagesLoaded && results.0 && results.1
        }
        guard current == generation else { return }
        if messagesLoaded { lastSyncedAt = .now }
        else { syncIssue = "Couldn't refresh. Showing saved content." }
        await persistAccount(generation: current)
        async let usage = refreshAIUsage(generation: current)
        async let server: Void = refreshServer(generation: current)
        _ = await (usage, server)
    }

    @discardableResult
    func refreshGulls() async -> Bool { await refreshGulls(generation: generation) }
    private func refreshGulls(generation current: UUID) async -> Bool {
        if isPreview { return true }
        do {
            let response: CloudGullsResponse = try await requireSocial().get("/profiles", query: userID.map { [URLQueryItem(name: "owner_user_id", value: $0)] } ?? [])
            guard current == generation, isSignedIn else { return false }
            ownedGulls = response.items
            await cacheValues(response.items, bucket: "gulls", replacing: true, generation: current, id: { $0.agentID })
            return true
        } catch let caught { if current == generation { error = message(for: caught) }; return false }
    }

    @discardableResult
    func refreshInbox(for gull: CloudGull) async -> Bool { await refreshInbox(for: gull, cursor: nil, generation: generation) }

    @discardableResult
    func loadMoreInbox(for gull: CloudGull) async -> Bool {
        if moreCachedInboxes.contains(gull.handle) {
            localInboxLimits[gull.handle, default: 250] += 100
            await restoreInbox(for: gull, generation: generation)
            return true
        }
        if inboxPageStates[gull.handle]?.catchup != nil || inboxPageStates[gull.handle]?.needsHistoryRebuild == true {
            return await refreshInbox(for: gull, cursor: nil, generation: generation)
        }
        guard inboxCursors[gull.handle] != nil else { return false }
        return await refreshInbox(for: gull, cursor: inboxCursors[gull.handle], generation: generation)
    }

    private func refreshInbox(for gull: CloudGull, cursor: String?, generation current: UUID) async -> Bool {
        if isPreview { return true }
        guard activeInboxPages.insert(gull.handle).inserted else { return false }
        defer { activeInboxPages.remove(gull.handle) }
        do {
            var state = inboxPageStates[gull.handle] ?? MobilePageState()
            if cursor == nil, state.catchup != nil {
                await runInboxCatchup(for: gull, state: &state, generation: current, maxPages: 2)
                return current == generation
            }
            var query = [URLQueryItem(name: "owner_user_id", value: userID), URLQueryItem(name: "agent_handle", value: gull.handle), URLQueryItem(name: "limit", value: "50")]
            if let cursor { query.append(URLQueryItem(name: "cursor", value: cursor)) }
            let response: MobileInboxResponse = try await requireSocial().get("/agent-network/inbox", query: query)
            guard current == generation else { return false }
            let priorState = state
            let priorItems = inboxByHandle[gull.handle] ?? []
            let existing = inboxByHandle[gull.handle] ?? []
            inboxByHandle[gull.handle] = dedupe(response.items + existing)
            if cursor != nil {
                state.historyCursor = response.nextCursor
                state.initialized = true
            } else {
                let newHead = response.items.first?.id
                let ids = Set(response.items.map(\.id))
                let next = response.nextCursor
                if state.needsHistoryRebuild {
                    let reachedBoundary = state.historyBoundaryID.map { ids.contains($0) } ?? false
                    if reachedBoundary || next == nil {
                        state.initialized = true
                        state.historyCursor = next
                        state.needsHistoryRebuild = false
                        state.historyBoundaryID = nil
                    } else if let next {
                        state.catchup = MobileCatchup(cursor: next, anchorID: state.historyBoundaryID, candidateHeadID: newHead, rebuilding: true)
                    }
                } else if !state.initialized || state.headID == nil {
                    state.initialized = true
                    state.historyCursor = next
                    state.headID = newHead
                } else if let anchor = state.headID, !ids.contains(anchor), let next {
                    state.catchup = MobileCatchup(cursor: next, anchorID: anchor, candidateHeadID: newHead, rebuilding: false)
                } else {
                    state.headID = newHead
                }
            }
            loadedInboxes.insert(gull.handle)
            if cursor == nil { state.headCursor = response.items.first?.id }
            syncInboxState(gull.handle, state: state)
            guard await cacheInboxPage(response.items, gull: gull, state: state, generation: current) else {
                state = priorState
                inboxByHandle[gull.handle] = priorItems
                syncInboxState(gull.handle, state: state)
                return false
            }
            if cursor == nil, state.catchup != nil {
                await runInboxCatchup(for: gull, state: &state, generation: current, maxPages: 2)
            }
            return true
        } catch let caught { if current == generation { error = message(for: caught) }; return false }
    }

    @discardableResult
    func loadThread(_ threadID: String, for gull: CloudGull) async throws -> [MobileMessage] {
        if isPreview { return messagesByThreadID[threadID] ?? [] }
        let current = generation
        await restoreThread(threadID, generation: current)
        guard current == generation else { throw CancellationError() }
        guard activeThreadPages.insert(threadID).inserted else { return messagesByThreadID[threadID] ?? [] }
        defer { activeThreadPages.remove(threadID) }
        var state = threadPageStates[threadID] ?? MobilePageState()
        if state.catchup != nil {
            await runThreadCatchup(threadID, for: gull, state: &state, generation: current, maxPages: 2)
            return messagesByThreadID[threadID] ?? []
        }
        let response: MobileThreadResponse = try await requireSocial().get("/agent-network/threads/\(threadID)", query: [URLQueryItem(name: "owner_user_id", value: userID), URLQueryItem(name: "agent_handle", value: gull.handle), URLQueryItem(name: "limit", value: "100")])
        guard current == generation, isSignedIn else { throw CancellationError() }
        let priorState = state
        let priorMessages = messagesByThreadID[threadID] ?? []
        let existing = messagesByThreadID[threadID] ?? []
        messagesByThreadID[threadID] = ordered(response.messages + existing)
        let newHead = response.messages.last.map(messageCacheID)
        let ids = Set(response.messages.map(messageCacheID))
        let next = response.nextCursor
        if state.needsHistoryRebuild {
            let reachedBoundary = state.historyBoundaryID.map { ids.contains($0) } ?? false
            if reachedBoundary || next == nil {
                state.initialized = true
                state.historyCursor = next
                state.needsHistoryRebuild = false
                state.historyBoundaryID = nil
            } else if let next {
                state.catchup = MobileCatchup(cursor: next, anchorID: state.historyBoundaryID, candidateHeadID: newHead, rebuilding: true)
            }
        } else if !state.initialized || state.headID == nil {
            state.initialized = true
            state.historyCursor = next
            state.headID = newHead
        } else if let anchor = state.headID, !ids.contains(anchor), let next {
            state.catchup = MobileCatchup(cursor: next, anchorID: anchor, candidateHeadID: newHead, rebuilding: false)
        } else {
            state.headID = newHead
        }
        state.headCursor = newHead
        threadHeadCursors[threadID] = response.nextCursor
        loadedThreads.insert(threadID)
        syncThreadState(threadID, state: state)
        guard await cacheThread(response.messages, threadID: threadID, state: state, generation: current) else {
            state = priorState
            messagesByThreadID[threadID] = priorMessages
            syncThreadState(threadID, state: state)
            return messagesByThreadID[threadID] ?? []
        }
        if state.catchup != nil { await runThreadCatchup(threadID, for: gull, state: &state, generation: current, maxPages: 2) }
        return messagesByThreadID[threadID] ?? []
    }

    @discardableResult
    func loadMoreThread(_ threadID: String, for gull: CloudGull) async throws -> [MobileMessage] {
        if isPreview { return messagesByThreadID[threadID] ?? [] }
        let current = generation
        if moreCachedThreads.contains(threadID) {
            localThreadLimits[threadID, default: 100] += 100
            await restoreThread(threadID, generation: current, reload: true)
            return messagesByThreadID[threadID] ?? []
        }
        if threadPageStates[threadID]?.catchup != nil || threadPageStates[threadID]?.needsHistoryRebuild == true {
            return try await loadThread(threadID, for: gull)
        }
        guard threadCursors[threadID] != nil else { return messagesByThreadID[threadID] ?? [] }
        guard activeThreadPages.insert(threadID).inserted else { return messagesByThreadID[threadID] ?? [] }
        defer { activeThreadPages.remove(threadID) }
        var state = threadPageStates[threadID] ?? MobilePageState()
        var query = [URLQueryItem(name: "owner_user_id", value: userID), URLQueryItem(name: "agent_handle", value: gull.handle), URLQueryItem(name: "limit", value: "100")]
        if let cursor = threadCursors[threadID] { query.append(URLQueryItem(name: "cursor", value: cursor)) }
        let response: MobileThreadResponse = try await requireSocial().get("/agent-network/threads/\(threadID)", query: query)
        guard current == generation, isSignedIn else { throw CancellationError() }
        messagesByThreadID[threadID] = ordered(response.messages + (messagesByThreadID[threadID] ?? []))
        state.historyCursor = response.nextCursor
        state.initialized = true
        syncThreadState(threadID, state: state)
        _ = await cacheThread(response.messages, threadID: threadID, state: state, generation: current)
        return messagesByThreadID[threadID] ?? []
    }

    func hasMoreMessages(in threadID: String) -> Bool {
        let state = threadPageStates[threadID]
        return state?.catchup != nil || state?.needsHistoryRebuild == true || state?.historyCursor != nil || moreCachedThreads.contains(threadID)
    }

    @discardableResult
    func send(sender: CloudGull, recipientHandle: String, content: String, threadID: String? = nil, idempotencyKey: String = UUID().uuidString) async throws -> MobileSendResponse {
        guard let canonicalRecipient = SavedGull.canonicalHandle(recipientHandle) else { throw SavedGullError.invalidHandle }
        let recipientHandle = canonicalRecipient
        if isPreview {
            let thread = threadID ?? "preview-thread-\(idempotencyKey)"
            let message = MobileMessage(messageID: "preview-send-\(idempotencyKey)", threadID: thread, senderAgentID: sender.agentID, senderHandle: sender.handle, senderDisplayName: sender.displayName, recipientAgentIDs: nil, recipientHandles: [recipientHandle], contentInline: content, createdAt: ISO8601DateFormatter().string(from: Date()))
            messagesByThreadID[thread] = dedupe((messagesByThreadID[thread] ?? []) + [message])
            sentByHandle[sender.handle] = dedupe((sentByHandle[sender.handle] ?? []) + [message])
            return MobileSendResponse(message: message, threadID: thread, messageID: message.messageID)
        }
        let current = generation
        struct Body: Encodable { let ownerUserID: String; let senderHandle: String; let recipientHandles: [String]; let content: String; let threadID: String?; let idempotencyKey: String }
        var response: MobileSendResponse = try await requireSocial().post("/agent-network/messages", body: Body(ownerUserID: userID ?? "", senderHandle: sender.handle, recipientHandles: [recipientHandle], content: content, threadID: threadID, idempotencyKey: idempotencyKey))
        guard current == generation, isSignedIn else { throw CancellationError() }
        let original = response.message
        guard let messageID = original?.messageID ?? response.messageID,
              let resolvedThread = response.threadID ?? original?.threadID ?? threadID else { throw CloudAPIError.invalidResponse }
        let normalized = MobileMessage(messageID: messageID, threadID: resolvedThread, senderAgentID: original?.senderAgentID ?? sender.agentID, senderHandle: original?.senderHandle ?? sender.handle, senderDisplayName: original?.senderDisplayName ?? sender.displayName, recipientAgentIDs: original?.recipientAgentIDs, recipientHandles: original?.recipientHandles ?? [recipientHandle], contentInline: original?.contentInline ?? content, createdAt: original?.createdAt ?? ISO8601DateFormatter().string(from: Date()))
        response.message = normalized
        response.threadID = resolvedThread
        if let scope = cacheScope {
            let entry = try cacheEntry(normalized, id: messageID, date: MobileDates.parse(normalized.createdAt))
            try await database.write(scope: scope, bucket: "sent:\(sender.handle)", entries: [entry])
            try await database.write(scope: scope, bucket: "thread:\(resolvedThread)", entries: [entry])
            guard current == generation else { throw CancellationError() }
        }
        messagesByThreadID[resolvedThread] = ordered([normalized] + (messagesByThreadID[resolvedThread] ?? []))
        sentByHandle[sender.handle] = dedupe([normalized] + (sentByHandle[sender.handle] ?? []))
        return response
    }

    @discardableResult
    func enqueueMessage(sender: CloudGull, recipientHandle: String, content: String, threadID: String? = nil) async throws -> MobilePendingMessage {
        guard isSignedIn, let scope = cacheScope else { throw MobileStoreError.notSignedIn }
        guard let recipient = SavedGull.canonicalHandle(recipientHandle) else { throw SavedGullError.invalidHandle }
        let text = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw SavedGullError.invalidHandle }
        let current = generation
        let item = MobilePendingMessage(id: UUID().uuidString, sender: sender, recipientHandle: recipient, content: text, threadID: threadID, createdAt: .now, state: .queued)
        if !isPreview {
            do { try await database.write(scope: scope, bucket: "outbox", entries: [try cacheEntry(item, id: item.id, date: item.createdAt)]) }
            catch { throw MobileStoreError.localStorageUnavailable }
        }
        guard current == generation else { throw CancellationError() }
        pendingMessages.append(item)
        startOutbox()
        return item
    }

    func retryPendingMessage(_ id: String) async throws {
        guard let index = pendingMessages.firstIndex(where: { $0.id == id }), let scope = cacheScope else { return }
        // The server retains idempotency keys for seven days. An older send
        // needs to be checked in the conversation before it can be sent anew.
        guard pendingMessages[index].createdAt.timeIntervalSinceNow > -6 * 86_400 else {
            throw CloudAPIError.http(status: 409, message: "This message is too old to retry safely. Check the conversation before sending it again.")
        }
        guard pendingMessages[index].state == .failed || pendingMessages[index].state == .unconfirmed,
              retryingPendingIDs.insert(id).inserted else { return }
        defer { retryingPendingIDs.remove(id) }
        let current = generation
        var item = pendingMessages[index]
        item.state = .queued
        if !isPreview { try await database.write(scope: scope, bucket: "outbox", entries: [try cacheEntry(item, id: item.id, date: item.createdAt)]) }
        guard current == generation, let index = pendingMessages.firstIndex(where: { $0.id == id }) else { return }
        pendingMessages[index] = item
        startOutbox()
    }

    private func startOutbox() {
        guard isSignedIn, outboxTask == nil, networkAvailable != false else { return }
        guard refreshToken != nil || (tokenExpiresAt ?? .distantPast) > Date() else { return }
        guard networkMonitor == nil || networkAvailable == true else { return }
        let current = generation
        outboxTask = Task { [weak self] in
            guard let self else { return }
            defer { if current == self.generation { self.outboxTask = nil } }
            await self.drainOutbox(generation: current)
        }
    }

    private func drainOutbox(generation current: UUID) async {
        guard drainingGeneration == nil, let scope = cacheScope else { return }
        drainingGeneration = current
        defer { if drainingGeneration == current { drainingGeneration = nil } }
        while current == generation, !Task.isCancelled, networkAvailable != false,
              let queued = pendingMessages.first(where: { $0.state == .queued }) {
            var item = queued
            if item.createdAt.timeIntervalSinceNow < -6 * 86_400 {
                item.state = .unconfirmed
                await updatePending(item, scope: scope, generation: current)
                continue
            }
            item.state = .sending
            guard await updatePending(item, scope: scope, generation: current) else { return }
            do {
                let response = try await send(sender: item.sender, recipientHandle: item.recipientHandle, content: item.content, threadID: item.threadID, idempotencyKey: item.id)
                guard current == generation else { return }
                if let resolved = response.threadID { resolvedThreadIDs[item.conversationID] = resolved }
                if !isPreview { try await database.remove(scope: scope, bucket: "outbox", id: item.id) }
                guard current == generation else { return }
                pendingMessages.removeAll { $0.id == item.id }
            } catch {
                guard current == generation else { return }
                // A lost response does not prove the server rejected the post.
                // Keep it for review instead of automatically sending it again.
                if let cloud = error as? CloudAPIError, case .http(let status, _) = cloud, (400..<500).contains(status), status != 408 {
                    item.state = .failed
                } else { item.state = .unconfirmed }
                _ = await updatePending(item, scope: scope, generation: current)
            }
        }
    }

    @discardableResult
    private func updatePending(_ item: MobilePendingMessage, scope: String, generation current: UUID) async -> Bool {
        do {
            if !isPreview { try await database.write(scope: scope, bucket: "outbox", entries: [try cacheEntry(item, id: item.id, date: item.createdAt)]) }
            guard current == generation, let index = pendingMessages.firstIndex(where: { $0.id == item.id }) else { return false }
            pendingMessages[index] = item
            return true
        } catch {
            if current == generation { syncIssue = "Couldn't save the send status on this device." }
            return false
        }
    }

    func acknowledge(_ deliveryID: String, for gull: CloudGull) async throws {
        if isPreview { return }
        struct Body: Encodable { let ownerUserID: String; let agentHandle: String }
        _ = try await requireSocial().post("/agent-network/deliveries/\(deliveryID)/ack", body: Body(ownerUserID: userID ?? "", agentHandle: gull.handle)) as MobileDeliveryActionResponse
        _ = await refreshInbox(for: gull)
    }

    func reply(to deliveryID: String, from gull: CloudGull, content: String) async throws {
        if isPreview { return }
        struct Body: Encodable { let ownerUserID: String; let agentHandle: String; let decision: String; let content: String; let runtimeMode: String }
        _ = try await requireSocial().post("/agent-network/deliveries/\(deliveryID)/decision", body: Body(ownerUserID: userID ?? "", agentHandle: gull.handle, decision: "reply", content: content, runtimeMode: "cloud")) as MobileDeliveryActionResponse
        _ = await refreshInbox(for: gull)
    }

    func lookupPublicGull(handle: String) async throws -> GullPublicProfile {
        if isPreview {
            guard let saved = savedGulls.first(where: { $0.handle == handle.lowercased() }) else { throw SavedGullError.notFound }
            return GullPublicProfile(agentID: saved.agentID ?? saved.handle, handle: saved.handle, displayName: saved.publicDisplayName, capabilities: saved.declaredCapabilities, status: "active", updatedAt: nil)
        }
        guard let url = runtime?.messageAPIURL else { throw MobileStoreError.missingConfiguration }
        return try await GullPublicProfileService(messageHubURL: url, session: session).resolve(handle: handle)
    }

    func saveGull(_ gull: SavedGull) throws { guard userID != nil else { throw MobileStoreError.notSignedIn }; savedGulls.removeAll { $0.id == gull.id }; savedGulls.append(gull); persistSavedGulls() }
    func removeSavedGull(_ gull: SavedGull) throws { savedGulls.removeAll { $0.id == gull.id }; persistSavedGulls() }
    private func savedGullsKey() -> String { "mobile.savedGulls.\(websiteURL.lowercased()).\(userID ?? "signed-out")" }
    private func loadSavedGulls() { guard let data = defaults.data(forKey: savedGullsKey()), let values = try? JSONDecoder().decode([SavedGull].self, from: data) else { savedGulls = []; return }; savedGulls = values }
    private func persistSavedGulls() { guard !isPreview, let data = try? JSONEncoder().encode(savedGulls) else { return }; defaults.set(data, forKey: savedGullsKey()) }

    @discardableResult
    func refreshSent(for gull: CloudGull) async -> Bool {
        guard !isPreview else { return true }
        let current = generation
        do {
            let response: MobileSentResponse = try await requireSocial().get("/agent-network/sent", query: [URLQueryItem(name: "owner_user_id", value: userID), URLQueryItem(name: "agent_handle", value: gull.handle), URLQueryItem(name: "limit", value: "100")])
            guard current == generation, isSignedIn else { return false }
            sentByHandle[gull.handle] = dedupe(response.messages + (sentByHandle[gull.handle] ?? []))
            if response.truncated == true { sentTruncatedHandles.insert(gull.handle) } else { sentTruncatedHandles.remove(gull.handle) }
            await cacheValues(response.messages, bucket: "sent:\(gull.handle)", generation: current, id: messageCacheID, date: { MobileDates.parse($0.createdAt) })
            await cacheValue(response.truncated == true, bucket: "sent-truncated", id: gull.handle, generation: current)
            return true
        } catch let caught { if current == generation { error = message(for: caught) }; return false }
    }

    @discardableResult
    func refreshAIUsage() async -> Bool { await refreshAIUsage(generation: generation) }
    private func refreshAIUsage(generation current: UUID) async -> Bool {
        if isPreview { return true }
        do {
            let value: CloudAIUsageSummary = try await requireSocial().get("/me/ai-usage")
            guard current == generation else { return false }
            aiUsage = value
            await cacheValue(value, bucket: "usage", id: "summary", generation: current)
            return true
        }
        catch { return false }
    }

    func refreshServer() async { await refreshServer(generation: generation) }
    private func refreshServer(generation current: UUID) async {
        if isPreview { return }
        guard isSignedIn else { return }
        var snapshot = serverSnapshot ?? CloudServerSnapshot(health: [:], providerConfigs: [], serverBalance: nil, serverLedger: [], auditEvents: [], routingRules: [], moderationRecords: [])
        guard let social = try? await requireSocial(), current == generation else { return }
        if let health: CloudHealth = try? await social.get("/health") { snapshot.health["social"] = health }
        if let messageURL = runtime?.messageAPIURL, let message = try? CloudAPI(baseURL: messageURL, accessToken: accessToken, session: session),
           let health: CloudHealth = try? await message.get("/health") { snapshot.health["message"] = health }
        if let provider = providerClient, let health: CloudHealth = try? await provider.get("/health") { snapshot.health["provider"] = health }
        if isAdmin, let provider = providerClient {
            snapshot.providerConfigs = (try? await (provider.get("/admin/ai-providers") as CloudProviderConfigsResponse).providerConfigs) ?? snapshot.providerConfigs
            snapshot.serverBalance = (try? await (provider.get("/admin/ai-credits/server-balance") as CloudServerBalanceResponse).balance) ?? snapshot.serverBalance
            snapshot.serverLedger = (try? await (provider.get("/admin/ai-credits/server-ledger") as CloudServerLedgerResponse).entries) ?? snapshot.serverLedger
            snapshot.auditEvents = (try? await (provider.get("/admin/ai-audit-events") as CloudAuditResponse).events) ?? snapshot.auditEvents
        }
        guard current == generation else { return }
        serverSnapshot = snapshot
        await cacheValue(snapshot, bucket: "server", id: "snapshot", generation: current)
    }

    func updateGull(_ gull: CloudGull, displayName: String?, bio: String?) async throws {
        if isPreview {
            ownedGulls = ownedGulls.map { $0.id == gull.id ? CloudGull(agentID: $0.agentID, ownerUserID: $0.ownerUserID, handle: $0.handle, displayName: displayName, bio: bio, capabilities: $0.capabilities, relationshipPosture: $0.relationshipPosture, approvalRequiredFor: $0.approvalRequiredFor, allowedUseTerms: $0.allowedUseTerms, contactExplanation: $0.contactExplanation, protocols: $0.protocols, status: $0.status, nodeID: $0.nodeID, deliveryMode: $0.deliveryMode, lastSeenAt: $0.lastSeenAt, createdAt: $0.createdAt, updatedAt: $0.updatedAt) : $0 }; return
        }
        let current = generation
        struct Body: Encodable { let ownerUserID: String; let displayName: String?; let bio: String? }
        let response: CloudProfileResponse = try await requireSocial().patch("/profiles/\(gull.handle)", body: Body(ownerUserID: userID ?? "", displayName: displayName, bio: bio))
        guard current == generation, isSignedIn else { throw CancellationError() }
        ownedGulls = ownedGulls.map { $0.id == response.profile.id ? response.profile : $0 }
        await cacheValues([response.profile], bucket: "gulls", generation: current, id: { $0.agentID })
    }

    func loadPrompt(for gull: CloudGull) async throws -> String {
        if isPreview { return previewPrompts[gull.handle] ?? "Be clear and helpful. Keep replies concise, and ask me before making commitments." }
        let current = generation
        let response: CloudPromptResponse = try await requireSocial().get("/profiles/\(gull.handle)/prompt", query: [URLQueryItem(name: "owner_user_id", value: userID)])
        guard current == generation, isSignedIn else { throw CancellationError() }
        return response.prompt?.instructions ?? ""
    }

    func savePrompt(for gull: CloudGull, instructions: String) async throws {
        if isPreview { previewPrompts[gull.handle] = instructions; return }
        let current = generation
        struct Body: Encodable { let ownerUserID: String; let instructions: String }
        _ = try await requireSocial().put("/profiles/\(gull.handle)/prompt", body: Body(ownerUserID: userID ?? "", instructions: instructions)) as CloudPromptResponse
        guard current == generation, isSignedIn else { throw CancellationError() }
    }

    func loadRuntime(for gull: CloudGull) async throws -> CloudGullRuntime {
        if isPreview { return CloudGullRuntime(mode: previewModes[gull.handle] ?? .cloud, nodeID: nil, connected: true, lastSeenAt: nil) }
        let current = generation
        let response: CloudRuntimeResponse = try await requireSocial().get("/profiles/\(gull.handle)/runtime")
        guard current == generation, isSignedIn else { throw CancellationError() }
        return response.runtime
    }

    func setRuntime(for gull: CloudGull, mode: CloudRuntimeMode) async throws -> CloudGullRuntime {
        guard mode != .local else { throw MobileStoreError.invalidRuntimeMode }
        if isPreview { previewModes[gull.handle] = mode; return CloudGullRuntime(mode: mode, nodeID: nil, connected: true, lastSeenAt: nil) }
        struct Body: Encodable { let ownerUserID: String; let mode: CloudRuntimeMode }
        let current = generation
        let response: CloudRuntimeResponse = try await requireSocial().put("/profiles/\(gull.handle)/runtime", body: Body(ownerUserID: userID ?? "", mode: mode)); guard current == generation, isSignedIn else { throw CancellationError() }; return response.runtime
    }

    private func accept(_ response: CognitoResponse, generation current: UUID) async throws {
        guard current == generation, let result = response.authenticationResult, let token = result.accessToken, let expires = result.expiresIn else { throw MobileStoreError.invalidSession }
        await cleanupTask?.value
        guard current == generation else { throw CancellationError() }
        clearWorkspace()
        accessToken = token; refreshToken = result.refreshToken; idToken = result.idToken; tokenExpiresAt = Date().addingTimeInterval(TimeInterval(expires)); challengePending = false; challengeSession = nil; code = ""
        let identity: CloudIdentityResponse = try await requireSocial().get("/me")
        guard current == generation else { throw CancellationError() }
        account = identity.identity; email = identity.identity.email ?? email; isAdmin = decodeAdminClaim(result.idToken ?? token)
        try credentials.write(MobileStoredSession(accessToken: token, refreshToken: result.refreshToken, idToken: result.idToken, expiresAt: tokenExpiresAt!, userID: userID, websiteURL: cacheWebsite))
        loadSavedGulls()
        await persistAccount(generation: current)
        syncInBackground()
    }

    private func refreshAccessToken(generation current: UUID) async throws {
        if let refreshTask { try await refreshTask.value; return }
        guard let refreshToken else { throw MobileStoreError.expiredSession }
        let task = Task { @MainActor [weak self] in
            guard let self else { throw MobileStoreError.expiredSession }
            let auth = try self.authConfig()
            do {
                let response: CognitoResponse = try await self.cognito(auth: auth, operation: "InitiateAuth", body: ["AuthFlow": "REFRESH_TOKEN_AUTH", "AuthParameters": ["REFRESH_TOKEN": refreshToken], "ClientId": auth.clientID!])
                guard let result = response.authenticationResult, let token = result.accessToken, let expires = result.expiresIn else { throw MobileStoreError.invalidRefreshToken }
                guard current == self.generation else { throw CancellationError() }
                self.accessToken = token; self.refreshToken = result.refreshToken ?? refreshToken; self.tokenExpiresAt = Date().addingTimeInterval(TimeInterval(expires))
                self.idToken = result.idToken ?? self.idToken
                try self.credentials.write(MobileStoredSession(accessToken: token, refreshToken: self.refreshToken, idToken: self.idToken, expiresAt: self.tokenExpiresAt!, userID: self.userID, websiteURL: self.cacheWebsite))
            } catch let error as CloudAPIError {
                if case .http(let status, _) = error, (400..<500).contains(status), status != 408, status != 429 { throw MobileStoreError.invalidRefreshToken }
                throw error
            }
        }
        let identifier = UUID()
        refreshTask = task
        refreshTaskID = identifier
        defer { if refreshTaskID == identifier { refreshTask = nil; refreshTaskID = nil } }
        try await task.value
    }

    private func requireSocial() async throws -> CloudAPI {
        let current = generation
        guard !accessToken.isEmpty else { throw MobileStoreError.notSignedIn }
        do {
            if (tokenExpiresAt ?? .distantPast).timeIntervalSinceNow < 60, refreshToken != nil {
                try await refreshAccessToken(generation: current)
            }
            guard current == generation else { throw CancellationError() }
            guard (tokenExpiresAt ?? .distantPast) > Date() else { throw MobileStoreError.expiredSession }
        } catch {
            if current == generation && isPermanentSessionError(error) {
                signOut()
            }
            throw error
        }
        guard let client = socialClient else { throw MobileStoreError.missingConfiguration }
        return client
    }
    private func makeClient(_ url: String?) -> CloudAPI? { guard !accessToken.isEmpty, let url else { return nil }; return try? CloudAPI(baseURL: url, accessToken: accessToken, session: session) }
    private func authConfig() throws -> CloudAuthConfig { guard let auth = runtime?.auth, auth.mode == "cognito", auth.issuer != nil, auth.clientID != nil else { throw MobileStoreError.missingConfiguration }; return auth }
    private func cognito<T: Decodable>(auth: CloudAuthConfig, operation: String, body: [String: Any]) async throws -> T {
        guard let issuer = auth.issuer, var components = URLComponents(string: issuer) else { throw MobileStoreError.missingConfiguration }; components.path = "/"; components.query = nil; guard let url = components.url else { throw MobileStoreError.missingConfiguration }
        var request = URLRequest(url: url); request.httpMethod = "POST"; request.setValue("application/x-amz-json-1.1", forHTTPHeaderField: "Content-Type"); request.setValue("AWSCognitoIdentityProviderService.\(operation)", forHTTPHeaderField: "X-Amz-Target"); request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request); guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw CloudAPIError.http(status: (response as? HTTPURLResponse)?.statusCode ?? -1, message: "Authentication failed.") }; return try JSONDecoder().decode(T.self, from: data)
    }
    private func normalized(_ value: String) -> String { value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
    private func clearWorkspace() {
        ownedGulls = []; inboxByHandle = [:]; inboxCursors = [:]; inboxHeadCursors = [:]
        messagesByThreadID = [:]; threadCursors = [:]; threadHeadCursors = [:]; loadedThreads = []
        savedGulls = []; sentByHandle = [:]; sentTruncatedHandles = []
        pendingMessages = []; resolvedThreadIDs = [:]; moreCachedInboxes = []; moreCachedThreads = []
        loadedInboxes = []; verifiedInboxCursors = []; verifiedThreadCursors = []
        inboxPageStates = [:]; threadPageStates = [:]; activeInboxPages = []; activeThreadPages = []
        localInboxLimits = [:]; localThreadLimits = [:]
        aiUsage = nil; serverSnapshot = nil; lastSyncedAt = nil; syncIssue = nil
    }

    private func clearSession() {
        refreshTask?.cancel(); refreshTask = nil; refreshTaskID = nil
        refreshingGeneration = nil; drainingGeneration = nil
        retryingPendingIDs = []
        clearWorkspace()
        accessToken = ""; refreshToken = nil; idToken = nil; tokenExpiresAt = nil
        account = nil; isAdmin = false; challengePending = false
        challengeSession = nil; challengeEmail = nil; email = ""; code = ""
        error = nil; canRetryRestore = false
    }

    private var cacheWebsite: String {
        websiteURL.trimmingCharacters(in: .whitespacesAndNewlines).lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    private func scope(for ownerID: String) -> String { "\(cacheWebsite.utf8.count):\(cacheWebsite):\(ownerID)" }
    private var cacheScope: String? { userID.map(scope(for:)) }

    private func cacheEntry<Value: Encodable>(_ value: Value, id: String, date: Date? = nil) throws -> MobileLocalDatabase.Entry {
        MobileLocalDatabase.Entry(id: id, data: try JSONEncoder().encode(value), sortKey: (date ?? .now).timeIntervalSince1970)
    }

    private func cachedValue<Value: Decodable>(_ type: Value.Type, scope: String, bucket: String, id: String) async throws -> Value? {
        guard let entry = try await database.entry(scope: scope, bucket: bucket, id: id) else { return nil }
        return try JSONDecoder().decode(type, from: entry.data)
    }

    private func cachedValues<Value: Decodable>(_ type: Value.Type, scope: String, bucket: String, limit: Int = 1000) async throws -> [Value] {
        let entries = try await database.read(scope: scope, bucket: bucket, limit: limit)
        return try entries.map { try JSONDecoder().decode(type, from: $0.data) }
    }

    private func cacheValue<Value: Encodable>(_ value: Value, bucket: String, id: String, generation current: UUID) async {
        guard !isPreview, current == generation, let scope = cacheScope else { return }
        do { try await database.write(scope: scope, bucket: bucket, entries: [try cacheEntry(value, id: id)]) }
        catch { if current == generation { syncIssue = "Couldn't update saved content on this device." } }
    }

    private func cacheValues<Value: Encodable>(_ values: [Value], bucket: String, replacing: Bool = false, generation current: UUID, id: (Value) -> String, date: (Value) -> Date? = { _ in nil }) async {
        guard !isPreview, current == generation, let scope = cacheScope else { return }
        do {
            let entries = try values.map { try cacheEntry($0, id: id($0), date: date($0)) }
            try await database.write(scope: scope, bucket: bucket, entries: entries, replacing: replacing)
        } catch { if current == generation { syncIssue = "Couldn't update saved content on this device." } }
    }

    private func syncInboxState(_ handle: String, state: MobilePageState) {
        inboxPageStates[handle] = state
        if let cursor = state.historyCursor { inboxCursors[handle] = cursor }
        else { inboxCursors.removeValue(forKey: handle) }
        if let head = state.headCursor { inboxHeadCursors[handle] = head }
        else { inboxHeadCursors.removeValue(forKey: handle) }
        if state.historyCursorVerified { verifiedInboxCursors.insert(handle) }
        else { verifiedInboxCursors.remove(handle) }
    }

    private func syncThreadState(_ threadID: String, state: MobilePageState) {
        threadPageStates[threadID] = state
        if let cursor = state.historyCursor { threadCursors[threadID] = cursor }
        else { threadCursors.removeValue(forKey: threadID) }
        if let head = state.headCursor { threadHeadCursors[threadID] = head }
        else { threadHeadCursors.removeValue(forKey: threadID) }
        if state.historyCursorVerified { verifiedThreadCursors.insert(threadID) }
        else { verifiedThreadCursors.remove(threadID) }
    }

    private func runInboxCatchup(for gull: CloudGull, state: inout MobilePageState, generation current: UUID, maxPages: Int) async {
        guard maxPages > 0 else { return }
        for _ in 0..<maxPages {
            guard current == generation, !Task.isCancelled, var catchup = state.catchup else { return }
            guard !catchup.visitedCursors.contains(catchup.cursor) else { syncIssue = "Message sync could not advance."; return }
            do {
                let cursor = catchup.cursor
                let query = [URLQueryItem(name: "owner_user_id", value: userID), URLQueryItem(name: "agent_handle", value: gull.handle), URLQueryItem(name: "limit", value: "50"), URLQueryItem(name: "cursor", value: cursor)]
                let response: MobileInboxResponse = try await requireSocial().get("/agent-network/inbox", query: query)
                guard current == generation else { return }
                let priorState = state
                let priorItems = inboxByHandle[gull.handle] ?? []
                inboxByHandle[gull.handle] = dedupe(response.items + (inboxByHandle[gull.handle] ?? []))
                let next = response.nextCursor
                guard next != cursor, next.map({ !catchup.visitedCursors.contains($0) }) ?? true else { syncIssue = "Message sync could not advance."; return }
                let reached = catchup.anchorID.map { anchor in response.items.contains { $0.id == anchor } } ?? false
                if reached || next == nil {
                    if catchup.rebuilding { state.historyCursor = next; state.needsHistoryRebuild = false; state.historyBoundaryID = nil }
                    state.headID = catchup.candidateHeadID
                    state.catchup = nil
                    state.historyCursorVerified = true
                } else if let next {
                    catchup.visitedCursors.insert(cursor); catchup.cursor = next; state.catchup = catchup
                }
                syncInboxState(gull.handle, state: state)
                guard await cacheInboxPage(response.items, gull: gull, state: state, generation: current) else {
                    state = priorState
                    inboxByHandle[gull.handle] = priorItems
                    syncInboxState(gull.handle, state: state)
                    return
                }
            } catch let caught { error = message(for: caught); return }
        }
    }

    private func runThreadCatchup(_ threadID: String, for gull: CloudGull, state: inout MobilePageState, generation current: UUID, maxPages: Int) async {
        guard maxPages > 0 else { return }
        for _ in 0..<maxPages {
            guard current == generation, !Task.isCancelled, var catchup = state.catchup else { return }
            guard !catchup.visitedCursors.contains(catchup.cursor) else { return }
            do {
                let cursor = catchup.cursor
                let query = [URLQueryItem(name: "owner_user_id", value: userID), URLQueryItem(name: "agent_handle", value: gull.handle), URLQueryItem(name: "limit", value: "100"), URLQueryItem(name: "cursor", value: cursor)]
                let response: MobileThreadResponse = try await requireSocial().get("/agent-network/threads/\(threadID)", query: query)
                guard current == generation else { return }
                let priorState = state
                let priorMessages = messagesByThreadID[threadID] ?? []
                messagesByThreadID[threadID] = ordered(response.messages + (messagesByThreadID[threadID] ?? []))
                let next = response.nextCursor
                guard next != cursor, next.map({ !catchup.visitedCursors.contains($0) }) ?? true else { return }
                let reached = catchup.anchorID.map { anchor in response.messages.contains { messageCacheID($0) == anchor } } ?? false
                if reached || next == nil {
                    if catchup.rebuilding { state.historyCursor = next; state.needsHistoryRebuild = false; state.historyBoundaryID = nil }
                    state.headID = catchup.candidateHeadID
                    state.catchup = nil
                    state.historyCursorVerified = true
                } else if let next {
                    catchup.visitedCursors.insert(cursor); catchup.cursor = next; state.catchup = catchup
                }
                syncThreadState(threadID, state: state)
                guard await cacheThread(response.messages, threadID: threadID, state: state, generation: current) else {
                    state = priorState
                    messagesByThreadID[threadID] = priorMessages
                    syncThreadState(threadID, state: state)
                    return
                }
            } catch { return }
        }
    }

    private func cacheInboxPage(_ items: [MobileInboxItem], gull: CloudGull, state: MobilePageState, generation current: UUID) async -> Bool {
        guard !isPreview, current == generation, let scope = cacheScope else { return false }
        do {
            let rows = try items.map { try cacheEntry($0, id: $0.id, date: MobileDates.parse($0.message?.createdAt ?? $0.delivery.createdAt)) }
            let page = try cacheEntry(
                state,
                id: gull.handle
            )
            try await database.write(batches: [
                .init(scope: scope, bucket: "inbox:\(gull.handle)", entries: rows),
                .init(scope: scope, bucket: "inbox-pages", entries: [page])
            ])
            return true
        } catch { if current == generation { syncIssue = "Couldn't update saved content on this device." }; return false }
    }

    private func persistAccount(generation current: UUID) async {
        guard let account, let runtime else { return }
        await cacheValue(MobileCachedAccount(identity: account, runtime: runtime, lastSyncedAt: lastSyncedAt), bucket: "account", id: "snapshot", generation: current)
    }

    private func restoreCachedWorkspace(ownerID: String, generation current: UUID) async {
        let scope = scope(for: ownerID)
        do {
            guard let cached = try await cachedValue(MobileCachedAccount.self, scope: scope, bucket: "account", id: "snapshot"),
                  cached.identity.userID == ownerID, current == generation else { return }
            let gulls = try await cachedValues(CloudGull.self, scope: scope, bucket: "gulls")
            let usage = try await cachedValue(CloudAIUsageSummary.self, scope: scope, bucket: "usage", id: "summary")
            let server = try await cachedValue(CloudServerSnapshot.self, scope: scope, bucket: "server", id: "snapshot")
            let pending = try await cachedValues(MobilePendingMessage.self, scope: scope, bucket: "outbox", limit: Int.max)
            guard current == generation else { return }
            account = cached.identity; email = cached.identity.email ?? ""; runtime = cached.runtime
            ownedGulls = gulls; aiUsage = usage; serverSnapshot = server; lastSyncedAt = cached.lastSyncedAt
            pendingMessages = pending.sorted { $0.createdAt < $1.createdAt }.map {
                var item = $0
                if item.state == .sending { item.state = .unconfirmed }
                return item
            }
            loadSavedGulls()
            await restoreCachedMessages(gulls: gulls, generation: current)
        } catch {
            if current == generation { syncIssue = "Couldn't read saved content on this device." }
        }
    }

    private func restoreCachedMessages(gulls: [CloudGull], generation current: UUID) async {
        guard let ownerID = userID else { return }
        let scope = scope(for: ownerID)
        do {
            for gull in gulls {
                guard current == generation, !Task.isCancelled else { return }
                if inboxByHandle[gull.handle] == nil {
                    await restoreInbox(for: gull, generation: current)
                }
                let sent = try await cachedValues(MobileMessage.self, scope: scope, bucket: "sent:\(gull.handle)", limit: 250)
                let truncated = try await cachedValue(Bool.self, scope: scope, bucket: "sent-truncated", id: gull.handle)
                guard current == generation else { return }
                if sentByHandle[gull.handle] == nil {
                    sentByHandle[gull.handle] = sent
                    if truncated == true { sentTruncatedHandles.insert(gull.handle) }
                }
            }
            // Warm recent conversations only; older bodies stay in SQLite.
            let recent = try await database.read(scope: scope, bucket: "thread-pages", limit: 12)
            for page in recent {
                guard current == generation, !Task.isCancelled else { return }
                if messagesByThreadID[page.id] == nil {
                    await restoreThread(page.id, generation: current)
                }
            }
        } catch {
            if current == generation { syncIssue = "Couldn't read saved messages." }
        }
    }

    private func restoreInbox(for gull: CloudGull, generation current: UUID) async {
        guard let scope = cacheScope else { return }
        do {
            let limit = localInboxLimits[gull.handle] ?? 250
            let items = try await cachedValues(MobileInboxItem.self, scope: scope, bucket: "inbox:\(gull.handle)", limit: limit + 1)
            let page = try await cachedValue(MobilePageState.self, scope: scope, bucket: "inbox-pages", id: gull.handle)
            guard current == generation else { return }
            inboxByHandle[gull.handle] = dedupe(Array(items.prefix(limit)) + (inboxByHandle[gull.handle] ?? []))
            if items.count > limit { moreCachedInboxes.insert(gull.handle) }
            else { moreCachedInboxes.remove(gull.handle) }
            if let page, !loadedInboxes.contains(gull.handle) {
                var restored = page
                if restored.version < MobilePageState.currentVersion {
                    restored.version = MobilePageState.currentVersion
                    restored.initialized = false
                    restored.needsHistoryRebuild = true
                    restored.historyBoundaryID = items.last?.id
                }
                inboxPageStates[gull.handle] = restored
                syncInboxState(gull.handle, state: restored)
                loadedInboxes.insert(gull.handle)
            }
        } catch { if current == generation { syncIssue = "Couldn't read saved messages." } }
    }

    func restoreCachedThread(_ threadID: String) async { await restoreThread(threadID, generation: generation) }

    private func restoreThread(_ threadID: String, generation current: UUID, reload: Bool = false) async {
        guard !isPreview, reload || !loadedThreads.contains(threadID), let scope = cacheScope else { return }
        let inboxMessages = inboxByHandle.values.flatMap { $0 }.compactMap(\.message)
        let sentMessages = sentByHandle.values.flatMap { $0 }
        let known = (inboxMessages + sentMessages).filter { $0.threadID == threadID }
        do {
            let limit = localThreadLimits[threadID] ?? 100
            let messages = try await cachedValues(MobileMessage.self, scope: scope, bucket: "thread:\(threadID)", limit: limit + 1)
            let page = try await cachedValue(MobilePageState.self, scope: scope, bucket: "thread-pages", id: threadID)
            guard current == generation else { return }
            let restored = ordered(Array(messages.prefix(limit)) + known)
            messagesByThreadID[threadID] = ordered(Array(restored.suffix(limit)) + (messagesByThreadID[threadID] ?? []))
            if messages.count > limit || restored.count > limit { moreCachedThreads.insert(threadID) }
            else { moreCachedThreads.remove(threadID) }
            if let page, !loadedThreads.contains(threadID) {
                var restoredPage = page
                if restoredPage.version < MobilePageState.currentVersion {
                    restoredPage.version = MobilePageState.currentVersion
                    restoredPage.initialized = false
                    restoredPage.needsHistoryRebuild = true
                    restoredPage.historyBoundaryID = restored.last.map(messageCacheID)
                }
                threadPageStates[threadID] = restoredPage
                syncThreadState(threadID, state: restoredPage)
                loadedThreads.insert(threadID)
            }
        } catch { if current == generation { syncIssue = "Couldn't read this saved conversation." } }
    }

    private func messageCacheID(_ value: MobileMessage) -> String {
        value.messageID ?? "\(value.threadID ?? "")|\(value.createdAt ?? "")|\(value.contentInline ?? "")"
    }

    private func cacheThread(_ messages: [MobileMessage], threadID: String, state: MobilePageState, generation current: UUID) async -> Bool {
        guard !isPreview, current == generation, let scope = cacheScope else { return false }
        do {
            let rows = try messages.map { try cacheEntry($0, id: messageCacheID($0), date: MobileDates.parse($0.createdAt)) }
            let page = try cacheEntry(state, id: threadID)
            try await database.write(batches: [
                .init(scope: scope, bucket: "thread:\(threadID)", entries: rows),
                .init(scope: scope, bucket: "thread-pages", entries: [page])
            ])
            return true
        } catch { if current == generation { syncIssue = "Couldn't update saved content on this device." }; return false }
    }

    private func dedupe(_ values: [MobileMessage]) -> [MobileMessage] { var seen = Set<String>(); return values.filter { seen.insert($0.messageID ?? "\($0.threadID ?? "")|\($0.createdAt ?? "")|\($0.contentInline ?? "")").inserted } }
    private func dedupe(_ values: [MobileInboxItem]) -> [MobileInboxItem] { var seen = Set<String>(); return values.filter { seen.insert($0.id).inserted } }
    private func ordered(_ values: [MobileMessage]) -> [MobileMessage] {
        dedupe(values).sorted {
            let first = MobileDates.parse($0.createdAt) ?? .distantPast
            let second = MobileDates.parse($1.createdAt) ?? .distantPast
            return first == second ? messageCacheID($0) < messageCacheID($1) : first < second
        }
    }
    private func message(for error: Error) -> String { (error as? LocalizedError)?.errorDescription ?? "Cloud request failed." }
    private func isPermanentSessionError(_ error: Error) -> Bool {
        if error is MobileStoreError { return (error as? MobileStoreError) == .invalidRefreshToken }
        if let cloud = error as? CloudAPIError, case .http(let status, _) = cloud { return status == 401 || status == 403 }
        return false
    }
    private func decodeAdminClaim(_ token: String) -> Bool {
        let parts = token.split(separator: "."); guard parts.count == 3 else { return false }
        var payload = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        payload += String(repeating: "=", count: (4 - payload.count % 4) % 4)
        guard let data = Data(base64Encoded: payload), let claims = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        if ["1", "true", "yes"].contains((claims["custom:seagull_admin"] as? String)?.lowercased()) { return true }
        let groups: [String]
        if let values = claims["cognito:groups"] as? [String] { groups = values }
        else if let value = claims["cognito:groups"] as? String { groups = value.split { $0 == "," || $0 == " " }.map(String.init) }
        else { groups = [] }
        let roles = [claims["custom:role"] as? String, claims["role"] as? String].compactMap { $0 }
        return (groups + roles).contains { ["seagull-admin", "server-owner", "admin"].contains($0.lowercased()) }
    }
}

private struct MobileCachedAccount: Codable {
    let identity: CloudHumanIdentity
    let runtime: CloudRuntimeConfig
    let lastSyncedAt: Date?
}

private struct MobilePageState: Codable {
    static let currentVersion = 3

    var version: Int = Self.currentVersion
    var initialized = false
    var historyCursor: String?
    var headCursor: String?
    var headID: String?
    var catchup: MobileCatchup?
    var needsHistoryRebuild = false
    var historyBoundaryID: String?
    var historyCursorVerified = false

    init() {}

    private enum CodingKeys: String, CodingKey {
        case version, initialized, historyCursor, headCursor, headID, catchup
        case needsHistoryRebuild, historyBoundaryID, historyCursorVerified
        case legacyCursor = "cursor"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        version = try container.decodeIfPresent(Int.self, forKey: .version) ?? 1
        initialized = try container.decodeIfPresent(Bool.self, forKey: .initialized) ?? false
        historyCursor = try container.decodeIfPresent(String.self, forKey: .historyCursor)
            ?? (try container.decodeIfPresent(String.self, forKey: .legacyCursor))
        headCursor = try container.decodeIfPresent(String.self, forKey: .headCursor)
        headID = try container.decodeIfPresent(String.self, forKey: .headID)
        catchup = try container.decodeIfPresent(MobileCatchup.self, forKey: .catchup)
        needsHistoryRebuild = try container.decodeIfPresent(Bool.self, forKey: .needsHistoryRebuild) ?? (version < Self.currentVersion)
        historyBoundaryID = try container.decodeIfPresent(String.self, forKey: .historyBoundaryID)
        historyCursorVerified = try container.decodeIfPresent(Bool.self, forKey: .historyCursorVerified) ?? false
        if version < Self.currentVersion { historyCursorVerified = false }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(version, forKey: .version)
        try container.encode(initialized, forKey: .initialized)
        try container.encodeIfPresent(historyCursor, forKey: .historyCursor)
        try container.encodeIfPresent(headCursor, forKey: .headCursor)
        try container.encodeIfPresent(headID, forKey: .headID)
        try container.encodeIfPresent(catchup, forKey: .catchup)
        try container.encode(needsHistoryRebuild, forKey: .needsHistoryRebuild)
        try container.encodeIfPresent(historyBoundaryID, forKey: .historyBoundaryID)
        try container.encode(historyCursorVerified, forKey: .historyCursorVerified)
    }
}

private struct MobileCatchup: Codable {
    var cursor: String
    var anchorID: String?
    var candidateHeadID: String?
    var rebuilding: Bool
    var visitedCursors: Set<String> = []
}

private struct CognitoResponse: Decodable {
    struct AuthenticationResult: Decodable { var accessToken: String?; var idToken: String?; var refreshToken: String?; var expiresIn: Int?; enum CodingKeys: String, CodingKey { case accessToken = "AccessToken", idToken = "IdToken", refreshToken = "RefreshToken", expiresIn = "ExpiresIn" } }
    var challengeName: String?; var session: String?; var authenticationResult: AuthenticationResult?
    enum CodingKeys: String, CodingKey { case challengeName = "ChallengeName", session = "Session", authenticationResult = "AuthenticationResult" }
}

private struct CloudIdentityResponse: Decodable { var identity: CloudHumanIdentity }
private struct CloudProfileResponse: Decodable { var profile: CloudGull }
private struct MobileDeliveryActionResponse: Decodable { var delivery: MobileDelivery? }

private struct PreviewCredentials: MobileCredentialStore {
    func read() throws -> MobileStoredSession? { nil }
    func write(_ session: MobileStoredSession) throws {}
    func delete() throws {}
}
