import Foundation
import Observation
import Security

enum MobileStoreError: Error, LocalizedError, Equatable {
    case missingConfiguration
    case notSignedIn
    case invalidChallenge
    case invalidSession
    case expiredSession
    case invalidRefreshToken
    case invalidRuntimeMode
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
    @ObservationIgnored private var challengeSession: String?
    @ObservationIgnored private var challengeEmail: String?
    @ObservationIgnored private var refreshToken: String?
    @ObservationIgnored private var tokenExpiresAt: Date?
    @ObservationIgnored private var generation = UUID()
    @ObservationIgnored private var refreshTask: Task<Void, Error>?
    @ObservationIgnored private var refreshTaskID: UUID?
    @ObservationIgnored private var isRefreshing = false
    @ObservationIgnored private var previewPrompts: [String: String] = [:]
    @ObservationIgnored private var previewModes: [String: CloudRuntimeMode] = [:]
    @ObservationIgnored private var loadedThreads: Set<String> = []
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
    private(set) var messagesByThreadID: [String: [MobileMessage]] = [:]
    private(set) var threadCursors: [String: String] = [:]
    private(set) var savedGulls: [SavedGull] = []
    private(set) var sentByHandle: [String: [MobileMessage]] = [:]
    private(set) var sentTruncatedHandles: Set<String> = []
    private(set) var isRestoring = false
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
        isPreview: Bool = false
    ) {
        self.websiteURL = websiteURL
        self.session = session
        self.credentials = credentials
        self.defaults = defaults
        self.isPreview = isPreview
    }

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
        account != nil && ((!accessToken.isEmpty && (tokenExpiresAt ?? .distantPast) > Date()) || refreshToken != nil)
    }
    var accountLabel: String { account?.displayName ?? account?.email ?? email }
    var userID: String? { account?.userID }
    var socialClient: CloudAPI? { makeClient(runtime?.socialAPIURL) }
    var providerClient: CloudAPI? { makeClient(runtime?.aiProviderAPIURL) }

    func prepare() async {
        if isPreview { return }
        guard !isRestoring else { return }
        let current = generation
        isRestoring = true
        canRetryRestore = false
        defer { isRestoring = false }
        do {
            try await loadConfiguration()
            guard current == generation, let saved = try credentials.read() else { return }
            accessToken = saved.accessToken; refreshToken = saved.refreshToken; tokenExpiresAt = saved.expiresAt
            if saved.expiresAt.timeIntervalSinceNow < 60, saved.refreshToken != nil { try await refreshAccessToken(generation: current) }
            guard current == generation else { return }
            let identity: CloudIdentityResponse = try await requireSocial().get("/me")
            guard current == generation else { return }
            account = identity.identity; email = identity.identity.email ?? ""; isAdmin = decodeAdminClaim(saved.idToken ?? saved.accessToken)
            loadSavedGulls()
            await refresh()
        } catch let caught {
            guard current == generation else { return }
            if isPermanentSessionError(caught) { clearSession(); try? credentials.delete() }
            else { canRetryRestore = true }
            error = message(for: caught)
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
    func signOut() { generation = UUID(); clearSession(); try? credentials.delete() }

    func refresh() async {
        guard !isPreview, !isRefreshing, isSignedIn else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        let current = generation
        error = nil
        _ = await refreshGulls(generation: current)
        guard current == generation else { return }
        for gull in ownedGulls { _ = await refreshInbox(for: gull, cursor: nil, generation: current) }
        for gull in ownedGulls {
            guard current == generation else { return }
            _ = await refreshSent(for: gull)
        }
        _ = await refreshAIUsage(generation: current)
        await refreshServer(generation: current)
    }

    @discardableResult
    func refreshGulls() async -> Bool { await refreshGulls(generation: generation) }
    private func refreshGulls(generation current: UUID) async -> Bool {
        if isPreview { return true }
        do {
            let response: CloudGullsResponse = try await requireSocial().get("/profiles", query: userID.map { [URLQueryItem(name: "owner_user_id", value: $0)] } ?? [])
            guard current == generation, isSignedIn else { return false }
            ownedGulls = response.items; return true
        } catch let caught { if current == generation { error = message(for: caught) }; return false }
    }

    @discardableResult
    func refreshInbox(for gull: CloudGull) async -> Bool { await refreshInbox(for: gull, cursor: nil, generation: generation) }

    @discardableResult
    func loadMoreInbox(for gull: CloudGull) async -> Bool {
        guard inboxCursors[gull.handle] != nil else { return false }
        return await refreshInbox(for: gull, cursor: inboxCursors[gull.handle], generation: generation)
    }

    private func refreshInbox(for gull: CloudGull, cursor: String?, generation current: UUID) async -> Bool {
        if isPreview { return true }
        do {
            var query = [URLQueryItem(name: "owner_user_id", value: userID), URLQueryItem(name: "agent_handle", value: gull.handle), URLQueryItem(name: "limit", value: "50")]
            if let cursor { query.append(URLQueryItem(name: "cursor", value: cursor)) }
            let response: MobileInboxResponse = try await requireSocial().get("/agent-network/inbox", query: query)
            guard current == generation else { return false }
            let alreadyLoaded = inboxByHandle[gull.handle] != nil
            inboxByHandle[gull.handle] = dedupe(response.items + (inboxByHandle[gull.handle] ?? []))
            if cursor != nil || !alreadyLoaded { inboxCursors[gull.handle] = response.nextCursor }
            return true
        } catch let caught { if current == generation { error = message(for: caught) }; return false }
    }

    @discardableResult
    func loadThread(_ threadID: String, for gull: CloudGull) async throws -> [MobileMessage] {
        if isPreview { return messagesByThreadID[threadID] ?? [] }
        let current = generation
        let response: MobileThreadResponse = try await requireSocial().get("/agent-network/threads/\(threadID)", query: [URLQueryItem(name: "owner_user_id", value: userID), URLQueryItem(name: "agent_handle", value: gull.handle), URLQueryItem(name: "limit", value: "100")])
        guard current == generation, isSignedIn else { throw CancellationError() }
        let alreadyLoaded = loadedThreads.contains(threadID)
        messagesByThreadID[threadID] = ordered(response.messages + (messagesByThreadID[threadID] ?? []))
        if !alreadyLoaded { threadCursors[threadID] = response.nextCursor }
        loadedThreads.insert(threadID)
        return messagesByThreadID[threadID] ?? []
    }

    @discardableResult
    func loadMoreThread(_ threadID: String, for gull: CloudGull) async throws -> [MobileMessage] {
        if isPreview { return messagesByThreadID[threadID] ?? [] }
        let current = generation
        guard threadCursors[threadID] != nil else { return messagesByThreadID[threadID] ?? [] }
        var query = [URLQueryItem(name: "owner_user_id", value: userID), URLQueryItem(name: "agent_handle", value: gull.handle), URLQueryItem(name: "limit", value: "100")]
        if let cursor = threadCursors[threadID] { query.append(URLQueryItem(name: "cursor", value: cursor)) }
        let response: MobileThreadResponse = try await requireSocial().get("/agent-network/threads/\(threadID)", query: query)
        guard current == generation, isSignedIn else { throw CancellationError() }
        messagesByThreadID[threadID] = ordered(response.messages + (messagesByThreadID[threadID] ?? []))
        threadCursors[threadID] = response.nextCursor
        return messagesByThreadID[threadID] ?? []
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
        if let original = response.message {
            let normalized = MobileMessage(messageID: original.messageID ?? response.messageID ?? idempotencyKey, threadID: response.threadID ?? original.threadID ?? threadID, senderAgentID: original.senderAgentID ?? sender.agentID, senderHandle: original.senderHandle ?? sender.handle, senderDisplayName: original.senderDisplayName ?? sender.displayName, recipientAgentIDs: original.recipientAgentIDs, recipientHandles: original.recipientHandles ?? [recipientHandle], contentInline: original.contentInline ?? content, createdAt: original.createdAt ?? ISO8601DateFormatter().string(from: Date()))
            response.message = normalized
            response.threadID = normalized.threadID
            if let resolvedThread = normalized.threadID { messagesByThreadID[resolvedThread] = ordered([normalized] + (messagesByThreadID[resolvedThread] ?? [])) }
            sentByHandle[sender.handle] = dedupe((sentByHandle[sender.handle] ?? []) + [normalized])
        }
        return response
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
            sentByHandle[gull.handle] = dedupe(response.messages)
            if response.truncated == true { sentTruncatedHandles.insert(gull.handle) } else { sentTruncatedHandles.remove(gull.handle) }
            return true
        } catch let caught { if current == generation { error = message(for: caught) }; return false }
    }

    @discardableResult
    func refreshAIUsage() async -> Bool { await refreshAIUsage(generation: generation) }
    private func refreshAIUsage(generation current: UUID) async -> Bool {
        if isPreview { return true }
        do { let value: CloudAIUsageSummary = try await requireSocial().get("/me/ai-usage"); guard current == generation else { return false }; aiUsage = value; return true }
        catch { return false }
    }

    func refreshServer() async { await refreshServer(generation: generation) }
    private func refreshServer(generation current: UUID) async {
        if isPreview { return }
        guard isSignedIn else { return }
        var snapshot = serverSnapshot ?? CloudServerSnapshot(health: [:], providerConfigs: [], serverBalance: nil, serverLedger: [], auditEvents: [], routingRules: [], moderationRecords: [])
        guard let social = try? await requireSocial(), current == generation else { return }
        snapshot.health["social"] = try? await social.get("/health")
        if let messageURL = runtime?.messageAPIURL, let message = try? CloudAPI(baseURL: messageURL, accessToken: accessToken, session: session) { snapshot.health["message"] = try? await message.get("/health") }
        if let provider = providerClient { snapshot.health["provider"] = try? await provider.get("/health") }
        if isAdmin, let provider = providerClient {
            snapshot.providerConfigs = (try? await (provider.get("/admin/ai-providers") as CloudProviderConfigsResponse).providerConfigs) ?? snapshot.providerConfigs
            snapshot.serverBalance = (try? await (provider.get("/admin/ai-credits/server-balance") as CloudServerBalanceResponse).balance) ?? snapshot.serverBalance
            snapshot.serverLedger = (try? await (provider.get("/admin/ai-credits/server-ledger") as CloudServerLedgerResponse).entries) ?? snapshot.serverLedger
            snapshot.auditEvents = (try? await (provider.get("/admin/ai-audit-events") as CloudAuditResponse).events) ?? snapshot.auditEvents
        }
        guard current == generation else { return }
        serverSnapshot = snapshot
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
        accessToken = token; refreshToken = result.refreshToken; tokenExpiresAt = Date().addingTimeInterval(TimeInterval(expires)); challengePending = false; challengeSession = nil; code = ""
        let identity: CloudIdentityResponse = try await requireSocial().get("/me")
        guard current == generation else { throw CancellationError() }
        account = identity.identity; email = identity.identity.email ?? email; isAdmin = decodeAdminClaim(result.idToken ?? token)
        try credentials.write(MobileStoredSession(accessToken: token, refreshToken: result.refreshToken, idToken: result.idToken, expiresAt: tokenExpiresAt!))
        loadSavedGulls()
        await refresh()
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
                try self.credentials.write(MobileStoredSession(accessToken: token, refreshToken: self.refreshToken, idToken: result.idToken, expiresAt: self.tokenExpiresAt!))
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
            if current == generation && (isPermanentSessionError(error) || (error as? MobileStoreError) == .expiredSession) {
                generation = UUID()
                clearSession()
                try? credentials.delete()
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
    private func clearSession() { refreshTask?.cancel(); refreshTask = nil; refreshTaskID = nil; accessToken = ""; refreshToken = nil; tokenExpiresAt = nil; account = nil; isAdmin = false; ownedGulls = []; inboxByHandle = [:]; inboxCursors = [:]; messagesByThreadID = [:]; threadCursors = [:]; loadedThreads = []; savedGulls = []; sentByHandle = [:]; sentTruncatedHandles = []; aiUsage = nil; serverSnapshot = nil; challengePending = false; challengeSession = nil; challengeEmail = nil; email = ""; code = ""; error = nil; canRetryRestore = false }
    private func dedupe(_ values: [MobileMessage]) -> [MobileMessage] { var seen = Set<String>(); return values.filter { seen.insert($0.messageID ?? "\($0.threadID ?? "")|\($0.createdAt ?? "")|\($0.contentInline ?? "")").inserted } }
    private func dedupe(_ values: [MobileInboxItem]) -> [MobileInboxItem] { var seen = Set<String>(); return values.filter { seen.insert($0.id).inserted } }
    private func ordered(_ values: [MobileMessage]) -> [MobileMessage] { dedupe(values).sorted { (MobileDates.parse($0.createdAt) ?? .distantPast) < (MobileDates.parse($1.createdAt) ?? .distantPast) } }
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
