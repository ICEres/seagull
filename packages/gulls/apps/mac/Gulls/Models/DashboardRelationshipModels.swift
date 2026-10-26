import Foundation

/// A relationship observed in the locally loaded inboxes. This model records
/// only senders present in deliveries; it does not infer ownership or human
/// identity from a handle.
struct DashboardRelationship: Identifiable, Equatable {
    let id: String
    let profileID: String
    let ownedGullHandle: String
    let ownedGullDisplayName: String?
    let counterpartID: String
    let counterpart: String
    let counterpartHandle: String?
    let groups: [DashboardConversationGroup]
    let deliveryCount: Int
    let attentionCount: Int
    let updatedAt: Date?
}

struct DashboardGullSummary: Identifiable, Equatable {
    let id: String
    let handle: String
    let displayName: String?
    let relationshipCount: Int
    let conversationCount: Int
    let deliveryCount: Int
    let attentionCount: Int
}

struct DashboardRelationshipSnapshot: Equatable {
    let relationships: [DashboardRelationship]
    let gulls: [DashboardGullSummary]
    let conversationCount: Int
    let deliveryCount: Int
    let counterpartCount: Int
    let attentionCount: Int

    func scoped(to profileID: String?) -> DashboardRelationshipSnapshot {
        guard let profileID else { return self }
        let scopedGulls = gulls.filter { $0.id == profileID }
        let scopedRoutes = relationships.filter { $0.profileID == profileID }
        return DashboardRelationshipSnapshot(
            relationships: scopedRoutes,
            gulls: scopedGulls,
            conversationCount: scopedGulls.reduce(0) { $0 + $1.conversationCount },
            deliveryCount: scopedGulls.reduce(0) { $0 + $1.deliveryCount },
            counterpartCount: Set(scopedRoutes.map(\.counterpartID)).count,
            attentionCount: scopedGulls.reduce(0) { $0 + $1.attentionCount }
        )
    }
}

enum DashboardRelationshipProjector {
    static func makeSnapshot(from profiles: [DashboardProfileInput]) -> DashboardRelationshipSnapshot {
        let normalizedProfiles = profiles.map { profile in
            DashboardProfileInput(
                profileID: profile.profileID,
                handle: profile.handle,
                displayName: profile.displayName,
                items: uniqueItems(profile.items)
            )
        }
        let dashboard = DashboardProjector.makeSnapshot(from: normalizedProfiles)
        let groups = dashboard.allGroups

        var relationshipsByID: [String: DashboardRelationshipAccumulator] = [:]
        var profileGroups: [String: [DashboardConversationGroup]] = [:]
        var profileItems: [String: [InboxItem]] = [:]
        let aliases = senderAliases(in: normalizedProfiles)
        for profile in normalizedProfiles {
            profileItems[profile.profileID] = profile.items
        }

        for group in groups {
            let routes = routeGroups(for: group, aliases: aliases)
            profileGroups[group.profileID, default: []].append(group)
            for route in routes {
                let identity = senderIdentity(for: route.items,
                                              profileID: group.profileID,
                                              aliases: aliases)
                let key = relationshipID(profileID: group.profileID,
                                          ownedGullHandle: group.ownedGullHandle,
                                          counterpartID: identity.id)
                var accumulator = relationshipsByID[key] ?? DashboardRelationshipAccumulator(
                    id: key,
                    profileID: group.profileID,
                    ownedGullHandle: group.ownedGullHandle,
                    ownedGullDisplayName: group.ownedGullDisplayName,
                    counterpartID: identity.id,
                    counterpart: identity.display,
                    counterpartHandle: identity.handle
                )
                accumulator.groups.append(route)
                if accumulator.counterpartHandle == nil, let handle = identity.handle {
                    accumulator.counterpartHandle = handle
                    accumulator.counterpart = identity.display
                }
                accumulator.deliveryCount += route.items.count
                if route.state == .needsAttention { accumulator.attentionCount += 1 }
                if isLater(route.updatedAt, than: accumulator.updatedAt) {
                    accumulator.updatedAt = route.updatedAt
                }
                relationshipsByID[key] = accumulator
            }
        }

        let relationships = relationshipsByID.values.map { $0.value }.sorted(by: relationshipIsNewer)
        let gulls = normalizedProfiles.map { profile in
            let ownGroups = profileGroups[profile.profileID] ?? []
            let ownRelationships = relationships.filter { $0.profileID == profile.profileID }
            return DashboardGullSummary(
                id: profile.profileID,
                handle: profile.handle,
                displayName: profile.displayName,
                relationshipCount: ownRelationships.count,
                conversationCount: ownGroups.count,
                deliveryCount: profileItems[profile.profileID]?.count ?? 0,
                attentionCount: Set(ownGroups.filter { $0.state == .needsAttention }.map(\.id)).count
            )
        }

        let counterpartKeys = Set(relationships.map(\.counterpartID).filter { !$0.hasPrefix("unknown:") })
        let unknownCount = relationships.reduce(into: 0) { count, relationship in
            if relationship.counterpartID.hasPrefix("unknown:") { count += 1 }
        }
        return DashboardRelationshipSnapshot(
            relationships: relationships,
            gulls: gulls,
            conversationCount: groups.count,
            deliveryCount: normalizedProfiles.reduce(0) { $0 + $1.items.count },
            counterpartCount: counterpartKeys.count + unknownCount,
            attentionCount: Set(groups.filter { $0.state == .needsAttention }.map(\.id)).count
        )
    }

