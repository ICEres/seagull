import SwiftUI

struct ServerSettingsView: View {
    private enum Action {
        case provider, credits, routing
    }

    @Bindable var account: CloudAccountStore
    @State private var provider = "openai"
    @State private var enabled = true
    @State private var models = ""
    @State private var apiKey = ""
    @State private var secretRef = ""
    @State private var region = ""
    @State private var changeReason = ""
    @State private var grantAmount = ""
    @State private var grantReason = ""
    @State private var routeMatch = ""
    @State private var routeName = "Map links"
    @State private var routeToHandle = ""
    @State private var routeMode = "copy"
    @State private var status: String?
    @State private var statusIsError = false
    @State private var statusAction: Action?
    @State private var isSaving = false
    @State private var initializedProviderSession: UUID?
    @State private var isRefreshing = false

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            HStack(spacing: 12) {
                Spacer()
                Button("Refresh", systemImage: "arrow.clockwise") { Task { await refreshServer() } }
                    .buttonStyle(.borderless)
                    .help("Refresh server")
                    .disabled(isRefreshing)
            }
            if let error = account.error {
                CloudSettingsStatus(message: error, isError: true)
                Button("Try again") { Task { await refreshServer() } }
                    .disabled(isRefreshing)
            }
            servicesSection
            if account.isAdmin {
                providerSection
                creditsSection
                routingSection
                activitySection
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .task(id: account.sessionID) {
            initializeProvider()
            await refreshServer()
            initializeProvider()
        }
        .onChange(of: account.serverSnapshot) { _, _ in initializeProvider() }
        .onChange(of: provider) { _, value in
            guard !isSaving, let config = account.serverSnapshot?.providerConfigs.first(where: { $0.provider == value }) else { return }
            loadProviderConfig(config)
        }
    }

