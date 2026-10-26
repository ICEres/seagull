import SwiftUI

// Actions and the floating reply surface are owned by MainWindow.
struct DeliveryDetailView: View {
    let item: InboxItem
    let localGullName: String
    var relatedItems: [InboxItem] = []
    var onSelectItem: ((InboxItem) -> Void)? = nil
    var onOpenProfile: ((String) -> Void)? = nil
    var senderProfileHandle: String? = nil
    var onOpenCodex: (() -> Void)? = nil
    var codexTask: CodexTask? = nil
    var onUseCodexDraft: (() -> Void)? = nil
    var onReopenCodexTask: (() -> Void)? = nil
    var onContinueCodex: ((String) -> Void)? = nil
    var onStopCodex: (() -> Void)? = nil
    var onApproveCodex: (() -> Void)? = nil
    var onDeclineCodex: (() -> Void)? = nil
    var onCheckStatusCodex: (() -> Void)? = nil
    var onApproveReply: (() -> Void)? = nil
    var onCheckReplyStatus: (() -> Void)? = nil
    var onTakeOverReply: (() -> Void)? = nil
    var compact = false
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @State private var contextExpanded = false

    @ViewBuilder
    var body: some View {
        if #available(macOS 26.0, *), !reduceTransparency {
            messageContent
                .gullsSafeAreaBar(edge: .top, spacing: 12) {
                    header
                }
        } else {
            messageContent
                .safeAreaInset(edge: .top, spacing: 0) {
                    header.background(GullsStyle.canvas)
                }
        }
    }

    private var messageContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                if relatedItems.count > 1 {
                    conversationContext
                }
                // Message content is untrusted input: plain text only, never
                // rendered as markdown/HTML, links stay inert.
                HStack(alignment: .bottom, spacing: 8) {
                    if !compact {
                        WingAvatar(identity: item.senderDisplay, size: 26)
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text(verbatim: item.senderDisplay)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                        Text(verbatim: item.bodyText ?? "(no inline content)")
                            .font(.body)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        if let created = item.message?.createdAt ?? item.delivery.createdAt {
                            Text(Self.displayReceived(created))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .trailing)
                        }
                    }
                    .padding(16)
                    .background(GullsStyle.messageIncoming, in: RoundedRectangle(cornerRadius: 18))
                    Spacer(minLength: compact ? 0 : 28)
                }
                if let reply = codexTask?.reply,
                   reply.status == .sent, reply.messageID != nil,
                   let content = reply.content,
                   !content.isEmpty {
                    HStack(alignment: .bottom, spacing: 8) {
                        Spacer(minLength: compact ? 0 : 28)
                        VStack(alignment: .leading, spacing: 8) {
                            Text(verbatim: localGullName)
                                .font(.caption.weight(.medium))
                                .foregroundStyle(.secondary)
                            Text(verbatim: content)
                                .font(.body)
                                .textSelection(.enabled)
                            if let sentAt = reply.sentAt {
                                Text(Self.displayReceived(sentAt))
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity, alignment: .trailing)
                            }
                        }
                        .padding(16)
                        .background(GullsStyle.messageOutgoing, in: RoundedRectangle(cornerRadius: 18))
                        if !compact {
                            WingAvatar(identity: localGullName, size: 26)
                        }
                    }
                }
                if let lastError = item.delivery.lastError {
                    Label(lastError, systemImage: "exclamationmark.triangle")
                        .font(.callout)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                }
                if let codexTask {
                    CodexTaskResultView(
                        task: codexTask,
                        gullName: localGullName,
                        onUseDraft: onUseCodexDraft,
                        onOpen: onReopenCodexTask,
                        onContinue: onContinueCodex,
                        onStop: onStopCodex,
                        onApprove: onApproveCodex,
                        onDecline: onDeclineCodex,
                        onCheckStatus: onCheckStatusCodex,
                        onApproveReply: onApproveReply,
                        onCheckReplyStatus: onCheckReplyStatus,
                        onTakeOverReply: onTakeOverReply
                    )
                }
                DisclosureGroup("Message details") {
                    metadata.padding(.top, 10)
                }
                .font(.subheadline)
                .foregroundStyle(.secondary)
            }
            .frame(maxWidth: 760, alignment: .leading)
            .padding(.horizontal, compact ? 14 : 28)
            .padding(.vertical, 18)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .gullsHiddenScrollbars()
    }

    private var conversationContext: some View {
        DisclosureGroup(isExpanded: $contextExpanded) {
            VStack(spacing: 4) {
                ForEach(relatedItems) { related in
                    Button {
                        onSelectItem?(related)
                    } label: {
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: related.id == item.id ? "circle.inset.filled" : "circle")
                                .font(.caption)
                                .foregroundStyle(related.id == item.id ? GullsStyle.accent : Color.secondary)
                                .padding(.top, 2)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(verbatim: related.bodyText ?? "No inline content")
                                    .font(.callout)
                                    .lineLimit(2)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                Text(verbatim: related.senderDisplay)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            StatusBadge(status: related.delivery.status)
                        }
                        .padding(10)
                        .background(related.id == item.id ? GullsStyle.field : Color.clear, in: RoundedRectangle(cornerRadius: 10))
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(related.id == item.id ? .isSelected : [])
                }
            }
            .padding(.top, 8)
        } label: {
            Text("Conversation context · \(relatedItems.count) loaded updates")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(.secondary)
        }
    }

    private var header: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) {
                senderIdentity.fixedSize()
                Spacer(minLength: 12)
                codexButton
                routingInformation.fixedSize()
            }
            VStack(alignment: .leading, spacing: 8) {
                senderIdentity
                codexButton
                routingInformation
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
        }
        .padding(.horizontal, compact ? 14 : 28)
        .padding(.vertical, 12)
    }

    @ViewBuilder
    private var codexButton: some View {
        if let onOpenCodex {
            Button(action: onOpenCodex) {
                Label { Text("Let \(localGullName) handle this") } icon: { GullsAIIcon() }
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Let \(localGullName) handle this")
            .help("Start a Codex task for this message")
        }
    }

    private var senderIdentity: some View {
        Group {
            if let handle = senderProfileHandle ?? item.message?.senderHandle.flatMap(SavedGull.canonicalHandle), let onOpenProfile {
                Button { onOpenProfile(handle) } label: { senderLabel }
                    .buttonStyle(.plain)
                    .help("View Gull profile")
            } else {
                senderLabel
            }
        }
    }

    private var senderLabel: some View {
        HStack(spacing: 12) {
            WingAvatar(identity: item.senderDisplay, size: 26)
            Text(verbatim: item.senderDisplay)
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)
                .help(item.senderDisplay)
        }
    }

    private var routingInformation: some View {
        HStack(spacing: 10) {
            Text("Via \(localGullName)")
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .help(localGullName)
            StatusBadge(status: item.delivery.status)
                .fixedSize()
        }
    }

    private var metadata: some View {
        Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 8) {
            metadataRow("Delivery", item.delivery.deliveryId)
            if let threadId = item.delivery.threadId {
                metadataRow("Thread", threadId)
            }
            if let intent = item.message?.intent {
                metadataRow("Intent", intent)
            }
            if let safety = item.message?.safetyStatus {
                metadataRow("Safety", safety)
            }
            if let stage = item.delivery.currentStage {
                metadataRow("Stage", stage)
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func metadataRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label).gridColumnAlignment(.trailing)
            Text(value).textSelection(.enabled)
        }
    }

    static func displayReceived(_ raw: String) -> String {
        guard let date = GullsDates.parse(raw) else { return raw }
        return date.formatted(date: .abbreviated, time: .standard)
    }
}
