import SwiftUI

struct MessagesView: View {
    @Environment(MobileAppStore.self) private var store
    @State private var searchText = ""
    @State private var showingComposer = false
    @State private var isLoading = false
    @State private var errorMessage: String?

    private var conversations: [MessageConversation] {
        let all = store.ownedGulls.flatMap { gull in
            let incoming = (store.inboxByHandle[gull.handle] ?? []).compactMap { item -> MessageConversation? in
                guard let threadID = item.delivery.threadID, !threadID.isEmpty else { return nil }
                let name = item.message?.senderDisplayName ?? (SavedGull.canonicalHandle(item.sender) == nil ? "Unavailable Gull" : nil)
                return MessageConversation(id: "\(gull.handle)|\(threadID)", ownedHandle: gull.handle, threadID: threadID, counterpartHandle: item.sender, counterpartName: name, latestContent: item.content, latestDate: parseDate(item.message?.createdAt ?? item.delivery.createdAt))
            }
            let outgoing = (store.sentByHandle[gull.handle] ?? []).compactMap { message -> MessageConversation? in
                guard let threadID = message.threadID, !threadID.isEmpty else { return nil }
                let own = normalizedHandle(gull.handle)
                guard let counterpart = message.recipientHandles?.first(where: { normalizedHandle($0) != own }) else { return nil }
                let name = store.savedGulls.first(where: { $0.handle == counterpart })?.displayName
                return MessageConversation(id: "\(gull.handle)|\(threadID)", ownedHandle: gull.handle, threadID: threadID, counterpartHandle: counterpart, counterpartName: name, latestContent: message.contentInline ?? "", latestDate: parseDate(message.createdAt))
            }
            let pending = store.pendingMessages.filter { $0.sender.handle == gull.handle }.map { item in
                MessageConversation(id: "\(gull.handle)|\(item.conversationID)", ownedHandle: gull.handle, threadID: item.conversationID, counterpartHandle: item.recipientHandle, counterpartName: store.savedGulls.first(where: { $0.handle == item.recipientHandle })?.displayName, latestContent: item.content, latestDate: item.createdAt)
            }
            return incoming + outgoing + pending
        }
        .reduce(into: [String: MessageConversation]()) { result, conversation in
            if let existing = result[conversation.id], existing.latestDate >= conversation.latestDate { return }
            result[conversation.id] = conversation
        }
        .values
        .sorted { $0.latestDate == $1.latestDate ? $0.id < $1.id : $0.latestDate > $1.latestDate }

        guard !searchText.isEmpty else { return all }
        return all.filter {
            $0.counterpartHandle.localizedCaseInsensitiveContains(searchText) ||
            ($0.counterpartName?.localizedCaseInsensitiveContains(searchText) ?? false) ||
            $0.ownedHandle.localizedCaseInsensitiveContains(searchText) ||
            $0.latestContent.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 10) {
                if isLoading && conversations.isEmpty {
                    ProgressView("Loading messages…").frame(maxWidth: .infinity).padding(.top, 64)
                } else if conversations.isEmpty {
                    ContentUnavailableView {
                        Label("No messages", systemImage: "bubble.left.and.bubble.right")
                    } description: {
                        Text("Messages between your Gulls and external Gulls will appear here.")
                    } actions: {
                        Button("New message") { showingComposer = true }.buttonStyle(.borderedProminent).tint(GullsTheme.accent)
                    }
                    .frame(maxWidth: .infinity).padding(.top, 56)
                } else {
                    if store.ownedGulls.contains(where: { store.sentTruncatedHandles.contains($0.handle) }) {
                        Text("Some older sent conversations may be unavailable.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 4)
                    }
                    ForEach(conversations) { conversation in
                        NavigationLink(value: conversation) { MessageConversationRow(conversation: conversation) }
                            .buttonStyle(.plain)
                    }
                    if store.canLoadMoreInbox {
                        Button("Load more conversations") { Task { await loadMore() } }
                            .frame(minHeight: 44)
                            .disabled(isLoading)
                    }
                }
                if let issue = store.syncIssue {
                    Text(issue).font(.caption).foregroundStyle(.secondary).padding(.vertical, 8)
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
        }
        .background(GullsTheme.background.ignoresSafeArea())
        .navigationTitle("Messages.")
        .searchable(text: $searchText, prompt: "Search messages")
        .toolbar {
            GullsNavigationTitle("Messages")
            ToolbarItem(placement: .topBarTrailing) {
                Button { showingComposer = true } label: { Image(systemName: "square.and.pencil") }
                    .accessibilityLabel("New message")
            }
        }
        .navigationDestination(for: MessageConversation.self) { conversation in
            NetworkConversationView(ownedHandle: conversation.ownedHandle, threadID: conversation.threadID, counterpartHandle: conversation.counterpartHandle)
        }
        .refreshable { await refresh() }
        .task { store.syncInBackground() }
        .sheet(isPresented: $showingComposer) { NewMessageSheet().presentationDetents([.medium, .large]) }
        .alert("Messages unavailable", isPresented: Binding(get: { errorMessage != nil }, set: { if !$0 { errorMessage = nil } })) {
            Button("OK", role: .cancel) { errorMessage = nil }
        } message: { Text(errorMessage ?? "Try again in a moment.") }
    }

    private func refresh() async {
        isLoading = true
        defer { isLoading = false }
        await store.refresh()
    }

    private func loadMore() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        for gull in store.ownedGulls where store.inboxCursors[gull.handle] != nil || store.moreCachedInboxes.contains(gull.handle) {
            if !(await store.loadMoreInbox(for: gull)) { errorMessage = store.error }
        }
    }
}

private struct MessageConversation: Hashable, Identifiable {
    let id: String
    let ownedHandle: String
    let threadID: String
    let counterpartHandle: String
    let counterpartName: String?
    let latestContent: String
    let latestDate: Date
}

private struct MessageConversationRow: View {
    let conversation: MessageConversation