    private var servicesSection: some View {
        CloudSettingsSection("Services", detail: "Cloud runtime health and shared allowance.") {
            if let server = account.serverSnapshot {
                CloudSettingsRow("Service health") {
                    HStack(spacing: 12) {
                        ForEach(["social", "message", "provider"], id: \.self) { service in
                            Label(serviceName(for: service), systemImage: server.health[service]?.ok == true ? "checkmark.circle.fill" : "circle")
                                .font(.caption.weight(.medium))
                                .foregroundStyle(server.health[service]?.ok == true ? .green : .secondary)
                        }
                    }
                }
                if let balance = server.serverBalance {
                    CloudAllowanceProgress(
                        title: "Server pool remaining",
                        available: balance.availableCredits,
                        total: server.serverLedger.reduce(0) { $0 + max($1.creditDelta, 0) },
                        usedLabel: "allocated to users"
                    )
                } else if account.isAdmin {
                    CloudSettingsRow("Server allowance", detail: "Available credits") {
                        Text("Unavailable").font(.caption)
                    }
                }
            } else {
                ProgressView("Loading server status…")
            }
            if !account.isAdmin {
                Text("Server administration requires an administrator account.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var providerSection: some View {
        CloudSettingsSection("AI provider", detail: "Controls which model handles cloud replies.") {
            if let config = account.serverSnapshot?.providerConfigs.first(where: { $0.provider == provider }) {
                CloudSettingsRow(displayName(for: config.provider), detail: config.allowedModels.joined(separator: ", ").isEmpty ? "All models allowed" : config.allowedModels.joined(separator: ", ")) {
                    Label(config.enabled ? "Enabled" : "Disabled", systemImage: config.enabled ? "checkmark.circle.fill" : "pause.circle")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(config.enabled ? .green : .secondary)
                }
            } else {
                CloudSettingsRow(displayName(for: provider), detail: provider) { Text("Not configured").font(.caption).foregroundStyle(.secondary) }
            }
            Text("Credentials stay on the server and are never persisted by this Mac.")
                .font(.caption).foregroundStyle(.secondary)
            CloudSettingsRow("Provider") {
                TextField("openai", text: $provider).cloudSettingsField().frame(maxWidth: 220).disabled(isSaving)
            }
            CloudSettingsRow("Enabled") { Toggle("", isOn: $enabled).labelsHidden().disabled(isSaving) }
            CloudSettingsRow("Allowed models") {
                TextField("Comma separated", text: $models).cloudSettingsField().frame(maxWidth: 300).disabled(isSaving)
            }
            CloudSettingsRow("API key") {
                SecureField("Leave blank to keep the existing key", text: $apiKey)
                    .cloudSettingsField().frame(maxWidth: 300).disabled(isSaving)
            }
            CloudSettingsRow("Secret reference") {
                TextField("Existing server secret", text: $secretRef)
                    .cloudSettingsField().frame(maxWidth: 300).disabled(isSaving)
            }
            CloudSettingsRow("Region") {
                TextField("Optional", text: $region)
                    .cloudSettingsField().frame(maxWidth: 300).disabled(isSaving)
            }
            CloudSettingsRow("Reason") {
                TextField("Reason for change", text: $changeReason)
                    .cloudSettingsField().frame(maxWidth: 300).disabled(isSaving)
            }
            HStack(spacing: 10) {
                Button(isSaving && statusAction == .provider ? "Updating…" : "Update provider") { Task { await saveProvider() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(isSaving)
                if isSaving { ProgressView().controlSize(.small) }
            }
            actionStatus(.provider)
        }
        .disabled(isRefreshing)
    }

    private var creditsSection: some View {
        CloudSettingsSection("Server credits", detail: "Grant allowance to the shared server pool.") {
            CloudSettingsRow("Amount") {
                TextField("Credits", text: $grantAmount)
                    .cloudSettingsField()
                    .frame(width: 110)
                    .disabled(isSaving)
            }
            CloudSettingsRow("Reason") {
                TextField("Why are you adding credits?", text: $grantReason)
                    .cloudSettingsField()
                    .disabled(isSaving)
            }
            Button(isSaving ? "Granting…" : "Grant credits") { Task { await grantCredits() } }
                .buttonStyle(.bordered)
                .disabled(isSaving || !canGrantCredits)
            actionStatus(.credits)
        }
    }

    private var routingSection: some View {
        VStack(alignment: .leading, spacing: 24) {
            CloudSettingsSection("Create routing rule", detail: "Route messages that contain a matching URL.") {
                CloudSettingsRow("Rule name") {
                    TextField("Name", text: $routeName).cloudSettingsField().disabled(isSaving)
                }
                CloudSettingsRow("URL contains") {
                    TextField("Matching text", text: $routeMatch).cloudSettingsField().disabled(isSaving)
                }
                CloudSettingsRow("Mode") {
                    Picker("Mode", selection: $routeMode) {
                        Text("Copy").tag("copy")
                        Text("Handoff").tag("handoff")
                        Text("Review").tag("review")
                        Text("Direct").tag("direct")
                        Text("Block").tag("block")
                    }
                    .disabled(isSaving)
                }
                CloudSettingsRow("Route to handle") {
                    TextField("Gull handle", text: $routeToHandle)
                        .cloudSettingsField()
                        .disabled(routeMode == "block" || isSaving)
                }
                Button("Create rule") { Task { await createRoute() } }
                    .buttonStyle(.bordered)
                    .disabled(isSaving || routeName.trimmingCharacters(in: .whitespaces).isEmpty || routeMatch.trimmingCharacters(in: .whitespaces).isEmpty || (routeMode != "block" && routeToHandle.trimmingCharacters(in: .whitespaces).isEmpty))
                actionStatus(.routing)
            }
            if let snapshot = account.serverSnapshot {
                CloudSettingsSection("Routing rules") {
                    if snapshot.routingRules.isEmpty { Text("No routing rules yet.").foregroundStyle(.secondary) }
                    ForEach(snapshot.routingRules) { rule in
                        CloudSettingsRow(rule.name, detail: "\(rule.urlContains.joined(separator: ", ")) · \(rule.mode)") {
                            Text(rule.enabled ? "Enabled" : "Disabled").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var activitySection: some View {
        if let snapshot = account.serverSnapshot {
            CloudSettingsSection("Server ledger") {
                if snapshot.serverLedger.isEmpty { Text("No credit changes yet.").foregroundStyle(.secondary) }
                ForEach(snapshot.serverLedger) { entry in
                    CloudSettingsRow(entry.reason, detail: CloudSettingsDate.label(entry.createdAt)) {
                        Text("\(entry.creditDelta >= 0 ? "+" : "")\(entry.creditDelta)").font(.caption.monospacedDigit())
                    }
                }
            }
            CloudSettingsSection("Moderation") {
                if snapshot.moderationRecords.isEmpty { Text("Nothing flagged.").foregroundStyle(.secondary) }
                ForEach(snapshot.moderationRecords) { record in
                    CloudSettingsRow(record.action, detail: "\(record.targetType) · \(record.targetID)") {
                        Text(record.status).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            CloudSettingsSection("Admin audit") {
                if snapshot.auditEvents.isEmpty { Text("No admin changes yet.").foregroundStyle(.secondary) }
                ForEach(snapshot.auditEvents) { event in
                    CloudSettingsRow(event.action, detail: "\(event.targetType)/\(event.targetID) · \(CloudSettingsDate.label(event.createdAt))") {
                        Text(event.reason ?? "").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        } else {
            ProgressView("Loading server activity…")
        }
    }

    private func refreshServer() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        await account.refreshServer()
    }

    @ViewBuilder
    private func actionStatus(_ action: Action) -> some View {
        if statusAction == action, let status {
            CloudSettingsStatus(message: status, isError: statusIsError)
        }
    }

    private func saveProvider() async {
        guard account.isAdmin, !isSaving else { return }
        let draft = CloudProviderDraft(
            provider: provider,
            enabled: enabled,
            allowedModels: models.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) },
            apiKey: apiKey.isEmpty ? nil : apiKey,
            secretRef: secretRef.isEmpty ? nil : secretRef,
            region: region.isEmpty ? nil : region,
            reason: changeReason
        )
        isSaving = true
        statusAction = .provider
        status = nil
        defer { isSaving = false }
        do {
            try await account.saveProvider(draft)
            apiKey = ""
            status = "Provider updated"
            statusIsError = false
        } catch {
            status = error.localizedDescription
            statusIsError = true
        }
    }

    private func grantCredits() async {
        guard account.isAdmin, !isSaving else { return }
        let requestedAmount = grantAmount
        let requestedReason = grantReason
        guard let amount = Int(requestedAmount), amount > 0 else {
            status = "Enter a positive credit amount"
            statusIsError = true
            return
        }
        isSaving = true
        statusAction = .credits
        status = nil
        defer { isSaving = false }
        do {
            try await account.grantServerCredits(amount: amount, reason: requestedReason)
            grantAmount = ""
            grantReason = ""
            status = "Credits granted"
            statusIsError = false
        } catch {
            status = error.localizedDescription
            statusIsError = true
        }
    }

    private func createRoute() async {
        guard account.isAdmin, !isSaving else { return }
        let draft = CloudRoutingRuleDraft(
            name: routeName,
            mode: routeMode,
            routeToHandles: routeMode == "block" ? [] : [routeToHandle],
            urlContains: routeMatch.isEmpty ? [] : [routeMatch],
            enabled: true
        )
        isSaving = true
        statusAction = .routing
        status = nil
        defer { isSaving = false }
        do {
            try await account.createRoutingRule(draft)
            routeName = "Map links"
            routeMatch = ""
            routeToHandle = ""
            status = "Routing rule created"
            statusIsError = false
        } catch {
            status = error.localizedDescription
            statusIsError = true
        }
    }

    private func loadProviderConfig(_ config: CloudProviderConfig) {
        provider = config.provider
        enabled = config.enabled
        models = config.allowedModels.joined(separator: ", ")
        secretRef = config.secretRef ?? ""
        region = config.region ?? ""
    }

    private func initializeProvider() {
        guard initializedProviderSession != account.sessionID,
              let config = account.serverSnapshot?.providerConfigs.first else { return }
        initializedProviderSession = account.sessionID
        loadProviderConfig(config)
    }

    private func displayName(for provider: String) -> String {
        switch provider.lowercased() {
        case "openai": return "OpenAI"
        case "bedrock": return "Amazon Bedrock"
        default: return provider.isEmpty ? "AI provider" : provider.capitalized
        }
    }

    private var canGrantCredits: Bool {
        (Int(grantAmount.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0) > 0
    }

    private func serviceName(for service: String) -> String {
        switch service {
        case "social": return "Profiles"
        case "message": return "Messages"
        case "provider": return "AI"
        default: return service.capitalized
        }
    }
}
