import Foundation
import Observation

// Owns the set of local Gull profiles shown by the Mac app. The registry only
// contains profile IDs; connection secrets remain in each profile's Keychain
// item through GullsConfig. Pairing tokens are request-only and are never
// persisted, logged, or included in a result.
@MainActor
@Observable
final class LocalConnectionsStore {
    private static let registryKey = "gull.profileIDs"

    private let defaults: UserDefaults
    private let tokenStore: any GullsTokenStore

    private(set) var profiles: [GullsConfig]
    private(set) var selectedProfileID: String

    var selectedConfig: GullsConfig? {
        profiles.first { $0.profileID == selectedProfileID }
    }

    /// Prefer a paired Gull over an old standalone development profile.
    /// Network availability must not change the initial inbox scope.
    var preferredInboxProfileID: String? {
        let configured = profiles.filter(\.isConfigured)
        return configured.first { $0.profileID == selectedProfileID && $0.isLocallyPaired }?.profileID
            ?? configured.first(where: \.isLocallyPaired)?.profileID
            ?? configured.first { $0.profileID == selectedProfileID }?.profileID
            ?? configured.first?.profileID
    }

    init(
        defaults: UserDefaults = .standard,
        tokenStore: any GullsTokenStore = KeychainStore()
    ) {
        self.defaults = defaults
        self.tokenStore = tokenStore
        let storedIDs = defaults.stringArray(forKey: Self.registryKey) ?? []
        let ids = Self.normalizedIDs(storedIDs)
        let resolvedIDs = ids.isEmpty ? [GullsConfig.defaultProfileID] : ids
        self.profiles = resolvedIDs.map { GullsConfig(profileID: $0, defaults: defaults, tokenStore: tokenStore) }
        self.selectedProfileID = defaults.string(forKey: "gull.selectedProfileID") ?? resolvedIDs[0]
        if !resolvedIDs.contains(self.selectedProfileID) {
            self.selectedProfileID = resolvedIDs[0]
        }
        persistRegistry()
    }

    @discardableResult
    func select(profileID: String) -> GullsConfig? {
        guard profiles.contains(where: { $0.profileID == profileID }) else { return nil }
        selectedProfileID = profileID
        defaults.set(profileID, forKey: "gull.selectedProfileID")
        return selectedConfig
    }

    @discardableResult
    func add(displayName: String? = nil) -> GullsConfig {
        let id = UUID().uuidString.lowercased()
        let config = GullsConfig(profileID: id, defaults: defaults, tokenStore: tokenStore, displayName: displayName)
        profiles.append(config)
        selectedProfileID = id
        defaults.set(id, forKey: "gull.selectedProfileID")
        persistRegistry()
        return config
    }

    // Removes a profile from the app registry. It intentionally does not
    // delete its Keychain item or UserDefaults values; a later re-add can
    // recover the profile, and remote revocation belongs to the web API.
    @discardableResult
    func remove(profileID: String) -> Bool {
        guard profileID != GullsConfig.defaultProfileID,
              let index = profiles.firstIndex(where: { $0.profileID == profileID }) else { return false }
        profiles.remove(at: index)
        if selectedProfileID == profileID {
            selectedProfileID = profiles.first?.profileID ?? GullsConfig.defaultProfileID
            defaults.set(selectedProfileID, forKey: "gull.selectedProfileID")
        }
        persistRegistry()
        return true
    }

    @discardableResult
    func importSharedEnvIntoSelected() -> [String]? {
        selectedConfig?.importFromSharedEnvFile()
    }

    struct PairResult: Equatable {
        let profileID: String
        let agentHandle: String
        let nodeID: String
    }

    enum PairError: Error, LocalizedError {
        case invalidServer
        case invalidResponse
        case profileRemoved
        case credentialStoreUnavailable
        case rejected(Int)
        case transport(String)

