import AppKit
import SwiftUI

struct DeliveryDetailView: View {
    @Bindable var store: InboxStore
    let item: InboxItem

    @State private var showReplyComposer = false
    @State private var replyText = ""
    @State private var showDraftSheet = false
    @State private var isBusy = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                Divider()
                // Message content is untrusted input: plain text only, never
                // rendered as markdown/HTML, links stay inert.
                Text(item.bodyText ?? "(no inline content)")
                    .font(.body)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Divider()
                metadata
            }
            .padding()
        }
        .safeAreaInset(edge: .bottom) { actionBar }
        .sheet(isPresented: $showReplyComposer) { replyComposer }
        .sheet(isPresented: $showDraftSheet) {
            DraftReplyView(store: store, deliveryID: item.id)
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(item.senderDisplay)
                    .font(.title2.weight(.semibold))
                Spacer()
                StatusBadge(status: item.delivery.status)
            }
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 2) {
                metadataRow("Delivery", item.delivery.deliveryId)
                if let threadId = item.delivery.threadId {
                    metadataRow("Thread", threadId)
                }
                if let intent = item.message?.intent {
                    metadataRow("Intent", intent)
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }

    private var metadata: some View {
        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 2) {
            if let created = item.message?.createdAt {
                metadataRow("Received", created)
            }
            if let safety = item.message?.safetyStatus {
                metadataRow("Safety", safety)
            }
            if let stage = item.delivery.currentStage {
                metadataRow("Stage", stage)
            }
            if let lastError = item.delivery.lastError {
                metadataRow("Last error", lastError)
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

    private var actionBar: some View {
        HStack(spacing: 10) {
            Button {
                replyText = ""
                showReplyComposer = true
            } label: {
                Label("Reply…", systemImage: "arrowshape.turn.up.left")
            }
            .keyboardShortcut("r", modifiers: .command)

            Button {
                showDraftSheet = true
            } label: {
                Label("Draft reply", systemImage: "wand.and.stars")
            }

            Button {
                run { await store.ack(item.id) }
            } label: {
                Label("Ack", systemImage: "checkmark")
            }

            Button(role: .destructive) {
                run { _ = await store.ignore(item.id) }
            } label: {
                Label("Ignore", systemImage: "nosign")
            }

            Spacer()

            Button {
                run {
                    if let result = await store.writeContextFile(for: item.id) {
                        NSWorkspace.shared.activateFileViewerSelecting(
                            [URL(fileURLWithPath: result.contextPath)]
                        )
                    }
                }
            } label: {
                Label("Write context file", systemImage: "doc.text")
            }
            .help("Write this delivery as markdown for your coding assistant and reveal it in Finder")
        }
        .disabled(isBusy)
        .overlay(alignment: .center) {
            if isBusy { ProgressView().controlSize(.small) }
        }
        .padding(10)
        .background(.bar)
    }

    private var replyComposer: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Reply to \(item.senderDisplay)")
                .font(.headline)
            TextEditor(text: $replyText)
                .font(.body)
                .frame(minWidth: 420, minHeight: 160)
                .border(.separator)
            HStack {
                Spacer()
                Button("Cancel") { showReplyComposer = false }
                    .keyboardShortcut(.cancelAction)
                Button("Send reply") {
                    let content = replyText.trimmingCharacters(in: .whitespacesAndNewlines)
                    showReplyComposer = false
                    run { _ = await store.reply(to: item.id, content: content) }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding()
    }

    private func run(_ action: @escaping () async -> Void) {
        isBusy = true
        Task {
            await action()
            isBusy = false
        }
    }
}