    private struct SenderIdentity {
        let id: String
        let display: String
        let handle: String?
    }

    private struct DashboardRelationshipAccumulator {
        let id: String
        let profileID: String
        let ownedGullHandle: String
        let ownedGullDisplayName: String?
        let counterpartID: String
        var counterpart: String
        var counterpartHandle: String?
        var groups: [DashboardConversationGroup] = []
        var deliveryCount = 0
        var attentionCount = 0
        var updatedAt: Date?

        var value: DashboardRelationship {
            DashboardRelationship(
                id: id,
                profileID: profileID,
                ownedGullHandle: ownedGullHandle,
                ownedGullDisplayName: ownedGullDisplayName,
                counterpartID: counterpartID,
                counterpart: counterpart,
                counterpartHandle: counterpartHandle,
                groups: groups.sorted(by: groupIsNewer),
                deliveryCount: deliveryCount,
                attentionCount: attentionCount,
                updatedAt: updatedAt
            )
        }
    }

    private static func routeGroups(for group: DashboardConversationGroup,
                                    aliases: [String: String]) -> [DashboardConversationGroup] {
        var itemsByIdentity: [String: [InboxItem]] = [:]
        for item in group.items {
            let identity = senderIdentity(in: item, profileID: group.profileID, aliases: aliases)
            itemsByIdentity[identity.id, default: []].append(item)
        }
        return itemsByIdentity.compactMap { _, items in
            let ordered = items.sorted(by: itemIsNewer)
            guard let projected = DashboardProjector.makeSnapshot(from: [
                DashboardProfileInput(
                    profileID: group.profileID,
                    handle: group.ownedGullHandle,
                    displayName: group.ownedGullDisplayName,
                    items: ordered
                )
            ]).allGroups.first else { return nil }
            let sender = senderIdentity(for: ordered, profileID: group.profileID, aliases: aliases)
            return DashboardConversationGroup(
                id: group.id,
                profileID: projected.profileID,
                ownedGullHandle: projected.ownedGullHandle,
                ownedGullDisplayName: projected.ownedGullDisplayName,
                threadID: projected.threadID,
                items: projected.items,
                attentionItems: projected.attentionItems,
                latestItem: projected.latestItem,
                title: projected.title,
                counterpart: sender.display,
                snippet: projected.snippet,
                state: projected.state,
                updatedAt: projected.updatedAt
            )
        }.sorted(by: groupIsNewer)
    }

    private static func senderIdentity(for items: [InboxItem],
                                       profileID: String,
                                       aliases: [String: String]) -> SenderIdentity {
        guard let first = items.first else {
            return SenderIdentity(id: "unknown:\(profileID):0:", display: "Unknown participant", handle: nil)
        }
        let identity = senderIdentity(in: first, profileID: profileID, aliases: aliases)
        let matching = items.filter { senderIdentity(in: $0, profileID: profileID, aliases: aliases).id == identity.id }
        let handle = matching.lazy.compactMap { firstNonEmpty($0.message?.senderHandle) }.first
        let displayName = matching.lazy.compactMap {
            firstNonEmpty($0.resolvedSenderDisplayName, $0.message?.senderDisplayName)
        }.first
        let display = GullIdentityDisplay.readableName(
            displayName: displayName, handle: handle, agentID: senderAgentID(in: first)
        ) ?? identity.display
        return SenderIdentity(id: identity.id, display: display, handle: handle ?? identity.handle)
    }