    var body: some View {
        HStack(spacing: 13) {
            GullAvatar(handle: conversation.counterpartHandle, size: 48)
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(conversation.counterpartName ?? conversation.counterpartHandle).font(.body.weight(.semibold)).lineLimit(1)
                    Spacer(minLength: 8)
                    Group {
                        if Calendar.current.isDateInToday(conversation.latestDate) {
                            Text(conversation.latestDate, format: .dateTime.hour().minute())
                        } else {
                            Text(conversation.latestDate, format: .dateTime.month(.abbreviated).day())
                        }
                    }.font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Text("via \(conversation.ownedHandle)").font(.caption).foregroundStyle(GullsTheme.accent)
                if conversation.counterpartName != nil {
                    Text(conversation.counterpartHandle).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Text(conversation.latestContent.isEmpty ? "New message" : conversation.latestContent).font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
            }
            Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
        }
        .padding(14).frame(minHeight: 78)
        .background(GullsTheme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine).accessibilityHint("Open conversation")
    }
}

struct NetworkConversationView: View {
    @Environment(MobileAppStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase
    let ownedHandle: String
    let threadID: String
    let counterpartHandle: String
    @State private var draft = ""
    @State private var isLoading = false
    @State private var isLoadingEarlier = false
    @State private var isSending = false
    @State private var errorMessage: String?
    @State private var retryTarget: MobilePendingMessage?
    private var effectiveThreadID: String { store.resolvedThreadIDs[threadID] ?? threadID }
    private var isLocalConversation: Bool { effectiveThreadID.hasPrefix("pending:") }
    private var pending: [MobilePendingMessage] {
        store.pendingMessages.filter { $0.sender.handle == ownedHandle && ($0.conversationID == threadID || $0.threadID == effectiveThreadID) }
    }
    private var ownedGull: CloudGull? { store.ownedGulls.first(where: { $0.handle == ownedHandle }) }
    private var resolvedRecipient: String? {
        if let handle = SavedGull.canonicalHandle(counterpartHandle) { return handle }
        return messages.compactMap(\.senderHandle).first { $0 != ownedHandle && SavedGull.canonicalHandle($0) != nil }
    }

    init(ownedHandle: String, threadID: String, counterpartHandle: String) {
        self.ownedHandle = ownedHandle; self.threadID = threadID; self.counterpartHandle = counterpartHandle
    }

    init(gull: CloudGull, threadID: String, counterpartHandle: String) {
        self.init(ownedHandle: gull.handle, threadID: threadID, counterpartHandle: counterpartHandle)
    }

    private var messages: [MobileMessage] { store.messagesByThreadID[effectiveThreadID] ?? [] }
    private var identifiedMessages: [IdentifiedMessage] {
        messages.map { message in
            IdentifiedMessage(message: message, id: message.messageID ?? "\(threadID):\(message.senderHandle ?? ""):\(message.createdAt ?? ""):\(message.contentInline ?? "")")
        }
    }

    var body: some View {
        ScrollViewReader { proxy in
            let history = ScrollView {
                LazyVStack(spacing: 12) {
                    if store.hasMoreMessages(in: effectiveThreadID) {
                        Button {
                            Task { await loadEarlier() }
                        } label: {
                            HStack(spacing: 8) {
                                if isLoadingEarlier { ProgressView() }
                                Text(isLoadingEarlier ? "Loading earlier messages…" : "Load earlier messages")
                            }
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(GullsTheme.accent)
                            .frame(minHeight: 44)
                        }
                        .disabled(isLoadingEarlier)
                    }
                    if isLoading && messages.isEmpty {
                        ProgressView("Loading conversation…").padding(.top, 70)
                    } else if messages.isEmpty && pending.isEmpty {
                        ContentUnavailableView("Start a conversation", systemImage: "bubble.left", description: Text("Send a message to \(counterpartHandle)." )).padding(.top, 60)
                    } else {
                        ForEach(Array(identifiedMessages.enumerated()), id: \.element.id) { index, identified in
                            if let date = MobileDates.parse(identified.message.createdAt), startsDay(at: index) {
                                Text(date, format: .dateTime.month(.abbreviated).day())
                                    .font(.caption.weight(.medium)).foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity).padding(.vertical, 8)
                            }
                            MessageBubble(message: identified.message, ownedHandle: ownedHandle).id(identified.id)
                        }
                        ForEach(pending) { message in
                            PendingMessageBubble(message: message) {
                                if message.state == .unconfirmed { retryTarget = message }
                                else { retry(message) }
                            }
                                .id(message.id)
                        }
                    }
                }.padding(.horizontal, 16).padding(.vertical, 18)
            }
            .background(GullsTheme.background.ignoresSafeArea())
            .scrollDismissesKeyboard(.interactively)
            .defaultScrollAnchor(.bottom, for: .initialOffset)

            Group {
                if #available(iOS 26, *) {
                    history
                        .safeAreaBar(edge: .bottom, spacing: 0) { composer }
                        .scrollEdgeEffectStyle(.soft, for: .bottom)
                } else {
                    history.safeAreaInset(edge: .bottom, spacing: 0) { composer }
                }
            }
            .onChange(of: pending.last?.id) { _, target in
                guard let target else { return }
                withAnimation(.snappy) { proxy.scrollTo(target, anchor: .bottom) }
            }
            .navigationTitle(counterpartHandle).navigationBarTitleDisplayMode(.inline)
            .toolbar(.hidden, for: .tabBar)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    VStack(spacing: 2) {
                        Text(store.savedGulls.first(where: { $0.handle == resolvedRecipient })?.displayName ?? resolvedRecipient ?? "Unavailable Gull")
                            .font(.headline).lineLimit(1)
                        Text("via \(ownedGull?.displayName ?? ownedHandle)").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .task(id: effectiveThreadID) { await load() }.refreshable { await load() }
            .task(id: scenePhase) { if scenePhase == .active { await poll() } }
            .alert("Message unavailable", isPresented: Binding(get: { errorMessage != nil }, set: { if !$0 { errorMessage = nil } })) {
                Button("OK", role: .cancel) { errorMessage = nil }
            } message: { Text(errorMessage ?? "Try again in a moment.") }
            .confirmationDialog("Retry this message?", isPresented: Binding(get: { retryTarget != nil }, set: { if !$0 { retryTarget = nil } }), presenting: retryTarget) { item in
                Button("Retry") { retry(item); retryTarget = nil }
                Button("Cancel", role: .cancel) { retryTarget = nil }
            } message: { _ in
                Text("The server may have received it. Check this conversation before retrying.")
            }
        }
    }

