import Foundation
import Observation
import Security
import CryptoKit

// Per-Gull app configuration. Public settings live in UserDefaults; connector
// tokens stay in profile-namespaced Keychain items. Legacy default keys and the
// legacy token are read as migration sources and are never deleted.
@Observable
final class GullsConfig {
    static let defaultPollInterval: Double = 15
    static let defaultProfileID = "default"

    let profileID: String

    var displayName: String { didSet { defaults.set(displayName, forKey: keys.displayName) } }
    var apiURL: String { didSet { defaults.set(apiURL, forKey: keys.apiURL) } }
    var socialAPIURL: String { didSet { defaults.set(socialAPIURL, forKey: keys.socialAPIURL) } }
    var nodeID: String { didSet { defaults.set(nodeID, forKey: keys.nodeID) } }
    var agentHandle: String { didSet { defaults.set(agentHandle, forKey: keys.agentHandle) } }
    var pollInterval: Double { didSet { defaults.set(pollInterval, forKey: keys.pollInterval) } }
    var contextDir: String { didSet { defaults.set(contextDir, forKey: keys.contextDir) } }
    var streamURL: String { didSet { defaults.set(streamURL, forKey: keys.streamURL) } }

    // Local inbox monitoring only. This never enables AI replies.
    var monitoringEnabled: Bool { didSet { defaults.set(monitoringEnabled, forKey: keys.monitoringEnabled) } }

    var codexEnabled: Bool { didSet { defaults.set(codexEnabled, forKey: keys.codexEnabled) } }

    // The connection editor saves explicitly; tokens never enter UserDefaults.
    var token: String {
        didSet {
            if isApplyingToken { return }
            defaults.set(true, forKey: keys.legacyTokenMigrated)
            if !tokenStore.setToken(token, for: profileID) {
                NSLog("Gulls: failed to store the connector token in the Keychain")
            }
        }
    }

    private let defaults: UserDefaults
    private let tokenStore: any GullsTokenStore
    private let keys: ProfileKeys
    private var isApplyingToken = false

    @discardableResult
    func setToken(_ value: String) -> Bool {
        guard tokenStore.setToken(value, for: profileID) else { return false }
        defaults.set(true, forKey: keys.legacyTokenMigrated)
        isApplyingToken = true
        token = value
        isApplyingToken = false
        return true
    }

    // Existing call sites continue to create the legacy/default profile.
    convenience init(defaults: UserDefaults = .standard) {
        self.init(profileID: Self.defaultProfileID, defaults: defaults, tokenStore: KeychainStore())
    }

    convenience init(defaults: UserDefaults = .standard, tokenStore: any GullsTokenStore) {
        self.init(profileID: Self.defaultProfileID, defaults: defaults, tokenStore: tokenStore)
    }

