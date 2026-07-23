import Foundation

// Codable models for the gulls CLI's --json output. The shapes are pinned by
// golden fixtures shared with the CLI:
// packages/gulls/connect/local-agent/internal/agentcli/testdata/contract/.
// Fields the hub may omit are optional; only identifiers are required.

struct VersionInfo: Decodable, Equatable {
    let program: String
    let version: String
}

struct Agent: Decodable, Equatable {
    let agentId: String?
    let handle: String?
    let displayName: String?
    let status: String?
    let triggerMode: String?

    enum CodingKeys: String, CodingKey {
        case agentId = "agent_id"
        case handle
        case displayName = "display_name"
        case status
        case triggerMode = "trigger_mode"
    }
}

// `whoami` returns the agent object either nested under "agent" or top-level;
// mirror the CLI's formatAgent fallback.
struct WhoamiResponse: Decodable, Equatable {
    let agent: Agent

    enum CodingKeys: String, CodingKey {
        case agent
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        if let nested = try container.decodeIfPresent(Agent.self, forKey: .agent) {
            agent = nested
        } else {
            agent = try Agent(from: decoder)
        }
        // Every Agent field is optional, so any JSON object would "decode".
        // Require at least one identity field so contract drift fails loudly
        // instead of showing "Connected as unknown handle".
        guard firstNonEmpty(agent.agentId, agent.handle) != nil else {
            throw DecodingError.dataCorrupted(.init(
                codingPath: decoder.codingPath,
                debugDescription: "whoami output contains neither agent_id nor handle"
            ))
        }
    }
}

struct InboxResponse: Decodable, Equatable {
    let items: [InboxItem]
}

struct InboxItem: Decodable, Equatable, Identifiable {
    let delivery: Delivery
    let message: Message?
    let currentMessage: CurrentMessage?

    var id: String { delivery.deliveryId }

    enum CodingKeys: String, CodingKey {
        case delivery
        case message
        case currentMessage = "current_message"
    }

    // Same fallbacks the CLI uses in itemSummary (context.go).
    var senderDisplay: String {
        firstNonEmpty(message?.senderHandle, message?.senderAgentId, delivery.senderAgentId) ?? "unknown"
    }

    var bodyText: String? {
        firstNonEmpty(currentMessage?.contentInline, message?.contentInline)
    }
}

// The delivery lifecycle states this build knows about. Decoding keeps the
// raw string (the hub may grow states we don't know yet); filtering, badge
// colors, and notification logic all switch on this one definition.
enum DeliveryStatus: String {
    case delivered
    case replied
    case acked
    case ignored
    case failed
}

struct Delivery: Decodable, Equatable {
    let deliveryId: String
    let messageId: String?
    let threadId: String?
    let senderAgentId: String?
    let recipientAgentId: String?
    let status: String?
    let currentStage: String?
    let lastError: String?
    let createdAt: String?
    let updatedAt: String?
    let ackedAt: String?

    enum CodingKeys: String, CodingKey {
        case deliveryId = "delivery_id"
        case messageId = "message_id"
        case threadId = "thread_id"
        case senderAgentId = "sender_agent_id"
        case recipientAgentId = "recipient_agent_id"
        case status
        case currentStage = "current_stage"
        case lastError = "last_error"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case ackedAt = "acked_at"
    }

    // nil when the hub sent no status or one this build doesn't know.
    var statusValue: DeliveryStatus? {
        status.flatMap(DeliveryStatus.init(rawValue:))
    }
}

struct Message: Decodable, Equatable {
    let messageId: String?
    let threadId: String?
    let senderAgentId: String?
    let senderHandle: String?
    let intent: String?
    let visibility: String?
    let contentInline: String?
    let safetyStatus: String?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case messageId = "message_id"
        case threadId = "thread_id"
        case senderAgentId = "sender_agent_id"
        case senderHandle = "sender_handle"
        case intent
        case visibility
        case contentInline = "content_inline"
        case safetyStatus = "safety_status"
        case createdAt = "created_at"
    }
}

