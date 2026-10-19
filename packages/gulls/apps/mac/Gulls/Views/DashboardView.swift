import Charts
import SwiftUI

struct DashboardView: View {
    let snapshot: DashboardSnapshot
    let relationships: DashboardRelationshipSnapshot
    let activity: [DashboardActivityDay]
    let scopeOptions: [DashboardGullSummary]
    let scopeProfileID: String?
    let onScopeChange: (String?) -> Void
    var scopeName: String? = nil
    var accountName = "You"
    var usage: CloudAIUsageSummary? = nil
    var usageScopeAgentID: String? = nil
    var isSignedIn = false
    var usageError: String? = nil
    let isRefreshing: Bool
    let hasConnections: Bool
    let onRefresh: () -> Void
    let onSelectRelationship: (DashboardRelationship) -> Void
    var selectedRelationshipID: String? = nil
    var onCloseRelationship: () -> Void = {}
    let onOpen: (DashboardConversationGroup) -> Void
    let onConversations: () -> Void
    let onSettings: () -> Void
    var localControls: [LocalControlStore] = []
    var onReviewLocalAction: (LocalControlStore, LocalActionRequest) -> Void = { _, _ in }
    var compact = false

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var relationshipView = RelationshipView.map

    private enum RelationshipView: String, CaseIterable {
        case map = "Map"
        case byGull = "By Gull"
    }

    private var localActionCount: Int {
        localControls.reduce(0) { $0 + $1.pendingRequests.count }
    }

    private var selectedRelationship: DashboardRelationship? {
        relationships.relationships.first { $0.id == selectedRelationshipID }
    }

