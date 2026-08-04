import AppKit
import SwiftUI

struct MainWindow: View {
    @Bindable var store: InboxStore
    @Environment(\.openSettings) private var openSettings

    // A sheet acts on the delivery captured when it opened, never on whatever
    // is selected when its button is pressed: a notification arriving
    // mid-compose moves the selection out from under an open sheet.
    private struct SheetTarget: Identifiable {
        let id: String
        let senderDisplay: String
    }

    @State private var replyTarget: SheetTarget?
    @State private var replyText = ""
    @State private var draftTarget: SheetTarget?
    @State private var isBusy = false

    var body: some View {
        NavigationSplitView {
            InboxListView(store: store)
                .navigationSplitViewColumnWidth(min: 260, ideal: 320)
        } detail: {
            if let item = store.selectedItem {
                DeliveryDetailView(item: item)
            } else {
                ContentUnavailableView(
                    "No delivery selected",
                    systemImage: "tray",
                    description: Text("Pick a delivery from the inbox to review it.")
                )
            }
        }
        .navigationTitle("Gulls")
        .navigationSubtitle(subtitle)
        .searchable(text: $store.searchText, prompt: "Search sender or content")
        .toolbar(id: "gulls-main") { mainToolbar }
        .safeAreaInset(edge: .bottom) {
            if let error = store.lastError {
                errorBar(error)
            }
        }
        .sheet(item: $replyTarget) { target in replyComposer(target) }
        .sheet(item: $draftTarget) { target in
            DraftReplyView(store: store, deliveryID: target.id)
        }
        // Keyed on isConfigured so finishing first-run Settings starts
        // polling/streaming right away — a plain .task would only ever run
        // once, leaving a freshly configured app idle until relaunch.
        .task(id: store.config.isConfigured) {
            guard store.config.isConfigured else {
                openSettings()
                return
            }
            await store.loadAgentProfile()
            await store.refresh()
            store.startPolling()
            store.startStreaming()
        }
    }

    // MARK: - Toolbar

    // Message actions live in the toolbar, Mail-style; the id-based form
    // enables the native "Customize Toolbar…" sheet.
    @ToolbarContentBuilder
    private var mainToolbar: some CustomizableToolbarContent {
        ToolbarItem(id: "reply", placement: .primaryAction) {
            Button {
                replyText = ""
                replyTarget = store.selectedItem.map {
                    SheetTarget(id: $0.id, senderDisplay: $0.senderDisplay)
                }
            } label: {
                Label("Reply", systemImage: "arrowshape.turn.up.left")
            }
            .disabled(store.selectedItem == nil || isBusy)
            .keyboardShortcut("r", modifiers: .command)
            .help("Reply to the selected delivery (⌘R)")
        }

        ToolbarItem(id: "draft-reply", placement: .primaryAction) {
            Button {
                draftTarget = store.selectedItem.map {
                    SheetTarget(id: $0.id, senderDisplay: $0.senderDisplay)
                }
            } label: {
                Label("Draft reply", systemImage: "wand.and.stars")
            }
            .disabled(store.selectedItem == nil || isBusy)
            .help("Generate a rule-based draft for the selected delivery")
        }

        ToolbarItem(id: "ack", placement: .primaryAction) {
            Button {
                runOnSelection { await store.ack($0) }
            } label: {
                Label("Ack", systemImage: "checkmark")
            }
            .disabled(store.selectedItem == nil || isBusy)
            .help("Acknowledge the selected delivery")
        }

        ToolbarItem(id: "ignore", placement: .primaryAction) {
            Button {
                runOnSelection { _ = await store.ignore($0) }
            } label: {
                Label("Ignore", systemImage: "nosign")
            }
            .disabled(store.selectedItem == nil || isBusy)
            .help("Ignore the selected delivery")
        }

        ToolbarItem(id: "context-file", placement: .secondaryAction) {
            Button {
                runOnSelection {
                    if let result = await store.writeContextFile(for: $0) {
                        NSWorkspace.shared.activateFileViewerSelecting(
                            [URL(fileURLWithPath: result.contextPath)]
                        )
                    }
                }
            } label: {
                Label("Write context file", systemImage: "doc.text")
            }
            .disabled(store.selectedItem == nil || isBusy)
            .help("Write this delivery as markdown for your coding assistant")
        }

        ToolbarItem(id: "filter", placement: .secondaryAction) {
            Menu {
                Picker("Filter", selection: $store.filter) {
                    ForEach(InboxStore.InboxFilter.allCases) { filter in
                        Text(filter.rawValue).tag(filter)
                    }
                }
                .pickerStyle(.inline)
            } label: {
                Label("Filter", systemImage: "line.3.horizontal.decrease.circle")
            }
            .help("Filter the inbox by delivery status")
        }

        ToolbarItem(id: "status", placement: .secondaryAction) {
            statusMenu
        }
    }

    // One glanceable status item instead of separate refresh/watch/stream
    // controls: polling and streaming always run; this shows their health.
    private var statusMenu: some View {
        Menu {
            Text(streamStatusText)
            if let lastRefresh = store.lastRefresh {
                Text("Last checked \(lastRefresh.formatted(date: .omitted, time: .standard))")
            }
            Text("\(store.awaitingCount) awaiting decision")
            Divider()
            Button("Refresh Now") {
                Task { await store.refresh() }
            }
            .keyboardShortcut("r", modifiers: [.command, .shift])
            Toggle("Pause Notifications", isOn: $store.notificationsPaused)
            Toggle("Show Message Text in Notifications", isOn: $store.showContentInNotifications)
                .help("Off by default: notification banners are readable on a locked screen.")
        } label: {
            Label("Status", systemImage: statusSymbol)
                .foregroundStyle(statusColor)
        }
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
        switch store.streamState {
        case .connected: return "Connected via stream — new deliveries arrive instantly"
        case .connecting: return "Stream connecting — polling in the meantime"
        case .down: return "Stream down — falling back to polling"
        case .failed(let message): return "Stream disabled (\(message)) — polling only; check Settings"
        case .off: return "Polling every \(Int(max(store.config.pollInterval, 5)))s (no stream URL configured)"
        }
    }

    // MARK: - Helpers

    private var subtitle: String {
        if let handle = store.agent?.handle {
            return handle
        }
        return store.config.isConfigured ? store.config.agentHandle : "Not configured — open Settings (⌘,)"
    }

    private func runOnSelection(_ action: @escaping (String) async -> Void) {
        guard let id = store.selectedItem?.id else { return }
        runOnDelivery(id, action)
    }

    private func runOnDelivery(_ id: String, _ action: @escaping (String) async -> Void) {
        isBusy = true
        Task {
            await action(id)
            isBusy = false
        }
    }

    private func replyComposer(_ target: SheetTarget) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Reply to \(target.senderDisplay)")
                .font(.headline)
            TextEditor(text: $replyText)
                .font(.body)
                .frame(minWidth: 420, minHeight: 160)
                .border(.separator)
            HStack {
                Spacer()
                Button("Cancel") { replyTarget = nil }
                    .keyboardShortcut(.cancelAction)
                Button("Send reply") {
                    let content = replyText.trimmingCharacters(in: .whitespacesAndNewlines)
                    replyTarget = nil
                    runOnDelivery(target.id) { _ = await store.reply(to: $0, content: content) }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding()
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
                Image(systemName: "xmark")
            }
            .buttonStyle(.plain)
        }
        .padding(10)
        .background(.bar)
    }
}
