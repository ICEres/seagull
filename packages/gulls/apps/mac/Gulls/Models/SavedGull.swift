import Foundation

/// Public identity data returned by the message hub for an external Gull.
/// This intentionally excludes owner-only fields and credentials.
struct GullPublicProfile: Codable, Equatable {
    let agentID: String
    let handle: String
    let displayName: String?
    let capabilities: [String]
    let status: String?
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case agentID = "agent_id"
        case handle
        case displayName = "display_name"
        case capabilities
        case status
        case updatedAt = "updated_at"
    }
}

/// A public external Gull saved by a signed-in user on this Mac.
///
/// Credentials, prompts, and other private server data are intentionally not
/// represented here. The canonical handle remains the stable Gull identity;
/// display names and labels are presentation metadata.
struct SavedGull: Codable, Equatable, Identifiable {
    let agentID: String?
    let handle: String
    let publicDisplayName: String?
    let bio: String?
    let declaredCapabilities: [String]
    let customDisplayName: String?
    let labels: [String]
    let savedAt: Date
    let updatedAt: Date

    var id: String { agentID ?? handle }

    var displayName: String {
        customDisplayName ?? publicDisplayName ?? Self.defaultDisplayName(for: handle)
    }

    init(agentID: String?, handle: String, publicDisplayName: String?, bio: String?,
         declaredCapabilities: [String], customDisplayName: String?, labels: [String],
         savedAt: Date = Date(), updatedAt: Date = Date()) throws {
        guard let canonicalHandle = Self.canonicalHandle(handle) else {
            throw SavedGullError.invalidHandle
        }
        self.agentID = Self.nonEmpty(agentID)
        self.handle = canonicalHandle
        self.publicDisplayName = Self.nonEmpty(publicDisplayName)
        self.bio = Self.nonEmpty(bio)
        self.declaredCapabilities = Self.normalizedCapabilities(declaredCapabilities)
        self.customDisplayName = Self.nonEmpty(customDisplayName)
        self.labels = Self.normalizedLabels(labels)
        self.savedAt = savedAt
        self.updatedAt = updatedAt
    }

    static func canonicalHandle(_ raw: String) -> String? {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard value.count >= 4, value.first == "@", value.filter({ $0 == ":" }).count == 1,
              !value.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains) else {
            return nil
        }
        let parts = value.dropFirst().split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2 else { return nil }
        let local = String(parts[0])
        let host = String(parts[1])
        guard isSafeHandlePart(local, first: true), isSafeHandlePart(host, first: false) else {
            return nil
        }
        return "@\(local):\(host)"
    }

    static func defaultDisplayName(for handle: String) -> String {
        guard let canonical = canonicalHandle(handle),
              let colon = canonical.firstIndex(of: ":") else { return handle }
        return String(canonical[canonical.index(after: canonical.startIndex)..<colon])
    }

    static func normalizedLabels(_ values: [String]) -> [String] {
        var seen = Set<String>()
        return values.compactMap { raw in
            let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !value.isEmpty, !value.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains) else {
                return nil
            }
            let key = value.lowercased()
            guard seen.insert(key).inserted else { return nil }
            return value
        }
    }

    private static func normalizedCapabilities(_ values: [String]) -> [String] {
        normalizedLabels(values)
    }

    private static func nonEmpty(_ value: String?) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !trimmed.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains) else {
            return nil
        }
        return trimmed
    }

    private static func isSafeHandlePart(_ value: String, first: Bool) -> Bool {
        guard !value.isEmpty else { return false }
        let scalars = Array(value.unicodeScalars)
        guard scalars.first.map({ isASCIIAlphaNumeric($0) }) == true else { return false }
        // Keep this in lockstep with seagull_protocol.HANDLE_RE:
        // local: [a-z0-9_.-]*, server: [a-z0-9.-]*.
        return scalars.allSatisfy { isASCIIAlphaNumeric($0) || $0 == "." || $0 == "-" || (first && $0 == "_") }
    }

    private static func isASCIIAlphaNumeric(_ scalar: UnicodeScalar) -> Bool {
        (scalar.value >= 48 && scalar.value <= 57) ||
        (scalar.value >= 97 && scalar.value <= 122)
    }
}

enum SavedGullError: Error, LocalizedError, Equatable {
    case invalidHandle
    case invalidScope
    case notFound

    var errorDescription: String? {
        switch self {
        case .invalidHandle: return "The Gull handle is not a valid canonical handle."
        case .invalidScope: return "A signed-in user and secure website are required."
        case .notFound: return "The saved Gull could not be found."
        }
    }
}
