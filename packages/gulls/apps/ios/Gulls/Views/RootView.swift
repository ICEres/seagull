import SwiftUI

struct RootView: View {
    @Environment(MobileAppStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase
    @State private var showingSettings = false
    @State private var selectedTab: WorkspaceTab = .overview
    @State private var isPrepared = false

    private enum WorkspaceTab: String, Hashable {
        case overview, messages, gulls
    }

    var body: some View {
        Group {
            if !isPrepared || store.isRestoring {
                VStack(spacing: 20) {
                    GullWing(name: .classic)
                        .stroke(GullsTheme.accent, style: StrokeStyle(lineWidth: 4, lineCap: .round))
                        .frame(width: 72, height: 32)
                        .accessibilityHidden(true)
                    ProgressView("Opening Gulls…")
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(GullsTheme.background)
            } else if store.isSignedIn {
                workspace
            } else {
                SignInView()
            }
        }
        .task {
            guard !isPrepared else { return }
            await store.prepare()
            isPrepared = true
        }
        .onChange(of: scenePhase) { _, phase in
            guard isPrepared else { return }
            if phase == .active {
                Task { await store.refresh() }
            }
        }
        .onChange(of: store.isSignedIn) { _, signedIn in
            if !signedIn {
                showingSettings = false
                selectedTab = .overview
            }
        }
    }

    private var workspace: some View {
        Group {
            if #available(iOS 26, *) {
                tabs.tabBarMinimizeBehavior(.onScrollDown)
            } else {
                tabs
            }
        }
        .sheet(isPresented: $showingSettings) {
            SettingsView()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .id(store.userID)
    }

    private var tabs: some View {
        TabView(selection: $selectedTab) {
            Tab("Overview", systemImage: "circle.hexagongrid", value: .overview) {
                NavigationStack {
                    OverviewView()
                        .toolbar { accountToolbar }
                }
            }
            Tab("Messages", systemImage: "bubble.left.and.bubble.right", value: .messages) {
                NavigationStack {
                    MessagesView()
                        .toolbar { accountToolbar }
                }
            }
            Tab("Gulls", image: "GullTab", value: .gulls) {
                NavigationStack {
                    GullsView()
                        .toolbar { accountToolbar }
                }
            }
        }
    }

    @ToolbarContentBuilder
    private var accountToolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                showingSettings = true
            } label: {
                Image(systemName: "person.crop.circle")
                    .imageScale(.large)
                    .frame(minWidth: 44, minHeight: 44)
            }
            .accessibilityLabel("Account and settings")
            .accessibilityIdentifier("account-settings")
        }
    }
}
