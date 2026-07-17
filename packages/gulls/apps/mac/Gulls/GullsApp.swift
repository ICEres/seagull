import SwiftUI

@main
struct GullsApp: App {
    @State private var store: InboxStore

    private let cli: GullsCLI?

    init() {
        let cli = GullsCLI.bundled()
        let config = GullsConfig()
        let notifier = Notifier()
        notifier.activate()
        self.cli = cli
        let store = InboxStore(cli: cli, config: config, notifier: notifier)
        _store = State(initialValue: store)
        // Terminate the stream subprocess on quit — otherwise it lingers
        // until its next stdout write hits the closed pipe.
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification,
            object: nil,
            queue: .main
        ) { _ in
            MainActor.assumeIsolated {
                store.stopStreaming()
            }
        }
    }

    var body: some Scene {
        WindowGroup {
            MainWindow(store: store)
        }
        .defaultSize(width: 900, height: 600)
        .windowToolbarStyle(.unified)

        Settings {
            SettingsView(config: store.config, cli: cli)
        }
    }
}
