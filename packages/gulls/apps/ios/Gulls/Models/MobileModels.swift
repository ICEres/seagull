import Foundation

struct MobileInboxItem: Codable, Equatable, Identifiable {
    var delivery: MobileDelivery
    var message: MobileMessage?
    var currentMessage: MobileCurrentMessage?
    var id: String { delivery.deliveryID }
    var sender: String { message?.senderHandle ?? message?.senderAgentID ?? delivery.senderAgentID ?? "Unknown Gull" }
    var content: String { currentMessage?.contentInline ?? message?.contentInline ?? "" }
}

struct MobileDelivery: Codable, Equatable {
    var deliveryID: String
    var messageID: String?
    var threadID: String?
    var senderAgentID: String?
    var recipientAgentID: String?
    var status: String?
    var currentStage: String?
    var createdAt: String?
    var updatedAt: String?
}

struct MobileMessage: Codable, Equatable {
    var messageID: String?
    var threadID: String?
    var senderAgentID: String?
    var senderHandle: String?
    var senderDisplayName: String? = nil
    var recipientAgentIDs: [String]? = nil
    var recipientHandles: [String]? = nil
    var contentInline: String?
    var createdAt: String?

    enum CodingKeys: String, CodingKey {
        case messageID, threadID, senderAgentID, senderHandle, senderDisplayName
        case recipientAgentIDs = "recipientAgentIds"
        case recipientHandles, contentInline, createdAt
    }
}

struct MobileCurrentMessage: Codable, Equatable {
    var contentInline: String?
}

struct MobileInboxResponse: Decodable, Equatable {
    var items: [MobileInboxItem]
    var nextCursor: String?
}

struct MobileThreadResponse: Decodable, Equatable {
    var threadID: String
    var messages: [MobileMessage]
    var nextCursor: String?
}
struct MobileSendResponse: Decodable, Equatable {
    var message: MobileMessage?
    var threadID: String?
    var messageID: String?
}

struct MobileSentResponse: Decodable {
    var messages: [MobileMessage]
    var truncated: Bool?
}

/// An approved outbound message remains on disk until the server acknowledges it.
struct MobilePendingMessage: Codable, Equatable, Identifiable {
    enum State: String, Codable { case queued, sending, failed, unconfirmed }
    let id: String
    let sender: CloudGull
    let recipientHandle: String
    let content: String
    let threadID: String?
    let createdAt: Date
    var state: State

    var conversationID: String { threadID ?? "pending:\(id)" }
}

enum MobileDates {
    static func parse(_ value: String?) -> Date? {
        guard let value else { return nil }
        return fractional.date(from: value) ?? standard.date(from: value)
    }

    private static let standard = ISO8601DateFormatter()
    private static let fractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
}
