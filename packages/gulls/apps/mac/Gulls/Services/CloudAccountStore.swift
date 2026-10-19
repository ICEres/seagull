import Foundation
import Observation

@MainActor
@Observable
final class CloudAccountStore {
    private let defaults: UserDefaults
    private let session: URLSession
    private let cli: GullsCLI?
    private let sharedSessionFile: SharedCloudSessionFile?
    private var challengeSession: String?
    private var challengeEmail: String?
    private var tokenExpiresAt: Date?
    @ObservationIgnored private var importedSharedSession: SharedCloudSession?
    @ObservationIgnored private var browserSignInTask: Task<Void, Never>?
    @ObservationIgnored private var browserSignInHandle: GullsCLI.StreamHandle?
    @ObservationIgnored private var browserSignInID: UUID?

    var websiteURL: String {
        didSet {
            defaults.set(websiteURL, forKey: Keys.websiteURL)
            guard oldValue != websiteURL else { return }
            runtime = nil
            signOut(sharedWebsiteURL: oldValue)
        }
    }
    private(set) var runtime: CloudRuntimeConfig?
    var email = ""
    var code = ""
    private(set) var challengePending = false
    private(set) var isBusy = false
    private(set) var isBrowserSignInPending = false
    private(set) var isRestoringSharedSession = false
    private(set) var error: String?
    private(set) var accessToken = ""
    private(set) var account: CloudHumanIdentity?
    private(set) var isAdmin = false
    private(set) var sessionID = UUID()
    private(set) var ownedGulls: [CloudGull] = []
    private(set) var aiUsage: CloudAIUsageSummary?
    private(set) var serverSnapshot: CloudServerSnapshot?

    private enum Keys { static let websiteURL = "cloudWebsiteURL" }

    init(defaults: UserDefaults = .standard, session: URLSession = .shared,
         cli: GullsCLI? = nil, sharedSessionURL: URL? = nil) {
        self.defaults = defaults
        self.session = session
        self.cli = cli
        self.sharedSessionFile = sharedSessionURL.map { SharedCloudSessionFile(url: $0) }
        websiteURL = defaults.string(forKey: Keys.websiteURL) ?? "https://sea.gulls.ai"
    }

    var isSignedIn: Bool { !accessToken.isEmpty && (tokenExpiresAt ?? .distantPast) > Date() }
    var accountLabel: String { account?.displayName ?? account?.email ?? email }
    var userID: String? { account?.userID }
    var canStartBrowserSignIn: Bool {
        !isBusy && !isBrowserSignInPending && !isRestoringSharedSession
    }

    var socialClient: CloudAPI? { makeClient(runtime?.socialAPIURL) }
    var messageClient: CloudAPI? { makeClient(runtime?.messageAPIURL) }
    var providerClient: CloudAPI? { makeClient(runtime?.aiProviderAPIURL) }

