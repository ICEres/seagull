import CryptoKit
import Foundation

enum LocalActionKind: String, Codable, CaseIterable {
    case command
    case readFile = "read_file"
    case writeFile = "write_file"
}

enum LocalActionResultStatus: String, Codable, CaseIterable {
    case succeeded
    case failed
    case rejected
    case cancelled
}

/// A request created for one owned Gull. The request is data until the owner
/// explicitly approves it in the Mac app.
struct LocalActionRequest: Codable, Equatable, Identifiable {
    static let legacyVersion = 1
    static let currentVersion = 2

    let version: Int
    let requestID: String
    let gullHandle: String
    let kind: LocalActionKind
    let createdAt: String
    let profileID: String?
    let codexTaskID: String?
    let codexTaskFolder: String?
    let codexTaskDigest: String?
    let connectionRevision: String?
    let executable: String?
    let arguments: [String]?
    let workingDirectory: String?
    let path: String?
    let content: String?

    // Review metadata is deliberately not part of the wire schema. It is
    // captured by LocalControlStore when the request enters the review queue.
    var reviewedOriginalContent: String?
    var reviewedOriginalHash: String?
    var reviewedRequestDigest: String?
    var reviewedOriginalExists: Bool?
    var reviewedOriginalReadable: Bool?
    var reviewedConnectionRevision: String?

    var id: String { requestID }

    enum CodingKeys: String, CodingKey {
        case version
        case requestID = "request_id"
        case gullHandle = "gull_handle"
        case kind
        case createdAt = "created_at"
        case profileID = "profile_id"
        case codexTaskID = "codex_task_id"
        case codexTaskFolder = "codex_task_folder"
        case codexTaskDigest = "codex_task_digest"
        case connectionRevision = "connection_revision"
        case executable
        case arguments
        case workingDirectory = "working_directory"
        case path
        case content
    }

    init(
        version: Int = legacyVersion,
        requestID: String,
        gullHandle: String,
        kind: LocalActionKind,
        createdAt: String,
        profileID: String? = nil,
        codexTaskID: String? = nil,
        codexTaskFolder: String? = nil,
        codexTaskDigest: String? = nil,
        connectionRevision: String? = nil,
        executable: String? = nil,
        arguments: [String]? = nil,
        workingDirectory: String? = nil,
        path: String? = nil,
        content: String? = nil,
        reviewedOriginalContent: String? = nil,
        reviewedOriginalHash: String? = nil,
        reviewedRequestDigest: String? = nil,
        reviewedOriginalExists: Bool? = nil,
        reviewedOriginalReadable: Bool? = nil,
        reviewedConnectionRevision: String? = nil
    ) {
        self.version = version
        self.requestID = requestID
        self.gullHandle = gullHandle
        self.kind = kind
        self.createdAt = createdAt
        self.profileID = profileID
        self.codexTaskID = codexTaskID
        self.codexTaskFolder = codexTaskFolder
        self.codexTaskDigest = codexTaskDigest
        self.connectionRevision = connectionRevision
        self.executable = executable
        self.arguments = arguments
        self.workingDirectory = workingDirectory
        self.path = path
        self.content = content
        self.reviewedOriginalContent = reviewedOriginalContent
        self.reviewedOriginalHash = reviewedOriginalHash
        self.reviewedRequestDigest = reviewedRequestDigest
        self.reviewedOriginalExists = reviewedOriginalExists
        self.reviewedOriginalReadable = reviewedOriginalReadable
        self.reviewedConnectionRevision = reviewedConnectionRevision
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let version = try container.decode(Int.self, forKey: .version)
        let requestID = try container.decode(String.self, forKey: .requestID)
        let gullHandle = try container.decode(String.self, forKey: .gullHandle)
        let kind = try container.decode(LocalActionKind.self, forKey: .kind)
        let createdAt = try container.decode(String.self, forKey: .createdAt)

        guard version == Self.legacyVersion || version == Self.currentVersion else {
            throw LocalActionModelError.invalidRequest("unsupported request version")
        }
        guard UUID(uuidString: requestID) != nil else {
            throw LocalActionModelError.invalidRequest("request_id must be a UUID")
        }
        guard Self.isCanonicalHandle(gullHandle) else {
            throw LocalActionModelError.invalidRequest("gull_handle is invalid")
        }
        guard GullsDates.parse(createdAt) != nil else {
            throw LocalActionModelError.invalidRequest("created_at must be ISO 8601")
        }
        let profileID = try container.decodeIfPresent(String.self, forKey: .profileID)
        let codexTaskID = try container.decodeIfPresent(String.self, forKey: .codexTaskID)
        let codexTaskFolder = try container.decodeIfPresent(String.self, forKey: .codexTaskFolder)
        let codexTaskDigest = try container.decodeIfPresent(String.self, forKey: .codexTaskDigest)
        let connectionRevision = try container.decodeIfPresent(String.self, forKey: .connectionRevision)
        if version == Self.currentVersion {
            guard let profileID, !profileID.isEmpty,
                  let codexTaskID, UUID(uuidString: codexTaskID) != nil,
                  let codexTaskFolder, codexTaskFolder.hasPrefix("/"),
                  let codexTaskDigest, codexTaskDigest.count == 64,
                  codexTaskDigest.allSatisfy({ $0.isHexDigit }),
                  let connectionRevision, !connectionRevision.isEmpty else {
                throw LocalActionModelError.invalidRequest("Codex request provenance is incomplete")
            }
        }

        self.init(
            version: version,
            requestID: requestID,
            gullHandle: gullHandle,
            kind: kind,
            createdAt: createdAt,
            profileID: profileID,
            codexTaskID: codexTaskID,
            codexTaskFolder: codexTaskFolder,
            codexTaskDigest: codexTaskDigest,
            connectionRevision: connectionRevision,
            executable: try container.decodeIfPresent(String.self, forKey: .executable),
            arguments: try container.decodeIfPresent([String].self, forKey: .arguments),
            workingDirectory: try container.decodeIfPresent(String.self, forKey: .workingDirectory),
            path: try container.decodeIfPresent(String.self, forKey: .path),
            content: try container.decodeIfPresent(String.self, forKey: .content)
        )
    }

