import AppKit
import SwiftUI

struct GullsMenuBarLabel: View {
    @Bindable var workspace: GullsWorkspace
    let lifecycle: AppLifecycleCoordinator
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        GullWing(name: .classic)
            .stroke(.primary, style: StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))
            .frame(width: 22, height: 12)
            .accessibilityLabel("Gulls")
            .task {
                lifecycle.start()
                workspace.onOpenWorkspace = { openWorkspace() }
            }
    }

    private func openWorkspace() {
        openWindow(id: "workspace")
        NSApp.activate(ignoringOtherApps: true)
    }
}

struct GullsMenuBarView: View {
    @Bindable var workspace: GullsWorkspace
    let lifecycle: AppLifecycleCoordinator
    @Environment(\.openWindow) private var openWindow
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        Group {
            Button("Open Gulls") { openWorkspace() }

            Divider()

            ForEach(workspace.connections.profiles, id: \.profileID) { config in
                let store = workspace.inboxes[config.profileID]
                let name = config.displayName.isEmpty ? config.agentHandle : config.displayName
                let label = name.isEmpty ? config.profileID : name
                Button {
                    workspace.setMonitoring(
                        !config.monitoringEnabled,
                        profileID: config.profileID
                    )
                } label: {
                    Label(statusLabel(for: config, store: store), systemImage: statusSymbol(for: config, store: store))
                }
                .disabled(!config.isConfigured)
                .help("Pause or resume monitoring for \(label)")
            }

            Divider()
            Text("Pending approvals: \(workspace.localControls.values.reduce(0) { $0 + $1.pendingRequests.count })")
                .foregroundStyle(.secondary)
            Divider()

            Button("Settings…") { openSettings() }
            Button("Quit Gulls") { NSApp.terminate(nil) }
        }
        .task {
            lifecycle.start()
        }
    }

    private func openWorkspace() {
        openWindow(id: "workspace")
        NSApp.activate(ignoringOtherApps: true)
    }

    private func statusLabel(for config: GullsConfig, store: InboxStore?) -> String {
        let name = config.displayName.isEmpty ? config.agentHandle : config.displayName
        let label = name.isEmpty ? config.profileID : name
        if !config.isConfigured { return "\(label): Needs setup" }
        return "\(label): \(store?.monitoringStatusText ?? (config.monitoringEnabled ? "Ready" : "Monitoring paused"))"
    }

    private func statusSymbol(for config: GullsConfig, store: InboxStore?) -> String {
        guard config.isConfigured else { return "exclamationmark.circle" }
        guard config.monitoringEnabled else { return "pause.circle" }
        if let store, store.runtimeManaged {
            switch store.runtimeStatus {
            case "connected": return "checkmark.circle"
            case "connecting", "reconnecting": return "arrow.triangle.2.circlepath"
            case "authorization_required", "unavailable": return "exclamationmark.circle"
            default: return "pause.circle"
            }
        }
        return store?.isMonitoring == true ? "checkmark.circle" : "pause.circle"
    }
}
