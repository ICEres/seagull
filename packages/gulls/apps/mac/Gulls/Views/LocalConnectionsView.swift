import AppKit
import SwiftUI

struct LocalConnectionsView: View {
    @Bindable var workspace: GullsWorkspace
    @Bindable var account: CloudAccountStore
    @Binding var pairingGull: CloudGull?
    @State private var selectedGullID = ""
    @State private var editingProfileID: String?
    @State private var controlProfileID: String?
    @State private var disconnectingProfile: GullsConfig?
    @State private var removingProfile: GullsConfig?
    @State private var isBusy = false
    @State private var status: String?
    @State private var statusIsError = false

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            settingsContent
            if let status { CloudSettingsStatus(message: status, isError: statusIsError) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 24)
        .padding(.top, 24)
        .padding(.bottom, 24)
        .task(id: account.sessionID) {
            if account.isSignedIn { await account.refreshGulls() }
            selectRequestedGull()
        }
        .onChange(of: pairingGull?.id) { _, _ in selectRequestedGull() }
        .confirmationDialog("Disconnect this Gull?", isPresented: Binding(
            get: { disconnectingProfile != nil },
            set: { if !$0 { disconnectingProfile = nil } }
        ), titleVisibility: .visible) {
            if let config = disconnectingProfile {
                Button("Disconnect \(connectionName(config))", role: .destructive) {
                    Task { await disconnect(config) }
                }
            }
        } message: {
            Text("The paired credential is revoked and Local replies switch to Manual.")
        }
        .confirmationDialog("Remove this saved connection?", isPresented: Binding(
            get: { removingProfile != nil },
            set: { if !$0 { removingProfile = nil } }
        ), titleVisibility: .visible) {
            if let config = removingProfile {
                Button("Remove from this Mac", role: .destructive) { remove(config) }
            }
        } message: {
            Text("Removes the saved connection from this app. Use Disconnect first to revoke its cloud credential.")
        }
    }

    @ViewBuilder
    private var settingsContent: some View {
        if let editingProfileID,
           let config = workspace.connections.profiles.first(where: { $0.profileID == editingProfileID }) {
            detailHeader
            CloudSettingsSection("Connection details", detail: "Advanced settings for \(connectionName(config)). Preferences save automatically. Update credentials separately.") {
                ConnectionSettingsView(config: config, cli: workspace.cli)
                    .id(config.profileID)
                if config.profileID != GullsConfig.defaultProfileID {
                    Button("Remove from this Mac", role: .destructive) { removingProfile = config }
                        .disabled(isBusy)
                }
            }
        } else if let controlProfileID,
                  let control = workspace.localControls[controlProfileID],
                  workspace.connections.profiles.contains(where: { $0.profileID == controlProfileID }) {
            detailHeader
            LocalControlView(control: control)
        } else {
            listContent
        }
    }

    private var listContent: some View {
        VStack(alignment: .leading, spacing: 24) {
            CloudSettingsSection("Gulls on this Mac", detail: "Each Gull has its own inbox, credentials, and monitoring switch.") {
                HStack {
                    Spacer()
                    Button("Add manually", systemImage: "plus") {
                        let config = workspace.connections.add()
                        workspace.synchronizeProfiles()
                        editingProfileID = config.profileID
                        controlProfileID = nil
                    }
                    .buttonStyle(.borderless)
                    .disabled(isBusy)
                }
                if workspace.connections.profiles.isEmpty {
                    Text("No local connections yet. Pair an owned Gull or add a connection manually.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                ForEach(workspace.connections.profiles, id: \.profileID) { config in
                    connectionRow(config)
                }
            }

            if account.isSignedIn {
                CloudSettingsSection("Connect an owned Gull", detail: "Pairing connects it to this Mac and switches its replies to Local automatically. It replaces the previous local connection for that Gull.") {
                    Picker("Gull", selection: $selectedGullID) {
                        Text("Choose a Gull").tag("")
                        ForEach(account.ownedGulls) { gull in
                            Text(gull.displayName ?? gull.handle).tag(gull.id)
                        }
                    }
                    HStack(spacing: 12) {
                        Button("Connect to this Mac") { Task { await connectSelectedGull() } }
                            .buttonStyle(.borderedProminent)
                            .disabled(selectedGullID.isEmpty || isBusy)
                        if isBusy { ProgressView().controlSize(.small) }
                    }
                }
            } else {
                CloudSettingsSection("Connect an owned Gull", detail: "Sign in with your browser to choose which Gulls run on this Mac.") {
                    if account.isBrowserSignInPending {
                        HStack(spacing: 10) {
                            ProgressView().controlSize(.small)
                            Text("Waiting for your browser…").font(.callout).foregroundStyle(.secondary)
                            Button("Cancel") { account.cancelBrowserSignIn() }
                        }
                    } else {
                        Button("Sign in with browser") { account.startBrowserSignIn() }
                            .buttonStyle(.borderedProminent)
                            .disabled(!account.canStartBrowserSignIn)
                    }
                    if let error = account.error { CloudSettingsStatus(message: error, isError: true) }
                }
            }

            Text("Monitoring continues with windows closed. Quit Gulls stops this Mac. Monitoring and AI replies are configured separately.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var detailHeader: some View {
        HStack {
            Button("Back to This Mac", systemImage: "chevron.left") {
                editingProfileID = nil
                controlProfileID = nil
            }
            .buttonStyle(.borderless)
            Spacer()
        }
    }

    private func connectionRow(_ config: GullsConfig) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 10) {
                Button {
                    workspace.connections.select(profileID: config.profileID)
                } label: {
                    HStack(spacing: 10) {
                        WingAvatar(identity: config.agentHandle.isEmpty ? config.profileID : config.agentHandle, size: 28)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(connectionName(config)).font(.subheadline.weight(.medium))
                            Text(config.isConfigured ? config.agentHandle : "Needs connection")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("Show this Gull’s inbox")
                Spacer(minLength: 8)
                if workspace.connections.selectedProfileID == config.profileID {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(GullsStyle.accent)
                        .help("Currently selected inbox")
                }
                Text(config.isLocallyPaired ? "Paired" : config.isConfigured ? "Configured" : "Not connected")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(config.isLocallyPaired || config.isConfigured ? Color.secondary : .orange)
                if config.isConfigured {
                    HStack(spacing: 6) {
                        Text("Monitor")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Toggle("Monitor inbox", isOn: Binding(
                            get: { config.monitoringEnabled },
                            set: { workspace.setMonitoring($0, profileID: config.profileID) }
                        ))
                        .toggleStyle(.switch)
                        .labelsHidden()
                        .help(config.monitoringEnabled ? "Pause inbox monitoring" : "Resume inbox monitoring")
                        .disabled(isBusy)
                    }
                }
                Button("Connection details", systemImage: "slider.horizontal.3") {
                    editingProfileID = config.profileID
                    controlProfileID = nil
                }
                .buttonStyle(.borderless)
            }
            if let store = workspace.inboxes[config.profileID], config.isConfigured {
                HStack(spacing: 12) {
                    Label(monitoringStatus(store),
                          systemImage: store.isMonitoring ? "circle.fill" : "pause.circle")
                        .foregroundStyle(store.lastError == nil ? Color.secondary : .orange)
                    if let date = store.lastRefresh {
                        Text("Checked \(date.formatted(date: .omitted, time: .shortened))")
                    }
                    Spacer(minLength: 0)
                    Button("Refresh") { Task { await store.refresh() } }
                        .disabled(workspace.cli == nil || store.isRefreshing || isBusy)
                    if ownedGull(for: config) != nil, config.isLocallyPaired {
                        Button("Disconnect", role: .destructive) { disconnectingProfile = config }
                            .disabled(isBusy)
                    }
                }
                .font(.caption)
                .buttonStyle(.borderless)
                if let error = store.lastError {
                    Text(error).font(.caption).foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if config.isConfigured, let control = workspace.localControls[config.profileID] {
                Button {
                    controlProfileID = config.profileID
                    editingProfileID = nil
                } label: {
                    HStack(spacing: 8) {
                        Label("Commands & files", systemImage: "terminal")
                        if !control.pendingRequests.isEmpty {
                            Text("\(control.pendingRequests.count) pending")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.right")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                    }
                }
                .font(.subheadline)
                .buttonStyle(.borderless)
                .foregroundStyle(.primary)
            }
        }
        .padding(.vertical, 5)
    }

    private func selectRequestedGull() {
        if let pairingGull {
            selectedGullID = pairingGull.id
            editingProfileID = nil
            controlProfileID = nil
        }
    }

    private func monitoringStatus(_ store: InboxStore) -> String {
        if store.runtimeManaged { return store.monitoringStatusText }
        if !store.config.monitoringEnabled { return "Paused" }
        if store.lastError != nil { return "Needs attention" }
        if store.isMonitoring { return "Monitoring" }
        return workspace.cli == nil ? "CLI unavailable" : "Starting…"
    }

    private func connectionName(_ config: GullsConfig) -> String {
        firstNonEmpty(config.displayName, workspace.inboxes[config.profileID]?.agent?.displayName,
                      config.agentHandle) ?? "New Gull"
    }

    private func ownedGull(for config: GullsConfig) -> CloudGull? {
        guard config.socialAPIURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
                == account.runtime?.socialAPIURL?.trimmingCharacters(in: CharacterSet(charactersIn: "/")) else { return nil }
        return account.ownedGulls.first { $0.handle == config.agentHandle }
    }

    private func connectSelectedGull() async {
        guard !isBusy, let gull = account.ownedGulls.first(where: { $0.id == selectedGullID }),
              let server = account.runtime?.socialAPIURL else { return }
        isBusy = true
        status = nil
        defer { isBusy = false }
        let sessionID = account.sessionID
        let previousSelection = workspace.connections.selectedProfileID
        var createdProfileID: String?
        var pairedConfig: GullsConfig?
        do {
            let pair = try await account.createLocalPairToken(for: gull)
            guard sessionID == account.sessionID, account.isSignedIn else { return }
            let config = workspace.connections.profiles.first { $0.agentHandle == gull.handle && $0.socialAPIURL == server }
                ?? workspace.connections.profiles.first { !$0.isConfigured && $0.token.isEmpty }
                ?? {
                    let added = workspace.connections.add(displayName: gull.displayName)
                    createdProfileID = added.profileID
                    return added
                }()
            workspace.inboxes[config.profileID]?.suspendMonitoring()
            _ = try await workspace.connections.pair(profileID: config.profileID, socialAPIURL: server,
                                                      pairingToken: pair.pairToken, expectedHandle: gull.handle,
                                                      session: workspace.pairingSession)
            config.displayName = gull.displayName ?? gull.handle
            config.monitoringEnabled = true
            pairedConfig = config
        } catch {
            if let createdProfileID {
                workspace.connections.remove(profileID: createdProfileID)
                workspace.connections.select(profileID: previousSelection)
            }
            await workspace.reconcile()
            status = error.localizedDescription
            statusIsError = true
            return
        }
        guard let config = pairedConfig else { return }
        workspace.synchronizeProfiles()
        workspace.connections.select(profileID: config.profileID)
        pairingGull = nil
        if sessionID == account.sessionID, account.isSignedIn {
            do {
                _ = try await account.setRuntime(for: gull, mode: .local)
                status = "\(connectionName(config)) is connected to this Mac."
                statusIsError = false
            } catch {
                status = "Paired to this Mac, but replies could not switch to Local. Choose Local under My Gulls to finish. \(error.localizedDescription)"
                statusIsError = true
            }
        } else {
            status = "Paired to this Mac. Sign in and choose Local under My Gulls to enable local replies."
            statusIsError = true
        }
        await workspace.reconcile()
    }

    private func disconnect(_ config: GullsConfig) async {
        guard !isBusy, let gull = ownedGull(for: config) else { return }
        isBusy = true
        defer { isBusy = false }
        workspace.setMonitoring(false, profileID: config.profileID)
        workspace.localControls[config.profileID]?.enabled = false
        workspace.localControls[config.profileID]?.stop()
        await workspace.reconcile()
        do {
            _ = try await account.disconnectLocalRuntime(for: gull)
            workspace.inboxes[config.profileID]?.stopMonitoring()
            guard config.setToken("") else {
                status = "The cloud connection was revoked, but Keychain could not remove the local credential."
                statusIsError = true
                return
            }
            config.nodeID = ""
            status = "\(connectionName(config)) was disconnected."
            statusIsError = false
        } catch {
            status = error.localizedDescription
            statusIsError = true
        }
    }

    private func remove(_ config: GullsConfig) {
        guard config.setToken("") else {
            status = "Keychain could not remove this credential."
            statusIsError = true
            return
        }
        workspace.inboxes[config.profileID]?.stopMonitoring()
        workspace.localControls[config.profileID]?.enabled = false
        workspace.localControls[config.profileID]?.stop()
        workspace.connections.remove(profileID: config.profileID)
        workspace.synchronizeProfiles()
        editingProfileID = nil
        status = "Saved connection removed."
        statusIsError = false
    }
}