    private static func senderIdentity(in item: InboxItem,
                                       profileID: String,
                                       aliases: [String: String] = [:]) -> SenderIdentity {
        let handle = normalized(item.message?.senderHandle)
        let agentID = senderAgentID(in: item)
        if !agentID.isEmpty {
            let display = GullIdentityDisplay.readableName(
                displayName: firstNonEmpty(item.resolvedSenderDisplayName, item.message?.senderDisplayName),
                handle: item.message?.senderHandle,
                agentID: agentID
            ) ?? "Unknown participant"
            return SenderIdentity(id: "agent:\(agentID)", display: display, handle: handle.isEmpty ? nil : handle)
        }
        if !handle.isEmpty {
            if let agentID = aliases[handle] {
                return SenderIdentity(id: agentID, display: item.senderDisplay, handle: handle)
            }
            return SenderIdentity(id: "handle:\(handle)", display: item.senderDisplay, handle: handle)
        }
        return SenderIdentity(id: "unknown:\(profileID.count):\(profileID)|\(item.id.count):\(item.id)", display: "Unknown participant", handle: nil)
    }

    private static func senderAgentID(in item: InboxItem) -> String {
        normalized(firstNonEmpty(item.message?.senderAgentId, item.delivery.senderAgentId))
    }

    private static func senderAliases(in profiles: [DashboardProfileInput]) -> [String: String] {
        var candidates: [String: Set<String>] = [:]
        for profile in profiles {
            for item in profile.items {
                let handle = normalized(item.message?.senderHandle)
                let agentID = senderAgentID(in: item)
                if !handle.isEmpty, !agentID.isEmpty {
                    candidates[handle, default: []].insert("agent:\(agentID)")
                }
            }
        }
        return candidates.compactMapValues { values in
            values.count == 1 ? values.first : nil
        }
    }

    private static func relationshipID(profileID: String, ownedGullHandle: String, counterpartID: String) -> String {
        [profileID, ownedGullHandle, counterpartID].map { "\($0.count):\($0)" }.joined(separator: "|")
    }

    private static func uniqueItems(_ items: [InboxItem]) -> [InboxItem] {
        var selected: [String: InboxItem] = [:]
        for item in items {
            guard let existing = selected[item.id] else { selected[item.id] = item; continue }
            if itemIsNewer(item, than: existing) { selected[item.id] = item }
        }
        return selected.values.sorted(by: itemIsNewer)
    }

    private static func normalized(_ value: String?) -> String {
        value?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
    }

    private static func timestamp(for item: InboxItem) -> Date? {
        (item.delivery.updatedAt ?? item.delivery.createdAt ?? item.message?.createdAt).flatMap(GullsDates.parse)
    }

    private static func itemIsNewer(_ lhs: InboxItem, than rhs: InboxItem) -> Bool {
        if let left = timestamp(for: lhs), let right = timestamp(for: rhs), left != right { return left > right }
        if timestamp(for: lhs) != nil, timestamp(for: rhs) == nil { return true }
        if timestamp(for: lhs) == nil, timestamp(for: rhs) != nil { return false }
        return lhs.id > rhs.id
    }

    private static func groupIsNewer(_ lhs: DashboardConversationGroup, _ rhs: DashboardConversationGroup) -> Bool {
        if let left = lhs.updatedAt, let right = rhs.updatedAt, left != right { return left > right }
        if lhs.updatedAt != nil, rhs.updatedAt == nil { return true }
        if lhs.updatedAt == nil, rhs.updatedAt != nil { return false }
        return lhs.id < rhs.id
    }

    private static func relationshipIsNewer(_ lhs: DashboardRelationship, _ rhs: DashboardRelationship) -> Bool {
        if let left = lhs.updatedAt, let right = rhs.updatedAt, left != right { return left > right }
        if lhs.updatedAt != nil, rhs.updatedAt == nil { return true }
        if lhs.updatedAt == nil, rhs.updatedAt != nil { return false }
        return lhs.id < rhs.id
    }

    private static func isLater(_ value: Date?, than other: Date?) -> Bool {
        guard let value else { return false }
        return other.map { value > $0 } ?? true
    }

}
