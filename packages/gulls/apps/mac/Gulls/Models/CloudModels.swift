import Foundation

// These models mirror the deployed web contracts. They deliberately contain
// only public account, Gull, runtime, usage, and server-control data; secrets
// are never decoded into a model.

struct CloudRuntimeConfig: Codable, Equatable {
    var socialAPIURL: String?
    var messageAPIURL: String?
    var aiProviderAPIURL: String?
    var adminDomainName: String?
    var auth: CloudAuthConfig?

    enum CodingKeys: String, CodingKey {
        case socialAPIURL = "socialApiUrl"
        case messageAPIURL = "messageApiUrl"
        case aiProviderAPIURL = "aiProviderApiUrl"
        case adminDomainName
        case auth
    }

    static func parseConfigJS(_ source: String) throws -> CloudRuntimeConfig {
        let prefix = "window.SEAGULL_CONFIG ="
        let normalized = source.trimmingCharacters(in: .whitespacesAndNewlines)
        guard normalized.hasPrefix(prefix), let range = normalized.range(of: prefix) else {
            throw CloudConfigError.missingAssignment
        }
        let tail = normalized[range.upperBound...].trimmingCharacters(in: .whitespacesAndNewlines)
        guard tail.first == "{" else { throw CloudConfigError.invalidPayload }
        var depth = 0
        var quoted = false
        var escaped = false
        var end: String.Index?
        for index in tail.indices {
            let character = tail[index]
            if quoted {
                if escaped { escaped = false }
                else if character == "\\" { escaped = true }
                else if character == "\"" { quoted = false }
                continue
            }
            if character == "\"" { quoted = true; continue }
            if character == "{" { depth += 1 }
            if character == "}" {
                depth -= 1
                if depth == 0 { end = index; break }
            }
        }
        guard let end else { throw CloudConfigError.invalidPayload }
        let jsonText = String(tail[...end])
        let remainder = tail[tail.index(after: end)...].trimmingCharacters(in: .whitespacesAndNewlines)
        guard remainder.isEmpty || remainder == ";" else { throw CloudConfigError.invalidPayload }
        guard let data = jsonText.data(using: .utf8) else {
            throw CloudConfigError.invalidPayload
        }
        do {
            return try JSONDecoder().decode(CloudRuntimeConfig.self, from: data)
        } catch {
            throw CloudConfigError.invalidPayload
        }
    }
}

enum CloudConfigError: Error, LocalizedError, Equatable {
    case missingAssignment
    case invalidPayload

    var errorDescription: String? {
        switch self {
        case .missingAssignment: return "The site configuration does not contain a supported SEAGULL_CONFIG assignment."
        case .invalidPayload: return "The site configuration is not valid JSON."
        }
    }
}

struct CloudAuthConfig: Codable, Equatable {
    var mode: String?
    var issuer: String?
    var hostedDomain: String?
    var clientID: String?
    var redirectURI: String?
    var logoutURI: String?

    enum CodingKeys: String, CodingKey {
        case mode, issuer, hostedDomain
        case clientID = "clientId"
        case redirectURI = "redirectUri"
        case logoutURI = "logoutUri"
    }
}

struct CloudHealth: Codable, Equatable {
    var ok: Bool
    var app: String?
    var storage: String?
}

struct CloudHumanIdentity: Codable, Equatable {
    var userID: String
    var provider: String
    var subject: String
    var email: String?
    var displayName: String?
    var createdAt: String?
    var updatedAt: String?
}

enum CloudRuntimeMode: String, Codable, CaseIterable {
    case cloud, local, manual
}

struct CloudAgentProfile: Codable, Equatable, Identifiable {
    var agentID: String
    var ownerUserID: String
    var handle: String
    var displayName: String?
    var bio: String?
    var capabilities: [String]
    var relationshipPosture: String
    var approvalRequiredFor: [String]
    var allowedUseTerms: [String]
    var contactExplanation: String?
    var protocols: [String]
    var status: String
    var nodeID: String?
    var deliveryMode: String?
    var lastSeenAt: String?
    var createdAt: String?
    var updatedAt: String?

