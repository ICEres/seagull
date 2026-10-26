import Foundation

struct CodexTaskRequest: Codable, Equatable {
    let version: Int
    let taskID: String
    let profileID: String
    let gullHandle: String
    let connectionRevision: String
    let deliveryID: String?
    let threadID: String?
    let goal: String
    let workingDirectory: String?
    let contextPath: String?
    let createdAt: String
    var replyAuthorizationID: String? = nil

    enum CodingKeys: String, CodingKey {
        case version, goal
        case taskID = "task_id", profileID = "profile_id", gullHandle = "gull_handle"
        case connectionRevision = "connection_revision", deliveryID = "delivery_id", threadID = "thread_id"
        case workingDirectory = "working_directory", contextPath = "context_path", createdAt = "created_at"
        case replyAuthorizationID = "reply_authorization_id"
    }
}

struct CodexTaskResult: Codable, Equatable {
    let version: Int
    let taskID: String
    let profileID: String
    let gullHandle: String
    let connectionRevision: String
    let requestSHA256: String
    let content: String
    let completedAt: String
    let codexThreadID: String?

    enum CodingKeys: String, CodingKey {
        case version, content
        case taskID = "task_id", profileID = "profile_id", gullHandle = "gull_handle"
        case connectionRevision = "connection_revision", requestSHA256 = "request_sha256"
        case completedAt = "completed_at", codexThreadID = "codex_thread_id"
    }
}

struct CodexTask: Equatable, Identifiable {
    let request: CodexTaskRequest
    let result: CodexTaskResult?
    let resultError: String?
    var execution: CodexTaskExecution? = nil
    var work: CodexWorkRecord? = nil
    var reply: GullReplyPublication? = nil

    var id: String { request.taskID }
}

struct CodexTaskExecution: Codable, Equatable {
    enum Status: String, Codable {
        case queued, starting, working, needsApproval, draftReady, interrupted, failed, cancelled, uncertain
    }

    var status: Status
    var output = ""
    var error: String?
    var codexThreadID: String?
    var turnID: String?
    var completedAt: String?
    var approvalID: String?
    var approvalSummary: String?
    var approvalDetails: String?

    var isActive: Bool { [.starting, .working, .needsApproval].contains(status) }
}
