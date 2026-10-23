import SwiftUI

struct GullConversationView: View {
    @Bindable var store: GullConversationStore
    let conversationID: String
    let senders: [GullConversationSender]
    var onOpenProfile: () -> Void = {}

    @State private var draft = ""
    @State private var error: String?
    @State private var isSending = false
    @State private var isLoadingEarlier = false
    @State private var retryTarget: GullConversationStore.PendingOutgoing?
    @State private var shouldFollowLatest = true
    @State private var visible = false
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var colorScheme

    private var conversation: GullConversation? {
        store.conversations.first { $0.id == conversationID }
    }

    private var sender: GullConversationSender? {
        guard let conversation else { return nil }
        return senders.first {
            $0.id == conversation.senderProfileID
                && $0.connectionRevision == conversation.connectionRevision
        }
    }

    var body: some View {
        Group {
            if let conversation {
                if #available(macOS 26.0, *), !reduceTransparency {
                    messageContent(conversation)
                        .gullsSafeAreaBar(edge: .top, spacing: 0) { header(conversation) }
                        .gullsSafeAreaBar(edge: .bottom, spacing: 0) { composer(conversation) }
                        .gullsScrollEdges()
                } else {
                    messageContent(conversation)
                        .safeAreaInset(edge: .top, spacing: 0) { header(conversation).background(GullsStyle.canvas) }
                        .safeAreaInset(edge: .bottom, spacing: 0) { composer(conversation).background(GullsStyle.canvas) }
                        .gullsScrollEdges()
                }
            } else {
                ContentUnavailableView("Conversation unavailable", systemImage: "bubble.left.and.bubble.right")
            }
        }
        .onAppear { visible = true }
        .onDisappear { visible = false; draft = "" }
        .task(id: conversationID) {
            await refreshLoop()
        }
        .confirmationDialog("Retry this message?", isPresented: Binding(
            get: { retryTarget != nil },
            set: { if !$0 { retryTarget = nil } }
        ), titleVisibility: .visible, presenting: retryTarget) { pending in
            Button("Retry") {
                if let conversation { retry(pending.id, conversation: conversation) }
                retryTarget = nil
            }
            Button("Cancel", role: .cancel) { retryTarget = nil }
        } message: { _ in
            Text("The server may have received it. Check this conversation before retrying.")
        }
    }

    @ViewBuilder
    private func messageContent(_ conversation: GullConversation) -> some View {
        ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        let messages = store.messages(for: conversation.id)
                        if messages.isEmpty {
                            VStack(alignment: .leading, spacing: 6) {
                                Image(systemName: conversation.threadID == nil ? "paperplane" : "bubble.left")
                                    .foregroundStyle(GullsStyle.accent)
                                Text(conversation.threadID == nil ? "Start the conversation" : "No messages yet")
                                    .font(.headline.weight(.medium))
                                Text(conversation.threadID == nil
                                     ? "Write a message below. Nothing is sent until you click the send button."
                                     : "New replies will appear here while this conversation is open.")
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.top, 48)
                        } else {
                            if store.hasMoreMessages(for: conversation.id) {
                                Button {
                                    loadEarlier(conversation)
                                } label: {
                                    HStack(spacing: 7) {
                                        if isLoadingEarlier { ProgressView().controlSize(.small) }
                                        Text(isLoadingEarlier ? "Loading earlier messages…" : "Load earlier messages")
                                    }
                                    .font(.caption)
                                    .foregroundStyle(GullsStyle.accent)
                                    .frame(maxWidth: .infinity, alignment: .center)
                                    .padding(.vertical, 8)
                                }
                                .buttonStyle(.plain)
                                .disabled(isLoadingEarlier)
                            }
                            ForEach(messages) { message in
                                VStack(alignment: .leading, spacing: 4) {
                                    messageRow(message, conversation: conversation)
                                    if let pending = store.pendingMessage(message.id) {
                                        HStack(spacing: 8) {
                                            Text(pendingLabel(pending))
                                                .font(.caption2).foregroundStyle(.secondary)
                                            if pending.state == .failed || pending.state == .unconfirmed {
                                                Button("Retry") {
                                                    if pending.state == .unconfirmed { retryTarget = pending }
                                                    else { retry(message.id, conversation: conversation) }
                                                }
                                                    .font(.caption2.weight(.medium))
                                                    .buttonStyle(.link)
                                            }
                                        }
                                        .padding(.leading, 45)
                                    }
                                }
                                .id(message.id)
                            }
                        }
                    }
                    .frame(maxWidth: 720, alignment: .leading)
                    .padding(.horizontal, 28)
                    .padding(.vertical, 20)
                    .frame(maxWidth: .infinity, alignment: .topLeading)
                }
                .gullsHiddenScrollbars()
                .gullsScrollEdges()
                .modifier(ConversationScrollTracking(shouldFollowLatest: $shouldFollowLatest))
                .onChange(of: store.messages(for: conversation.id).last?.id) { _, id in
                    guard shouldFollowLatest, let id else { return }
                    withAnimation(reduceMotion ? nil : .smooth(duration: 0.22)) { proxy.scrollTo(id, anchor: .bottom) }
                }
        }
    }

    private func header(_ conversation: GullConversation) -> some View {
        HStack(spacing: 10) {
            Button(action: onOpenProfile) {
                HStack(spacing: 10) {
                    GullAvatar(handle: conversation.recipientHandle, size: 32)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(conversation.displayName).font(.headline.weight(.semibold))
                        Text(conversation.recipientHandle).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .buttonStyle(.plain)
            .contentShape(Rectangle())
            .help("Open Gull profile")
            Spacer()
        }
        .padding(.horizontal, 28)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func messageRow(_ message: GullConversationMessage, conversation: GullConversation) -> some View {
        let isOwn = message.senderHandle == conversation.senderHandle
            || (message.senderAgentID != nil && message.senderAgentID == conversation.senderAgentID)
        let senderLabel: String
        if isOwn {
            senderLabel = sender?.displayName ?? conversation.senderHandle
        } else if message.senderHandle == conversation.recipientHandle
                    || (message.senderAgentID != nil && message.senderAgentID == conversation.recipientAgentID) {
            senderLabel = conversation.recipientName ?? conversation.recipientHandle
        } else {
            senderLabel = message.senderHandle ?? message.senderAgentID ?? "Unknown Gull"
        }
        let avatarIdentity = message.senderHandle ?? message.senderAgentID ?? senderLabel
        return HStack(alignment: .top, spacing: 9) {
            GullAvatar(handle: avatarIdentity, size: 24)
            VStack(alignment: .leading, spacing: 3) {
                Text(senderLabel)
                    .font(.caption.weight(.medium)).foregroundStyle(.secondary)
                Text(message.content).font(.body)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(isOwn ? GullsStyle.field : Color.clear, in: RoundedRectangle(cornerRadius: 12))
    }

    private func composer(_ conversation: GullConversation) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            if let sender {
                HStack(spacing: 6) {
                    Text("Sending as").font(.caption).foregroundStyle(.secondary)
                    Text(sender.displayName).font(.caption.weight(.medium))
                    Text(sender.handle).font(.caption2).foregroundStyle(.tertiary)
                }
            } else {
                Label("This Gull connection changed. Reconnect it before sending.", systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
            if let error {
                Text(error).font(.caption).foregroundStyle(.red)
            }
            HStack(alignment: .bottom, spacing: 10) {
                TextField("Write a message", text: $draft, axis: .vertical)
                    .textFieldStyle(.plain)
                    .lineLimit(1...6)
                    .onSubmit { send(conversation) }
                Button(action: { send(conversation) }) {
                    if isSending { ProgressView().controlSize(.small) }
                    else { Image(systemName: "arrow.up") }
                }
                .buttonStyle(.borderedProminent)
                .tint(GullsStyle.accent)
                .accessibilityLabel("Send message")
                .help("Send message")
                .disabled(isSending || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || sender == nil)
            }
        }
        .padding(12)
        .gullsGlass(cornerRadius: 24)
        .overlay {
            RoundedRectangle(cornerRadius: 24)
                .stroke(Color.primary.opacity(colorScheme == .dark ? 0.18 : 0.12), lineWidth: 0.75)
        }
        .padding(.horizontal, 18)
        .padding(.top, 8)
        .padding(.bottom, 16)
    }

    private func send(_ conversation: GullConversation) {
        guard !isSending, let sender,
              sender.connectionRevision == conversation.connectionRevision else { return }
        let text = draft
        isSending = true
        error = nil
        Task {
            do {
                _ = try await store.send(conversation.id, content: text, environment: sender.environment) {
                    // The outbox is durable at this point, so let the user
                    // continue composing while delivery runs in the background.
                    draft = ""
                    isSending = false
                }
            } catch {
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            isSending = false
        }
    }

    private func retry(_ pendingID: String, conversation: GullConversation) {
        guard !isSending, let sender else { return }
        isSending = true
        error = nil
        Task {
            do {
                _ = try await store.retryPending(pendingID, environment: sender.environment)
            } catch {
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            isSending = false
        }
    }

    private func pendingLabel(_ pending: GullConversationStore.PendingOutgoing) -> String {
        switch pending.state {
        case .queued: return "Queued"
        case .sending: return "Sending in background"
        case .unconfirmed: return "Not confirmed"
        case .failed: return "Could not send"
        }
    }

    private func loadEarlier(_ conversation: GullConversation) {
        guard !isLoadingEarlier, let sender else { return }
        isLoadingEarlier = true
        Task {
            do {
                _ = try await store.loadMore(conversation.id, environment: sender.environment)
            } catch {
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            isLoadingEarlier = false
        }
    }

    private func refreshLoop() async {
        while !Task.isCancelled && visible {
            if let conversation, let sender {
                await store.sendQueued(environment: sender.environment)
                if conversation.threadID != nil {
                    do { _ = try await store.open(conversation.id, environment: sender.environment); error = nil }
                    catch { if !Task.isCancelled { self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription } }
                }
            }
            try? await Task.sleep(for: .seconds(8))
        }
    }
}

private struct ConversationScrollTracking: ViewModifier {
    @Binding var shouldFollowLatest: Bool

    func body(content: Content) -> some View {
        if #available(macOS 15.0, *) {
            content.onScrollGeometryChange(for: Bool.self) { geometry in
                geometry.contentOffset.y + geometry.containerSize.height
                    >= geometry.contentSize.height - 44
            } action: { _, isAtBottom in
                shouldFollowLatest = isAtBottom
            }
        } else {
            content
        }
    }
}
