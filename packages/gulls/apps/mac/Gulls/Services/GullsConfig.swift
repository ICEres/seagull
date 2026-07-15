import Foundation
import Observation
import Security

// App configuration. URL/handle/interval live in UserDefaults; the connector
// token lives in the Keychain (never in a plaintext file). The CLI's
// ~/.config/seagull/env can be imported one-way; the app never writes it.
@Observable
final class GullsConfig {

    static let defaultPollInterval: Double = 15

    var apiURL: String {
        didSet { defaults.set(apiURL, forKey: Keys.apiURL) }
    }

    var agentHandle: String {
        didSet { defaults.set(agentHandle, forKey: Keys.agentHandle) }
    }

    var pollInterval: Double {
        didSet { defaults.set(pollInterval, forKey: Keys.pollInterval) }
    }

    var contextDir: String {
        didSet { defaults.set(contextDir, forKey: Keys.contextDir) }
    }

    // Optional WebSocket URL for push (ws:// or wss://). Empty = polling only.
    var streamURL: String {
        didSet { defaults.set(streamURL, forKey: Keys.streamURL) }
    }

    var token: String {
        didSet { Keychain.setToken(token) }
    }

    private let defaults: UserDefaults

    private enum Keys {
        static let apiURL = "apiURL"
        static let agentHandle = "agentHandle"
        static let pollInterval = "pollInterval"
        static let contextDir = "contextDir"
        static let streamURL = "streamURL"
    }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        apiURL = defaults.string(forKey: Keys.apiURL) ?? ""
        agentHandle = defaults.string(forKey: Keys.agentHandle) ?? ""
        let storedInterval = defaults.double(forKey: Keys.pollInterval)
        pollInterval = storedInterval > 0 ? storedInterval : Self.defaultPollInterval
        contextDir = defaults.string(forKey: Keys.contextDir) ?? Self.defaultContextDir.path
        streamURL = defaults.string(forKey: Keys.streamURL) ?? ""
        token = Keychain.token() ?? ""
    }

    var isConfigured: Bool {
        !apiURL.trimmingCharacters(in: .whitespaces).isEmpty
            && !agentHandle.trimmingCharacters(in: .whitespaces).isEmpty
    }

    func cliEnvironment() -> GullsCLI.Environment {
        GullsCLI.Environment(
            apiURL: apiURL.trimmingCharacters(in: .whitespaces),
            agentHandle: agentHandle.trimmingCharacters(in: .whitespaces),
            token: token.isEmpty ? nil : token,
            contextDir: URL(fileURLWithPath: (contextDir as NSString).expandingTildeInPath),
            streamURL: streamURL.trimmingCharacters(in: .whitespaces)
        )
    }

    static var defaultContextDir: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Gulls/agent-context")
    }

    // MARK: - One-way import from the CLI's env file

    static var sharedEnvFile: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/seagull/env")
    }

    var sharedEnvFileExists: Bool {
        FileManager.default.fileExists(atPath: Self.sharedEnvFile.path)
    }

    // Returns the imported keys, or nil when the file is missing/unreadable.
    @discardableResult
    func importFromSharedEnvFile() -> [String]? {
        guard let text = try? String(contentsOf: Self.sharedEnvFile, encoding: .utf8) else {
            return nil
        }
        let values = Self.parseEnvFile(text)
        var imported: [String] = []
        if let value = values["SEAGULL_API_URL"], !value.isEmpty {
            apiURL = value
            imported.append("SEAGULL_API_URL")
        }
        if let value = values["SEAGULL_AGENT_HANDLE"], !value.isEmpty {
            agentHandle = value
            imported.append("SEAGULL_AGENT_HANDLE")
        }
        if let value = values["SEAGULL_CONNECTOR_TOKEN"], !value.isEmpty {
            token = value
            imported.append("SEAGULL_CONNECTOR_TOKEN")
        }
        if let value = values["SEAGULL_AGENT_POLL_INTERVAL"], let interval = Double(value), interval > 0 {
            pollInterval = interval
            imported.append("SEAGULL_AGENT_POLL_INTERVAL")
        }
        if let value = values["SEAGULL_STREAM_URL"], !value.isEmpty {
            streamURL = value
            imported.append("SEAGULL_STREAM_URL")
        }
        return imported
    }

    // Mirrors loadEnvFile in the CLI (config.go): skip blanks and #-comments,
    // strip a leading "export ", cut on the first "=", trim, strip one layer
    // of matching quotes.
    static func parseEnvFile(_ text: String) -> [String: String] {
        var values: [String: String] = [:]
        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            var line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.isEmpty || line.hasPrefix("#") {
                continue
            }
            if line.hasPrefix("export ") {
                line = String(line.dropFirst("export ".count)).trimmingCharacters(in: .whitespaces)
            }
            guard let separator = line.firstIndex(of: "=") else {
                continue
            }
            let name = String(line[..<separator]).trimmingCharacters(in: .whitespaces)
            if name.isEmpty {
                continue
            }
            var value = String(line[line.index(after: separator)...]).trimmingCharacters(in: .whitespaces)
            if value.count >= 2, let first = value.first, let last = value.last,
               first == last, first == "\"" || first == "'" {
                value = String(value.dropFirst().dropLast())
            }
            values[name] = value
        }
        return values
    }
}

// Minimal Keychain wrapper for the connector token (generic password,
// service ai.gulls.mac).
enum Keychain {
    private static let service = "ai.gulls.mac"
    private static let account = "connector-token"

    static func token() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    static func setToken(_ token: String) {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        if token.isEmpty {
            SecItemDelete(base as CFDictionary)
            return
        }
        let data = Data(token.utf8)
        let update: [String: Any] = [kSecValueData as String: data]
        let status = SecItemUpdate(base as CFDictionary, update as CFDictionary)
        if status == errSecItemNotFound {
            var add = base
            add[kSecValueData as String] = data
            SecItemAdd(add as CFDictionary, nil)
        }
    }
}
