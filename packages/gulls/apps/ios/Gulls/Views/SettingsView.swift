import SwiftUI

struct SettingsView: View {
    @Environment(MobileAppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @AppStorage("gulls.appearance") private var appearance = GullsAppearance.system.rawValue
    @State private var showingSignOut = false
    @State private var isRefreshing = false

    private enum SectionID: String, CaseIterable, Identifiable {
        case account = "Account", appearance = "Appearance", usage = "AI usage", server = "Server"
        var id: String { rawValue }
    }

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                VStack(spacing: 0) {
                    HStack(spacing: 8) {
                        ForEach(SectionID.allCases) { section in
                            Button(section.rawValue) {
                                withAnimation(reduceMotion ? nil : .smooth(duration: 0.3)) {
                                    proxy.scrollTo(section, anchor: .top)
                                }
                            }
                            .font(.footnote.weight(.medium))
                            .lineLimit(1)
                            .minimumScaleFactor(0.85)
                            .frame(maxWidth: .infinity, minHeight: 44)
                        }
                    }
                    .padding(.horizontal, 16)
                    .buttonStyle(.plain)
                    .foregroundStyle(GullsTheme.accent)

                    Form {
                        accountSection.listRowBackground(GullsTheme.surface).id(SectionID.account)
                        appearanceSection.listRowBackground(GullsTheme.surface).id(SectionID.appearance)
                        usageSection.listRowBackground(GullsTheme.surface).id(SectionID.usage)
                        serverSection.listRowBackground(GullsTheme.surface).id(SectionID.server)
                        Section {
                            Button("Sign out", role: .destructive) { showingSignOut = true }
                                .frame(minHeight: 32)
                        }
                        .listRowBackground(GullsTheme.surface)
                    }
                    .scrollContentBackground(.hidden)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    GullsPageTitle("Settings").font(.headline)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .refreshable { await refresh() }
            .task { await refresh() }
            .confirmationDialog("Sign out of Gulls on this iPhone?", isPresented: $showingSignOut, titleVisibility: .visible) {
                Button("Sign out", role: .destructive) { store.signOut(); dismiss() }
            } message: {
                Text("Your Gulls will continue running in the cloud.")
            }
        }
        .gullsSheet()
    }

    private var accountSection: some View {
        Section {
            HStack(spacing: 14) {
                Image(systemName: "person.crop.circle")
                    .font(.largeTitle)
                    .foregroundStyle(GullsTheme.accent)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 5) {
                    Text(store.accountLabel).font(.headline)
                    if let email = store.account?.email, email != store.accountLabel {
                        Text(email).font(.subheadline).foregroundStyle(.secondary)
                    }
                    Text(store.isAdmin ? "Administrator" : "Gulls account")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .textSelection(.enabled)
            }
            .padding(.vertical, 8)
            if let url = URL(string: store.websiteURL) {
                Link(destination: url) {
                    Label("Open Gulls on the web", systemImage: "arrow.up.right.square")
                        .frame(minHeight: 32)
                }
            }
        } header: { Text("Account") }
    }

    private var appearanceSection: some View {
        Section {
            Picker("Color scheme", selection: $appearance) {
                ForEach(GullsAppearance.allCases) { option in
                    Text(option.title).tag(option.rawValue)
                }
            }
            .pickerStyle(.segmented)
            .padding(.vertical, 6)
        } header: { Text("Appearance") } footer: {
            Text("System follows your device. Changes apply immediately.")
        }
    }