    var body: some View {
        if #available(macOS 26.0, *), !reduceTransparency {
            content
                .safeAreaBar(edge: .top, spacing: 12) { header }
                .gullsScrollEdges()
        } else {
            content
                .safeAreaInset(edge: .top, spacing: 0) { header.background(GullsStyle.canvas) }
                .gullsScrollEdges()
        }
    }

    private var content: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    if hasConnections {
                        statistics
                        connections.id("dashboard-connections")
                        if let selectedRelationship {
                            DashboardRelationshipDetailView(
                                relationship: selectedRelationship,
                                relationships: relationships.relationships,
                                onSelect: onSelectRelationship,
                                onOpen: onOpen,
                                compact: compact,
                                onClose: onCloseRelationship
                            )
                            .id("dashboard-relationship")
                        }
                        needsYou
                        LocalActionsDashboardSection(controls: localControls, onReview: onReviewLocalAction, compact: compact)
                        activityChart
                        cloudUsage
                        Text("Based on up to 100 loaded deliveries per connected Gull. Connections show observed incoming messages; activity uses creation dates where available.")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    } else {
                        emptySetup
                        cloudUsage
                    }
                }
                .frame(maxWidth: 960, alignment: .leading)
                .padding(.horizontal, compact ? 16 : 28)
                .padding(.vertical, 22)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
            .background(GullsStyle.canvas)
            .gullsHiddenScrollbars()
            .onChange(of: selectedRelationship?.id, initial: true) { oldID, newID in
                guard oldID != nil || newID != nil else { return }
                withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) {
                    proxy.scrollTo(newID == nil ? "dashboard-connections" : "dashboard-relationship", anchor: .top)
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    GullsPageTitle("Overview")
                        .font(.title2.weight(.semibold))
                    Text("Your circle of collaboration")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                Button(action: onRefresh) {
                    if isRefreshing {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("Refresh dashboard", systemImage: "arrow.clockwise")
                            .labelStyle(.iconOnly)
                    }
                }
                .disabled(isRefreshing)
                .help("Refresh messages and cloud usage")
                Button(action: onConversations) {
                    Label("All conversations", systemImage: "bubble.left.and.bubble.right")
                        .labelStyle(.iconOnly)
                }
                .help("Show all loaded conversations")
            }
            .buttonStyle(.borderless)
            if scopeOptions.count > 1 {
                Picker("Dashboard scope", selection: Binding(get: { scopeProfileID }, set: onScopeChange)) {
                    Text("All connected Gulls").tag(String?.none)
                    ForEach(scopeOptions) { gull in
                        Text(gull.displayName ?? gull.handle).tag(Optional(gull.id))
                    }
                }
                .pickerStyle(.menu)
                .labelsHidden()
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 240, alignment: .leading)
                .controlSize(.small)
            } else {
                Text(scopeName ?? "Connected on this Mac")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, compact ? 16 : 28)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var statistics: some View {
        HStack(alignment: .top, spacing: 12) {
            metric("Counterparts", value: relationships.counterpartCount)
            metric("Conversations", value: relationships.conversationCount)
            metric("Needs you", value: snapshot.needsAttention.count + localActionCount, prominent: true)
        }
        .accessibilityElement(children: .contain)
    }

    private func metric(_ title: String, value: Int, prominent: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(value.formatted())
                .font(.system(size: compact ? 27 : 32, weight: .medium, design: .rounded))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.65)
                .foregroundStyle(prominent && value > 0 ? GullsStyle.accent : Color.primary)
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private var connections: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text("Connections").font(.headline)
                Spacer(minLength: 8)
                Picker("Relationship view", selection: $relationshipView) {
                    ForEach(RelationshipView.allCases, id: \.self) { view in
                        Text(view.rawValue).tag(view)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: 136)
            }
            if relationshipView == .map {
                DashboardRelationshipMap(
                    snapshot: relationships,
                    accountName: accountName,
                    selectedRelationshipID: selectedRelationshipID,
                    onSelect: onSelectRelationship,
                    compact: compact
                )
            } else {
                relationshipsByGull
            }
        }
    }

    private var relationshipsByGull: some View {
        VStack(alignment: .leading, spacing: 24) {
            ForEach(relationships.gulls) { gull in
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 9) {
                        GullAvatar(handle: gull.handle, size: 30)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(gull.displayName ?? gull.handle).font(.subheadline.weight(.semibold))
                            Text("\(gull.deliveryCount) received · \(gull.conversationCount) conversations")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 0)
                    }
                    let routes = relationships.relationships.filter { $0.profileID == gull.id }
                    if routes.isEmpty {
                        Text("No connections in the loaded messages.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    ForEach(routes) { route in
                        Button { onSelectRelationship(route) } label: {
                            HStack(spacing: 10) {
                                GullAvatar(handle: route.counterpartHandle ?? route.counterpartID, size: 24)
                                Text(route.counterpart).font(.caption).lineLimit(1)
                                Spacer(minLength: 4)
                                Text(route.attentionCount > 0 ? "\(route.attentionCount) to review" : "\(route.deliveryCount) received")
                                    .font(.caption2)
                                    .foregroundStyle(route.attentionCount > 0 ? GullsStyle.accent : .secondary)
                                Image(systemName: "chevron.right").font(.caption2)
                            }
                            .foregroundStyle(Color.primary)
                            .padding(.vertical, 7)
                            .padding(.horizontal, 8)
                            .contentShape(Rectangle())
                            .background(route.id == selectedRelationshipID ? GullsStyle.field : .clear, in: RoundedRectangle(cornerRadius: 9))
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(route.counterpart), to \(gull.displayName ?? gull.handle), \(route.deliveryCount) received")
                        .accessibilityAddTraits(route.id == selectedRelationshipID ? .isSelected : [])
                    }
                }
            }
        }
    }

    private var needsYou: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Needs you").font(.headline)
                Spacer()
                Text("\(snapshot.needsAttention.count) conversations")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if snapshot.needsAttention.isEmpty {
                Label("No conversations waiting for review", systemImage: "checkmark.circle")
                    .font(.subheadline).foregroundStyle(.secondary)
            } else {
                ForEach(Array(snapshot.needsAttention.prefix(3))) { group in
                    Button { onOpen(group) } label: {
                        HStack(alignment: .top, spacing: 10) {
                            GullAvatar(handle: group.ownedGullHandle, size: 28)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(group.title).font(.subheadline.weight(.medium)).lineLimit(2)
                                Text("\(group.counterpart) · via \(group.ownedGullDisplayName ?? group.ownedGullHandle)")
                                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                if group.attentionItems.contains(where: { $0.delivery.statusValue == .failed }) {
                                    Text("Delivery failed").font(.caption2).foregroundStyle(.red)
                                }
                            }
                            Spacer(minLength: 0)
                            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
                        }
                        .foregroundStyle(Color.primary)
                        .padding(.vertical, 7)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityHint("Open conversation to review")
                }
                if snapshot.needsAttention.count > 3 {
                    Button("View all conversations", action: onConversations)
                        .buttonStyle(.borderless).font(.caption)
                }
            }
        }
    }

    private var activityChart: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Activity").font(.headline)
                Spacer()
                Text("Past 7 days").font(.caption).foregroundStyle(.secondary)
            }
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(activity.reduce(0) { $0 + $1.receivedCount }.formatted())
                    .font(.title3.weight(.medium)).monospacedDigit()
                Text("messages received").font(.caption).foregroundStyle(.secondary)
            }
            Chart(activity) { day in
                BarMark(x: .value("Day", day.date, unit: .day), y: .value("Received", day.receivedCount))
                    .foregroundStyle(GullsStyle.accent.opacity(0.7))
                    .cornerRadius(3)
                    .accessibilityLabel(day.date.formatted(.dateTime.month(.abbreviated).day()))
                    .accessibilityValue("\(day.receivedCount) received")
            }
            .chartYScale(domain: 0...max(1, activity.map(\.receivedCount).max() ?? 0))
            .chartYAxis(.hidden)
            .chartXAxis {
                AxisMarks(values: .stride(by: .day)) { _ in
                    AxisValueLabel(format: .dateTime.weekday(.abbreviated))
                }
            }
            .frame(height: 95)
        }
    }

    private var cloudUsage: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Cloud AI").font(.headline)
                Spacer()
                Text(scopeName ?? "Your account")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            if isSignedIn, let usage {
                if let records = usageRecords {
                    HStack(alignment: .top, spacing: 14) {
                        metric("Recorded requests", value: records.count)
                        metric("Tokens processed", value: records.reduce(0) { $0 + ($1.totalTokens ?? $1.inputTokens + $1.outputTokens) })
                    }
                } else {
                    Text("No cloud profile is linked to this Gull.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                HStack {
                    Text("Credits left · shared by your account").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text(usage.balance.availableCredits.formatted()).font(.subheadline.weight(.medium)).monospacedDigit()
                }
                if let usageError {
                    Label(usageError, systemImage: "exclamationmark.triangle")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Text(isSignedIn ? usageError ?? "Refresh to load cloud usage." : "Sign in to view cloud usage and your allowance.")
                    .font(.caption).foregroundStyle(.secondary)
                Button("Open Settings", action: onSettings).buttonStyle(.borderless).font(.caption)
            }
        }
    }

    private var usageRecords: [CloudUsageRecord]? {
        guard let usage else { return nil }
        guard scopeProfileID != nil else { return usage.usage }
        guard let usageScopeAgentID else { return nil }
        return usage.usage.filter { $0.agentID == usageScopeAgentID }
    }

    private var emptySetup: some View {
        VStack(alignment: .leading, spacing: 12) {
            GullWing(name: .classic)
                .stroke(GullsStyle.accent, style: StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round))
                .frame(width: 42, height: 20)
            Text("Connect a Gull to get started").font(.headline)
            Text("See your connected Gulls, their relationships, and the conversations that need you.")
                .font(.callout).foregroundStyle(.secondary)
            Button("Open Settings", action: onSettings).buttonStyle(.borderless)
        }
        .padding(.top, 24)
    }
}