struct CurrentMessage: Decodable, Equatable {
    let contentInline: String?
    let contentRef: String?

    enum CodingKeys: String, CodingKey {
        case contentInline = "content_inline"
        case contentRef = "content_ref"
    }
}

struct OpenResult: Decodable, Equatable {
    let contextPath: String
    let delivery: Delivery?

    enum CodingKeys: String, CodingKey {
        case contextPath = "context_path"
        case delivery
    }
}

struct DraftReplyResult: Decodable, Equatable {
    let outcome: String
    let reason: String?
    let appliedRules: [String: JSONValue]?
    let triggerLabels: [String]?
    let deliveryId: String?
    let draft: String?
    let draftSent: Bool
    let deliveryDecisionSubmitted: Bool
    let deliveryDecision: DecisionResult?

    enum CodingKeys: String, CodingKey {
        case outcome
        case reason
        case appliedRules = "applied_rules"
        case triggerLabels = "trigger_labels"
        case deliveryId = "delivery_id"
        case draft
        case draftSent = "draft_sent"
        case deliveryDecisionSubmitted = "delivery_decision_submitted"
        case deliveryDecision = "delivery_decision"
    }
}

struct DecisionResult: Decodable, Equatable {
    let delivery: Delivery
    let reply: ReplyRef?
}

struct ReplyRef: Decodable, Equatable {
    let messageId: String?
    let threadId: String?

    enum CodingKeys: String, CodingKey {
        case messageId = "message_id"
        case threadId = "thread_id"
    }
}

struct WatchOnceResult: Decodable, Equatable {
    let newCount: Int
    let contextPaths: [String]?

    enum CodingKeys: String, CodingKey {
        case newCount = "new_count"
        case contextPaths = "context_paths"
    }
}

// One NDJSON line from `gulls --json stream` (contract fixtures
// stream_connected/stream_event/stream_disconnected). Events are wake-up
// signals only — the inbox fetch remains the source of truth.
struct StreamLine: Decodable, Equatable {
    let type: String
    let url: String?
    let eventType: String?
    let deliveryId: String?
    let messageId: String?
    let threadId: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case type
        case url
        case eventType = "event_type"
        case deliveryId = "delivery_id"
        case messageId = "message_id"
        case threadId = "thread_id"
        case error
    }
}

// Loosely-typed corners of the contract (applied_rules, workflow_trace,
// action_request) stay as JSONValue instead of forcing full schemas.
enum JSONValue: Decodable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case null
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    var displayText: String {
        switch self {
        case .string(let value): return value
        case .number(let value):
            return value == value.rounded() ? String(Int(value)) : String(value)
        case .bool(let value): return value ? "true" : "false"
        case .null: return "null"
        case .array(let values): return values.map(\.displayText).joined(separator: ", ")
        case .object(let values):
            return values.keys.sorted().map { "\($0)=\(values[$0]!.displayText)" }.joined(separator: "; ")
        }
    }
}

func firstNonEmpty(_ values: String?...) -> String? {
    for value in values {
        if let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return value
        }
    }
    return nil
}

// Hub timestamps arrive in more than one ISO 8601 flavor: the Go hubstub
// emits second-precision RFC 3339 ("…T09:15:23Z"), while the real hub's
// datetime_to_string uses Python isoformat() — microseconds plus a "+00:00"
// offset. Formatters are cached; building one per row render is expensive.
enum GullsDates {
    private static let fractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let plain = ISO8601DateFormatter()

    static func parse(_ raw: String) -> Date? {
        if let date = plain.date(from: raw) ?? fractional.date(from: raw) {
            return date
        }
        // ISO8601DateFormatter is strict about fractional-second width;
        // Python emits 6 digits. Drop the fraction and parse the rest.
        if let fraction = raw.range(of: #"\.\d+"#, options: .regularExpression) {
            var trimmed = raw
            trimmed.removeSubrange(fraction)
            return plain.date(from: trimmed)
        }
        return nil
    }
}
