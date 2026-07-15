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
        _store = State(initialValue: InboxStore(cli: cli, config: config, notifier: notifier))
    }

    var body: some Scene {
        WindowGroup {
            MainWindow(store: store)
        }
        .defaultSize(width: 900, height: 600)

        Settings {
            SettingsView(config: store.config, cli: cli)
        }
    }
}