    var id: String { agentID }
}

typealias CloudGull = CloudAgentProfile

struct CloudGullRuntime: Codable, Equatable {
    var mode: CloudRuntimeMode
    var nodeID: String?
    var connected: Bool
    var lastSeenAt: String?
}

struct CloudPersonalAgentAsset: Codable, Equatable, Identifiable {
    var assetID: String
    var ownerUserID: String
    var assetType: String
    var name: String
    var instructions: String
    var description: String?
    var style: String?
    var tags: [String]
    var maxOutputChars: Int?
    var status: String
    var createdAt: String?
    var updatedAt: String?

    var id: String { assetID }
}

struct CloudAgentAssetBinding: Codable, Equatable {
    var agentID: String
    var ownerUserID: String
    var promptAssetID: String?
    var skillAssetID: String?
    var createdAt: String?
    var updatedAt: String?
}

struct CloudAgentChatSession: Codable, Equatable, Identifiable {
    var chatID: String
    var ownerUserID: String
    var agentID: String
    var agentHandle: String
    var title: String
    var senderAgentID: String?
    var senderHandle: String?
    var promptAssetID: String?
    var skillAssetID: String?
    var hubThreadID: String?
    var createdAt: String?
    var updatedAt: String?

    var id: String { chatID }
}

struct CloudAgentChatMessage: Codable, Equatable, Identifiable {
    var chatMessageID: String
    var chatID: String
    var ownerUserID: String
    var senderType: String
    var content: String
    var hubMessageID: String?
    var hubThreadID: String?
    var deliveryStatus: String?
    var deliveryError: String?
    var aiRunID: String?
    var aiRunState: String?
    var aiError: String?
    var runtimeMode: CloudRuntimeMode?
    var createdAt: String?
    var updatedAt: String?

    var id: String { chatMessageID }
}

struct CloudNodeRecord: Codable, Equatable, Identifiable {
    var nodeID: String
    var ownerUserID: String
    var nodeType: String
    var status: String
    var agentCount: Int
    var lastSeenAt: String?
    var createdAt: String?
    var updatedAt: String?

    var id: String { nodeID }
}

struct CloudPairToken: Codable, Equatable {
    var pairToken: String
    var nodeID: String?
    var ownerUserID: String?
    var expiresAt: String
    var createdAt: String?
    var usedAt: String?
}

struct CloudUsageRecord: Codable, Equatable, Identifiable {
    var usageID: String
    var ownerUserID: String
    var agentID: String
    var runID: String?
    var provider: String?
    var model: String
    var inputTokens: Int
    var outputTokens: Int
    var cachedTokens: Int?
    var totalTokens: Int?
    var estimatedCostUnits: Int?
    var taskID: String?
    var messageID: String?
    var approvalState: String?
    var createdAt: String?

    var id: String { usageID }
}

struct CloudCreditBalance: Codable, Equatable {
    var ownerUserID: String?
    var availableCredits: Int
}

struct CloudCreditLedgerEntry: Codable, Equatable, Identifiable {
    var entryID: String
    var ownerUserID: String?
    var entryType: String?
    var creditDelta: Int
    var reason: String
    var usageID: String?
    var runID: String?
    var createdAt: String?

    var id: String { entryID }
}

struct CloudAIUsageSummary: Codable, Equatable {
    var ownerUserID: String
    var balance: CloudCreditBalance
    var usage: [CloudUsageRecord]
    var entries: [CloudCreditLedgerEntry]
}

struct CloudProviderConfig: Codable, Equatable, Identifiable {
    var providerConfigID: String
    var provider: String
    var enabled: Bool
    var allowedModels: [String]
    var secretRef: String?
    var region: String?
    var createdAt: String?
    var updatedAt: String?

