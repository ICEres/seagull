import AppKit
import SwiftUI

struct MainWindow: View {
    @Bindable var store: InboxStore
    var workspace: GullsWorkspace? = nil
    var account: CloudAccountStore? = nil
    @Environment(\.openSettings) private var openSettings
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @FocusState private var replyFocused: Bool

    // Notifications may change the selection while a reply is being written.
    // Keep its recipient bound to the delivery captured when composing began.
    private struct ReplyTarget: Identifiable {
        let deliveryID: String
        let profileID: String
        let connectionRevision: String
        let senderDisplay: String

        var id: String { "\(profileID):\(connectionRevision):\(deliveryID)" }
    }

    private enum Destination { case overview, messages, gulls }

    private enum ContentColumns {
        case both, listOnly, detailOnly

        var showsList: Bool { self != .detailOnly }
        var showsDetail: Bool { self != .listOnly }
    }

    private struct LocalReview: Identifiable {
        let profileID: String
        let control: LocalControlStore
        let request: LocalActionRequest
        var id: String { "\(profileID):\(request.id)" }
    }

    @State private var destination = Destination.overview
    @State private var scopeProfileID: String?
    @State private var localReview: LocalReview?
    @State private var replyTarget: ReplyTarget?
    @State private var replyText = ""
    @State private var draftTarget: ReplyTarget?
    @State private var isBusy = false
    @State private var sidebarExpanded = true
    @State private var contentColumns = ContentColumns.both
    @State private var usesCompactLayout = false
    @State private var compactContentColumns = ContentColumns.listOnly
    @State private var sidebarWidth: CGFloat = 218
    @State private var sidebarResizeOrigin: CGFloat?
    @State private var conversationListWidth: CGFloat = 320
    @State private var listResizeOrigin: CGFloat?
    @State private var handledSelectionRevision = 0
    @State private var handledDeliveryID: String?
    @State private var selectedRelationshipID: String?
    @State private var isRefreshingDashboard = false
    @State private var usageLoadingSessionID: UUID?
    @State private var dashboardUsageError: String?

    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.width < 760
            let navigationExpanded = sidebarExpanded && !compact
            let columns = compact ? compactContentColumns : contentColumns
            let navigationWidth = navigationExpanded
                ? min(sidebarWidth, max(190, geometry.size.width - 580)) : 64
            let availableWidth = max(0, geometry.size.width - navigationWidth)
            let splitListWidth = min(conversationListWidth, max(260, availableWidth * 0.44))
            let listWidth = columns == .both ? splitListWidth : availableWidth
            let detailWidth = columns == .both ? availableWidth - splitListWidth : availableWidth