    func loadConfiguration() async {
        let generation = sessionID
        isBusy = true; error = nil
        defer { isBusy = false }
        do {
            guard let base = safeWebsiteURL(), let url = URL(string: base + "/config.js") else { throw CloudAPIError.invalidBaseURL }
            var request = URLRequest(url: url); request.httpMethod = "GET"
            let (data, response) = try await session.data(for: request, delegate: CloudRedirectDelegate(origin: url.originKey))
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw CloudAPIError.invalidResponse }
            let loaded = try CloudRuntimeConfig.parseConfigJS(String(decoding: data, as: UTF8.self))
            guard generation == sessionID else { return }
            runtime = loaded
        } catch let caughtError {
            guard generation == sessionID else { return }
            runtime = nil
            if isSignedIn { signOut() }
            self.error = sanitized(caughtError)
        }
    }

    func beginSignIn() async {
        if runtime == nil { await loadConfiguration() }
        let generation = sessionID
        isBusy = true; error = nil; challengePending = false
        defer { isBusy = false }
        do {
            let auth = try cognitoConfig()
            guard let clientID = auth.clientID else { throw CloudAccountError.missingAuthConfig }
            let result: CognitoResponse = try await cognitoRequest(auth: auth, operation: "InitiateAuth", body: [
                "AuthFlow": "USER_AUTH",
                "AuthParameters": ["USERNAME": normalize(email), "PREFERRED_CHALLENGE": "EMAIL_OTP"],
                "ClientId": clientID,
            ])
            guard result.challengeName == "EMAIL_OTP", let session = result.session else { throw CloudAccountError.invalidChallenge }
            guard generation == sessionID else { return }
            challengeSession = session; challengeEmail = normalize(email); challengePending = true
        } catch let caughtError { if generation == sessionID { self.error = sanitized(caughtError) } }
    }

    func completeSignIn() async {
        guard let challengeSessionValue = challengeSession, let challengeEmail else { error = "Start email sign-in first."; return }
        let generation = sessionID
        isBusy = true; error = nil
        defer { isBusy = false }
        do {
            let auth = try cognitoConfig()
            guard let clientID = auth.clientID else { throw CloudAccountError.missingAuthConfig }
            let result: CognitoResponse = try await cognitoRequest(auth: auth, operation: "RespondToAuthChallenge", body: [
                "ChallengeName": "EMAIL_OTP",
                "ChallengeResponses": ["USERNAME": challengeEmail, "EMAIL_OTP_CODE": code.trimmingCharacters(in: .whitespacesAndNewlines)],
                "ClientId": clientID,
                "Session": challengeSessionValue,
            ])
            guard generation == sessionID else { return }
            guard let authResult = result.authenticationResult, let token = authResult.accessToken else { throw CloudAccountError.invalidSession }
            guard let socialURL = runtime?.socialAPIURL, let temporaryClient = try? CloudAPI(baseURL: socialURL, accessToken: token, session: session) else {
                throw CloudAccountError.identityUnavailable
            }
            let identityResponse: CloudIdentityResponse = try await temporaryClient.get("/me")
            guard generation == sessionID else { return }
            accessToken = token
            tokenExpiresAt = Date().addingTimeInterval(TimeInterval(authResult.expiresIn ?? 3600))
            account = identityResponse.identity
            isAdmin = decodeAdminClaim(authResult.idToken ?? token)
            challengePending = false; challengeSession = nil; code = ""
            sessionID = UUID()
        } catch let caughtError { if generation == sessionID { self.error = sanitized(caughtError) } }
    }

    func signOut(sharedWebsiteURL: String? = nil) {
        cancelBrowserSignIn()
        clearAccountSession()
        guard let sharedSessionFile else { return }
        do { try sharedSessionFile.remove(for: sharedWebsiteURL ?? websiteURL) }
        catch { self.error = "The shared CLI sign-in could not be cleared. Run gulls logout and try again." }
    }

    private func clearAccountSession() {
        accessToken = ""; tokenExpiresAt = nil; account = nil; isAdmin = false
        challengePending = false; challengeSession = nil; challengeEmail = nil; code = ""
        ownedGulls = []; aiUsage = nil; serverSnapshot = nil; sessionID = UUID()
        importedSharedSession = nil
        error = nil
    }

    func startBrowserSignIn() {
        guard !isSignedIn, canStartBrowserSignIn else { return }
        guard let cli, let sharedSessionFile else {
            error = "The bundled Gulls CLI is unavailable. Reinstall the Mac app to sign in from your browser."
            return
        }
        guard let website = SharedCloudSessionFile.normalizedWebsite(websiteURL) else {
            error = "Choose a secure website in Connection details before signing in."
            return
        }
        let attempt = UUID()
        let pendingFile = SharedCloudSessionFile(url: sharedSessionFile.url.deletingLastPathComponent()
            .appendingPathComponent(".account-login-\(attempt.uuidString).json"))
        browserSignInID = attempt
        isBrowserSignInPending = true
        error = nil
        browserSignInTask = Task {
            defer {
                try? pendingFile.remove(for: website)
                if browserSignInID == attempt {
                    browserSignInID = nil
                    browserSignInTask = nil
                    browserSignInHandle = nil
                    isBrowserSignInPending = false
                }
            }
            do {
                try Task.checkCancellation()
                let handle = try await cli.openBrowserLogin(websiteURL: website, sessionFile: pendingFile.url)
                guard browserSignInID == attempt, !Task.isCancelled else {
                    handle.terminate()
                    return
                }
                browserSignInHandle = handle
                for try await _ in handle.lines { try Task.checkCancellation() }
                try Task.checkCancellation()
                guard browserSignInID == attempt else { return }
                await restoreSharedSession(from: pendingFile)
                if !isSignedIn, browserSignInID == attempt, error == nil {
                    error = "Browser sign-in did not finish. Try again."
                }
            } catch is CancellationError {
                // Cancelling closes the local callback listener through the CLI handle.
            } catch {
                if browserSignInID == attempt { self.error = sanitized(error) }
            }
        }
    }

    func cancelBrowserSignIn() {
        browserSignInID = nil
        browserSignInTask?.cancel()
        browserSignInHandle?.terminate()
        browserSignInTask = nil
        browserSignInHandle = nil
        isBrowserSignInPending = false
    }

    func synchronizeSharedSession() async {
        guard let sharedSessionFile, !isBrowserSignInPending else { return }
        await restoreSharedSession(from: sharedSessionFile)
    }

    private func restoreSharedSession(from source: SharedCloudSessionFile) async {
        guard let sharedSessionFile, !isRestoringSharedSession else { return }
        if isSignedIn, importedSharedSession == nil { return }
        isRestoringSharedSession = true
        defer { isRestoringSharedSession = false }
        let generation = sessionID
        do {
            guard let saved = try source.read(for: websiteURL), saved.expirationDate > Date() else {
                if importedSharedSession != nil { clearAccountSession() }
                return
            }
            guard saved != importedSharedSession else { return }
            if runtime == nil { await loadConfiguration() }
            guard generation == sessionID, !Task.isCancelled else { return }
            guard let socialURL = runtime?.socialAPIURL else { throw CloudAccountError.identityUnavailable }
            let client = try CloudAPI(baseURL: socialURL, accessToken: saved.accessToken, session: session)
            let response: CloudIdentityResponse = try await client.get("/me")
            guard generation == sessionID, !Task.isCancelled,
                  saved.expirationDate > Date(), !response.identity.userID.isEmpty,
                  try source.read(for: websiteURL) == saved else { return }
            if source.url != sharedSessionFile.url { try sharedSessionFile.write(saved) }
            accessToken = saved.accessToken
            tokenExpiresAt = saved.expirationDate
            account = response.identity
            email = response.identity.email ?? ""
            isAdmin = decodeAdminClaim(saved.accessToken)
            importedSharedSession = saved
            ownedGulls = []; aiUsage = nil; serverSnapshot = nil
            sessionID = UUID()
            error = nil
        } catch {
            if generation == sessionID, !Task.isCancelled {
                self.error = "The saved sign-in could not be verified. Sign in again from your browser."
            }
        }
    }

    func cancelChallenge() {
        challengePending = false; challengeSession = nil; challengeEmail = nil; code = ""
    }

    @discardableResult
    func refreshGulls() async -> Bool {
        guard let client = socialClient else { error = "Cloud Social API is not configured."; return false }
        let generation = sessionID
        do {
            let response: CloudGullsResponse = try await client.get("/profiles", query: userID.map { [URLQueryItem(name: "owner_user_id", value: $0)] } ?? [])
            guard generation == sessionID, isSignedIn else { return false }
            ownedGulls = response.items
            return true
        } catch let caughtError {
            if generation == sessionID { self.error = sanitized(caughtError) }
            return false
        }
    }

    func updateGull(_ gull: CloudGull, displayName: String?, bio: String?) async throws {
        guard let client = socialClient, let owner = userID else { throw CloudAccountError.notSignedIn }
        let generation = sessionID
        struct Body: Encodable { var ownerUserID: String; var displayName: String?; var bio: String? }
        let response: CloudProfileResponse = try await client.patch("/profiles/\(gull.handle)", body: Body(ownerUserID: owner, displayName: displayName, bio: bio))
        guard generation == sessionID else { throw CancellationError() }
        ownedGulls = ownedGulls.map { $0.agentID == response.profile.agentID ? response.profile : $0 }
    }

    func loadPrompt(for gull: CloudGull) async throws -> String {
        guard let client = socialClient, let owner = userID else { throw CloudAccountError.notSignedIn }
        let response: CloudPromptResponse = try await client.get("/profiles/\(gull.handle)/prompt", query: [URLQueryItem(name: "owner_user_id", value: owner)])
        return response.prompt?.instructions ?? ""
    }

    func savePrompt(for gull: CloudGull, instructions: String) async throws {
        guard let client = socialClient, let owner = userID else { throw CloudAccountError.notSignedIn }
        struct Body: Encodable { var ownerUserID: String; var instructions: String }
        _ = try await client.put("/profiles/\(gull.handle)/prompt", body: Body(ownerUserID: owner, instructions: instructions)) as CloudPromptResponse
    }

    func setRuntime(for gull: CloudGull, mode: CloudRuntimeMode) async throws -> CloudGullRuntime {
        guard let client = socialClient, let owner = userID else { throw CloudAccountError.notSignedIn }
        struct Body: Encodable { var ownerUserID: String; var mode: CloudRuntimeMode }
        let response: CloudRuntimeResponse = try await client.put("/profiles/\(gull.handle)/runtime", body: Body(ownerUserID: owner, mode: mode))
        return response.runtime
    }

    func loadRuntime(for gull: CloudGull) async throws -> CloudGullRuntime {
        guard let client = socialClient else { throw CloudAccountError.notSignedIn }
        let response: CloudRuntimeResponse = try await client.get("/profiles/\(gull.handle)/runtime")
        return response.runtime
    }

    func createLocalPairToken(for gull: CloudGull) async throws -> CloudPairToken {
        guard let client = socialClient else { throw CloudAccountError.notSignedIn }
        let response: CloudPairTokenResponse = try await client.post("/profiles/\(gull.handle)/local-pair-tokens")
        return response.pairToken
    }

    func disconnectLocalRuntime(for gull: CloudGull) async throws -> CloudGullRuntime {
        guard let client = socialClient else { throw CloudAccountError.notSignedIn }
        let response: CloudRuntimeResponse = try await client.delete("/profiles/\(gull.handle)/local-connection")
        return response.runtime
    }

    @discardableResult
    func refreshAIUsage() async -> Bool {
        guard let client = socialClient else { error = "Cloud Social API is not configured."; return false }
        let generation = sessionID
        do {
            let value: CloudAIUsageSummary = try await client.get("/me/ai-usage")
            guard generation == sessionID, isSignedIn else { return false }
            aiUsage = value
            return true
        }
        catch let caughtError {
            if generation == sessionID { self.error = sanitized(caughtError) }
            return false
        }
    }

    func refreshServer() async {
        guard isSignedIn, let message = messageClient, let social = socialClient else { error = "Sign in to the cloud account first."; return }
        let generation = sessionID
        var failures: [String] = []
        var snapshot = serverSnapshot ?? CloudServerSnapshot(health: [:], providerConfigs: [], serverBalance: nil, serverLedger: [], auditEvents: [], routingRules: [], moderationRecords: [])
        snapshot.health["social"] = try? await social.get("/health")
        snapshot.health["message"] = try? await message.get("/health")
        if let provider = providerClient {
            snapshot.health["provider"] = try? await provider.get("/health")
        }
        do { snapshot.routingRules = try await (message.get("/routing-rules") as CloudRoutingRulesResponse).items }
        catch { failures.append("Routing: \(sanitized(error))") }
        do { snapshot.moderationRecords = try await (social.get("/moderation") as CloudModerationResponse).items }
        catch { failures.append("Moderation: \(sanitized(error))") }
        if isAdmin, let provider = providerClient {
            do { snapshot.providerConfigs = try await (provider.get("/admin/ai-providers") as CloudProviderConfigsResponse).providerConfigs }
            catch { failures.append("AI provider: \(sanitized(error))") }
            do { snapshot.serverBalance = try await (provider.get("/admin/ai-credits/server-balance") as CloudServerBalanceResponse).balance }
            catch { failures.append("Server credits: \(sanitized(error))") }
            do { snapshot.serverLedger = try await (provider.get("/admin/ai-credits/server-ledger") as CloudServerLedgerResponse).entries }
            catch { failures.append("Server ledger: \(sanitized(error))") }
            do { snapshot.auditEvents = try await (provider.get("/admin/ai-audit-events") as CloudAuditResponse).events }
            catch { failures.append("Audit: \(sanitized(error))") }
        }
        guard generation == sessionID, isSignedIn else { return }
        serverSnapshot = snapshot
        error = failures.isEmpty ? nil : failures.joined(separator: "\n")
    }

    func saveProvider(_ draft: CloudProviderDraft) async throws {
        guard let client = providerClient, let actor = userID else { throw CloudAccountError.notSignedIn }
        struct Body: Encodable { var adminActorID: String; var enabled: Bool; var allowedModels: [String]; var apiKey: String?; var secretRef: String?; var region: String?; var reason: String? }
        _ = try await client.post("/admin/ai-providers/\(draft.provider)", body: Body(adminActorID: actor, enabled: draft.enabled, allowedModels: draft.allowedModels, apiKey: draft.apiKey, secretRef: draft.secretRef, region: draft.region, reason: draft.reason)) as CloudProviderResponse
        await refreshServer()
    }

    func grantServerCredits(amount: Int, reason: String) async throws {
        guard let client = providerClient, let actor = userID else { throw CloudAccountError.notSignedIn }
        struct Body: Encodable { var adminActorID: String; var creditAmount: Int; var reason: String }
        _ = try await client.post("/admin/ai-credits/server-grants", body: Body(adminActorID: actor, creditAmount: amount, reason: reason)) as CloudGrantResponse
        await refreshServer()
    }

    func createRoutingRule(_ draft: CloudRoutingRuleDraft) async throws {
        guard let client = messageClient else { throw CloudAccountError.notSignedIn }
        _ = try await client.post("/routing-rules", body: draft) as CloudRoutingRuleResponse
        await refreshServer()
    }

    private func safeWebsiteURL() -> String? {
        SharedCloudSessionFile.normalizedWebsite(websiteURL)
    }

    private func makeClient(_ value: String?) -> CloudAPI? {
        guard isSignedIn, let value, !value.isEmpty else { return nil }
        return try? CloudAPI(baseURL: value, accessToken: accessToken, session: session)
    }

    private func cognitoConfig() throws -> CloudAuthConfig {
        guard let auth = runtime?.auth, auth.mode == "cognito", let issuer = auth.issuer, let clientID = auth.clientID else { throw CloudAccountError.missingAuthConfig }
        guard let issuerURL = URL(string: issuer), issuerURL.scheme == "https" else { throw CloudAccountError.missingAuthConfig }
        var result = auth; result.issuer = issuerURL.absoluteString; result.clientID = clientID; return result
    }

    private func cognitoRequest<T: Decodable>(auth: CloudAuthConfig, operation: String, body: [String: Any]) async throws -> T {
        guard let issuer = auth.issuer, let parsed = URL(string: issuer), var components = URLComponents(url: parsed, resolvingAgainstBaseURL: false) else { throw CloudAccountError.missingAuthConfig }
        components.path = "/"
        components.query = nil; components.fragment = nil
        guard let url = components.url else { throw CloudAccountError.missingAuthConfig }
        var request = URLRequest(url: url); request.httpMethod = "POST"
        request.setValue("application/x-amz-json-1.1", forHTTPHeaderField: "Content-Type")
        request.setValue("AWSCognitoIdentityProviderService.\(operation)", forHTTPHeaderField: "X-Amz-Target")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request, delegate: CloudRedirectDelegate(origin: url.originKey))
        let payload = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw CloudAPIError.http(status: (response as? HTTPURLResponse)?.statusCode ?? -1, message: (payload?["message"] as? String) ?? "Authentication failed")
        }
        do { return try JSONDecoder().decode(T.self, from: data) } catch { throw CloudAPIError.decoding }
    }

    private func normalize(_ value: String) -> String { value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
    private func sanitized(_ error: Error) -> String { (error as? LocalizedError)?.errorDescription ?? "Cloud account request failed." }
    private func decodeAdminClaim(_ token: String) -> Bool {
        let parts = token.split(separator: "."); guard parts.count == 3 else { return false }
        var value = String(parts[1]); value += String(repeating: "=", count: (4 - value.count % 4) % 4); value = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        guard let data = Data(base64Encoded: value), let claims = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        let adminFlag = (claims["custom:seagull_admin"] as? String) ?? (claims["seagull_admin"] as? String)
        if ["1", "true", "yes"].contains(adminFlag?.lowercased()) { return true }
        let groups: [String]
        if let values = claims["cognito:groups"] as? [String] { groups = values }
        else if let value = claims["cognito:groups"] as? String { groups = value.split { $0 == "," || $0 == " " }.map(String.init) }
        else { groups = [] }
        let roles = [claims["custom:role"] as? String, claims["role"] as? String].compactMap { $0 }
        let allowed = Set(["seagull-admin", "server-owner", "admin"])
        return (groups + roles).contains { allowed.contains($0.lowercased()) }
    }

#if DEBUG
    func setTestSession(accessToken: String, userID: String, admin: Bool) {
        self.accessToken = accessToken
        tokenExpiresAt = .distantFuture
        account = CloudHumanIdentity(userID: userID, provider: "test", subject: userID, email: nil, displayName: nil, createdAt: nil, updatedAt: nil)
        isAdmin = admin
        sessionID = UUID()
    }
#endif
}