    private var usageSection: some View {
        Section {
            if let usage = store.aiUsage {
                allowance(available: usage.balance.availableCredits, granted: usage.entries.reduce(0) { $0 + max($1.creditDelta, 0) })
                LabeledContent("Requests", value: usage.usage.count.formatted())
                LabeledContent("Tokens processed", value: usage.usage.reduce(0) { $0 + tokens($1) }.formatted())

                let groups = Dictionary(grouping: usage.usage, by: \.agentID)
                    .sorted { $0.value.reduce(0) { $0 + tokens($1) } > $1.value.reduce(0) { $0 + tokens($1) } }
                let totalTokens = max(usage.usage.reduce(0) { $0 + tokens($1) }, 1)
                ForEach(groups, id: \.key) { agentID, records in
                    let gull = store.ownedGulls.first { $0.agentID == agentID }
                    let value = records.reduce(0) { $0 + tokens($1) }
                    VStack(alignment: .leading, spacing: 10) {
                        HStack(spacing: 10) {
                            GullAvatar(handle: gull?.handle ?? agentID, size: 28)
                            Text(gull?.displayName ?? gull?.handle ?? "Gull")
                                .font(.subheadline.weight(.medium))
                            Spacer(minLength: 8)
                            Text("\(value.formatted()) tokens")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        ProgressView(value: Double(value), total: Double(totalTokens))
                            .accessibilityLabel("\(gull?.displayName ?? "Gull"), share of recorded tokens")
                    }
                    .padding(.vertical, 6)
                }
                if usage.usage.isEmpty {
                    Text("Cloud AI activity will appear after your first reply.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            } else if isRefreshing {
                ProgressView("Loading AI usage…")
            } else {
                Label("Usage is unavailable. Pull to refresh.", systemImage: "arrow.clockwise")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        } header: { Text("AI usage") } footer: {
            Text("Allowance is shared by your Gulls. Activity reflects records returned by the server.")
        }
    }

    private var serverSection: some View {
        Section {
            LabeledContent("Website") {
                Text(store.websiteURL.replacingOccurrences(of: "https://", with: ""))
                    .foregroundStyle(.secondary)
            }
            if let snapshot = store.serverSnapshot {
                ForEach(["social", "message", "provider"], id: \.self) { service in
                    HStack {
                        Text(serviceTitle(service))
                        Spacer()
                        if let health = snapshot.health[service] {
                            Label(health.ok ? "Available" : "Unavailable", systemImage: health.ok ? "checkmark.circle.fill" : "exclamationmark.circle")
                                .foregroundStyle(health.ok ? .green : .orange)
                                .font(.subheadline)
                        } else {
                            Text("Unknown").foregroundStyle(.secondary).font(.subheadline)
                        }
                    }
                }
                if store.isAdmin {
                    if let balance = snapshot.serverBalance {
                        allowance(available: balance.availableCredits, granted: snapshot.serverLedger.reduce(0) { $0 + max($1.creditDelta, 0) }, title: "Server pool")
                    }
                    ForEach(snapshot.providerConfigs) { provider in
                        VStack(alignment: .leading, spacing: 5) {
                            HStack {
                                Text(provider.provider == "openai" ? "OpenAI" : provider.provider.capitalized)
                                    .font(.subheadline.weight(.medium))
                                Spacer()
                                Text(provider.enabled ? "Enabled" : "Disabled")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Text(provider.allowedModels.joined(separator: ", "))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                    }
                    ForEach(snapshot.routingRules) { rule in
                        LabeledContent(rule.name, value: rule.enabled ? "Active" : "Paused")
                    }
                    if let url = URL(string: store.websiteURL + "/settings") {
                        Link("Manage server on the web", destination: url)
                            .frame(minHeight: 32)
                    }
                }
            } else if isRefreshing {
                ProgressView("Checking services…")
            } else {
                Button("Refresh server status") { Task { await refresh() } }
                    .frame(minHeight: 32)
            }
        } header: { Text("Server") }
    }

    private func allowance(available: Int, granted: Int, title: String = "Credits remaining") -> some View {
        let total = max(granted, available, 1)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).font(.subheadline)
                Spacer()
                Text(max(available, 0).formatted())
                    .font(.title2.weight(.semibold))
                    .monospacedDigit()
            }
            ProgressView(value: Double(max(available, 0)), total: Double(total))
                .accessibilityLabel(title)
                .accessibilityValue("\(max(available, 0)) credits")
        }
        .padding(.vertical, 8)
    }

    private func tokens(_ record: CloudUsageRecord) -> Int {
        record.totalTokens ?? (record.inputTokens + record.outputTokens)
    }

    private func serviceTitle(_ service: String) -> String {
        switch service {
        case "social": "Accounts"
        case "message": "Messages"
        default: "Cloud AI"
        }
    }

    private func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        _ = await store.refreshAIUsage()
        await store.refreshServer()
    }
}