    init(
        profileID: String,
        defaults: UserDefaults = .standard,
        tokenStore: any GullsTokenStore = KeychainStore(),
        displayName: String? = nil
    ) {
        let normalizedID = profileID.trimmingCharacters(in: .whitespacesAndNewlines)
        self.profileID = normalizedID.isEmpty ? Self.defaultProfileID : normalizedID
        self.defaults = defaults
        self.tokenStore = tokenStore
        self.keys = ProfileKeys(profileID: self.profileID)

        let legacy = self.profileID == Self.defaultProfileID
        self.displayName = defaults.string(forKey: keys.displayName)
            ?? displayName
            ?? (legacy ? defaults.string(forKey: "displayName") : nil)
            ?? ""
        self.apiURL = defaults.string(forKey: keys.apiURL)
            ?? (legacy ? defaults.string(forKey: "apiURL") : nil)
            ?? ""
        self.socialAPIURL = defaults.string(forKey: keys.socialAPIURL)
            ?? (legacy ? defaults.string(forKey: "socialAPIURL") : nil)
            ?? ""
        self.nodeID = defaults.string(forKey: keys.nodeID)
            ?? (legacy ? defaults.string(forKey: "nodeID") : nil)
            ?? ""
        self.agentHandle = defaults.string(forKey: keys.agentHandle)
            ?? (legacy ? defaults.string(forKey: "agentHandle") : nil)
            ?? ""
        let storedInterval = defaults.object(forKey: keys.pollInterval) == nil
            ? (legacy ? defaults.double(forKey: "pollInterval") : 0)
            : defaults.double(forKey: keys.pollInterval)
        self.pollInterval = storedInterval > 0 ? storedInterval : Self.defaultPollInterval
        self.contextDir = defaults.string(forKey: keys.contextDir)
            ?? (legacy ? defaults.string(forKey: "contextDir") : nil)
            ?? Self.contextDirectory(for: self.profileID, isDefault: legacy).path
        self.streamURL = defaults.string(forKey: keys.streamURL)
            ?? (legacy ? defaults.string(forKey: "streamURL") : nil)
            ?? ""
        self.monitoringEnabled = defaults.object(forKey: keys.monitoringEnabled) == nil
            ? (legacy ? (defaults.object(forKey: "monitoringEnabled") as? Bool ?? true) : true)
            : defaults.bool(forKey: keys.monitoringEnabled)
        self.codexEnabled = defaults.bool(forKey: keys.codexEnabled)
        let legacyToken = legacy && !defaults.bool(forKey: keys.legacyTokenMigrated)
            ? tokenStore.legacyToken()
            : nil
        self.token = tokenStore.token(for: self.profileID)
            ?? legacyToken
            ?? ""
    }

    var isConfigured: Bool {
        !apiURL.trimmingCharacters(in: .whitespaces).isEmpty
            && !agentHandle.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var isLocallyPaired: Bool {
        !token.isEmpty && !socialAPIURL.trimmingCharacters(in: .whitespaces).isEmpty && !nodeID.isEmpty
    }

    // Stable within a configuration state, without exposing the connector
    // token in logs, identifiers, or persisted metadata.
    var connectionRevision: String {
        let source = [apiURL, socialAPIURL, nodeID, agentHandle, contextDir, streamURL,
                      String(pollInterval), token].joined(separator: "\u{1f}")
        return SHA256.hash(data: Data(source.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    func cliEnvironment() -> GullsCLI.Environment {
        GullsCLI.Environment(
            profileID: profileID,
            connectionRevision: connectionRevision,
            apiURL: apiURL.trimmingCharacters(in: .whitespaces),
            agentHandle: agentHandle.trimmingCharacters(in: .whitespaces),
            token: token.isEmpty ? nil : token,
            contextDir: URL(fileURLWithPath: (contextDir as NSString).expandingTildeInPath),
            streamURL: streamURL.trimmingCharacters(in: .whitespaces),
            socialAPIURL: socialAPIURL.trimmingCharacters(in: .whitespaces),
            nodeID: nodeID.trimmingCharacters(in: .whitespaces)
        )
    }

    static var defaultContextDir: URL { contextDirectory(for: defaultProfileID, isDefault: true) }

    static func contextDirectory(for profileID: String, isDefault: Bool = false) -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Gulls/agent-context")
        return isDefault ? base : base.appendingPathComponent(profileID, isDirectory: true)
    }

    // MARK: - One-way import from the CLI's env file

    static var sharedEnvFile: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".config/seagull/env")
    }

    var sharedEnvFileExists: Bool { FileManager.default.fileExists(atPath: Self.sharedEnvFile.path) }

    @discardableResult
    func importFromSharedEnvFile() -> [String]? {
        guard let text = try? String(contentsOf: Self.sharedEnvFile, encoding: .utf8) else { return nil }
        let values = Self.parseEnvFile(text)
        var imported: [String] = []
        func importValue(_ key: String, _ apply: (String) -> Void) {
            if let value = values[key], !value.isEmpty { apply(value); imported.append(key) }
        }
        importValue("SEAGULL_API_URL") { apiURL = $0 }
        importValue("SEAGULL_SOCIAL_API_URL") { socialAPIURL = $0 }
        importValue("SEAGULL_NODE_ID") { nodeID = $0 }
        importValue("SEAGULL_AGENT_HANDLE") { agentHandle = $0 }
        importValue("SEAGULL_CONNECTOR_TOKEN") { token = $0 }
        importValue("SEAGULL_AGENT_CONTEXT_DIR") { contextDir = $0 }
        if let value = values["SEAGULL_AGENT_POLL_INTERVAL"], let interval = Double(value), interval > 0 {
            pollInterval = interval; imported.append("SEAGULL_AGENT_POLL_INTERVAL")
        }
        importValue("SEAGULL_STREAM_URL") { streamURL = $0 }
        return imported
    }

    // Mirrors loadEnvFile in the CLI (config.go).
    static func parseEnvFile(_ text: String) -> [String: String] {
        var values: [String: String] = [:]
        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            var line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.isEmpty || line.hasPrefix("#") { continue }
            if line.hasPrefix("export ") { line = String(line.dropFirst("export ".count)).trimmingCharacters(in: .whitespaces) }
            guard let separator = line.firstIndex(of: "=") else { continue }
            let name = String(line[..<separator]).trimmingCharacters(in: .whitespaces)
            if name.isEmpty { continue }
            var value = String(line[line.index(after: separator)...]).trimmingCharacters(in: .whitespaces)
            if value.count >= 2, let first = value.first, let last = value.last,
               first == last, first == "\"" || first == "'" { value = String(value.dropFirst().dropLast()) }
            values[name] = value
        }
        return values
    }

