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
    private let windowControlHeight: CGFloat = 48

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

    private struct CodexLaunch: Identifiable {
        let id = UUID()
        let tasks: CodexTaskStore
        let inbox: InboxStore
        let item: InboxItem
    }

    private struct CodexDraft {
        let task: CodexTask
        let tasks: CodexTaskStore
        let target: ReplyTarget
    }

    @State private var destination = Destination.overview
    // The app has one workspace window; retain its explicit scope across launches.
    @AppStorage("workspace.scopeProfileID") private var storedScopeProfileID: String?
    @State private var localReview: LocalReview?
    @State private var codexLaunch: CodexLaunch?
    @State private var pendingCodexDraft: CodexDraft?
    @State private var activeCodexDraft: CodexDraft?
    @State private var pendingCodexSendConfirmation: CodexDraft?
    @State private var codexError: String?
    @State private var replyTarget: ReplyTarget?
    @State private var replyText = ""
    @State private var draftTarget: ReplyTarget?
    @State private var replySurfaceHeight: CGFloat = 0
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
    @State private var directory: GullDirectoryStore
    @State private var conversations: GullConversationStore
    @State private var selectedDirectoryHandle: String?
    @State private var directoryFallbackName: String?
    @State private var selectedStartedConversationID: String?
    @State private var isAddingGull = false
    @State private var directoryError: String?
    @State private var statusIssue: String?
    @State private var dashboardProjectionCache = DashboardProjectionCache()

    init(store: InboxStore, workspace: GullsWorkspace? = nil, account: CloudAccountStore? = nil,
         directory: GullDirectoryStore? = nil, conversations: GullConversationStore? = nil) {
        self.store = store
        self.workspace = workspace
        self.account = account
        _directory = State(initialValue: directory ?? GullDirectoryStore())
        _conversations = State(initialValue: conversations ?? GullConversationStore(cli: store.cli))
    }

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
                    attentionCount: snapshot.needsAttention.count,
                    scopeName: scopeName,
                    accountName: accountName,
                    onOverview: { navigate(to: .overview) },
                    onMessages: { navigate(to: .messages) },
                    onGulls: { navigate(to: .gulls) }
                )
                .padding(.top, extendsContentUnderControls ? windowControlHeight : 0)
                .frame(width: navigationWidth)
                .clipped()
                .overlay(alignment: .trailing) {
                    if navigationExpanded { sidebarResizeHandle }
                }
                if destination == .overview {
                    dashboard(compact: compact)
                        .frame(width: availableWidth)
                        .clipped()
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
                    detailContent(availableHeight: geometry.size.height)
                        .frame(width: detailWidth)
                        .frame(width: columns.showsDetail ? detailWidth : 0, alignment: .leading)
                        .clipped()
                        .frame(maxHeight: .infinity)
                        .disabled(!columns.showsDetail)
                        .allowsHitTesting(columns.showsDetail)
                        .accessibilityHidden(!columns.showsDetail)
                        .accessibilityElement(children: .contain)
                        .accessibilityLabel(destination == .gulls ? "Gull profile" : "Conversation detail")
                }
            }
            .padding(.top, extendsContentUnderControls ? 0 : windowControlHeight)
            .environment(\.gullsWindowControlInset, extendsContentUnderControls ? windowControlHeight : 0)
            .overlay(alignment: .top) {
                windowControls
            }
            .onChange(of: compact, initial: true) { _, compact in
                if compact {
                    if contentColumns != .both { compactContentColumns = contentColumns }
                    if replyFocused || draftTarget != nil { compactContentColumns = .detailOnly }
                }
                usesCompactLayout = compact
            }
        }
        .ignoresSafeArea(.container, edges: .top)
        .gullsWindowBackground()
        .tint(GullsStyle.accent)
        .gullsWindowChrome(hidesTitleBar: true)
        .background {
            Button("Reply", action: beginReply)
                .keyboardShortcut("r", modifiers: .command)
                .disabled(!canActOnSelection)
                .hidden()
        }
        .frame(minWidth: 380, minHeight: 620)
        .sheet(item: $localReview) { review in
            LocalActionReviewView(control: review.control, request: review.request) {
                localReview = nil
            }
        }
        .sheet(item: $codexLaunch) { launch in
            if let cli = launch.inbox.cli {
                CodexTaskSetupView(tasks: launch.tasks, cli: cli, inbox: launch.inbox, item: launch.item)
            }
        }
        .confirmationDialog("Replace your unsent reply?", isPresented: Binding(
            get: { pendingCodexDraft != nil },
            set: { if !$0 { pendingCodexDraft = nil } }
        ), titleVisibility: .visible, presenting: pendingCodexDraft) { draft in
            Button("Replace with Codex draft") { applyCodexDraft(draft) }
            Button("Cancel", role: .cancel) { pendingCodexDraft = nil }
        } message: { _ in
            Text("Your current reply will be replaced. The Codex draft will still need to be sent by you.")
        }
        .alert(pendingCodexSendConfirmation == nil ? "Couldn’t complete the Codex action" : "Reply sent; Codex status not updated", isPresented: Binding(
            get: { codexError != nil }, set: { if !$0 { codexError = nil } }
        )) {
            if pendingCodexSendConfirmation != nil {
                Button("Retry status update") { retryCodexSendConfirmation() }
            }
            Button("OK", role: .cancel) { codexError = nil }
        } message: {
            if pendingCodexSendConfirmation != nil {
                Text(
                    "The reply was sent successfully. "
                    + (codexError ?? "The local Codex draft status could not be updated.")
                    + " Retrying only updates local status; it will not send the reply again."
                )
            } else {
                Text(codexError ?? "")
            }
        }
        .sheet(isPresented: $isAddingGull) {
            let generation = account?.sessionID
            AddGullView(messageAPIURL: messageAPIURL) { profile in
                guard generation == account?.sessionID, let userID = directoryUserID else {
                    throw SavedGullError.invalidScope
                }
                if !ownedGulls.contains(where: { $0.handle == profile.handle }) {
                    try directory.save(profile, userID: userID, websiteURL: directoryWebsiteURL)
                }
                selectDirectoryGull(profile.handle)
            }
        }
        .alert("Could not open conversation", isPresented: Binding(
            get: { directoryError != nil }, set: { if !$0 { directoryError = nil } }
        )) {
            Button("OK") { directoryError = nil }
        } message: {
            Text(directoryError ?? "")
        }
        .alert(actionFailure?.title ?? "Couldn’t complete the action", isPresented: Binding(
            get: { actionFailure != nil },
            set: { if !$0 { dismissActionFailure() } }
        ), presenting: actionFailure) { _ in
            Button("Open Settings") { openSettings() }
            Button("OK", role: .cancel) {}
        } message: { failure in
            Text(failure.message)
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
        .onChange(of: directoryScope, initial: true) { _, scope in
            conversations.activate(scope: scope)
            selectedStartedConversationID = nil
            selectedDirectoryHandle = nil
            directoryFallbackName = nil
            isAddingGull = false
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
            if let storedScopeProfileID, storedScopeProfileID != "all", !profileIDs.contains(storedScopeProfileID) {
                self.storedScopeProfileID = nil
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
            conversationsList
        case .gulls:
            WorkspaceGullsView(
                ownedGulls: ownedGulls,
                savedGulls: savedGulls,
                selectedHandle: selectedDirectoryHandle,
                compact: usesCompactLayout || contentColumns == .both,
                canSave: directoryUserID != nil,
                onSelect: { selectDirectoryGull($0) },
                onAdd: { isAddingGull = true },
                onSettings: { openSettings() }
            )
        }
    }

    private var conversationsList: some View {
        ConversationsView(
            snapshot: snapshot,
            scopeName: scopeName,
            onOpen: openConversation,
            compact: usesCompactLayout || contentColumns == .both,
            selectedGroupID: selectedMessageGroupID,
            startedConversations: visibleStartedConversations,
            selectedStartedConversationID: selectedStartedConversationID,
            onOpenStarted: openStartedConversation,
            onHistorySearch: { query, status in
                for source in scopedStores {
                    source.history.search(query: query, status: status)
                }
            },
            historyMatchedDeliveryIDs: { profileID in
                scopedStores.first(where: { $0.config.profileID == profileID })
                    .map { Set($0.history.items.map(\.id)) } ?? []
            },
            isHistorySearchReady: { profileID, query, status in
                scopedStores.first(where: { $0.config.profileID == profileID })?
                    .history.hasLoaded(query: query, status: status) ?? false
            },
            onLoadMore: loadMoreHistory,
            isLoadingMore: scopedStores.contains { $0.history.isLoading },
            hasMoreHistory: scopedStores.contains { $0.history.nextCursor != nil },
            isHistoryUnavailable: scopedStores.contains {
                $0.config.isConfigured && $0.history.lastError != nil
            },
            isHistorySyncIncomplete: scopedStores.contains {
                $0.config.isConfigured && $0.history.total != nil && !$0.history.syncComplete
            }
        )
    }

    @ViewBuilder
    private func detailContent(availableHeight: CGFloat) -> some View {
        if destination == .gulls {
            if let handle = selectedDirectoryHandle {
                gullProfile(handle)
            } else {
                ContentUnavailableView {
                    Label("Select a Gull", systemImage: "rectangle.and.text.magnifyingglass")
                } description: {
                    Text("Choose one of your Gulls or a saved Gull to see its profile and conversations.")
                }
            }
        } else if let conversation = selectedStartedConversation {
            GullConversationView(store: conversations, conversationID: conversation.id, senders: conversationSenders) {
                openGullProfile(handle: conversation.recipientHandle, name: conversation.recipientName)
            }
            .id("\(directoryScope ?? ""): \(conversation.id)")
        } else if let item = displayedItem {
            detailWithReply(item, availableHeight: availableHeight)
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
            accountName: account?.hasWorkspace == true ? accountName : "You",
            usage: account?.aiUsage,
            usageScopeAgentID: scopedCloudAgentID,
            isSignedIn: account?.hasWorkspace == true,
            usageError: dashboardUsageError,
            historySummary: MessageHistorySummary.aggregate(scopedStores.compactMap { $0.history.summary }),
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
            codexTasks: scopedStores.compactMap { workspace?.codexTasks[$0.config.profileID] },
            onOpenCodexTask: { tasks, task in
                if let deliveryID = task.request.deliveryID {
                    openDelivery(profileID: task.request.profileID, deliveryID: deliveryID)
                } else {
                    do {
                        try tasks.open(task)
                    } catch {
                        codexError = error.localizedDescription
                    }
                }
            },
            compact: compact
        )
    }

    @ViewBuilder
    private func detailWithReply(_ item: InboxItem, availableHeight: CGFloat) -> some View {
        let tasks = workspace?.codexTasks[store.config.profileID]
        let task = tasks?.latestTask(for: item.id)
        let displayName = senderDisplay(for: item)
        let target = ReplyTarget(deliveryID: item.id, profileID: store.config.profileID,
                                 connectionRevision: store.config.connectionRevision, senderDisplay: displayName)
        let detail = DeliveryDetailView(
            item: item,
            localGullName: localGullName,
            relatedItems: selectedGroup?.items ?? [],
            onSelectItem: { openDelivery(profileID: store.config.profileID, deliveryID: $0.id) },
            onOpenProfile: { handle in openGullProfile(handle: handle, name: displayName) },
            senderProfileHandle: profileHandle(for: item),
            onOpenCodex: tasks?.config.codexEnabled == true && store.cli != nil ? { beginCodexTask() } : nil,
            codexTask: task,
            onUseCodexDraft: task?.result != nil ? {
                if let tasks, let task { useCodexDraft(CodexDraft(task: task, tasks: tasks, target: target)) }
            } : nil,
            onReopenCodexTask: tasks?.config.codexEnabled == true ? {
                if let tasks, let task {
                    do { try tasks.open(task) } catch { codexError = error.localizedDescription }
                }
            } : nil,
            onContinueCodex: tasks != nil && task != nil ? { followUp in
                if let tasks, let task {
                    runCodexTask(task, target: target, in: tasks, followUp: followUp)
                }
            } : nil,
            onStopCodex: tasks != nil && task != nil ? {
                if let tasks, let task,
                   let current = currentCodexTask(task, target: target, in: tasks) {
                    Task { await tasks.stop(current) }
                }
            } : nil,
            onApproveCodex: tasks != nil && task != nil ? {
                if let tasks, let task,
                   let current = currentCodexTask(task, target: target, in: tasks) {
                    if let control = tasks.localControl, let approvalID = current.execution?.approvalID,
                       let request = control.pendingRequests.first(where: { $0.id == approvalID }) {
                        localReview = LocalReview(profileID: target.profileID, control: control, request: request)
                    }
                }
            } : nil,
            onDeclineCodex: tasks != nil && task != nil ? {
                if let tasks, let task,
                   let current = currentCodexTask(task, target: target, in: tasks) {
                    tasks.decline(current)
                }
            } : nil,
            onCheckStatusCodex: tasks != nil && task?.execution?.status == .uncertain ? {
                guard let tasks, let task,
                      let current = currentCodexTask(task, target: target, in: tasks) else {
                    codexError = "This Codex task is no longer attached to the current message. Open the message again."
                    return
                }
                Task {
                    do { try await tasks.checkStatus(current) }
                    catch { codexError = error.localizedDescription }
                }
            } : nil,
            onApproveReply: tasks != nil && task != nil ? {
                guard let tasks, let task,
                      let current = currentCodexTask(task, target: target, in: tasks) else { return }
                Task {
                    do { try await tasks.approveReply(current) }
                    catch { codexError = error.localizedDescription }
                }
            } : nil,
            onCheckReplyStatus: tasks != nil && task != nil ? {
                guard let tasks, let task,
                      let current = currentCodexTask(task, target: target, in: tasks) else { return }
                Task {
                    do { try await tasks.checkReplyStatus(current) }
                    catch { codexError = error.localizedDescription }
                }
            } : nil,
            onTakeOverReply: tasks != nil && task != nil ? {
                guard let tasks, let task,
                      let current = currentCodexTask(task, target: target, in: tasks) else { return }
                Task {
                    do {
                        let content = try await tasks.takeOverReply(current)
                        await MainActor.run {
                            guard replyTarget == nil || replyTarget?.id == target.id else {
                                codexError = "The current reply belongs to another message; the Gull reply was taken over without replacing it."
                                return
                            }
                            if replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                               let content {
                                replyText = content
                            }
                            replyTarget = target
                            replyFocused = true
                        }
                    } catch { codexError = error.localizedDescription }
                }
            } : nil,
            bottomContentInset: replySurfaceHeight,
            compact: usesCompactLayout
        )
            .id(selectedGroup?.id ?? "\(store.config.profileID):\(item.id)")
            .transition(.opacity)
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.16), value: item.id)
            .overlay(alignment: .bottom) {
                replySurface(availableHeight: availableHeight)
                    .onGeometryChange(for: CGFloat.self) { geometry in
                        geometry.size.height
                    } action: { height in
                        if abs(replySurfaceHeight - height) > 0.5 {
                            replySurfaceHeight = height
                        }
                    }
            }
        if #available(macOS 26.0, *) {
            detail
                .scrollEdgeEffectHidden(true, for: .bottom)
        } else {
            detail
        }
    }

    // MARK: - Window controls

    private var visibleContentColumns: ContentColumns {
        usesCompactLayout ? compactContentColumns : contentColumns
    }

    private var extendsContentUnderControls: Bool {
        if #available(macOS 26.0, *) { return !reduceTransparency }
        return false
    }

    @ViewBuilder
    private var windowControls: some View {
        if #available(macOS 26.0, *) {
            GlassEffectContainer(spacing: 8) {
                windowControlRow
                    .buttonStyle(.glass)
            }
        } else {
            windowControlRow
                .buttonStyle(.bordered)
        }
    }

    private var windowControlRow: some View {
        HStack(spacing: 8) {
            navigationControls
            Spacer(minLength: 16)
            if destination != .overview, !usesCompactLayout {
                Button(action: toggleDetail) {
                    Label(visibleContentColumns.showsDetail ? "Hide Details" : "Show Details", systemImage: "rectangle.trailinghalf.inset.filled")
                }
                .keyboardShortcut("d", modifiers: [.command, .control])
                .help(visibleContentColumns == .detailOnly ? "Show the list and hide details" : visibleContentColumns.showsDetail ? "Hide the right column" : "Show the right column")
            }
            if destination == .messages, selectedStartedConversationID == nil {
                messageActions
            }
            statusMenu
        }
        .labelStyle(.iconOnly)
        .buttonBorderShape(.circle)
        .controlSize(.large)
        .tint(nil)
        .padding(.leading, 88)
        .padding(.trailing, 12)
        .frame(height: windowControlHeight)
    }

    @ViewBuilder
    private var navigationControls: some View {
        if !usesCompactLayout {
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

        if destination != .overview {
            Button(action: toggleList) {
                Label(usesCompactLayout && !visibleContentColumns.showsList ? "Back to List" : visibleContentColumns.showsList ? "Hide List" : "Show List",
                      systemImage: usesCompactLayout && !visibleContentColumns.showsList ? "chevron.left" : "rectangle.leadinghalf.inset.filled")
            }
            .keyboardShortcut("l", modifiers: [.command, .control])
            .help(visibleContentColumns == .listOnly ? "Show details and hide the list" : visibleContentColumns.showsList ? "Hide the middle column" : "Show the middle column")
        }
    }

    private var messageActions: some View {
        Menu {
            Button(action: beginReply) {
                Label("Reply", systemImage: "arrowshape.turn.up.left")
            }
            Button {
                showDetail()
                draftTarget = selectedTarget
            } label: {
                Label { Text("Draft reply") } icon: { GullsAIIcon() }
            }
            if workspace?.codexTasks[store.config.profileID]?.config.codexEnabled == true {
                Button(action: beginCodexTask) {
                    Label { Text("Let \(localGullName) handle this") } icon: { GullsAIIcon() }
                }
                .disabled(store.cli == nil)
            }
            Divider()
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
        .menuStyle(.borderlessButton)
        .buttonStyle(.borderless)
        .menuIndicator(.hidden)
        .frame(width: 26, height: 26)
        .gullsGlass(cornerRadius: 13)
        .disabled(!canActOnSelection)
        .accessibilityLabel("More")
        .help("More message actions")
    }

    private func beginReply() {
        showDetail()
        guard let target = replyTarget ?? selectedTarget else { return }
        Task { @MainActor in
            do {
                if let tasks = workspace?.codexTasks[target.profileID] {
                    try await tasks.prepareOwnerDecision(deliveryID: target.deliveryID)
                }
                guard source(for: target) != nil else { return }
                replyTarget = target
                replyFocused = true
            } catch { codexError = error.localizedDescription }
        }
    }

    // One status item for transport health and monitoring controls.
    private var statusMenu: some View {
        Menu {
            Text(localGullName)
            Text(streamStatusText)
            if let error = store.lastError {
                Button("Show Issue…") { statusIssue = error }
            }
            if store.runtimeManaged { Text("Local AI worker: Not configured") }
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
        .menuStyle(.borderlessButton)
        .buttonStyle(.borderless)
        .menuIndicator(.hidden)
        .frame(width: 26, height: 26)
        .gullsGlass(cornerRadius: 13)
        .help(store.lastError == nil ? streamStatusText : "\(localGullName) needs attention. Click for details.")
        .accessibilityLabel(store.lastError == nil ? "Status" : "Status, needs attention")
        .alert("\(localGullName) needs attention", isPresented: Binding(
            get: { statusIssue != nil }, set: { if !$0 { statusIssue = nil } }
        ), presenting: statusIssue) { _ in
            if store.runtimeManaged, ["unavailable", "reconnecting"].contains(store.runtimeStatus) {
                Button("Retry Connection") {
                    let source = store
                    Task { await source.refresh() }
                }
            }
            Button("Open Settings") { openSettings() }
            Button("OK", role: .cancel) {}
        } message: { issue in
            Text(issue)
        }
    }

    private var statusSymbol: String {
        if store.isRefreshing { return "arrow.triangle.2.circlepath" }
        if store.lastError != nil { return "exclamationmark.circle" }
        if store.runtimeManaged {
            switch store.runtimeStatus {
            case "connected": return "circle.fill"
            case "authorization_required", "unavailable": return "exclamationmark.circle"
            case "paused", "stopped": return "pause.circle"
            default: return "arrow.triangle.2.circlepath"
            }
        }
        switch store.streamState {
        case .off: return "circle.fill"
        case .failed: return "bolt.slash.fill"
        default: return "bolt.fill"
        }
    }

    private var statusColor: Color {
        if store.lastError != nil { return .orange }
        if store.runtimeManaged {
            guard store.monitoringEnabled else { return .secondary }
            switch store.runtimeStatus {
            case "connected": return .green
            case "connecting", "reconnecting": return .orange
            case "authorization_required", "unavailable": return .red
            default: return .secondary
            }
        }
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
        if store.runtimeManaged {
            return store.runtimeStatus == "connected"
                ? "Monitoring on this Mac · checking every \(Int(max(store.config.pollInterval, 5)))s"
                : store.monitoringStatusText
        }
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
        if destination == .gulls, selectedDirectoryHandle == nil {
            selectedDirectoryHandle = ownedGulls.first?.handle ?? savedGulls.first?.handle
        }
        if destination != .overview { showList() }
    }

    private var scopeProfileID: String? {
        get {
            if storedScopeProfileID == "all" { return nil }
            if let storedScopeProfileID, stores.contains(where: { $0.config.profileID == storedScopeProfileID }) {
                return storedScopeProfileID
            }
            return workspace?.connections.preferredInboxProfileID
                ?? (store.config.isConfigured ? store.config.profileID : nil)
        }
        nonmutating set { storedScopeProfileID = newValue ?? "all" }
    }

    private func selectDirectoryGull(_ handle: String) {
        guard let canonical = SavedGull.canonicalHandle(handle) else { return }
        selectedDirectoryHandle = canonical
        directoryFallbackName = nil
        if let profileID = ownedGulls.first(where: { $0.handle == canonical })?.profileID {
            workspace?.connections.select(profileID: profileID)
        }
        showDetail()
    }

    private func openGullProfile(handle: String, name: String?) {
        guard let canonical = SavedGull.canonicalHandle(handle) else { return }
        destination = .gulls
        selectDirectoryGull(canonical)
        directoryFallbackName = name == handle ? nil : name
    }

    private func openStartedConversation(_ conversation: GullConversation) {
        guard visibleStartedConversations.contains(where: { $0.id == conversation.id }) else { return }
        if scopeProfileID != nil { scopeProfileID = conversation.senderProfileID }
        selectedStartedConversationID = conversation.id
        destination = .messages
        showDetail()
    }

    private func startConversation(to handle: String, name: String?, agentID: String?, sender: GullConversationSender) {
        guard let scope = directoryScope,
              conversationSenders.contains(where: { $0 == sender }) else { return }
        do {
            let conversation = try conversations.start(recipientHandle: handle, recipientName: name,
                                                       recipientAgentID: agentID, sender: sender, scope: scope)
            openStartedConversation(conversation)
        } catch { directoryError = error.localizedDescription }
    }

    private func gullProfile(_ handle: String) -> some View {
        let owned = ownedGulls.first { $0.handle == handle }
        let agentID = savedGulls.first { $0.handle == handle }?.agentID
        let groups = owned.map { owned in
            allSnapshot.allGroups.filter { $0.profileID == owned.profileID }
        } ?? allRelationships.relationships.filter { relationship in
            relationship.counterpartHandle.flatMap(SavedGull.canonicalHandle) == handle
                || agentID.map { relationship.counterpartID == "agent:\($0)" } == true
        }.flatMap(\.groups).sorted { ($0.updatedAt ?? .distantPast) > ($1.updatedAt ?? .distantPast) }
        let started = visibleStartedConversations.filter {
            owned == nil ? $0.recipientHandle == handle : $0.senderHandle == handle
        }

        return GullProfileView(
            handle: handle, owned: owned, fallbackName: directoryFallbackName,
            directory: directory, userID: directoryUserID, websiteURL: directoryWebsiteURL,
            messageAPIURL: messageAPIURL, groups: groups, startedConversations: started,
            senders: conversationSenders, compact: usesCompactLayout || contentColumns == .both,
            onOpen: openConversation, onOpenStarted: openStartedConversation,
            onStart: { sender, name, agentID in
                startConversation(to: handle, name: name, agentID: agentID, sender: sender)
            },
            onMessages: {
                if let profileID = owned?.profileID { scopeProfileID = profileID }
                selectedStartedConversationID = nil
                destination = .messages
                showList()
            },
            onSettings: { openSettings() }
        )
        .id("\(account?.sessionID.uuidString ?? ""): \(handle)")
    }

    private func profileHandle(for item: InboxItem) -> String? {
        if let handle = item.message?.senderHandle.flatMap(SavedGull.canonicalHandle) { return handle }
        guard let agentID = firstNonEmpty(item.message?.senderAgentId, item.delivery.senderAgentId) else { return nil }
        if let saved = savedGulls.first(where: { $0.agentID == agentID }) { return saved.handle }
        if let handle = account?.ownedGulls.first(where: { $0.agentID == agentID })?.handle {
            return SavedGull.canonicalHandle(handle)
        }
        return allRelationships.relationships.first {
            $0.counterpartID == "agent:\(agentID)" && $0.counterpartHandle != nil
        }?.counterpartHandle.flatMap(SavedGull.canonicalHandle) ?? SavedGull.canonicalHandle(agentID)
    }

    private func senderDisplay(for item: InboxItem, savedGulls: [SavedGull]? = nil) -> String {
        let agentID = firstNonEmpty(item.message?.senderAgentId, item.delivery.senderAgentId)
        let handle = item.message?.senderHandle.flatMap(SavedGull.canonicalHandle)
        if let saved = (savedGulls ?? self.savedGulls).first(where: {
            (agentID != nil && $0.agentID == agentID) || (handle != nil && $0.handle == handle)
        }) {
            return saved.displayName
        }
        if let owned = account?.ownedGulls.first(where: {
            (agentID != nil && $0.agentID == agentID) || (handle != nil && $0.handle == handle)
        }) {
            return firstNonEmpty(owned.displayName, SavedGull.defaultDisplayName(for: owned.handle))
                ?? item.senderDisplay
        }
        return item.senderDisplay
    }

    private func resolvedSender(in item: InboxItem, savedGulls: [SavedGull]) -> InboxItem {
        var resolved = item
        let name = senderDisplay(for: item, savedGulls: savedGulls)
        if name != item.senderDisplay { resolved.resolvedSenderDisplayName = name }
        return resolved
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

    private var directoryUserID: String? {
        account?.hasWorkspace == true ? account?.userID : nil
    }

    private var directoryWebsiteURL: String { account?.websiteURL ?? "" }

    private var directoryScope: String? {
        guard let userID = directoryUserID,
              let website = SharedCloudSessionFile.normalizedWebsite(directoryWebsiteURL) else { return nil }
        return "\(website)\n\(userID)"
    }

    private var messageAPIURL: String? {
        firstNonEmpty(account?.runtime?.messageAPIURL, stores.first(where: { $0.config.isConfigured })?.config.apiURL)
    }

    private var savedGulls: [SavedGull] {
        guard let userID = directoryUserID else { return [] }
        let ownedHandles = Set(ownedGulls.map(\.handle))
        return directory.records(for: userID, websiteURL: directoryWebsiteURL)
            .filter { !ownedHandles.contains($0.handle) }
    }

    private var ownedGulls: [WorkspaceOwnedGull] {
        var values: [String: WorkspaceOwnedGull] = [:]
        for cloud in account?.hasWorkspace == true ? account?.ownedGulls ?? [] : [] {
            guard let handle = SavedGull.canonicalHandle(cloud.handle) else { continue }
            values[handle] = WorkspaceOwnedGull(
                handle: handle, displayName: firstNonEmpty(cloud.displayName) ?? SavedGull.defaultDisplayName(for: handle),
                status: "Not connected to this Mac", profileID: nil, bio: cloud.bio, capabilities: cloud.capabilities
            )
        }
        for source in stores where source.config.isConfigured {
            guard let handle = SavedGull.canonicalHandle(source.config.agentHandle) else { continue }
            let cloud = values[handle]
            values[handle] = WorkspaceOwnedGull(
                handle: handle,
                displayName: firstNonEmpty(source.config.displayName, cloud?.displayName, source.agent?.displayName)
                    ?? SavedGull.defaultDisplayName(for: handle),
                status: source.isCurrent ? source.monitoringStatusText : "Connection changed",
                profileID: source.config.profileID, bio: cloud?.bio, capabilities: cloud?.capabilities ?? []
            )
        }
        return values.values.sorted { $0.displayName.localizedStandardCompare($1.displayName) == .orderedAscending }
    }

    private var conversationSenders: [GullConversationSender] {
        stores.filter { $0.config.isConfigured && $0.isCurrent && $0.cli != nil }.map { source in
            GullConversationSender(
                id: source.config.profileID,
                displayName: firstNonEmpty(source.config.displayName, source.agent?.displayName)
                    ?? SavedGull.defaultDisplayName(for: source.config.agentHandle),
                handle: source.config.agentHandle,
                agentID: firstNonEmpty(source.agent?.agentId,
                                      account?.ownedGulls.first(where: { $0.handle == source.config.agentHandle })?.agentID),
                connectionRevision: source.config.connectionRevision,
                environment: source.config.cliEnvironment()
            )
        }
    }

    private var visibleStartedConversations: [GullConversation] {
        guard let directoryScope, conversations.activeScope == directoryScope else { return [] }
        return conversations.conversations.filter { scopeProfileID == nil || $0.senderProfileID == scopeProfileID }
    }

    private var selectedStartedConversation: GullConversation? {
        visibleStartedConversations.first { $0.id == selectedStartedConversationID }
    }

    private var selectedMessageGroupID: String? {
        if let conversation = selectedStartedConversation {
            guard let threadID = conversation.threadID else { return nil }
            return snapshot.allGroups.first { $0.profileID == conversation.senderProfileID && $0.threadID == threadID }?.id
        }
        return displayedItem == nil ? nil : selectedGroup?.id
    }

    private var scopedStores: [InboxStore] {
        stores.filter { scopeProfileID == nil || $0.config.profileID == scopeProfileID }
    }

    private func loadMoreHistory() {
        let targets = scopedStores
        Task {
            for source in targets {
                await source.history.loadMore()
            }
        }
    }

    private var dashboardProfiles: [DashboardProfileInput] {
        // Resolve the directory once per projection, not once per message.
        let saved = savedGulls
        return stores.filter { $0.config.isConfigured }.map {
            DashboardProfileInput(
                profileID: $0.config.profileID,
                handle: $0.config.agentHandle,
                displayName: firstNonEmpty($0.config.displayName, $0.agent?.displayName),
                items: $0.isCurrent ? $0.mergedItems.map { resolvedSender(in: $0, savedGulls: saved) } : []
            )
        }
    }

    private var scopedDashboardProfiles: [DashboardProfileInput] {
        dashboardProfiles.filter { scopeProfileID == nil || $0.profileID == scopeProfileID }
    }

    private var allSnapshot: DashboardSnapshot {
        dashboardProjectionCache.snapshot(from: dashboardProfiles)
    }

    private var allRelationships: DashboardRelationshipSnapshot {
        dashboardProjectionCache.relationships(from: dashboardProfiles)
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
        return selectedGroup?.items.first { $0.id == item.id }
    }

    private var canActOnSelection: Bool {
        destination == .messages && selectedStartedConversationID == nil && displayedItem != nil && !isBusy && draftTarget == nil
    }

    private func openConversation(_ group: DashboardConversationGroup) {
        if let threadID = group.threadID, let started = visibleStartedConversations.first(where: { conversation in
            conversation.threadID == threadID && conversation.senderProfileID == group.profileID
                && conversationSenders.contains { $0.id == group.profileID && $0.connectionRevision == conversation.connectionRevision }
        }) {
            openStartedConversation(started)
            return
        }
        openDelivery(profileID: group.profileID, deliveryID: group.primaryItem.id)
    }

    private func openDelivery(profileID: String, deliveryID: String, reveal: Bool = true) {
        if let workspace {
            guard workspace.selectDelivery(profileID: profileID, deliveryID: deliveryID) else { return }
            handledSelectionRevision = workspace.selectionRevision
        } else {
            guard store.config.profileID == profileID, store.isCurrent,
                  store.mergedItems.contains(where: { $0.id == deliveryID }) else { return }
            store.selectedDeliveryID = deliveryID
        }
        handledDeliveryID = deliveryID
        if reveal { showSelectedDelivery(profileID: profileID) }
    }

    private func showSelectedDelivery(profileID: String? = nil) {
        selectedStartedConversationID = nil
        destination = .messages
        if scopeProfileID != nil { scopeProfileID = profileID ?? store.config.profileID }
        showDetail()
    }

    private func ensureSelection() {
        guard destination != .gulls, selectedStartedConversation == nil, displayedItem == nil else { return }
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

    private func beginCodexTask() {
        guard canActOnSelection, let target = selectedTarget, let source = source(for: target),
              let item = source.mergedItems.first(where: { $0.id == target.deliveryID }), source.cli != nil,
              let tasks = workspace?.codexTasks[target.profileID], tasks.config.codexEnabled else { return }
        codexLaunch = CodexLaunch(tasks: tasks, inbox: source, item: item)
    }

    private func currentCodexTask(_ task: CodexTask, target: ReplyTarget, in tasks: CodexTaskStore) -> CodexTask? {
        guard source(for: target) != nil,
              tasks.config.profileID == target.profileID,
              tasks.config.connectionRevision == target.connectionRevision,
              let current = tasks.tasks.first(where: { $0.id == task.id }),
              current.request == task.request else { return nil }
        return current
    }

    private func runCodexTask(_ task: CodexTask, target: ReplyTarget, in tasks: CodexTaskStore,
                              followUp: String? = nil) {
        guard let current = currentCodexTask(task, target: target, in: tasks) else {
            codexError = "This Codex task is no longer attached to the current message. Open the message again."
            return
        }
        Task {
            do {
                try await tasks.run(current, followUp: followUp)
            } catch {
                codexError = error.localizedDescription
            }
        }
    }

    private func useCodexDraft(_ draft: CodexDraft) {
        guard !isBusy else { return }
        if draftTarget != nil || !replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            pendingCodexDraft = draft
        } else {
            applyCodexDraft(draft)
        }
    }

    private func applyCodexDraft(_ draft: CodexDraft) {
        guard !isBusy else { return }
        do {
            guard let source = source(for: draft.target),
                  source.mergedItems.contains(where: { $0.id == draft.target.deliveryID }),
                  draft.tasks.config.profileID == draft.target.profileID,
                  draft.tasks.config.connectionRevision == draft.target.connectionRevision else {
                throw CodexTaskStore.Failure("This Gull’s connection changed. Open the original message again.")
            }
            let content = try draft.tasks.draft(for: draft.task, deliveryID: draft.target.deliveryID)
            if let activeCodexDraft, !sameCodexDraft(activeCodexDraft, draft) {
                guard markCodexDraft(.superseded, activeCodexDraft) else { return }
            }
            replyTarget = draft.target
            replyText = content
            activeCodexDraft = draft
            draftTarget = nil
            pendingCodexDraft = nil
            openDelivery(profileID: draft.target.profileID, deliveryID: draft.target.deliveryID)
            showDetail()
            replyFocused = true
        } catch { codexError = error.localizedDescription }
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
                senderDisplay: senderDisplay(for: $0)
            )
        }
    }

    @ViewBuilder
    private func replySurface(availableHeight: CGFloat) -> some View {
        VStack(spacing: 0) {
            if let target = draftTarget {
                if let source = source(for: target) {
                    DraftReplyView(store: source, deliveryID: target.deliveryID, recipient: target.senderDisplay) {
                        draftTarget = nil
                    }
                    .id(target.id)
                    // Size the floating review from the pane, not itself.
                    .frame(height: min(380, availableHeight * 0.55))
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
        .gullsGlass(cornerRadius: 24, style: .clear)
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
                    if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        discardActiveCodexDraft()
                        replyTarget = nil
                    } else if replyTarget == nil {
                        replyTarget = target
                    }
                    replyText = text
                }
            ))
                .font(.body)
                .scrollContentBackground(.hidden)
                .scrollIndicators(.never)
                .frame(height: 48)
                .focused($replyFocused)
                .disabled(isBusy)
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
                    Label { Text("Draft reply") } icon: { GullsAIIcon() }
                        .labelStyle(.iconOnly)
                        .font(.system(size: 17))
                        .frame(width: 32, height: 32)
                        .contentShape(Circle())
                }
                .buttonStyle(.plain)
                .disabled(isBusy || !available)
                .accessibilityLabel("Draft reply")
                .help("Draft a reply using this Gull’s rules")
                Spacer(minLength: 0)
                Button {
                    sendReply(to: target)
                } label: {
                    Group {
                        if isBusy {
                            ProgressView().controlSize(.small).tint(GullsStyle.canvas)
                        } else {
                            Image(systemName: "arrow.up")
                                .font(.system(size: 14, weight: .semibold))
                        }
                    }
                    .frame(width: 28, height: 28)
                    .foregroundStyle(colorScheme == .dark ? Color.black : Color.white)
                    .background(colorScheme == .dark ? Color.white : Color.black, in: Circle())
                    .frame(width: 36, height: 36)
                    .contentShape(Circle())
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
        if let task = workspace?.codexTasks[target.profileID]?.latestTask(for: target.deliveryID),
           let reply = task.reply,
           (reply.deliveryUnresolved || [.sending, .uncertain, .sent].contains(reply.status)) {
            codexError = reply.status == .sent
                ? "This message already has a sent Gull reply."
                : "The Gull reply delivery is unresolved. Check its status before sending."
            return
        }
        // Capture before awaiting: neither a refresh nor a notification can
        // redirect this send to the newly selected delivery.
        replyTarget = target
        isBusy = true
        let codexDraft = activeCodexDraft
        Task {
            guard source.config.connectionRevision == target.connectionRevision else {
                isBusy = false
                return
            }
            if await source.reply(to: target.deliveryID, content: content) != nil {
                if let codexDraft, codexDraft.target.id == target.id {
                    if !markCodexDraft(.sent, codexDraft) {
                        pendingCodexSendConfirmation = codexDraft
                        codexError = codexError ?? "The local Codex draft status could not be updated."
                    }
                    activeCodexDraft = nil
                }
                replyText = ""
                replyTarget = nil
            }
            isBusy = false
        }
    }

    private func retryCodexSendConfirmation() {
        guard let pendingCodexSendConfirmation else { return }
        do {
            try pendingCodexSendConfirmation.tasks.updateDraftDisposition(
                .sent,
                for: pendingCodexSendConfirmation.task,
                deliveryID: pendingCodexSendConfirmation.target.deliveryID
            )
            self.pendingCodexSendConfirmation = nil
            codexError = nil
        } catch {
            codexError = error.localizedDescription
        }
    }

    private func sameCodexDraft(_ lhs: CodexDraft, _ rhs: CodexDraft) -> Bool {
        lhs.task.id == rhs.task.id && lhs.target.id == rhs.target.id
    }

    @discardableResult
    private func markCodexDraft(_ disposition: CodexDraftDisposition, _ draft: CodexDraft) -> Bool {
        do {
            try draft.tasks.updateDraftDisposition(disposition, for: draft.task, deliveryID: draft.target.deliveryID)
            return true
        } catch {
            codexError = error.localizedDescription
            return false
        }
    }

    private func discardActiveCodexDraft() {
        guard let activeCodexDraft else { return }
        _ = markCodexDraft(.discarded, activeCodexDraft)
        self.activeCodexDraft = nil
    }

    private func targetGullName(_ target: ReplyTarget) -> String {
        guard let source = source(for: target) else { return "the original Gull" }
        return firstNonEmpty(source.config.displayName, source.agent?.displayName, source.config.agentHandle) ?? "your Gull"
    }

    private var actionFailure: InboxStore.ActionFailure? {
        stores.compactMap(\.actionFailure).first
    }

    private func dismissActionFailure() {
        guard let id = actionFailure?.id else { return }
        for source in stores where source.actionFailure?.id == id {
            source.actionFailure = nil
        }
    }
}