    @ViewBuilder
    private var composer: some View {
        if isLocalConversation {
            Text("Your first message is saved on this device.")
                .font(.caption).foregroundStyle(.secondary).padding()
        } else if let resolvedRecipient {
            MessageComposer(text: $draft, isSending: isSending, placeholder: "Message \(resolvedRecipient)") { send() }
        } else {
            Text("This Gull's identity is unavailable. Pull to refresh before replying.")
                .font(.footnote).foregroundStyle(.secondary).padding(16)
                .frame(maxWidth: .infinity).gullsGlass()
                .padding(.horizontal, 16).padding(.vertical, 8)
        }
    }

    private func startsDay(at index: Int) -> Bool {
        guard index > 0,
              let date = MobileDates.parse(messages[index].createdAt),
              let previous = MobileDates.parse(messages[index - 1].createdAt) else { return true }
        return !Calendar.current.isDate(date, inSameDayAs: previous)
    }

    private func load() async {
        guard !isLocalConversation else { return }
        await store.restoreCachedThread(effectiveThreadID)
        isLoading = messages.isEmpty && pending.isEmpty
        defer { isLoading = false }
        do {
            guard let ownedGull else {
                errorMessage = "This Gull is no longer available."
                return
            }
            try await store.loadThread(effectiveThreadID, for: ownedGull)
        } catch {
            if messages.isEmpty { errorMessage = error.localizedDescription }
        }
    }

