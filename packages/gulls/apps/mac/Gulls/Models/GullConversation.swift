import Foundation

/// A conversation started from the Mac app. Only routing metadata is stored;
/// credentials and message bodies remain outside the persisted record.
struct GullConversation: Codable, Equatable, Identifiable {
    let id: String
    let recipientHandle: String
    var recipientAgentID: String?
    var recipientName: String?
    let senderProfileID: String
    let senderHandle: String
    var senderAgentID: String?
    let connectionRevision: String
    var threadID: String?
    let createdAt: Date
    var updatedAt: Date

    var displayName: String { recipientName ?? recipientHandle }
}

struct GullConversationMessage: Codable, Equatable, Identifiable {
    let id: String
    let threadID: String?
    let senderHandle: String?
    let senderAgentID: String?
    let content: String
    let createdAt: Date?
}

struct GullConversationSender: Identifiable, Equatable {
    let id: String
    let displayName: String
    let handle: String
    let agentID: String?
    let connectionRevision: String
    let environment: GullsCLI.Environment

    init(id: String, displayName: String, handle: String, agentID: String? = nil,
         connectionRevision: String, environment: GullsCLI.Environment) {
        self.id = id
        self.displayName = displayName
        self.handle = handle
        self.agentID = agentID
        self.connectionRevision = connectionRevision
        self.environment = environment
    }

    static func == (lhs: GullConversationSender, rhs: GullConversationSender) -> Bool {
        lhs.id == rhs.id && lhs.handle == rhs.handle && lhs.agentID == rhs.agentID
            && lhs.connectionRevision == rhs.connectionRevision
    }
}

struct GullPostResult: Decodable, Equatable {
    let messageID: String?
    let threadID: String?

    enum CodingKeys: String, CodingKey {
        case messageID = "message_id"
        case threadID = "thread_id"
    }
}

struct GullThreadResult: Decodable, Equatable {
    let threadID: String
    let messages: [GullThreadMessage]
    let nextCursor: String?

    enum CodingKeys: String, CodingKey {
        case threadID = "thread_id"
        case messages
        case nextCursor = "next_cursor"
    }
}

struct GullThreadMessage: Decodable, Equatable, Identifiable {
    let messageID: String
    let threadID: String?
    let senderAgentID: String?
    let senderHandle: String?
    let contentInline: String?
    let createdAt: String?

    var id: String { messageID }

    enum CodingKeys: String, CodingKey {
        case messageID = "message_id"
        case threadID = "thread_id"
        case senderAgentID = "sender_agent_id"
        case senderHandle = "sender_handle"
        case contentInline = "content_inline"
        case createdAt = "created_at"
    }
}