            HStack(spacing: 0) {
                WorkspaceSidebar(
                    compact: !navigationExpanded,
                    overviewSelected: destination == .overview,
                    messagesSelected: destination == .messages,
                    gullsSelected: destination == .gulls,
                    totalAttentionCount: allSnapshot.needsAttention.count,
                    accountName: accountName,
                    onOverview: { navigate(to: .overview) },
                    onMessages: { navigate(to: .messages) },
                    onGulls: { navigate(to: .gulls) }
                )
                .frame(width: navigationWidth)
                .clipped()
                .overlay(alignment: .trailing) {
                    if navigationExpanded { sidebarResizeHandle }
                }
                if destination == .overview {
                    dashboard(compact: compact)
                        .frame(width: availableWidth)
                        .accessibilityElement(children: .contain)
                        .accessibilityLabel("Dashboard")
                } else {
                    listContent
                        .frame(width: listWidth)
                        .frame(width: columns.showsList ? listWidth : 0, alignment: .leading)
                        .clipped()
                        .disabled(!columns.showsList)
                        .allowsHitTesting(columns.showsList)
                        .accessibilityHidden(!columns.showsList)
                        .overlay(alignment: .trailing) {
                            if columns == .both { conversationResizeHandle(width: listWidth) }
                        }
                        .accessibilityElement(children: .contain)
                        .accessibilityLabel(destination == .gulls ? "Gull list" : "Message list")
                    detailContent
                        .frame(width: detailWidth)
                        .frame(width: columns.showsDetail ? detailWidth : 0, alignment: .leading)
                        .clipped()
                        .frame(maxHeight: .infinity)
                        .disabled(!columns.showsDetail)
                        .allowsHitTesting(columns.showsDetail)
                        .accessibilityHidden(!columns.showsDetail)
                        .accessibilityElement(children: .contain)
                        .accessibilityLabel(destination == .gulls ? "Gull overview" : "Conversation detail")
                }
            }
            .onChange(of: compact, initial: true) { _, compact in
                if compact {
                    if contentColumns != .both { compactContentColumns = contentColumns }
                    if replyFocused || draftTarget != nil { compactContentColumns = .detailOnly }
                }
                usesCompactLayout = compact
            }
        }
        .background(GullsStyle.canvas)
        .navigationTitle("Gulls")
        .tint(GullsStyle.accent)
        .toolbarBackground(.hidden, for: .windowToolbar)
        .gullsWindowChrome()
        .toolbar(id: "gulls-main") {
            if #available(macOS 26.0, *) {
                mainToolbar.sharedBackgroundVisibility(.hidden)
            } else {
                mainToolbar
            }
        }
        .frame(minWidth: 380, minHeight: 620)
        .sheet(item: $localReview) { review in
            LocalActionReviewView(control: review.control, request: review.request) {
                localReview = nil
            }
        }
        .safeAreaInset(edge: .bottom) {
            if let error = store.lastError {
                errorBar(error)
            }
        }
        .task(id: workspace == nil ? store.config.connectionRevision : "workspace") {
            guard workspace == nil else { return }
            guard store.config.isConfigured else {
                openSettings()
                return
            }
            await store.loadAgentProfile()
            await store.refresh()
            if store.config.monitoringEnabled { store.startMonitoring() }
        }
        .task(id: account?.sessionID) {
            await refreshDashboardUsage()
        }
        .onChange(of: workspace?.selectionRevision) { _, revision in
            guard let revision, revision != handledSelectionRevision else { return }
            handledSelectionRevision = revision
            showSelectedDelivery()
        }
        .onChange(of: store.selectedDeliveryID) { _, id in
            if workspace == nil, id != nil, id != handledDeliveryID {
                handledDeliveryID = id
                showSelectedDelivery()
            }
        }
        .onChange(of: stores.map(\.config.profileID)) { _, profileIDs in
            if let scopeProfileID, !profileIDs.contains(scopeProfileID) {
                self.scopeProfileID = nil
            }
            if let localReview, !profileIDs.contains(localReview.profileID) {
                self.localReview = nil
            }
        }
        .onChange(of: workspace?.connections.selectedProfileID) { _, profileID in
            if scopeProfileID != nil { scopeProfileID = profileID }
        }
        .onAppear { ensureSelection() }
        .onChange(of: scopeProfileID) { _, _ in ensureSelection() }
        .onChange(of: snapshot.allGroups.flatMap { $0.items.map(\.id) }) { _, _ in
            ensureSelection()
        }
        .onChange(of: visibleContentColumns.showsDetail) { _, visible in
            if !visible { replyFocused = false }
        }
    }

    @ViewBuilder
    private var listContent: some View {
        switch destination {
        case .overview:
            EmptyView()
        case .messages:
            ConversationsView(
                snapshot: snapshot,
                scopeName: scopeName,
                onOpen: openConversation,
                compact: usesCompactLayout || contentColumns == .both,
                selectedGroupID: displayedItem == nil ? nil : selectedGroup?.id
            )
        case .gulls:
            WorkspaceGullsView(
                stores: stores,
                selectedProfileID: scopeProfileID,
                attentionCounts: attentionCounts,
                compact: usesCompactLayout || contentColumns == .both,
                onSelect: selectGull,
                onSettings: { openSettings() }
            )
        }
    }

    @ViewBuilder
    private var detailContent: some View {
        if destination == .gulls {
            dashboard(compact: usesCompactLayout || contentColumns == .both)
        } else if let item = displayedItem {
            detailWithReply(item)
                .gullsScrollEdges()
        } else {
            ContentUnavailableView {
                Label("Select a conversation", systemImage: "bubble.left.and.bubble.right")
            } description: {
                Text("Choose a conversation from the list to review its context and reply.")
            }
        }
    }

    private func dashboard(compact: Bool) -> some View {
        DashboardView(
            snapshot: snapshot,
            relationships: relationshipSnapshot,
            activity: DashboardActivityProjector.makeDays(from: scopedDashboardProfiles),
            scopeOptions: allRelationships.gulls,
            scopeProfileID: scopeProfileID,
            onScopeChange: { scopeProfileID = $0 },
            scopeName: scopeName,
            accountName: account?.isSignedIn == true ? accountName : "You",
            usage: account?.aiUsage,
            usageScopeAgentID: scopedCloudAgentID,
            isSignedIn: account?.isSignedIn == true,
            usageError: dashboardUsageError,
            isRefreshing: isRefreshingDashboard || usageLoadingSessionID != nil || scopedStores.contains { $0.isRefreshing },
            hasConnections: scopedStores.contains { $0.config.isConfigured },
            onRefresh: refreshDashboard,
            onSelectRelationship: selectRelationship,
            selectedRelationshipID: selectedRelationship?.id,
            onCloseRelationship: { selectedRelationshipID = nil },
            onOpen: openConversation,
            onConversations: {
                destination = .messages
                showList()
            },
            onSettings: { openSettings() },
            localControls: scopedLocalControls,
            onReviewLocalAction: { control, request in
                guard let profileID = workspace?.localControls.first(where: { $0.value === control })?.key else { return }
                localReview = LocalReview(profileID: profileID, control: control, request: request)
            },
            compact: compact
        )
    }

    @ViewBuilder
    private func detailWithReply(_ item: InboxItem) -> some View {
        let detail = DeliveryDetailView(
            item: item,
            localGullName: localGullName,
            relatedItems: selectedGroup?.items ?? [],
            onSelectItem: { openDelivery(profileID: store.config.profileID, deliveryID: $0.id) },
            compact: usesCompactLayout
        )
            .id(selectedGroup?.id ?? "\(store.config.profileID):\(item.id)")
            .transition(.opacity)
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.16), value: item.id)
        if #available(macOS 26.0, *), !reduceTransparency {
            detail
                .safeAreaBar(edge: .bottom, spacing: 0) { replySurface }
        } else {
            detail.safeAreaInset(edge: .bottom, spacing: 0) { replySurface }
        }
    }

    // MARK: - Toolbar

    private var visibleContentColumns: ContentColumns {
        usesCompactLayout ? compactContentColumns : contentColumns
    }

    // Native shortcuts complement the inline reply surface; the id-based
    // form preserves the "Customize Toolbar…" sheet.
    @ToolbarContentBuilder
    private var mainToolbar: some CustomizableToolbarContent {
        if !usesCompactLayout {
            ToolbarItem(id: "sidebar", placement: .navigation) {
                Button {
                    withAnimation(reduceMotion ? nil : .smooth(duration: 0.24)) {
                        sidebarExpanded.toggle()
                    }
                } label: {
                    Label(sidebarExpanded ? "Collapse Sidebar" : "Expand Sidebar", systemImage: "sidebar.left")
                }
                .keyboardShortcut("s", modifiers: [.command, .control])
                .help(sidebarExpanded ? "Collapse Sidebar to Icons" : "Expand Sidebar")
            }
        }

        if destination != .overview {
            ToolbarItem(id: "list-visibility", placement: .navigation) {
                Button(action: toggleList) {
                    Label(usesCompactLayout && !visibleContentColumns.showsList ? "Back to List" : visibleContentColumns.showsList ? "Hide List" : "Show List",
                          systemImage: usesCompactLayout && !visibleContentColumns.showsList ? "chevron.left" : "rectangle.leadinghalf.inset.filled")
                }
                .keyboardShortcut("l", modifiers: [.command, .control])
                .help(visibleContentColumns == .listOnly ? "Show details and hide the list" : visibleContentColumns.showsList ? "Hide the middle column" : "Show the middle column")
            }
        }

        if destination != .overview, !usesCompactLayout {
            ToolbarItem(id: "detail-visibility", placement: .primaryAction) {
                Button(action: toggleDetail) {
                    Label(visibleContentColumns.showsDetail ? "Hide Details" : "Show Details", systemImage: "rectangle.trailinghalf.inset.filled")
                }
                .keyboardShortcut("d", modifiers: [.command, .control])
                .help(visibleContentColumns == .detailOnly ? "Show the list and hide details" : visibleContentColumns.showsDetail ? "Hide the right column" : "Show the right column")
            }
        }

        ToolbarItem(id: "reply", placement: .primaryAction) {
            Button {
                showDetail()
                if replyTarget == nil {
                    replyTarget = selectedTarget
                }
                replyFocused = true
            } label: {
                Label("Reply", systemImage: "arrowshape.turn.up.left")
            }
            .disabled(!canActOnSelection)
            .keyboardShortcut("r", modifiers: .command)
            .help("Reply to the selected delivery (⌘R)")
        }
        .defaultCustomization(.hidden)

        ToolbarItem(id: "draft-reply", placement: .primaryAction) {
            Button {
                showDetail()
                draftTarget = selectedTarget
            } label: {
                Label("Draft reply", systemImage: "wand.and.stars")
            }
            .disabled(!canActOnSelection)
            .help("Generate a rule-based draft for the selected delivery")
        }
        .defaultCustomization(.hidden)

        if destination != .overview {
            ToolbarItem(id: "more", placement: .primaryAction) {
                Menu {
                    Button {
                        runOnSelection { source, id in await source.ack(id) }
                    } label: {
                        Label("Acknowledge", systemImage: "checkmark")
                    }
                    Button {
                        runOnSelection { source, id in _ = await source.ignore(id) }
                    } label: {
                        Label("Ignore", systemImage: "nosign")
                    }
                    Divider()
                    Button {
                        runOnSelection { source, id in
                            if let result = await source.writeContextFile(for: id) {
                                NSWorkspace.shared.activateFileViewerSelecting(
                                    [URL(fileURLWithPath: result.contextPath)]
                                )
                            }
                        }
                    } label: {
                        Label("Write context file", systemImage: "doc.text")
                    }
                } label: {
                    Label("More", systemImage: "ellipsis")
                }
                .menuIndicator(.hidden)
                .disabled(!canActOnSelection)
                .help("More message actions")
            }
        }

        ToolbarItem(id: "status", placement: .primaryAction) {
            statusMenu
        }
    }

    // One status item for transport health and monitoring controls.
    private var statusMenu: some View {
        Menu {
            Text(localGullName)
            Text(streamStatusText)
            if let lastRefresh = store.lastRefresh {
                Text("Last checked \(lastRefresh.formatted(date: .omitted, time: .standard))")
            }
            Text("\(snapshot.needsAttention.count) conversations need you")
            Divider()
            Button("Refresh Now") {
                refreshDashboard()
            }
            .keyboardShortcut("r", modifiers: [.command, .shift])
            Toggle("Monitor \(localGullName)", isOn: Binding(
                get: { store.config.monitoringEnabled },
                set: { enabled in
                    if enabled { store.startMonitoring() } else { store.stopMonitoring() }
                }
            ))
            Toggle("Pause Notifications", isOn: $store.notificationsPaused)
            Toggle("Show Message Text in Notifications", isOn: $store.showContentInNotifications)
                .help("Off by default: notification banners are readable on a locked screen.")
        } label: {
            Label("Status", systemImage: statusSymbol)
                .foregroundStyle(statusColor)
        }
        .menuIndicator(.hidden)
        .help(streamStatusText)
    }

    private var statusSymbol: String {
        if store.isRefreshing { return "arrow.triangle.2.circlepath" }
        switch store.streamState {
        case .off: return "circle.fill"
        case .failed: return "bolt.slash.fill"
        default: return "bolt.fill"
        }
    }

    private var statusColor: Color {
        switch store.streamState {
        case .connected: return .green
        case .connecting, .down: return .orange
        case .failed: return .red
        case .off: return store.lastError == nil ? .secondary : .red
        }
    }

    private var streamStatusText: String {
        if !store.config.isConfigured { return "Connect your Gull in Settings" }
        if !store.config.monitoringEnabled { return "Inbox monitoring paused" }
        if store.cli == nil { return "Bundled CLI unavailable; check Settings" }
        switch store.streamState {
        case .connected: return "Connected via stream — new deliveries arrive instantly"
        case .connecting: return "Stream connecting — polling in the meantime"
        case .down: return "Stream down — falling back to polling"
        case .failed(let message): return "Stream disabled (\(message)) — polling only; check Settings"
        case .off: return "Polling every \(Int(max(store.config.pollInterval, 5)))s (no stream URL configured)"
        }
    }

    // MARK: - Helpers

    private func navigate(to destination: Destination) {
        self.destination = destination
        if destination == .gulls {
            let selected = stores.first { $0.config.profileID == store.config.profileID && $0.config.isConfigured }
                ?? stores.first { $0.config.isConfigured }
            scopeProfileID = selected?.config.profileID
            if let scopeProfileID { workspace?.connections.select(profileID: scopeProfileID) }
        } else {
            scopeProfileID = nil
        }
        if destination != .overview { showList() }
    }

    private func selectGull(_ profileID: String) {
        guard stores.contains(where: { $0.config.profileID == profileID }) else { return }
        workspace?.connections.select(profileID: profileID)
        scopeProfileID = profileID
        showDetail()
    }

    private func selectRelationship(_ relationship: DashboardRelationship) {
        selectedRelationshipID = relationship.id
        destination = .overview
    }

    private func refreshDashboard() {
        guard !isRefreshingDashboard else { return }
        let sources = scopedStores
        isRefreshingDashboard = true
        Task {
            defer { isRefreshingDashboard = false }
            for source in sources { await source.refresh() }
            await refreshDashboardUsage()
        }
    }

    private func refreshDashboardUsage() async {
        guard let account, account.isSignedIn else {
            dashboardUsageError = nil
            return
        }
        let generation = account.sessionID
        usageLoadingSessionID = generation
        defer {
            if usageLoadingSessionID == generation { usageLoadingSessionID = nil }
        }
        let loaded = await account.refreshAIUsage()
        guard generation == account.sessionID else { return }
        dashboardUsageError = loaded ? nil : account.aiUsage == nil
            ? "Cloud usage unavailable. Refresh to retry."
            : "Refresh failed. Showing previous cloud usage."
        await account.refreshGulls()
    }

    private func toggleList() {
        guard destination != .overview else { return }
        withAnimation(reduceMotion ? nil : .smooth(duration: 0.24)) {
            if usesCompactLayout {
                compactContentColumns = compactContentColumns == .detailOnly ? .listOnly : .detailOnly
            } else {
                contentColumns = contentColumns == .detailOnly ? .both : .detailOnly
            }
        }
    }

    private func toggleDetail() {
        guard destination != .overview else { return }
        withAnimation(reduceMotion ? nil : .smooth(duration: 0.24)) {
            if usesCompactLayout {
                compactContentColumns = compactContentColumns == .listOnly ? .detailOnly : .listOnly
            } else {
                contentColumns = contentColumns == .listOnly ? .both : .listOnly
            }
        }
    }

    private func showList() {
        guard !visibleContentColumns.showsList else { return }
        withAnimation(reduceMotion ? nil : .smooth(duration: 0.24)) {
            if usesCompactLayout { compactContentColumns = .listOnly }
            else { contentColumns = .both }
        }
    }

    private func showDetail() {
        guard !visibleContentColumns.showsDetail else { return }
        withAnimation(reduceMotion ? nil : .smooth(duration: 0.24)) {
            if usesCompactLayout { compactContentColumns = .detailOnly }
            else { contentColumns = .both }
        }
    }

    private var sidebarResizeHandle: some View {
        Color.clear
            .frame(width: 6)
            .contentShape(Rectangle())
            .onHover { hovering in
                (hovering ? NSCursor.resizeLeftRight : NSCursor.arrow).set()
            }
            .gesture(
                DragGesture(minimumDistance: 1)
                    .onChanged { value in
                        let origin = sidebarResizeOrigin ?? sidebarWidth
                        sidebarResizeOrigin = origin
                        sidebarWidth = min(280, max(190, origin + value.translation.width))
                    }
                    .onEnded { _ in sidebarResizeOrigin = nil }
            )
            .accessibilityLabel("Sidebar width")
            .accessibilityAdjustableAction { direction in
                switch direction {
                case .increment: sidebarWidth = min(280, sidebarWidth + 10)
                case .decrement: sidebarWidth = max(190, sidebarWidth - 10)
                @unknown default: break
                }
            }
    }

    private func conversationResizeHandle(width: CGFloat) -> some View {
        Color.clear
            .frame(width: 6)
            .contentShape(Rectangle())
            .onHover { hovering in
                (hovering ? NSCursor.resizeLeftRight : NSCursor.arrow).set()
            }
            .gesture(
                DragGesture(minimumDistance: 1)
                    .onChanged { value in
                        let origin = listResizeOrigin ?? width
                        listResizeOrigin = origin
                        setContentListWidth(origin + value.translation.width)
                    }
                    .onEnded { _ in listResizeOrigin = nil }
            )
            .accessibilityLabel("Conversation list width")
            .accessibilityAdjustableAction { direction in
                switch direction {
                case .increment: setContentListWidth(width + 10)
                case .decrement: setContentListWidth(width - 10)
                @unknown default: break
                }
            }
    }

    private func setContentListWidth(_ width: CGFloat) {
        conversationListWidth = min(420, max(260, width))
    }

    private var stores: [InboxStore] {
        guard let workspace else { return [store] }
        return workspace.connections.profiles.compactMap { workspace.inboxes[$0.profileID] }
    }

    private var scopedStores: [InboxStore] {
        stores.filter { scopeProfileID == nil || $0.config.profileID == scopeProfileID }
    }

    private var dashboardProfiles: [DashboardProfileInput] {
        stores.filter { $0.config.isConfigured }.map {
            DashboardProfileInput(
                profileID: $0.config.profileID,
                handle: $0.config.agentHandle,
                displayName: firstNonEmpty($0.config.displayName, $0.agent?.displayName),
                items: $0.isCurrent ? $0.items : []
            )
        }
    }

    private var scopedDashboardProfiles: [DashboardProfileInput] {
        dashboardProfiles.filter { scopeProfileID == nil || $0.profileID == scopeProfileID }
    }

    private var allSnapshot: DashboardSnapshot {
        DashboardProjector.makeSnapshot(from: dashboardProfiles)
    }

    private var allRelationships: DashboardRelationshipSnapshot {
        DashboardRelationshipProjector.makeSnapshot(from: dashboardProfiles)
    }

    private var relationshipSnapshot: DashboardRelationshipSnapshot {
        allRelationships.scoped(to: scopeProfileID)
    }

    private var selectedRelationship: DashboardRelationship? {
        relationshipSnapshot.relationships.first { $0.id == selectedRelationshipID }
    }

    private var scopedCloudAgentID: String? {
        guard let scopeProfileID,
              let source = stores.first(where: { $0.config.profileID == scopeProfileID }) else { return nil }
        return account?.ownedGulls.first { $0.handle == source.config.agentHandle }?.agentID
    }

    private var snapshot: DashboardSnapshot {
        guard let scopeProfileID else { return allSnapshot }
        let all = allSnapshot
        return DashboardSnapshot(
            needsAttention: all.needsAttention.filter { $0.profileID == scopeProfileID },
            inProgress: all.inProgress.filter { $0.profileID == scopeProfileID },
            handled: all.handled.filter { $0.profileID == scopeProfileID }
        )
    }

    private var attentionCounts: [String: Int] {
        var counts = Dictionary(grouping: allSnapshot.needsAttention, by: \.profileID).mapValues(\.count)
        for (profileID, control) in workspace?.localControls ?? [:] {
            counts[profileID, default: 0] += control.pendingRequests.count
        }
        return counts
    }

    private var scopedLocalControls: [LocalControlStore] {
        guard let workspace else { return [] }
        return workspace.connections.profiles
            .filter { scopeProfileID == nil || $0.profileID == scopeProfileID }
            .compactMap { workspace.localControls[$0.profileID] }
    }

    private var scopeName: String? {
        guard let scoped = stores.first(where: { $0.config.profileID == scopeProfileID }) else { return nil }
        return firstNonEmpty(scoped.config.displayName, scoped.agent?.displayName, scoped.config.agentHandle)
    }

    private var accountName: String {
        firstNonEmpty(account?.accountLabel) ?? "Your account"
    }

    private var selectedGroup: DashboardConversationGroup? {
        guard let id = store.selectedDeliveryID else { return nil }
        return allSnapshot.allGroups.first {
            $0.profileID == store.config.profileID && $0.items.contains { $0.id == id }
        }
    }

    private var displayedItem: InboxItem? {
        guard let item = store.selectedItem,
              snapshot.allGroups.contains(where: { group in
                  group.profileID == store.config.profileID && group.items.contains { $0.id == item.id }
              }) else { return nil }
        return item
    }

    private var canActOnSelection: Bool {
        destination == .messages && displayedItem != nil && !isBusy && draftTarget == nil
    }

    private func openConversation(_ group: DashboardConversationGroup) {
        openDelivery(profileID: group.profileID, deliveryID: group.primaryItem.id)
    }

    private func openDelivery(profileID: String, deliveryID: String, reveal: Bool = true) {
        if let workspace {
            guard workspace.selectDelivery(profileID: profileID, deliveryID: deliveryID) else { return }
            handledSelectionRevision = workspace.selectionRevision
        } else {
            guard store.config.profileID == profileID, store.isCurrent,
                  store.items.contains(where: { $0.id == deliveryID }) else { return }
            store.selectedDeliveryID = deliveryID
        }
        handledDeliveryID = deliveryID
        if reveal { showSelectedDelivery(profileID: profileID) }
    }

    private func showSelectedDelivery(profileID: String? = nil) {
        destination = .messages
        if scopeProfileID != nil { scopeProfileID = profileID ?? store.config.profileID }
        showDetail()
    }

    private func ensureSelection() {
        guard destination != .gulls, displayedItem == nil else { return }
        let group = snapshot.allGroups.first { $0.profileID == store.config.profileID }
            ?? snapshot.allGroups.first
        if let group {
            openDelivery(profileID: group.profileID, deliveryID: group.primaryItem.id, reveal: false)
        }
    }

    private func source(for target: ReplyTarget) -> InboxStore? {
        let source: InboxStore?
        if let workspace {
            guard workspace.connections.profiles.contains(where: { $0.profileID == target.profileID }) else { return nil }
            source = workspace.inboxes[target.profileID]
        } else {
            source = store.config.profileID == target.profileID ? store : nil
        }
        guard let source, source.isCurrent,
              source.config.connectionRevision == target.connectionRevision else { return nil }
        return source
    }

    private func runOnSelection(_ action: @escaping (InboxStore, String) async -> Void) {
        guard canActOnSelection, let target = selectedTarget, let source = source(for: target) else { return }
        isBusy = true
        Task {
            if source.config.connectionRevision == target.connectionRevision {
                await action(source, target.deliveryID)
            }
            isBusy = false
        }
    }

    private var localGullName: String {
        firstNonEmpty(store.config.displayName, store.agent?.displayName, store.agent?.handle, store.config.agentHandle) ?? "your Gull"
    }

    private var selectedTarget: ReplyTarget? {
        displayedItem.map {
            ReplyTarget(
                deliveryID: $0.id,
                profileID: store.config.profileID,
                connectionRevision: store.config.connectionRevision,
                senderDisplay: $0.senderDisplay
            )
        }
    }

    @ViewBuilder
    private var replySurface: some View {
        VStack(spacing: 0) {
            if let target = draftTarget {
                if let source = source(for: target) {
                    DraftReplyView(store: source, deliveryID: target.deliveryID, recipient: target.senderDisplay) {
                        draftTarget = nil
                    }
                    .id(target.id)
                    .containerRelativeFrame(.vertical) { height, _ in
                        min(380, height * 0.55)
                    }
                    .transition(.opacity)
                } else {
                    HStack {
                        Text("This Gull’s connection changed. Generate a new draft from its current inbox.")
                            .font(.callout)
                        Spacer()
                        Button("Close") { draftTarget = nil }
                    }
                    .padding(16)
                }
            } else if let target = replyTarget ?? selectedTarget {
                replyComposer(target)
                    .transition(.opacity)
            }
        }
        .gullsGlass(cornerRadius: 24)
        .overlay {
            RoundedRectangle(cornerRadius: 24)
                .strokeBorder(
                    Color.primary.opacity(colorScheme == .dark ? 0.18 : 0.12),
                    lineWidth: 0.75
                )
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
        .padding(.horizontal, 18)
        .padding(.top, 8)
        .padding(.bottom, 16)
        .animation(reduceMotion ? nil : .smooth(duration: 0.24), value: draftTarget?.id)
        .animation(reduceMotion ? nil : .smooth(duration: 0.2), value: replyTarget?.id)
    }

    private func replyComposer(_ target: ReplyTarget) -> some View {
        let available = source(for: target) != nil
        let canSend = available && !isBusy && !replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return VStack(alignment: .leading, spacing: 10) {
            if target.id != selectedTarget?.id {
                Button {
                    openDelivery(profileID: target.profileID, deliveryID: target.deliveryID)
                } label: {
                    Label("Reply to \(target.senderDisplay) via \(targetGullName(target))", systemImage: "arrow.uturn.backward")
                        .font(.caption.weight(.medium))
                        .lineLimit(1)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
                .disabled(!available)
                .accessibilityLabel("View message from \(target.senderDisplay)")
                .help("Replying to \(target.senderDisplay). Click to view the message.")
            }
            TextEditor(text: Binding(
                get: { replyText },
                set: { text in
                    if replyTarget == nil { replyTarget = target }
                    replyText = text
                }
            ))
                .font(.body)
                .scrollContentBackground(.hidden)
                .scrollIndicators(.never)
                .frame(height: 48)
                .focused($replyFocused)
                .disabled(isBusy)
                .overlay(alignment: .topLeading) {
                    if replyText.isEmpty {
                        Text("Message \(target.senderDisplay)…")
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                            .padding(.leading, 5)
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                    }
                }
                .accessibilityLabel("Reply to \(target.senderDisplay)")
            if !available {
                Text("This Gull’s connection changed. Copy your reply before clearing it.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 10) {
                Button {
                    draftTarget = target
                } label: {
                    Label("Draft reply", systemImage: "wand.and.stars")
                        .labelStyle(.iconOnly)
                        .font(.system(size: 17))
                        .frame(width: 32, height: 32)
                        .contentShape(Circle())
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
                .disabled(isBusy || !available)
                .help("Draft a reply using this Gull’s rules")
                if replyTarget != nil {
                    Button {
                        replyText = ""
                        replyTarget = nil
                    } label: {
                        Label(replyText.isEmpty ? "Cancel reply" : "Clear reply", systemImage: "xmark")
                            .labelStyle(.iconOnly)
                            .frame(width: 32, height: 32)
                            .contentShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                    .disabled(isBusy)
                    .help(replyText.isEmpty ? "Cancel reply" : "Clear reply")
                }
                Spacer(minLength: 0)
                Button {
                    sendReply(to: target)
                } label: {
                    Group {
                        if isBusy {
                            ProgressView().controlSize(.small).tint(GullsStyle.canvas)
                        } else {
                            Image(systemName: "arrow.up")
                                .font(.system(size: 17, weight: .semibold))
                        }
                    }
                    .frame(width: 36, height: 36)
                    .foregroundStyle(colorScheme == .dark ? Color.black : Color.white)
                    .background(colorScheme == .dark ? Color.white : Color.black, in: Circle())
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(!canSend)
                .opacity(canSend || isBusy ? 1 : 0.35)
                .accessibilityLabel(isBusy ? "Sending reply" : "Send reply")
                .help("Send reply (⌘↵)")
            }
        }
        .padding(14)
    }

    private func sendReply(to target: ReplyTarget) {
        let content = replyText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !isBusy, !content.isEmpty, let source = source(for: target) else { return }
        // Capture before awaiting: neither a refresh nor a notification can
        // redirect this send to the newly selected delivery.
        replyTarget = target
        isBusy = true
        Task {
            guard source.config.connectionRevision == target.connectionRevision else {
                isBusy = false
                return
            }
            if await source.reply(to: target.deliveryID, content: content) != nil {
                replyText = ""
                replyTarget = nil
            }
            isBusy = false
        }
    }

    private func targetGullName(_ target: ReplyTarget) -> String {
        guard let source = source(for: target) else { return "the original Gull" }
        return firstNonEmpty(source.config.displayName, source.agent?.displayName, source.config.agentHandle) ?? "your Gull"
    }

    private func errorBar(_ message: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.yellow)
            Text(message)
                .font(.callout)
                .textSelection(.enabled)
                .lineLimit(2)
            Spacer()
            Button("Settings…") { openSettings() }
                .controlSize(.small)
            Button {
                store.lastError = nil
            } label: {
                Label("Dismiss error", systemImage: "xmark")
                    .labelStyle(.iconOnly)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(GullsStyle.canvas)
    }
}