    var id: String { providerConfigID }
}

struct CloudServerCreditLedgerEntry: Codable, Equatable, Identifiable {
    var entryID: String
    var creditDelta: Int
    var reason: String
    var adminActorID: String?
    var entryType: String?
    var ownerUserID: String?
    var userCreditEntryID: String?
    var createdAt: String?

    var id: String { entryID }
}

struct CloudServerCreditBalance: Codable, Equatable {
    var availableCredits: Int
}

struct CloudAdminAuditEvent: Codable, Equatable, Identifiable {
    var auditID: String
    var adminActorID: String?
    var action: String
    var targetType: String
    var targetID: String
    var reason: String?
    var metadata: [String: String]?
    var createdAt: String?

    var id: String { auditID }
}

struct CloudRoutingRule: Codable, Equatable, Identifiable {
    var ruleID: String
    var name: String
    var mode: String
    var routeToHandles: [String]
    var urlContains: [String]
    var enabled: Bool
    var createdAt: String?
    var updatedAt: String?

    var id: String { ruleID }
}

struct CloudModerationRecord: Codable, Equatable, Identifiable {
    var moderationID: String
    var createdByUserID: String
    var targetType: String
    var targetID: String
    var action: String
    var reason: String
    var status: String
    var createdAt: String?
    var resolvedAt: String?

    var id: String { moderationID }
}

struct CloudProviderDraft: Encodable, Equatable {
    var provider: String
    var enabled: Bool
    var allowedModels: [String]
    var apiKey: String? = nil
    var secretRef: String?
    var region: String?
    var reason: String?
}

struct CloudRoutingRuleDraft: Encodable, Equatable {
    var name: String
    var mode: String
    var routeToHandles: [String]
    var urlContains: [String]
    var enabled: Bool
}

struct CloudServerSnapshot: Equatable {
    var health: [String: CloudHealth]
    var providerConfigs: [CloudProviderConfig]
    var serverBalance: CloudServerCreditBalance?
    var serverLedger: [CloudServerCreditLedgerEntry]
    var auditEvents: [CloudAdminAuditEvent]
    var routingRules: [CloudRoutingRule]
    var moderationRecords: [CloudModerationRecord]
}

struct CloudProviderConfigsResponse: Decodable { var providerConfigs: [CloudProviderConfig] }
struct CloudProviderResponse: Decodable { var providerConfig: CloudProviderConfig }
struct CloudServerBalanceResponse: Decodable { var balance: CloudServerCreditBalance }
struct CloudServerLedgerResponse: Decodable { var entries: [CloudServerCreditLedgerEntry] }
struct CloudGrantResponse: Decodable { var entry: CloudServerCreditLedgerEntry }
struct CloudAuditResponse: Decodable { var events: [CloudAdminAuditEvent] }
struct CloudRoutingRulesResponse: Decodable { var items: [CloudRoutingRule] }
struct CloudRoutingRuleResponse: Decodable { var routingRule: CloudRoutingRule }
struct CloudModerationResponse: Decodable { var items: [CloudModerationRecord] }
struct CloudGullsResponse: Decodable { var items: [CloudGull]; var nextCursor: String? }
struct CloudPromptResponse: Decodable { var prompt: CloudPersonalAgentAsset? }
struct CloudRuntimeResponse: Decodable { var runtime: CloudGullRuntime }
struct CloudPairTokenResponse: Decodable { var pairToken: CloudPairToken; var socialAPIURL: String? }

struct CloudDashboard: Codable, Equatable {
    var health: CloudHealth
    var identity: CloudHumanIdentity
    var profiles: CloudPage<CloudAgentProfile>
    var moderation: CloudPage<CloudModerationRecord>
}

struct CloudPage<Item: Codable & Equatable>: Codable, Equatable {
    var items: [Item]
    var count: Int?
    var nextCursor: String?
}
