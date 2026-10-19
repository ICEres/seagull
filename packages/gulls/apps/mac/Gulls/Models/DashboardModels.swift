import Foundation

/// The minimum data the dashboard needs from one locally connected Gull.
/// Keeping this input separate from InboxStore makes the projection easy to
/// build for several profiles without coupling the view to store ownership.
struct DashboardProfileInput: Equatable {
    let profileID: String
    let handle: String
    let displayName: String?
    let items: [InboxItem]
}

typealias DashboardProfile = DashboardProfileInput

enum DashboardGroupState: String, Equatable {
    case needsAttention
    case inProgress
    case handled
}

/// One dashboard row represents a work conversation, not an individual
/// message. All deliveries remain attached so a row can still expose every
/// independent decision in that conversation.
struct DashboardConversationGroup: Identifiable, Equatable {
    let id: String
    let profileID: String
    let ownedGullHandle: String
    let ownedGullDisplayName: String?
    let threadID: String?
    let items: [InboxItem]
    let attentionItems: [InboxItem]
    let latestItem: InboxItem
    let title: String
    let counterpart: String
    let snippet: String?
    let state: DashboardGroupState
    let updatedAt: Date?

    var attentionCount: Int { attentionItems.count }

    /// The item a review action should open first. It is the newest pending
    /// delivery, while preserving the rest of the queue in `attentionItems`.
    var primaryItem: InboxItem { attentionItems.first ?? latestItem }
}

struct DashboardSnapshot: Equatable {
    let needsAttention: [DashboardConversationGroup]
    let inProgress: [DashboardConversationGroup]
    let handled: [DashboardConversationGroup]

    var allGroups: [DashboardConversationGroup] {
        needsAttention + inProgress + handled
    }

    var attentionCount: Int {
        needsAttention.reduce(0) { $0 + $1.attentionCount }
    }
}

enum DashboardProjector {
    /// Projects current local inbox snapshots into the dashboard's three
    /// supervision sections. This is deliberately a pure function: no AI
    /// summary or inferred health score is introduced at this layer.
    static func makeSnapshot(from profiles: [DashboardProfileInput]) -> DashboardSnapshot {
        var metadata: [String: DashboardProfileInput] = [:]
        var grouped: [GroupKey: [InboxItem]] = [:]

        for profile in profiles {
            metadata[profile.profileID] = profile
            for item in profile.items {
                let key = groupKey(profileID: profile.profileID, item: item)
                grouped[key, default: []].append(item)
            }
        }

        let groups = grouped.compactMap { key, items -> DashboardConversationGroup? in
            guard let profile = metadata[key.profileID], let latest = latestItem(in: items) else {
                return nil
            }

            let orderedItems = items.sorted(by: itemIsNewer)
            let attentionItems = orderedItems.filter(isAttention)
            let state: DashboardGroupState
            if !attentionItems.isEmpty {
                state = .needsAttention
            } else if orderedItems.contains(where: isInProgress) {
                state = .inProgress
            } else {
                state = .handled
            }

            let focusItem = attentionItems.first ?? latest
            let counterpart = focusItem.senderDisplay
            let title = title(for: focusItem, counterpart: counterpart)
            return DashboardConversationGroup(
                id: key.description,
                profileID: profile.profileID,
                ownedGullHandle: profile.handle,
                ownedGullDisplayName: profile.displayName,
                threadID: key.threadID,
                items: orderedItems,
                attentionItems: attentionItems,
                latestItem: latest,
                title: title,
                counterpart: counterpart,
                snippet: focusItem.bodyText,
                state: state,
                updatedAt: timestamp(for: latest)
            )
        }

        let ordered = groups.sorted(by: groupIsNewer)
        return DashboardSnapshot(
            needsAttention: ordered.filter { $0.state == .needsAttention },
            inProgress: ordered.filter { $0.state == .inProgress },
            handled: ordered.filter { $0.state == .handled }
        )
    }

    private struct GroupKey: Hashable, CustomStringConvertible {
        let profileID: String
        let identity: String
        let threadID: String?

        var description: String { "\(profileID):\(identity)" }
    }

    private static func groupKey(profileID: String, item: InboxItem) -> GroupKey {
        let rawThreadID = item.delivery.threadId ?? item.message?.threadId
        if let threadID = rawThreadID?.trimmingCharacters(in: .whitespacesAndNewlines),
           !threadID.isEmpty {
            return GroupKey(profileID: profileID, identity: "thread:\(threadID)", threadID: threadID)
        }
        return GroupKey(profileID: profileID, identity: "delivery:\(item.id)", threadID: nil)
    }

    private static func latestItem(in items: [InboxItem]) -> InboxItem? {
        items.sorted(by: itemIsNewer).first
    }

    private static func itemIsNewer(_ lhs: InboxItem, _ rhs: InboxItem) -> Bool {
        switch compareDates(timestamp(for: lhs), timestamp(for: rhs)) {
        case .orderedDescending: return true
        case .orderedAscending: return false
        case .orderedSame: return lhs.id > rhs.id
        }
    }

    private static func groupIsNewer(_ lhs: DashboardConversationGroup,
                                     _ rhs: DashboardConversationGroup) -> Bool {
        switch compareDates(lhs.updatedAt, rhs.updatedAt) {
        case .orderedDescending: return true
        case .orderedAscending: return false
        case .orderedSame: return lhs.id < rhs.id
        }
    }

    private static func compareDates(_ lhs: Date?, _ rhs: Date?) -> ComparisonResult {
        switch (lhs, rhs) {
        case let (left?, right?):
            if left > right { return .orderedDescending }
            if left < right { return .orderedAscending }
            return .orderedSame
        case (_?, nil): return .orderedDescending
        case (nil, _?): return .orderedAscending
        case (nil, nil): return .orderedSame
        }
    }

    private static func timestamp(for item: InboxItem) -> Date? {
        let raw = item.delivery.updatedAt
            ?? item.delivery.createdAt
            ?? item.message?.createdAt
        return raw.flatMap(GullsDates.parse)
    }

    private static func normalized(_ value: String?) -> String {
        value?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
    }

    private static func isAttention(_ item: InboxItem) -> Bool {
        let status = normalized(item.delivery.status)
        if item.delivery.statusValue == .failed || status == "failed" {
            return true
        }
        // A terminal delivery status wins over a stale current stage.
        if status == "acked" || status == "ignored" || status == "replied" {
            return false
        }
        if item.delivery.statusValue == .delivered {
            return true
        }
        let pendingValues = [
            "needs_review", "needs-review", "pending_action", "pending-action",
            "pending", "awaiting_decision", "awaiting-decision", "awaiting_review",
            "awaiting-review", "action_required", "action-required"
        ]
        if pendingValues.contains(status) {
            return true
        }
        let activeValues = [
            "queued", "processing", "sending", "working", "running",
            "in_progress", "in-progress"
        ]
        if activeValues.contains(status) {
            return false
        }
        // Keep missing and future protocol states visible. A new hub state
        // must never disappear from supervision until its semantics are known.
        return true
    }

    private static func isInProgress(_ item: InboxItem) -> Bool {
        let status = normalized(item.delivery.status)
        if status == "acked" || status == "ignored" || status == "replied" || status == "failed" {
            return false
        }
        let activeValues = ["queued", "processing", "sending", "working", "running", "in_progress", "in-progress"]
        return activeValues.contains(status)
    }

    private static func title(for item: InboxItem, counterpart: String) -> String {
        if let body = item.bodyText?.split(whereSeparator: \.isNewline).first,
           !body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return String(body).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return "Conversation with \(counterpart)"
    }
}
