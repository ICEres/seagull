import SwiftUI

struct SettingsView: View {
    @Bindable var config: GullsConfig
    let cli: GullsCLI?

    @State private var connectionStatus: ConnectionStatus = .idle
    @State private var importStatus: String?
    // Edited locally and committed on Return / close — binding the SecureField
    // straight to config.token would hit the Keychain on every keystroke.
    @State private var tokenDraft = ""

    enum ConnectionStatus: Equatable {
        case idle
        case testing
        case success(String)
        case failure(String)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                settingsHeader

                settingsSection("Connection", subtitle: "Connect this Mac to your Message Hub.") {
                    settingsField("API URL") {
                        TextField("http://localhost:8200", text: $config.apiURL)
                            .textContentType(nil)
                            .autocorrectionDisabled()
                    }
                    settingsField("Agent handle") {
                        TextField("@worker:gulls.ai", text: $config.agentHandle)
                            .autocorrectionDisabled()
                    }
                    settingsField("Connector token") {
                        SecureField("Stored in Keychain", text: $tokenDraft)
                            .onSubmit { commitToken() }
                    }
                    Text("The token is stored in your Keychain and saved when you press Return or close Settings.")
                        .settingsNote()
                }

                settingsSection("Advanced", subtitle: "Optional transport and handoff settings.") {
                    DisclosureGroup {
                        VStack(alignment: .leading, spacing: 18) {
                            settingsField("Stream URL") {
                                TextField("ws://localhost:8200/stream", text: $config.streamURL)
                                    .autocorrectionDisabled()
                            }
                            Text("Optional WebSocket URL for instant delivery push. Leave empty for polling only. Takes effect on relaunch.")
                                .settingsNote()

                            settingsField("Poll interval") {
                                HStack(spacing: 10) {
                                    TextField(
                                        "Seconds",
                                        value: $config.pollInterval,
                                        format: .number.precision(.fractionLength(0...1))
                                    )
                                    .multilineTextAlignment(.trailing)
                                    .frame(width: 90)
                                    Text("seconds")
                                        .foregroundStyle(.secondary)
                                    Stepper("", value: $config.pollInterval, in: 5...600, step: 5)
                                        .labelsHidden()
                                }
                            }

                            settingsField("Context directory") {
                                TextField("~/Library/Application Support/Gulls/agent-context", text: $config.contextDir)
                                    .autocorrectionDisabled()
                            }
                            Text("Where context files are saved for your coding assistant.")
                                .settingsNote()
                        }
                        .padding(.top, 14)
                    } label: {
                        Label("Transport and handoff", systemImage: "slider.horizontal.3")
                            .font(.headline)
                    }
                    .tint(GullsStyle.accent)
                }

                settingsSection("Actions", subtitle: "Import existing CLI settings or verify the connection.") {
                    HStack(spacing: 12) {
                        Button("Import from ~/.config/seagull/env") {
                            importFromEnvFile()
                        }
                        .disabled(!config.sharedEnvFileExists)
                        if let importStatus {
                            Text(importStatus)
                                .settingsNote()
                        }
                    }

                    HStack(spacing: 12) {
                        Button("Test connection") {
                            testConnection()
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(GullsStyle.accent)
                        .disabled(!config.isConfigured || cli == nil || connectionStatus == .testing)
                        connectionStatusLabel
                    }
                }
            }
            .frame(maxWidth: 620, alignment: .leading)
            .padding(.horizontal, 28)
            .padding(.vertical, 26)
        }
        .background(GullsStyle.canvas)
        .frame(minWidth: 520, minHeight: 500)
        .onAppear { tokenDraft = config.token }
        .onDisappear { commitToken() }
    }

    private var settingsHeader: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Settings")
                .font(.system(size: 26, weight: .semibold))
            Text("Manage how Gulls connects and saves local context.")
                .foregroundStyle(.secondary)
        }
    }

    private func settingsSection<Content: View>(
        _ title: String,
        subtitle: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.headline)
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            VStack(alignment: .leading, spacing: 14) {
                content()
            }
        }
    }

    private func settingsField<Content: View>(
        _ title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(.secondary)
            content()
                .textFieldStyle(.plain)
                .padding(.horizontal, 11)
                .padding(.vertical, 9)
                .background(GullsStyle.field, in: RoundedRectangle(cornerRadius: 10))
        }
    }

    private func commitToken() {
        if tokenDraft != config.token {
            config.token = tokenDraft
        }
    }

    @ViewBuilder
    private var connectionStatusLabel: some View {
        switch connectionStatus {
        case .idle:
            EmptyView()
        case .testing:
            ProgressView().controlSize(.small)
        case .success(let message):
            Label(message, systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .font(.caption)
        case .failure(let message):
            Label(message, systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.red)
                .font(.caption)
                .textSelection(.enabled)
        }
    }

    private func importFromEnvFile() {
        if let imported = config.importFromSharedEnvFile() {
            importStatus = imported.isEmpty ? "No matching keys found." : "Imported \(imported.count) value(s)."
            // Import may have set the token behind the draft's back.
            tokenDraft = config.token
        } else {
            importStatus = "Could not read the env file."
        }
    }

    private func testConnection() {
        guard let cli else { return }
        commitToken()
        connectionStatus = .testing
        let environment = config.cliEnvironment()
        Task {
            do {
                let agent = try await cli.whoami(environment: environment)
                let handle = agent.handle ?? "unknown handle"
                let status = agent.status ?? "unknown status"
                connectionStatus = .success("Connected as \(handle) (\(status))")
            } catch {
                connectionStatus = .failure(error.localizedDescription)
            }
        }
    }
}

private extension View {
    func settingsNote() -> some View {
        self
            .font(.caption)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}
