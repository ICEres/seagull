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
    var historySummary: MessageHistorySummary? = nil
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
    var codexTasks: [CodexTaskStore] = []
    var onOpenCodexTask: (CodexTaskStore, CodexTask) -> Void = { _, _ in }
    var compact = false

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var relationshipView = RelationshipView.map
    @State private var isHeaderCondensed = false

    private enum RelationshipView: String, CaseIterable {
        case map = "Map"
        case byGull = "List"
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
                .gullsSafeAreaBar(edge: .top, spacing: 0, style: .minimal) { header }
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
                    headerDetails
                        .gullsHeaderControlsVisibility(isCondensed: $isHeaderCondensed)
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
                        codexActivity
                        LocalActionsDashboardSection(controls: localControls, onReview: onReviewLocalAction, compact: compact)
                        activityChart
                        cloudUsage
                        Text("Based on message history currently synced to this Mac. Older history may still be loading; activity uses creation dates where available.")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    } else {
                        emptySetup
                        codexActivity
                        cloudUsage
                    }
                }
                .frame(maxWidth: 960, alignment: .leading)
                .padding(.horizontal, compact ? 14 : 28)
                .padding(.vertical, 22)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
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
        HStack(spacing: 12) {
            GullsPageTitle("Overview")
                .font(.title2.weight(.semibold))
                .lineLimit(1)
            Spacer(minLength: 0)
            if isHeaderCondensed && scopeOptions.count > 1 {
                Menu { scopePicker } label: {
                    Label("Dashboard scope", systemImage: "line.3.horizontal.decrease")
                        .labelStyle(.iconOnly)
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .frame(width: 28, height: 28)
                .accessibilityValue(scopeName ?? "All connected Gulls")
                .help("Dashboard scope: \(scopeName ?? "All connected Gulls")")
            }
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
        .frame(minHeight: 28)
        .padding(.horizontal, compact ? 14 : 28)
        .padding(.top, 12)
        .padding(.bottom, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var headerDetails: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Your circle of collaboration")
                .font(.caption)
                .foregroundStyle(.secondary)
            if scopeOptions.count > 1 {
                scopePicker
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
    }

    private var scopePicker: some View {
        Picker("Dashboard scope", selection: Binding(get: { scopeProfileID }, set: onScopeChange)) {
            Text("All connected Gulls").tag(String?.none)
            ForEach(scopeOptions) { gull in
                Text(gull.displayName ?? gull.handle).tag(Optional(gull.id))
            }
        }
    }

    private var statistics: some View {
        HStack(alignment: .top, spacing: 12) {
            metric("Counterparts", value: historySummary?.distinctSenders ?? relationships.counterpartCount)
            metric("Conversations", value: historySummary?.distinctThreads ?? relationships.conversationCount)
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
                HStack(spacing: 16) {
                    ForEach(RelationshipView.allCases, id: \.self) { view in
                        Button {
                            relationshipView = view
                        } label: {
                            Text(view.rawValue)
                                .font(.subheadline)
                                .fontWeight(relationshipView == view ? .semibold : .regular)
                                .foregroundStyle(relationshipView == view ? GullsStyle.accent : .secondary)
                                .padding(.vertical, 4)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityAddTraits(relationshipView == view ? .isSelected : [])
                        .help(view == .map ? "Show the relationship map" : "Show connections grouped by Gull")
                    }
                }
                .fixedSize()
                .accessibilityElement(children: .contain)
                .accessibilityLabel("Relationship view")
                .accessibilityValue(relationshipView.rawValue)
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

    private var codexActivity: some View {
        let entries = codexEntries
        return Group {
            if !entries.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Text("Codex").font(.headline)
                        Spacer(minLength: 8)
                        Text(codexSummary)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    ForEach(entries.prefix(4)) { entry in
                        Button { onOpenCodexTask(entry.store, entry.task) } label: {
                            HStack(alignment: .top, spacing: 10) {
                                GullAvatar(handle: entry.store.config.cliEnvironment().agentHandle, size: 28)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(entry.task.request.goal)
                                        .font(.subheadline.weight(.medium))
                                        .lineLimit(2)
                                    Text("\(entry.gullName) · \(codexStatus(entry.task))")
                                        .font(.caption)
                                        .foregroundStyle(entry.task.execution?.status == .needsApproval ? GullsStyle.accent : .secondary)
                                        .lineLimit(1)
                                }
                                Spacer(minLength: 0)
                                Image(systemName: "chevron.right")
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                            }
                            .foregroundStyle(Color.primary)
                            .padding(.vertical, 7)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Codex task: \(entry.task.request.goal), \(codexStatus(entry.task))")
                    }
                    if entries.count > 4 {
                        Text("\(entries.count - 4) more Codex tasks in Settings")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private struct CodexDashboardEntry: Identifiable {
        let store: CodexTaskStore
        let task: CodexTask

        var id: String { "\(task.request.profileID):\(task.id)" }

        @MainActor var gullName: String {
            let configured = store.config.displayName.trimmingCharacters(in: .whitespacesAndNewlines)
            return configured.isEmpty ? store.config.cliEnvironment().agentHandle : configured
        }
    }

    private var codexEntries: [CodexDashboardEntry] {
        codexTasks.flatMap { store in
            store.tasks.compactMap { task in
                task.execution == nil ? nil : CodexDashboardEntry(store: store, task: task)
            }
        }
        .sorted { ($0.task.request.createdAt, $0.id) > ($1.task.request.createdAt, $1.id) }
    }

    private var codexSummary: String {
        let statuses = codexEntries.compactMap { $0.task.execution?.status }
        let active = statuses.filter { $0 == .starting || $0 == .working }.count
        let approval = statuses.filter { $0 == .needsApproval }.count
        let ready = statuses.filter { $0 == .draftReady }.count
        var parts: [String] = []
        if active > 0 { parts.append("\(active) working") }
        if approval > 0 { parts.append("\(approval) needs approval") }
        if ready > 0 { parts.append("\(ready) ready") }
        return parts.joined(separator: " · ")
    }

    private func codexStatus(_ task: CodexTask) -> String {
        switch task.execution?.status {
        case .starting: return "Starting"
        case .working: return "Working"
        case .needsApproval: return "Needs approval"
        case .draftReady: return "Draft ready"
        case .interrupted: return "Stopped"
        case .failed: return "Failed"
        case nil: return "Awaiting draft"
        }
    }

    private var activityChart: some View {
        let chartActivity = historyActivity ?? activity
        return VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Activity").font(.headline)
                Spacer()
                Text("Past 7 days").font(.caption).foregroundStyle(.secondary)
            }
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(chartActivity.reduce(0) { $0 + $1.receivedCount }.formatted())
                    .font(.title3.weight(.medium)).monospacedDigit()
                Text("messages received").font(.caption).foregroundStyle(.secondary)
            }
            Chart(chartActivity) { day in
                BarMark(x: .value("Day", day.date, unit: .day), y: .value("Received", day.receivedCount))
                    .foregroundStyle(GullsStyle.accent.opacity(0.7))
                    .cornerRadius(3)
                    .accessibilityLabel(day.date.formatted(.dateTime.month(.abbreviated).day()))
                    .accessibilityValue("\(day.receivedCount) received")
            }
            .chartYScale(domain: 0...max(1, chartActivity.map(\.receivedCount).max() ?? 0))
            .chartYAxis(.hidden)
            .chartXAxis {
                AxisMarks(values: .stride(by: .day)) { _ in
                    AxisValueLabel(format: .dateTime.weekday(.abbreviated))
                }
            }
            .frame(height: 95)
        }
    }

    private var historyActivity: [DashboardActivityDay]? {
        guard let historySummary else { return nil }
        let calendar = Calendar.current
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.dateFormat = "yyyy-MM-dd"
        return historySummary.dailyReceived.compactMap { day in
            guard let date = formatter.date(from: day.day) else { return nil }
            return DashboardActivityDay(date: calendar.startOfDay(for: date), receivedCount: day.count)
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
    var startedConversations: [GullConversation] = []
    var selectedStartedConversationID: String? = nil
    var onOpenStarted: (GullConversation) -> Void = { _ in }
    var onHistorySearch: (String, String?) -> Void = { _, _ in }
    var historyMatchedDeliveryIDs: (String) -> Set<String> = { _ in [] }
    var isHistorySearchReady: (String, String, String?) -> Bool = { _, _, _ in false }
    var onLoadMore: () -> Void = {}
    var isLoadingMore = false
    var hasMoreHistory = false
    var isHistoryUnavailable = false
    var isHistorySyncIncomplete = false

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.gullsWindowControlInset) private var windowControlInset
    @State private var searchText = ""
    @State private var filter: ConversationFilter = .all
    @State private var searchScrollOffset: CGFloat = 0
    @State private var isSearchExpanded = false
    @State private var searchFocusRequest = 0
    @State private var searchMetadataHeight: CGFloat = 0
    @State private var searchTitleWidth: CGFloat = 0
    @State private var isHistoryNoticePresented = false

    private let searchHeaderTopPadding: CGFloat = 12
    private let searchHeaderBottomPadding: CGFloat = 4

    private var searchCollapseInset: CGFloat { searchHeaderTopPadding + 28 + 8 }

    private var searchPinDistance: CGFloat {
        28 + searchHeaderBottomPadding + searchMetadataHeight + 10
    }
    private var searchDistanceFromTitle: CGFloat {
        if #available(macOS 15.0, *) { return max(searchPinDistance - searchScrollOffset, 0) }
        return 0
    }
    private var isHeaderCondensed: Bool {
        searchDistanceFromTitle <= searchCollapseInset - searchHeaderTopPadding
    }
    private var searchControlsTopInset: CGFloat {
        let scrolledInset = searchHeaderTopPadding + searchDistanceFromTitle
        return isHeaderCondensed && isSearchExpanded
            ? max(scrolledInset, searchCollapseInset)
            : scrolledInset
    }
    private var showsHistoryInfo: Bool {
        (isHeaderCondensed || isHistoryNoticePresented) && historyNotice != nil
    }

    private enum ConversationFilter: String, CaseIterable, Identifiable {
        case all = "All"
        case needsYou = "Needs you"
        case inProgress = "In progress"
        case handled = "Handled"

        var id: String { rawValue }

        var historyStatus: String? {
            switch self {
            case .all: return nil
            case .needsYou: return "delivered"
            case .inProgress: return nil
            case .handled: return nil
            }
        }
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
            let localMatch = [group.title, group.counterpart, group.ownedGullHandle, group.snippet ?? ""]
                .joined(separator: " ")
                .lowercased()
                .contains(query)
            if localMatch { return true }
            guard isHistorySearchReady(group.profileID, query, filter.historyStatus) else { return false }
            let matchedIDs = historyMatchedDeliveryIDs(group.profileID)
            return group.items.contains { matchedIDs.contains($0.id) }
        }
    }

    private var filteredStartedConversations: [GullConversation] {
        guard filter == .all else { return [] }
        let existing = Set(snapshot.allGroups.compactMap { group -> String? in
            guard let threadID = group.threadID else { return nil }
            return "\(group.profileID):\(threadID)"
        })
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return startedConversations.filter { conversation in
            if let threadID = conversation.threadID,
               existing.contains("\(conversation.senderProfileID):\(threadID)") { return false }
            guard query.isEmpty else {
                return [conversation.displayName, conversation.recipientHandle, conversation.senderHandle]
                    .joined(separator: " ").lowercased().contains(query)
            }
            return true
        }
    }

    private var conversationCount: Int {
        filteredGroups.count + filteredStartedConversations.count
    }

    private var historyNotice: String? {
        if isHistoryUnavailable {
            return "History is temporarily unavailable. Showing loaded messages; search results may be incomplete."
        }
        if isHistorySyncIncomplete {
            return "Older history hasn't finished syncing. Search results may be incomplete."
        }
        return nil
    }

    var body: some View {
        Group {
            if #available(macOS 26.0, *), !reduceTransparency {
                content
                    .gullsSafeAreaBar(edge: .top, spacing: 0, style: .minimal) { searchHeader }
                    .gullsScrollEdges()
                    .onAppear { onHistorySearch(searchText, filter.historyStatus) }
            } else {
                content
                    .safeAreaInset(edge: .top, spacing: 0) { searchHeader.background(GullsStyle.canvas) }
                    .gullsScrollEdges()
                    .onAppear { onHistorySearch(searchText, filter.historyStatus) }
            }
        }
        .background {
            Button("Search conversations") { searchFocusRequest += 1 }
                .keyboardShortcut("f", modifiers: .command)
                .hidden()
        }
        .overlay(alignment: .topLeading) { stickySearchControls }
    }

    private var searchHeader: some View {
        HStack(spacing: 8) {
            GullsPageTitle("Messages")
                .font(.title2.weight(.semibold))
                .lineLimit(1)
                .onGeometryChange(for: CGFloat.self) { $0.size.width } action: {
                    searchTitleWidth = $0
                }
            Spacer(minLength: 0)
        }
        .frame(height: 28)
        .frame(maxWidth: compact ? .infinity : 860, alignment: .leading)
        .padding(.horizontal, compact ? 14 : 28)
        .padding(.top, searchHeaderTopPadding)
        .padding(.bottom, searchHeaderBottomPadding)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var searchMetadata: some View {
        HStack(spacing: 8) {
            if let scopeName {
                Text(scopeName)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            Text(conversationCount == 1 ? "1 conversation" : "\(conversationCount) conversations")
                .foregroundStyle(.tertiary)
        }
        .font(.caption)
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: {
            searchMetadataHeight = $0
        }
    }

    private var stickySearchControls: some View {
        GeometryReader { geometry in
            let inset: CGFloat = compact ? 14 : 28
            let rowWidth = max(min(geometry.size.width - inset * 2, compact ? .infinity : 860), 0)
            let infoSpace: CGFloat = showsHistoryInfo ? 38 : 0
            let titleSpace = compact ? 0 : searchTitleWidth + 12
            let expandedWidth = max(min(rowWidth - titleSpace - infoSpace - 38, 260), 56)
            HStack(spacing: 10) {
                GullsStickySearchField(
                    text: searchBinding, isPinned: isHeaderCondensed,
                    focusRequest: searchFocusRequest, expandedWidth: expandedWidth,
                    isExpanded: $isSearchExpanded,
                    accessibilityLabel: "Search conversations", help: "Search conversations (⌘F)"
                )
                filterMenu.gullsGlass(cornerRadius: 14)
                if showsHistoryInfo, let historyNotice {
                    Button { isHistoryNoticePresented = true } label: {
                        Image(systemName: "info.circle")
                            .frame(width: 28, height: 28)
                    }
                    .buttonStyle(.borderless)
                    .gullsGlass(cornerRadius: 14)
                    .accessibilityLabel("Message history status")
                    .help(historyNotice)
                    .popover(isPresented: $isHistoryNoticePresented, arrowEdge: .bottom) {
                        Text(historyNotice)
                            .font(.caption)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(14)
                            .frame(width: 280, alignment: .leading)
                    }
                }
            }
            .frame(width: rowWidth, height: 28)
            .animation(reduceMotion ? nil : .spring(response: 0.4, dampingFraction: 0.8), value: isHeaderCondensed)
            .animation(reduceMotion ? nil : .spring(response: 0.4, dampingFraction: 0.8), value: infoSpace)
            .offset(x: inset, y: windowControlInset + searchControlsTopInset)
            .animation(reduceMotion ? nil : .spring(response: 0.4, dampingFraction: 0.8), value: isSearchExpanded)
        }
    }

    private var searchBinding: Binding<String> {
        Binding(get: { searchText }, set: {
            searchText = $0
            onHistorySearch($0, filter.historyStatus)
        })
    }

    private var filterMenu: some View {
        Menu { filterOptions } label: {
            Label("Filter conversations", systemImage: "line.3.horizontal.decrease")
                .labelStyle(.iconOnly)
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .foregroundStyle(filter == .all ? Color.secondary : GullsStyle.accent)
        .frame(width: 28, height: 28)
        .accessibilityValue(filter.rawValue)
        .help("Filter: \(filter.rawValue)")
    }

    private var filterOptions: some View {
        Picker("Filter", selection: Binding(
            get: { filter },
            set: {
                filter = $0
                onHistorySearch(searchText, $0.historyStatus)
            }
        )) {
            ForEach(ConversationFilter.allCases) { option in
                Text(option.rawValue).tag(option)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if #available(macOS 15.0, *) {
            messageScrollView
                .onScrollGeometryChange(for: CGFloat.self) { geometry in
                    min(max(geometry.contentOffset.y + geometry.contentInsets.top, 0), searchPinDistance)
                } action: { _, offset in
                    searchScrollOffset = offset
                }
        } else {
            messageScrollView
        }
    }

    private var messageScrollView: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                searchMetadata.padding(.bottom, 10)
                Color.clear
                    .frame(height: 28)
                    .padding(.bottom, compact ? 10 : 14)
                    .accessibilityHidden(true)
                if let historyNotice {
                    Text(historyNotice)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.bottom, compact ? 10 : 14)
                }
                conversationRows
            }
            .frame(maxWidth: compact ? .infinity : 860, alignment: .leading)
            .padding(.horizontal, compact ? 14 : 28)
            .padding(.bottom, compact ? 16 : 24)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .gullsHiddenScrollbars()
    }

    @ViewBuilder
    private var conversationRows: some View {
        if filteredGroups.isEmpty && filteredStartedConversations.isEmpty && !hasMoreHistory {
            ContentUnavailableView("No conversations", systemImage: "bubble.left.and.bubble.right")
                .frame(maxWidth: .infinity)
                .padding(.top, 70)
        } else {
            ForEach(filteredStartedConversations) { conversation in
                startedConversationRow(conversation)
            }
            ForEach(filteredGroups) { group in
                conversationRow(group)
            }
            if hasMoreHistory {
                Button(action: onLoadMore) {
                    HStack {
                        if isLoadingMore { ProgressView().controlSize(.small) }
                        Text(isLoadingMore ? "Loading history…" : "Load more history")
                        Spacer()
                    }
                    .font(.caption)
                    .foregroundStyle(GullsStyle.accent)
                    .padding(.vertical, 12)
                    .padding(.horizontal, 10)
                }
                .buttonStyle(.plain)
                .disabled(isLoadingMore)
            }
        }
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
            .padding(.horizontal, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(GullsListRowButtonStyle(isSelected: selectedGroupID == group.id))
        .accessibilityAddTraits(selectedGroupID == group.id ? .isSelected : [])
    }

    private func startedConversationRow(_ conversation: GullConversation) -> some View {
        Button { onOpenStarted(conversation) } label: {
            HStack(alignment: .top, spacing: 12) {
                GullAvatar(handle: conversation.recipientHandle, size: compact ? 26 : 28)
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(conversation.displayName)
                            .font(.subheadline.weight(.semibold))
                            .lineLimit(1)
                        Spacer(minLength: 4)
                        Text("Started")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                    Text("\(conversation.recipientHandle) · via \(conversation.senderHandle)")
                        .font(.caption).foregroundStyle(.secondary)
                        .lineLimit(compact ? 1 : nil)
                    if conversation.threadID == nil {
                        Text("Ready to send")
                            .font(.caption2).foregroundStyle(.tertiary)
                    }
                }
            }
            .foregroundStyle(Color.primary)
            .padding(.vertical, compact ? 8 : 12)
            .padding(.horizontal, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(GullsListRowButtonStyle(isSelected: selectedStartedConversationID == conversation.id))
        .accessibilityAddTraits(selectedStartedConversationID == conversation.id ? .isSelected : [])
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