        var errorDescription: String? {
            switch self {
            case .invalidServer: return "Pairing server must use HTTPS; HTTP is allowed only for loopback development."
            case .invalidResponse: return "The pairing response was incomplete."
            case .profileRemoved: return "This local Gull was removed before pairing finished."
            case .credentialStoreUnavailable: return "The connector token could not be saved in the Keychain."
            case .rejected(let status): return "Pairing was rejected (HTTP \(status))."
            case .transport(let message): return "Pairing failed: \(message)"
            }
        }
    }

    // Exchanges a one-time web pairing token for a node-bound runtime token.
    // The token is kept in memory only for this request and is never echoed.
    func pair(
        profileID: String,
        socialAPIURL: String,
        pairingToken: String,
        expectedHandle: String? = nil,
        session: URLSession = .shared
    ) async throws -> PairResult {
        guard let config = profiles.first(where: { $0.profileID == profileID }) else {
            throw PairError.profileRemoved
        }
        let base = socialAPIURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard Self.isSecureEndpoint(base), !pairingToken.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let url = URL(string: base + "/local-connections/pair") else {
            throw PairError.invalidServer
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["pair_token": pairingToken])

        // Pairing tokens are bearer credentials. Use a per-request session
        // whose delegate refuses redirects, including redirects in injected
        // preview/test sessions. The cloned configuration preserves custom
        // URLProtocol handlers without reusing a session delegate we do not
        // control.
        let requestSession = URLSession(
            configuration: session.configuration,
            delegate: NoRedirectSessionDelegate(),
            delegateQueue: nil
        )
        defer { requestSession.invalidateAndCancel() }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await requestSession.data(for: request)
        } catch {
            throw PairError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else { throw PairError.transport("invalid server response") }
        guard (200..<300).contains(http.statusCode) else { throw PairError.rejected(http.statusCode) }
        guard let payload = try? JSONDecoder().decode(PairResponse.self, from: data),
              !payload.apiURL.isEmpty, !payload.socialAPIURL.isEmpty,
              !payload.agentHandle.isEmpty, !payload.nodeID.isEmpty,
              payload.token.hasPrefix("sga_"),
              expectedHandle == nil || expectedHandle == payload.agentHandle,
              Self.isSecureEndpoint(payload.apiURL), Self.isSecureEndpoint(payload.socialAPIURL) else {
            throw PairError.invalidResponse
        }

        guard profiles.contains(where: { $0.profileID == profileID }) else {
            throw PairError.profileRemoved
        }
        guard config.setToken(payload.token) else {
            throw PairError.credentialStoreUnavailable
        }

        config.apiURL = payload.apiURL
        config.socialAPIURL = payload.socialAPIURL
        config.agentHandle = payload.agentHandle
        config.nodeID = payload.nodeID
        return PairResult(profileID: config.profileID, agentHandle: config.agentHandle, nodeID: config.nodeID)
    }

    private func persistRegistry() {
        defaults.set(profiles.map(\.profileID), forKey: Self.registryKey)
    }

    private static func normalizedIDs(_ raw: [String]) -> [String] {
        var seen = Set<String>()
        return ([GullsConfig.defaultProfileID] + raw)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && seen.insert($0).inserted }
    }

    private static func isSecureEndpoint(_ raw: String) -> Bool {
        guard let url = URL(string: raw), let scheme = url.scheme?.lowercased(), let host = url.host else { return false }
        if scheme == "https" { return true }
        return scheme == "http" && ["localhost", "127.0.0.1", "::1"].contains(host.lowercased())
    }
}

private struct PairResponse: Decodable {
    let apiURL: String
    let socialAPIURL: String
    let agentHandle: String
    let nodeID: String
    let token: String

    enum CodingKeys: String, CodingKey {
        case apiURL = "api_url"
        case socialAPIURL = "social_api_url"
        case agentHandle = "agent_handle"
        case nodeID = "node_id"
        case token
    }
}

private final class NoRedirectSessionDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}
