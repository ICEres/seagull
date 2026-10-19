import SwiftUI

struct SettingsView: View {
    @Bindable var workspace: GullsWorkspace
    @Bindable var account: CloudAccountStore
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var section: Section = .account
    @State private var pairingGull: CloudGull?

    private enum Section: String, CaseIterable, Identifiable {
        case account = "Account"
        case usage = "AI usage"
        case gulls = "My Gulls"
        case local = "This Mac"
        case server = "Server"

        var id: String { rawValue }
        var symbol: String? {
            switch self {
            case .account: return "person.crop.circle"
            case .gulls: return nil
            case .usage: return "chart.bar"
            case .server: return "server.rack"
            case .local: return "desktopcomputer"
            }
        }
    }

    private struct SectionFrames: PreferenceKey {
        static let defaultValue: [Section: CGRect] = [:]

        static func reduce(value: inout [Section: CGRect], nextValue: () -> [Section: CGRect]) {
            value.merge(nextValue(), uniquingKeysWith: { _, next in next })
        }
    }

    private var visibleSections: [Section] {
        Section.allCases.filter { $0 != .server || account.isAdmin }
    }

    var body: some View {
        ScrollViewReader { proxy in
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 22) {
                    navigationGroup("Personal", sections: [.account, .usage], proxy: proxy)
                    navigationGroup("Gulls", sections: [.gulls, .local], proxy: proxy)
                    if account.isAdmin {
                        navigationGroup("Administration", sections: [.server], proxy: proxy)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 12)
                .padding(.top, 18)
                .frame(width: 174)

                settingsLayout(proxy: proxy)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .gullsScrollEdges()
            }
            .onChange(of: account.isAdmin) { _, isAdmin in
                if section == .server, !isAdmin { scroll(to: .account, using: proxy) }
            }
        }
        .background(GullsStyle.canvas)
        .tint(GullsStyle.accent)
        .navigationTitle("Settings")
        .toolbarBackground(.hidden, for: .windowToolbar)
        .gullsWindowChrome()
        .frame(width: 800, height: 580)
        .background {
            Button("Close Settings") { dismiss() }
                .keyboardShortcut(.cancelAction)
                .hidden()
        }
    }

    private func navigationGroup(_ title: String, sections: [Section], proxy: ScrollViewProxy) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 12)
                .padding(.bottom, 4)
                .accessibilityAddTraits(.isHeader)
            ForEach(sections) { item in
                Button {
                    scroll(to: item, using: proxy)
                } label: {
                    HStack(spacing: 8) {
                        if let symbol = item.symbol {
                            Image(systemName: symbol).frame(width: 18)
                        } else {
                            GullWing(name: .classic)
                                .stroke(style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round))
                                .frame(width: 18, height: 12)
                        }
                        Text(item.rawValue)
                    }
                    .font(.subheadline.weight(section == item ? .semibold : .regular))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .contentShape(RoundedRectangle(cornerRadius: 10))
                }
                .buttonStyle(.plain)
                .background(section == item ? GullsStyle.field : .clear, in: RoundedRectangle(cornerRadius: 10))
                .accessibilityAddTraits(section == item ? .isSelected : [])
            }
        }
    }

    private func scroll(to destination: Section, using proxy: ScrollViewProxy) {
        if reduceMotion {
            proxy.scrollTo(destination, anchor: .top)
        } else {
            withAnimation(.easeInOut(duration: 0.25)) {
                proxy.scrollTo(destination, anchor: .top)
            }
        }
    }

    @ViewBuilder
    private func settingsLayout(proxy: ScrollViewProxy) -> some View {
        if #available(macOS 26.0, *), !reduceTransparency {
            settingsPage(proxy: proxy).safeAreaBar(edge: .top, spacing: 0) { header }
        } else {
            settingsPage(proxy: proxy).safeAreaInset(edge: .top, spacing: 0) {
                header.background(GullsStyle.canvas)
            }
        }
    }

    private var header: some View {
        HStack {
            GullsPageTitle(section.rawValue).font(.title3.weight(.semibold))
            Spacer()
            Text("Preferences save automatically")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 14)
    }

    private func settingsPage(proxy: ScrollViewProxy) -> some View {
        GeometryReader { viewport in
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(visibleSections) { item in
                        VStack(alignment: .leading, spacing: 0) {
                            GullsPageTitle(item.rawValue)
                                .font(.title2.weight(.semibold))
                                .accessibilityAddTraits(.isHeader)
                                .padding(.horizontal, 24)
                                .padding(.top, 24)
                            sectionContent(item, proxy: proxy)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .id(item)
                        .background {
                            GeometryReader { geometry in
                                Color.clear.preference(key: SectionFrames.self, value: [
                                    item: geometry.frame(in: .named("settingsScroll"))
                                ])
                            }
                        }
                    }
                }
                .padding(.bottom, 24)
            }
            .coordinateSpace(name: "settingsScroll")
            .gullsHiddenScrollbars()
            .onPreferenceChange(SectionFrames.self) { frames in
                let atBottom = frames.values.map(\.maxY).max().map { $0 <= viewport.size.height } ?? false
                let visible = atBottom ? visibleSections.last : visibleSections.last {
                    (frames[$0]?.minY ?? .infinity) <= 36
                }
                if let visible, visible != section { section = visible }
            }
        }
    }

    @ViewBuilder
    private func sectionContent(_ item: Section, proxy: ScrollViewProxy) -> some View {
        switch item {
        case .account:
            AccountSettingsView(account: account)
        case .local:
            LocalConnectionsView(workspace: workspace, account: account, pairingGull: $pairingGull)
        case .gulls, .usage, .server:
            if account.isSignedIn {
                switch item {
                case .gulls:
                    GullSettingsView(account: account, onPair: { gull in
                        pairingGull = gull
                        scroll(to: .local, using: proxy)
                    })
                case .usage:
                    AIUsageSettingsView(account: account)
                default:
                    ServerSettingsView(account: account)
                }
            } else {
                CloudSettingsSection("Sign in to your account", detail: "Manage your Gulls and cloud settings with your email account.") {
                    Button("Sign in") {
                        scroll(to: .account, using: proxy)
                        account.startBrowserSignIn()
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!account.canStartBrowserSignIn)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(24)
            }
        }
    }
}
