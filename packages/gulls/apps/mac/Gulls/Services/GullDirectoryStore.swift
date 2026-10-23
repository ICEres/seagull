import Foundation
import Observation

@MainActor
@Observable
final class GullDirectoryStore {
    private let defaults: UserDefaults
    private let storageKey = "savedGullDirectory.v1"
    private var entries: [Entry]

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.entries = Self.load(from: defaults, key: storageKey)
    }

    func records(for userID: String, websiteURL: String) -> [SavedGull] {
        guard let scope = Scope(userID: userID, websiteURL: websiteURL) else { return [] }
        return entries.filter { $0.scope == scope }.map(\.gull).sorted { $0.displayName.localizedCaseInsensitiveCompare($1.displayName) == .orderedAscending }
    }

    @discardableResult
    func save(_ profile: CloudGull, userID: String, websiteURL: String) throws -> SavedGull {
        try save(agentID: profile.agentID, handle: profile.handle, displayName: profile.displayName,
                 bio: profile.bio, declaredCapabilities: profile.capabilities,
                 userID: userID, websiteURL: websiteURL)
    }

    @discardableResult
    func save(_ profile: GullPublicProfile, userID: String, websiteURL: String) throws -> SavedGull {
        try save(agentID: profile.agentID, handle: profile.handle, displayName: profile.displayName,
                 bio: nil, declaredCapabilities: profile.capabilities,
                 userID: userID, websiteURL: websiteURL)
    }

    @discardableResult
    func save(_ relationship: DashboardRelationship, userID: String, websiteURL: String) throws -> SavedGull {
        let agentID = relationship.counterpartID.hasPrefix("agent:")
            ? String(relationship.counterpartID.dropFirst("agent:".count))
            : nil
        guard let handle = relationship.counterpartHandle else { throw SavedGullError.invalidHandle }
        return try upsert(agentID: agentID, handle: handle, displayName: relationship.counterpart,
                          bio: nil, declaredCapabilities: [], preserveEmptyCapabilities: true,
                          userID: userID, websiteURL: websiteURL)
    }

    @discardableResult
    func save(agentID: String?, handle: String, displayName: String?, bio: String?,
              declaredCapabilities: [String], userID: String, websiteURL: String) throws -> SavedGull {
        try upsert(agentID: agentID, handle: handle, displayName: displayName, bio: bio,
                   declaredCapabilities: declaredCapabilities, preserveEmptyCapabilities: false,
                   userID: userID, websiteURL: websiteURL)
    }

    private func upsert(agentID: String?, handle: String, displayName: String?, bio: String?,
                        declaredCapabilities: [String], preserveEmptyCapabilities: Bool,
                        userID: String, websiteURL: String) throws -> SavedGull {
        guard let scope = Scope(userID: userID, websiteURL: websiteURL) else { throw SavedGullError.invalidScope }
        guard let canonical = SavedGull.canonicalHandle(handle) else { throw SavedGullError.invalidHandle }
        let normalizedAgentID = agentID?.trimmingCharacters(in: .whitespacesAndNewlines)
        let matching = entries.firstIndex { entry in
            guard entry.scope == scope else { return false }
            if entry.gull.handle == canonical { return true }
            guard let normalizedAgentID, !normalizedAgentID.isEmpty else { return false }
            return entry.gull.agentID == normalizedAgentID
        }
        let now = Date()
        let existing = matching.map { entries[$0].gull }
        let record = try SavedGull(
            agentID: normalizedAgentID ?? existing?.agentID,
            handle: canonical,
            publicDisplayName: displayName ?? existing?.publicDisplayName,
            bio: bio ?? existing?.bio,
            declaredCapabilities: declaredCapabilities.isEmpty && preserveEmptyCapabilities
                ? (existing?.declaredCapabilities ?? []) : declaredCapabilities,
            customDisplayName: existing?.customDisplayName,
            labels: existing?.labels ?? [],
            savedAt: existing?.savedAt ?? now,
            updatedAt: now
        )
        let entry = Entry(scope: scope, gull: record)
        if let matching { entries[matching] = entry } else { entries.append(entry) }
        persist()
        return record
    }

    @discardableResult
    func updateLabels(_ labels: [String], for handle: String, userID: String, websiteURL: String) throws -> SavedGull {
        try update(handle: handle, userID: userID, websiteURL: websiteURL) { current in
            try SavedGull(agentID: current.agentID, handle: current.handle,
                          publicDisplayName: current.publicDisplayName, bio: current.bio,
                          declaredCapabilities: current.declaredCapabilities,
                          customDisplayName: current.customDisplayName, labels: labels,
                          savedAt: current.savedAt, updatedAt: Date())
        }
    }

    @discardableResult
    func updateDisplayName(_ displayName: String?, for handle: String, userID: String, websiteURL: String) throws -> SavedGull {
        try update(handle: handle, userID: userID, websiteURL: websiteURL) { current in
            try SavedGull(agentID: current.agentID, handle: current.handle,
                          publicDisplayName: current.publicDisplayName, bio: current.bio,
                          declaredCapabilities: current.declaredCapabilities,
                          customDisplayName: displayName, labels: current.labels,
                          savedAt: current.savedAt, updatedAt: Date())
        }
    }

    func remove(_ handle: String, userID: String, websiteURL: String) throws {
        guard let scope = Scope(userID: userID, websiteURL: websiteURL) else { throw SavedGullError.invalidScope }
        guard let canonical = SavedGull.canonicalHandle(handle) else { throw SavedGullError.invalidHandle }
        let oldCount = entries.count
        entries.removeAll { $0.scope == scope && $0.gull.handle == canonical }
        guard entries.count != oldCount else { throw SavedGullError.notFound }
        persist()
    }

    private func update(handle: String, userID: String, websiteURL: String,
                        transform: (SavedGull) throws -> SavedGull) throws -> SavedGull {
        guard let scope = Scope(userID: userID, websiteURL: websiteURL) else { throw SavedGullError.invalidScope }
        guard let canonical = SavedGull.canonicalHandle(handle) else { throw SavedGullError.invalidHandle }
        guard let index = entries.firstIndex(where: { $0.scope == scope && $0.gull.handle == canonical }) else {
            throw SavedGullError.notFound
        }
        let updated = try transform(entries[index].gull)
        entries[index] = Entry(scope: scope, gull: updated)
        persist()
        return updated
    }

    private func persist() {
        guard let data = try? JSONEncoder().encode(entries) else { return }
        defaults.set(data, forKey: storageKey)
    }

    private static func load(from defaults: UserDefaults, key: String) -> [Entry] {
        guard let data = defaults.data(forKey: key), let decoded = try? JSONDecoder().decode([Entry].self, from: data) else { return [] }
        var seen = Set<String>()
        return decoded.filter { entry in
            let key = "\(entry.scope.userID)\n\(entry.scope.websiteURL)\n\(entry.gull.handle)"
            return seen.insert(key).inserted
        }
    }

    private struct Scope: Codable, Equatable {
        let userID: String
        let websiteURL: String

        init?(userID: String, websiteURL: String) {
            let normalizedUserID = userID.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !normalizedUserID.isEmpty, let normalizedWebsite = SharedCloudSessionFile.normalizedWebsite(websiteURL) else { return nil }
            self.userID = normalizedUserID
            self.websiteURL = normalizedWebsite
        }
    }

    private struct Entry: Codable {
        let scope: Scope
        let gull: SavedGull
    }
}
