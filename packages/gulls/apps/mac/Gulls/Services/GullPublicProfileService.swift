import Foundation

/// Resolves an external Gull's public card from the Message Hub.
///
/// The service deliberately constructs CloudAPI without an access token. A
/// public Gull card must never require or transmit the signed-in user's token.
final class GullPublicProfileService {
    private let api: CloudAPI

    init(messageHubURL: String, session: URLSession? = nil) throws {
        api = try CloudAPI(baseURL: messageHubURL, session: session)
    }

    convenience init(apiURL: String, session: URLSession? = nil) throws {
        try self.init(messageHubURL: apiURL, session: session)
    }

    func resolve(handle: String) async throws -> GullPublicProfile {
        guard let requested = SavedGull.canonicalHandle(handle) else {
            throw GullPublicProfileServiceError.invalidHandle
        }
        let response: PublicAgentResponse = try await api.get("/agents/\(requested)")
        guard let returned = SavedGull.canonicalHandle(response.agent.handle), returned == requested else {
            throw GullPublicProfileServiceError.mismatchedHandle
        }
        guard !response.agent.agentID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw GullPublicProfileServiceError.invalidResponse
        }
        return GullPublicProfile(
            agentID: response.agent.agentID,
            handle: returned,
            displayName: response.agent.displayName,
            capabilities: response.agent.capabilities,
            status: response.agent.status,
            updatedAt: response.agent.updatedAt
        )
    }

    private struct PublicAgentResponse: Decodable {
        let agent: PublicAgent
    }

    // CloudAPI already normalizes snake_case keys to these camel-case names.
    // Keep this DTO separate from the persisted model, whose Codable shape is
    // intentionally stable across API changes.
    private struct PublicAgent: Decodable {
        let agentID: String
        let handle: String
        let displayName: String?
        let capabilities: [String]
        let status: String?
        let updatedAt: String?
    }
}

enum GullPublicProfileServiceError: Error, LocalizedError, Equatable {
    case invalidHandle
    case mismatchedHandle
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .invalidHandle: return "The Gull handle is not a valid canonical handle."
        case .mismatchedHandle: return "The public profile returned a different Gull handle."
        case .invalidResponse: return "The public Gull profile is incomplete."
        }
    }
}
