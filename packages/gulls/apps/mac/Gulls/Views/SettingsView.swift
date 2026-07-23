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
        Form {
            Section("Message Hub") {
                TextField("API URL", text: $config.apiURL, prompt: Text("http://localhost:8200"))
                    .textContentType(nil)
                    .autocorrectionDisabled()
                TextField("Agent handle", text: $config.agentHandle, prompt: Text("@worker:gulls.ai"))
                    .autocorrectionDisabled()
                SecureField("Connector token", text: $tokenDraft)
                    .onSubmit { commitToken() }
                Text("The token is stored in your Keychain, not in a file. Saved when you press Return or close Settings.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TextField("Stream URL", text: $config.streamURL, prompt: Text("ws://localhost:8200/stream"))
                    .autocorrectionDisabled()
                Text("Optional WebSocket URL for instant delivery push (ws:// or wss://). Leave empty for polling only. Takes effect on relaunch.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Polling") {
                HStack {
                    TextField(
                        "Poll interval (seconds)",
                        value: $config.pollInterval,
                        format: .number.precision(.fractionLength(0...1))
                    )
                    Stepper("", value: $config.pollInterval, in: 5...600, step: 5)
                        .labelsHidden()
                }
            }

            Section("Context handoff") {
                TextField("Context directory", text: $config.contextDir)
                    .autocorrectionDisabled()
                Text("Where “Write context file” saves delivery markdown for your coding assistant.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section {
                HStack {
                    Button("Import from ~/.config/seagull/env") {
                        importFromEnvFile()
                    }
                    .disabled(!config.sharedEnvFileExists)
                    if let importStatus {
                        Text(importStatus)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                HStack {
                    Button("Test connection") {
                        testConnection()
                    }
                    .disabled(!config.isConfigured || cli == nil || connectionStatus == .testing)
                    connectionStatusLabel
                }
            }
        }
        .formStyle(.grouped)
        .frame(minWidth: 480, minHeight: 380)
        .onAppear { tokenDraft = config.token }
        .onDisappear { commitToken() }
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