    private func loadEarlier() async {
        guard !isLoadingEarlier, let ownedGull else {
            if ownedGull == nil { errorMessage = "This Gull is no longer available." }
            return
        }
        isLoadingEarlier = true
        defer { isLoadingEarlier = false }
        do { _ = try await store.loadMoreThread(effectiveThreadID, for: ownedGull) }
        catch { errorMessage = error.localizedDescription }
    }

    private func poll() async {
        guard !store.isPreview else { return }
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(10))
            guard !Task.isCancelled else { return }
            guard !isLocalConversation else { continue }
            guard let ownedGull else {
                errorMessage = "This Gull is no longer available."
                return
            }
            do { _ = try await store.loadThread(effectiveThreadID, for: ownedGull) }
            catch { /* Keep the current conversation visible during quiet refresh. */ }
        }
    }

    private func send() {
        let content = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty, !isSending else { return }
        guard let ownedGull, let resolvedRecipient else { return }
        isSending = true
        Task {
            defer { isSending = false }
            do {
                try await store.enqueueMessage(sender: ownedGull, recipientHandle: resolvedRecipient, content: content, threadID: effectiveThreadID)
                draft = ""
            } catch { errorMessage = error.localizedDescription }
        }
    }

    private func retry(_ item: MobilePendingMessage) {
        Task {
            do { try await store.retryPendingMessage(item.id) }
            catch { errorMessage = error.localizedDescription }
        }
    }
}

private struct IdentifiedMessage: Identifiable {
    let message: MobileMessage
    let id: String
}