private enum CloudAccountError: Error, LocalizedError {
    case invalidChallenge, invalidSession, missingAuthConfig, notSignedIn, identityUnavailable
    var errorDescription: String? {
        switch self { case .invalidChallenge: return "Cognito did not start an email-code challenge."; case .invalidSession: return "Cognito did not return an authenticated session."; case .missingAuthConfig: return "The cloud site has no usable Cognito configuration."; case .notSignedIn: return "Sign in to the cloud account first."; case .identityUnavailable: return "The cloud account identity could not be verified." }
    }
}

private struct CognitoResponse: Decodable {
    struct AuthenticationResult: Decodable {
        var accessToken: String?
        var idToken: String?
        var expiresIn: Int?

        enum CodingKeys: String, CodingKey {
            case accessToken = "AccessToken"
            case idToken = "IdToken"
            case expiresIn = "ExpiresIn"
        }
    }
    var challengeName: String?
    var session: String?
    var authenticationResult: AuthenticationResult?

    enum CodingKeys: String, CodingKey {
        case challengeName = "ChallengeName"
        case session = "Session"
        case authenticationResult = "AuthenticationResult"
    }
}
private struct CloudIdentityResponse: Decodable { var identity: CloudHumanIdentity }
private struct CloudProfileResponse: Decodable { var profile: CloudGull }
