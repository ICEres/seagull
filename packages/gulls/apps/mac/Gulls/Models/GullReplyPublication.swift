import Foundation

/// A single owner-delegated reply. Its public content is separate from private
/// Codex output, and its immutable key is reused for delivery reconciliation.
struct GullReplyPublication: Codable, Equatable {
    enum Status: String, Codable {
        case waitingForReply, needsReview, readyToSend, sending, uncertain, sent, revoked, failed
    }

    let taskID: String
    let profileID: String
    let connectionRevision: String
    let requestDigest: String
    let deliveryID: String
    let publicationKey: String
    var automatic: Bool
    var status: Status = .waitingForReply
    var content: String?
    var messageID: String?
    var sentAt: String?
    var error: String?
    var deliveryUnresolved = false

    var canTakeOver: Bool { !deliveryUnresolved && ![.sending, .uncertain, .sent, .revoked].contains(status) }
    var canApprove: Bool { [.needsReview, .failed].contains(status) && content != nil }

    func validate(request: CodexTaskRequest, digest: String) throws {
        guard taskID == request.taskID, profileID == request.profileID,
              connectionRevision == request.connectionRevision, requestDigest == digest,
              deliveryID == request.deliveryID, publicationKey == request.replyAuthorizationID,
              UUID(uuidString: publicationKey) != nil else {
            throw CodexTaskStore.Failure("The reply authorization does not match this task and Gull.")
        }
    }
}

/// Only this explicit artifact can become a public reply. result.json stays private.
struct GullReplySubmission: Codable, Equatable {
    let version: Int
    let taskID: String
    let profileID: String
    let gullHandle: String
    let connectionRevision: String
    let requestSHA256: String
    let authorizationID: String
    let content: String
    let submittedAt: String

    enum CodingKeys: String, CodingKey {
        case version, content
        case taskID = "task_id", profileID = "profile_id", gullHandle = "gull_handle"
        case connectionRevision = "connection_revision", requestSHA256 = "request_sha256"
        case authorizationID = "authorization_id", submittedAt = "submitted_at"
    }
}

struct GullReplyReceipt: Decodable {
    let publicationKey: String
    let found: Bool
    let delivery: Delivery?
    let reply: MessageReceipt?

    struct MessageReceipt: Decodable {
        let messageID: String
        let threadID: String?
        let message: Message?

        var content: String? { message?.contentInline }
        var createdAt: String? { message?.createdAt }

        enum CodingKeys: String, CodingKey {
            case messageID = "message_id", threadID = "thread_id"
            case message
        }
    }

    enum CodingKeys: String, CodingKey {
        case publicationKey = "publication_key"
        case found, delivery, reply
    }
}
