import SwiftUI

@main
struct GullsApp: App {
    @State private var workspace: GullsWorkspace
    @State private var account: CloudAccountStore
    @State private var lifecycle: AppLifecycleCoordinator
    private let isTestHost: Bool

    init() {
        let isTestHost = ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
        self.isTestHost = isTestHost
        let cli = isTestHost ? nil : GullsCLI.bundled()
        let notifier = Notifier()
        if !isTestHost { notifier.activate() }
        // Hosted unit tests must not load real paired credentials or start
        // background polling against the user's cloud account.
        let defaults = isTestHost
            ? UserDefaults(suiteName: "ai.gulls.test-host.\(UUID().uuidString)")!
            : .standard
        let connections = isTestHost
            ? LocalConnectionsStore(defaults: defaults, tokenStore: TestHostTokenStore())
            : LocalConnectionsStore()
        let workspace = GullsWorkspace(connections: connections, cli: cli, notifier: notifier,
                                       notifiedDirectory: isTestHost ? FileManager.default.temporaryDirectory : nil,
                                       localControlDefaults: defaults)
        _workspace = State(initialValue: workspace)
        let account = CloudAccountStore(defaults: defaults, cli: cli,
                                        sharedSessionURL: isTestHost ? nil : SharedCloudSessionFile.defaultURL)
        _account = State(initialValue: account)
        let lifecycle = AppLifecycleCoordinator(
            workspace: workspace,
            account: account,
            isTestHost: isTestHost
        )
        _lifecycle = State(initialValue: lifecycle)
        // Terminate app-owned monitoring and approved local commands on quit.
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification,
            object: nil,
            queue: .main
        ) { _ in
            MainActor.assumeIsolated {
                account.cancelBrowserSignIn()
                lifecycle.stopForTermination()
            }
        }
    }

    var body: some Scene {
        Window("Gulls", id: "workspace") {
            WorkspaceWindow(workspace: workspace, account: account, lifecycle: lifecycle)
        }
        .defaultSize(width: 980, height: 720)
        .windowToolbarStyle(.unified)

        MenuBarExtra {
            GullsMenuBarView(workspace: workspace, lifecycle: lifecycle)
        } label: {
            GullsMenuBarLabel(workspace: workspace, lifecycle: lifecycle)
        }

        Settings {
            SettingsView(workspace: workspace, account: account)
        }
        .windowResizability(.contentSize)
    }
}

private struct WorkspaceWindow: View {
    @Bindable var workspace: GullsWorkspace
    let account: CloudAccountStore
    let lifecycle: AppLifecycleCoordinator
    @Environment(\.openSettings) private var openSettings
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        MainWindow(store: workspace.selectedStore, workspace: workspace, account: account)
            .task { lifecycle.start() }
            .onAppear {
                workspace.onOpenWorkspace = {
                    openWindow(id: "workspace")
                    NSApp.activate(ignoringOtherApps: true)
                }
                if !ProcessInfo.processInfo.environment.keys.contains("XCTestConfigurationFilePath"),
                   workspace.connections.profiles.allSatisfy({ !$0.isConfigured }) {
                    openSettings()
                }
            }
            .onChange(of: workspace.attentionCount) { _, _ in workspace.updateBadge() }
    }
}

private struct TestHostTokenStore: GullsTokenStore {
    func token(for profileID: String) -> String? { nil }
    func legacyToken() -> String? { nil }
    func setToken(_ token: String, for profileID: String) -> Bool { true }
}
