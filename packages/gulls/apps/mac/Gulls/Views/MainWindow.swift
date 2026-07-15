import SwiftUI

struct MainWindow: View {
    @Bindable var store: InboxStore
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        NavigationSplitView {
            InboxListView(store: store)
                .navigationSplitViewColumnWidth(min: 260, ideal: 320)
        } detail: {
            if let item = store.selectedItem {
                DeliveryDetailView(store: store, item: item)
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
        .toolbar {
            ToolbarItemGroup {
                if store.streamState != .off {
                    streamIndicator
                }
                if store.isRefreshing {
                    ProgressView().controlSize(.small)
                }
                Button {
                    Task { await store.refresh() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .disabled(!store.config.isConfigured)
                Toggle(isOn: pollingBinding) {
                    Label("Watch", systemImage: "eye")
                }
                .toggleStyle(.button)
                .disabled(!store.config.isConfigured)
                .help("Poll the inbox and show a notification for new deliveries")
            }
        }
        .safeAreaInset(edge: .bottom) {
            if let error = store.lastError {
                errorBar(error)
            }
        }
        .task {
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

    private var streamIndicator: some View {
        Image(systemName: "bolt.fill")
            .foregroundStyle(store.streamState == .connected ? Color.green : Color.secondary)
            .help(streamHelp)
    }

    private var streamHelp: String {
        switch store.streamState {
        case .connected: return "Stream connected — new deliveries arrive instantly"
        case .connecting: return "Stream connecting…"
        case .down: return "Stream down — falling back to polling"
        case .off: return ""
        }
    }

    private var subtitle: String {
        if let handle = store.agent?.handle {
            return handle
        }
        return store.config.isConfigured ? store.config.agentHandle : "Not configured — open Settings (⌘,)"
    }

    private var pollingBinding: Binding<Bool> {
        Binding(
            get: { store.isPolling },
            set: { enabled in
                if enabled {
                    store.startPolling()
                } else {
                    store.stopPolling()
                }
            }
        )
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