private struct MessageBubble: View {
    let message: MobileMessage
    let ownedHandle: String
    private var isOutgoing: Bool { message.senderHandle == ownedHandle }
    var body: some View {
        HStack {
            if isOutgoing { Spacer(minLength: 48) }
            VStack(alignment: isOutgoing ? .trailing : .leading, spacing: 3) {
                Text(message.contentInline ?? "").font(.body).foregroundStyle(isOutgoing ? .white : .primary).padding(.horizontal, 14).padding(.vertical, 10).background(isOutgoing ? GullsTheme.accent : GullsTheme.incoming, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .textSelection(.enabled)
                if let date = parseOptionalDate(message.createdAt) { Text(date, style: .time).font(.caption2).foregroundStyle(.secondary) }
            }
            if !isOutgoing { Spacer(minLength: 48) }
        }
    }
}

private struct PendingMessageBubble: View {
    let message: MobilePendingMessage
    let retry: () -> Void
    var body: some View {
        HStack { Spacer(minLength: 48); VStack(alignment: .trailing, spacing: 5) {
            Text(message.content).font(.body).foregroundStyle(.white.opacity(0.85)).padding(.horizontal, 14).padding(.vertical, 10).background(GullsTheme.accent.opacity(0.65), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            switch message.state {
            case .queued:
                Text("Waiting to send").font(.caption).foregroundStyle(.secondary)
            case .sending:
                Text("Sending…").font(.caption).foregroundStyle(.secondary)
            case .failed, .unconfirmed:
                HStack(spacing: 10) {
                    Text(message.state == .unconfirmed ? "Delivery unconfirmed" : "Not sent").font(.caption).foregroundStyle(.secondary)
                    Button("Retry", action: retry).font(.caption.weight(.medium)).foregroundStyle(GullsTheme.accent).frame(minHeight: 44)
                }
            }
        } }
    }
}

private struct MessageComposer: View {
    @Binding var text: String
    let isSending: Bool
    let placeholder: String
    let send: () -> Void
    private var canSend: Bool { !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isSending }
    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField(placeholder, text: $text, axis: .vertical)
                .lineLimit(1...5)
                .textFieldStyle(.plain)
                .padding(.leading, 10)
                .padding(.vertical, 8)
            Button(action: send) {
                Image(systemName: isSending ? "arrow.up.circle.dotted" : "arrow.up.circle.fill")
                    .font(.title2)
                    .foregroundStyle(canSend ? GullsTheme.accent : Color.secondary.opacity(0.45))
                    .frame(width: 44, height: 44)
            }
            .disabled(!canSend)
            .accessibilityLabel("Send message")
        }
        .padding(6)
        .gullsGlass(cornerRadius: 28, interactive: true)
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
    }
}

struct NewMessageSheet: View {
    @Environment(MobileAppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var senderHandle = ""
    @State private var recipientHandle: String
    @State private var content = ""
    @State private var isSending = false
    @State private var errorMessage: String?
    init(recipientHandle: String = "") {
        _recipientHandle = State(initialValue: recipientHandle)
    }
    private var isValid: Bool { !senderHandle.isEmpty && isValidHandle(recipientHandle) && !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    var body: some View {
        NavigationStack {
            Form {
                if store.ownedGulls.isEmpty {
                    Section {
                        Label("No owned Gull is available", systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.secondary)
                        Text("Create or restore a Gull before sending messages.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Section("From") { Picker("Your Gull", selection: $senderHandle) { ForEach(store.ownedGulls) { gull in Text(gull.handle).tag(gull.handle) } } }
                        .listRowBackground(GullsTheme.surface)
                }
                Section("To") { TextField("gull:domain or @gull:domain", text: $recipientHandle).textInputAutocapitalization(.never).autocorrectionDisabled() }
                    .listRowBackground(GullsTheme.surface)
                Section("Message") { TextField("Write a message", text: $content, axis: .vertical).lineLimit(4...10) }
                    .listRowBackground(GullsTheme.surface)
                if let errorMessage { Text(errorMessage).font(.footnote).foregroundStyle(.red) }
            }.scrollContentBackground(.hidden).navigationTitle("New message").navigationBarTitleDisplayMode(.inline).toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Send") { send() }.disabled(!isValid || isSending) }
            }
            .disabled(isSending)
            .onAppear { senderHandle = store.ownedGulls.first?.handle ?? "" }
        }
        .gullsSheet()
    }
    private func send() {
        guard isValid else { return }; isSending = true
        Task {
            do {
                guard let sender = store.ownedGulls.first(where: { $0.handle == senderHandle }) else { throw MobileStoreError.notSignedIn }
                try await store.enqueueMessage(sender: sender, recipientHandle: normalizedHandle(recipientHandle), content: content)
                dismiss()
            }
            catch { errorMessage = error.localizedDescription; isSending = false }
        }
    }
}

private func parseDate(_ value: String?) -> Date { MobileDates.parse(value) ?? .distantPast }
private func parseOptionalDate(_ value: String?) -> Date? { MobileDates.parse(value) }
private func normalizedHandle(_ handle: String) -> String {
    let value = handle.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    return value.hasPrefix("@") ? value : "@\(value)"
}
private func isValidHandle(_ handle: String) -> Bool {
    SavedGull.canonicalHandle(normalizedHandle(handle)) != nil
}

#Preview("Messages") { NavigationStack { MessagesView() }.environment(MobileAppStore.preview()) }