    private struct ProfileKeys {
        let displayName, apiURL, socialAPIURL, nodeID, agentHandle, pollInterval, contextDir, streamURL, monitoringEnabled, codexEnabled, legacyTokenMigrated: String
        init(profileID: String) {
            let prefix = "gull.profile.\(profileID)."
            displayName = prefix + "displayName"; apiURL = prefix + "apiURL"; socialAPIURL = prefix + "socialAPIURL"
            nodeID = prefix + "nodeID"; agentHandle = prefix + "agentHandle"; pollInterval = prefix + "pollInterval"
            contextDir = prefix + "contextDir"; streamURL = prefix + "streamURL"; monitoringEnabled = prefix + "monitoringEnabled"
            codexEnabled = prefix + "codexEnabled"
            legacyTokenMigrated = prefix + "legacyTokenMigrated"
        }
    }
}

protocol GullsTokenStore {
    func token(for profileID: String) -> String?
    func legacyToken() -> String?
    @discardableResult func setToken(_ token: String, for profileID: String) -> Bool
}

struct KeychainStore: GullsTokenStore {
    func token(for profileID: String) -> String? { Keychain.token(for: profileID) }
    func legacyToken() -> String? { Keychain.legacyToken() }
    func setToken(_ token: String, for profileID: String) -> Bool { Keychain.setToken(token, for: profileID) }
}

enum Keychain {
    private static let service = "ai.gulls.mac"
    private static let legacyAccount = "connector-token"

    static func token(for profileID: String) -> String? { read(account: "connector-token.\(profileID)") }
    static func legacyToken() -> String? { read(account: legacyAccount) }
    @discardableResult static func setToken(_ token: String, for profileID: String) -> Bool {
        write(token, account: "connector-token.\(profileID)")
    }

    private static func read(account: String) -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
            kSecAttrAccount as String: account, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func write(_ token: String, account: String) -> Bool {
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
            kSecAttrAccount as String: account]
        if token.isEmpty { let status = SecItemDelete(base as CFDictionary); return status == errSecSuccess || status == errSecItemNotFound }
        let data = Data(token.utf8)
        var status = SecItemUpdate(base as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound { var add = base; add[kSecValueData as String] = data; status = SecItemAdd(add as CFDictionary, nil) }
        return status == errSecSuccess
    }
}
