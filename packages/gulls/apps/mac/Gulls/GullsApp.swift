import SwiftUI

@main
struct GullsApp: App {
    @State private var workspace: GullsWorkspace
    @State private var account: CloudAccountStore
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
        // Terminate the stream subprocess on quit — otherwise it lingers
        // until its next stdout write hits the closed pipe.
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification,
            object: nil,
            queue: .main
        ) { _ in
            MainActor.assumeIsolated {
                workspace.stopAll()
                account.cancelBrowserSignIn()
            }
        }
    }

    var body: some Scene {
        WindowGroup {
            WorkspaceWindow(workspace: workspace, account: account, isTestHost: isTestHost)
        }
        .defaultSize(width: 980, height: 720)
        .windowToolbarStyle(.unified)

        Settings {
            SettingsView(workspace: workspace, account: account)
        }
        .windowResizability(.contentSize)
    }
}

private struct WorkspaceWindow: View {
    @Bindable var workspace: GullsWorkspace
    let account: CloudAccountStore
    let isTestHost: Bool
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        MainWindow(store: workspace.selectedStore, workspace: workspace, account: account)
            .task(id: workspace.configurationKey) {
                guard !isTestHost else { return }
                try? await Task.sleep(for: .milliseconds(300))
                guard !Task.isCancelled else { return }
                await workspace.reconcile()
                if workspace.connections.profiles.allSatisfy({ !$0.isConfigured }) { openSettings() }
            }
            .onChange(of: workspace.attentionCount) { _, _ in workspace.updateBadge() }
            .task {
                guard !isTestHost else { return }
                while !Task.isCancelled {
                    workspace.refreshLocalActions()
                    try? await Task.sleep(for: .seconds(2))
                }
            }
            .task {
                guard !isTestHost else { return }
                while !Task.isCancelled {
                    await account.synchronizeSharedSession()
                    try? await Task.sleep(for: .seconds(5))
                }
            }
    }
}

private struct TestHostTokenStore: GullsTokenStore {
    func token(for profileID: String) -> String? { nil }
    func legacyToken() -> String? { nil }
    func setToken(_ token: String, for profileID: String) -> Bool { true }
}