    static func isCanonicalHandle(_ value: String) -> Bool {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && !trimmed.contains(where: \.isWhitespace)
    }
}

struct LocalActionResult: Codable, Equatable, Identifiable {
    static let currentVersion = 1

    let version: Int
    let requestID: String
    let gullHandle: String
    let status: LocalActionResultStatus
    let completedAt: String
    let stdout: String?
    let stderr: String?
    let exitCode: Int32?
    let content: String?
    let error: String?

    var id: String { requestID }

    enum CodingKeys: String, CodingKey {
        case version
        case requestID = "request_id"
        case gullHandle = "gull_handle"
        case status
        case completedAt = "completed_at"
        case stdout
        case stderr
        case exitCode = "exit_code"
        case content
        case error
    }

    init(
        version: Int = currentVersion,
        requestID: String,
        gullHandle: String,
        status: LocalActionResultStatus,
        completedAt: String,
        stdout: String? = nil,
        stderr: String? = nil,
        exitCode: Int32? = nil,
        content: String? = nil,
        error: String? = nil
    ) {
        self.version = version
        self.requestID = requestID
        self.gullHandle = gullHandle
        self.status = status
        self.completedAt = completedAt
        self.stdout = stdout
        self.stderr = stderr
        self.exitCode = exitCode
        self.content = content
        self.error = error
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let version = try container.decode(Int.self, forKey: .version)
        let requestID = try container.decode(String.self, forKey: .requestID)
        let gullHandle = try container.decode(String.self, forKey: .gullHandle)
        let status = try container.decode(LocalActionResultStatus.self, forKey: .status)
        let completedAt = try container.decode(String.self, forKey: .completedAt)

        guard version == Self.currentVersion else {
            throw LocalActionModelError.invalidResult("unsupported result version")
        }
        guard UUID(uuidString: requestID) != nil else {
            throw LocalActionModelError.invalidResult("request_id must be a UUID")
        }
        guard LocalActionRequest.isCanonicalHandle(gullHandle) else {
            throw LocalActionModelError.invalidResult("gull_handle is invalid")
        }
        guard GullsDates.parse(completedAt) != nil else {
            throw LocalActionModelError.invalidResult("completed_at must be ISO 8601")
        }

        self.init(
            version: version,
            requestID: requestID,
            gullHandle: gullHandle,
            status: status,
            completedAt: completedAt,
            stdout: try container.decodeIfPresent(String.self, forKey: .stdout),
            stderr: try container.decodeIfPresent(String.self, forKey: .stderr),
            exitCode: try container.decodeIfPresent(Int32.self, forKey: .exitCode),
            content: try container.decodeIfPresent(String.self, forKey: .content),
            error: try container.decodeIfPresent(String.self, forKey: .error)
        )
    }
}

enum LocalActionModelError: Error, LocalizedError, Equatable {
    case invalidRequest(String)
    case invalidResult(String)

    var errorDescription: String? {
        switch self {
        case .invalidRequest(let message): return "Invalid local action request: \(message)"
        case .invalidResult(let message): return "Invalid local action result: \(message)"
        }
    }
}

extension LocalActionRequest {
    var canonicalDigest: String? {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        guard let data = try? encoder.encode(self) else { return nil }
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
