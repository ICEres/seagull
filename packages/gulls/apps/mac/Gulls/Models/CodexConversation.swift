import CryptoKit
import Foundation

enum CodexTaskRoute: String, Codable {
    case embedded, external
}

/// Private routing metadata. The immutable version-1 task remains the input
/// and result boundary; these records never become a public Gull identity.
struct CodexWorkRecord: Codable, Equatable {
    enum Publication: String, Codable { case prepared, ready }

    let taskID: String
    let profileID: String
    let connectionRevision: String
    let apiBaseURL: String
    let requestDigest: String
    var conversationKey: String?
    let sourceMessageID: String?
    let sourceDeliveryID: String?
    let ownerRequestID: String?
    let deduplicationKey: String
    let instructionsDigest: String
    let snapshotDigest: String
    let cliExecutablePath: String
    let createdAt: Date
    var publication: Publication = .prepared
    var route: CodexTaskRoute?
    var contextID: String?
    var predecessorTaskID: String?
    var queuedAt: Date?
    var state: CodexTaskExecution.Status?
    var draftDisposition: CodexDraftDisposition = .available
    var dispatchNonce: String?
    var inputDigest: String?
    var dispatchIntentAt: Date?
    var turnAcknowledged = false
    var conversationDigest: String?
    var resultDigest: String?

    static func hash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func normalizedAPIURL(_ value: String) throws -> String {
        guard var parts = URLComponents(string: value.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = parts.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = parts.host?.lowercased(), !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil else {
            throw CodexTaskStore.Failure("The Gull server address is invalid.")
        }
        parts.scheme = scheme
        parts.host = host
        if (scheme == "https" && parts.port == 443) || (scheme == "http" && parts.port == 80) { parts.port = nil }
        while parts.path.hasSuffix("/") { parts.path.removeLast() }
        guard let normalized = parts.string else { throw CodexTaskStore.Failure("The Gull server address is invalid.") }
        return normalized
    }

    static func conversationKey(profileID: String, apiURL: String, revision: String, threadID: String) throws -> String {
        // JSON arrays preserve field boundaries even when an ID contains a separator.
        let values = [profileID, try normalizedAPIURL(apiURL), revision, threadID]
        return hash(String(decoding: try JSONEncoder().encode(values), as: UTF8.self))
    }
}

enum CodexDraftDisposition: String, Codable {
    case available, used, sent, discarded, superseded
}

struct CodexConversationContext: Codable, Equatable {
    let id: String
    let conversationKey: String
    let profileID: String
    let connectionRevision: String
    let route: CodexTaskRoute
    let workingDirectory: String?
    let instructionsDigest: String
    let policyDigest: String
    let createdAt: Date
    var codexThreadID: String?
    var latestTaskID: String?
    var lastSnapshotDigest: String?
    var includedMessageIDs: [String] = []

    func matches(folder: String?, instructions: String, policy: String) -> Bool {
        workingDirectory == folder && instructionsDigest == instructions && policyDigest == policy
    }
}

struct CodexContextMessage: Codable, Equatable {
    let id: String
    let sender: String
    let content: String
    let createdAt: String?
}
