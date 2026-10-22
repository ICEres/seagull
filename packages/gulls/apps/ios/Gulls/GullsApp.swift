import SwiftUI

@main
struct GullsApp: App {
    @State private var store: MobileAppStore = {
        #if DEBUG
        if CommandLine.arguments.contains("--preview") || ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil { return .preview() }
        #endif
        return MobileAppStore()
    }()
    @AppStorage("gulls.appearance") private var appearance = GullsAppearance.system.rawValue

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(store)
                .tint(GullsTheme.accent)
                .preferredColorScheme(GullsAppearance(rawValue: appearance)?.colorScheme)
        }
    }
}