struct ConversationsView: View {
    let snapshot: DashboardSnapshot
    var scopeName: String? = nil
    let onOpen: (DashboardConversationGroup) -> Void
    var compact: Bool = false
    var selectedGroupID: String? = nil

    @State private var searchText = ""
    @State private var filter: ConversationFilter = .all

    private enum ConversationFilter: String, CaseIterable, Identifiable {
        case all = "All"
        case needsYou = "Needs you"
        case inProgress = "In progress"
        case handled = "Handled"

        var id: String { rawValue }
    }

    private var filteredGroups: [DashboardConversationGroup] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return snapshot.allGroups.filter { group in
            switch filter {
            case .all: break
            case .needsYou: guard group.state == .needsAttention else { return false }
            case .inProgress: guard group.state == .inProgress else { return false }
            case .handled: guard group.state == .handled else { return false }
            }
            guard !query.isEmpty else { return true }
            return [group.title, group.counterpart, group.ownedGullHandle, group.snippet ?? ""]
                .joined(separator: " ")
                .lowercased()
                .contains(query)
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: compact ? 10 : 14) {
                HStack(spacing: 10) {
                    HStack(spacing: 8) {
                        Image(systemName: "magnifyingglass")
                            .foregroundStyle(.secondary)
                        TextField(compact ? "Search" : "Search conversations", text: $searchText)
                            .textFieldStyle(.plain)
                            .accessibilityLabel("Search conversations")
                    }
                    .padding(.horizontal, compact ? 9 : 11)
                    .padding(.vertical, compact ? 7 : 8)
                    .background(GullsStyle.field, in: Capsule())

                    Picker("Filter", selection: $filter) {
                        ForEach(ConversationFilter.allCases) { option in
                            Text(option.rawValue).tag(option)
                        }
                    }
                    .pickerStyle(.menu)
                    .labelsHidden()
                }

                HStack(alignment: compact ? .center : .firstTextBaseline, spacing: 8) {
                    VStack(alignment: .leading, spacing: compact ? 2 : 0) {
                        GullsPageTitle("Messages")
                            .font(compact ? .headline.weight(.semibold) : .title2.weight(.semibold))
                        if let scopeName {
                            Text(scopeName)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        if compact {
                            Text("\(filteredGroups.count) conversations")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                    }
                    Spacer(minLength: 0)
                    if !compact {
                        Text("\(filteredGroups.count)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                if filteredGroups.isEmpty {
                    ContentUnavailableView("No conversations", systemImage: "bubble.left.and.bubble.right")
                        .frame(maxWidth: .infinity)
                        .padding(.top, 70)
                } else {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(filteredGroups) { group in
                            conversationRow(group)
                        }
                    }
                }
            }
            .frame(maxWidth: compact ? .infinity : 860, alignment: .leading)
            .padding(.horizontal, compact ? 14 : 28)
            .padding(.vertical, compact ? 16 : 24)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .background(GullsStyle.canvas)
        .gullsHiddenScrollbars()
        .gullsScrollEdges()
    }

    private func conversationRow(_ group: DashboardConversationGroup) -> some View {
        Button {
            onOpen(group)
        } label: {
            HStack(alignment: .top, spacing: 12) {
                GullAvatar(handle: group.ownedGullHandle, size: compact ? 26 : 28)
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(group.title)
                            .font(.subheadline.weight(.semibold))
                            .lineLimit(compact ? 1 : 2)
                        Spacer(minLength: 4)
                        if !compact {
                            Text(stateLabel(group.state))
                                .font(.caption2)
                                .foregroundStyle(group.state == .needsAttention ? GullsStyle.accent : .secondary)
                        }
                    }
                    Text("\(group.counterpart) · via \(group.ownedGullDisplayName ?? group.ownedGullHandle)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(compact ? 1 : nil)
                    if let snippet = conversationSupportingText(group) {
                        Text(snippet)
                            .font(compact ? .caption : .callout)
                            .foregroundStyle(.secondary)
                            .lineLimit(compact ? 1 : 2)
                    }
                    if compact {
                        Text(stateLabel(group.state))
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(group.state == .needsAttention ? GullsStyle.accent : .secondary)
                            .lineLimit(1)
                    } else {
                        Text(group.items.count == 1 ? "1 loaded update" : "\(group.items.count) loaded updates")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
            .foregroundStyle(Color.primary)
            .padding(.vertical, compact ? 8 : 12)
            .padding(.horizontal, compact ? 10 : 0)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .background {
            if compact && selectedGroupID == group.id {
                RoundedRectangle(cornerRadius: 10)
                    .fill(GullsStyle.accent.opacity(0.14))
            }
        }
        .accessibilityAddTraits(compact && selectedGroupID == group.id ? .isSelected : [])
    }

    private func stateLabel(_ state: DashboardGroupState) -> String {
        switch state {
        case .needsAttention: return "Needs you"
        case .inProgress: return "In progress"
        case .handled: return "Handled"
        }
    }

}

private func conversationSupportingText(_ group: DashboardConversationGroup) -> String? {
    guard let text = group.snippet else { return nil }
    let lines = text.split(whereSeparator: \.isNewline)
    let remainder = lines.dropFirst().joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
    return remainder.isEmpty ? nil : remainder
}
