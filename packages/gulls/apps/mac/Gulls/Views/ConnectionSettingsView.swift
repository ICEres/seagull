import AppKit
import SwiftUI

struct ConnectionSettingsView: View {
    let config: GullsConfig
    let cli: GullsCLI?
    @State private var draft = Draft()
    @State private var savedOrdinaryDraft = OrdinaryDraft()
    @State private var status: String?
    @State private var isError = false
    @State private var isTesting = false
    @State private var hasLoadedDraft = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Required")
                .font(.subheadline.weight(.semibold))
            Text("These values identify the local Gull and its message service.")
                .font(.caption)
                .foregroundStyle(.secondary)
            field("Name") { TextField("Gull name", text: $draft.displayName) }
            field("Message API") { TextField("http://localhost:8200", text: $draft.apiURL) }
            field("Gull handle") { TextField("@worker:gulls.ai", text: $draft.agentHandle) }
            field("Connector token") {
                HStack(spacing: 8) {
                    SecureField("Stored in Keychain", text: $draft.token)
                    if tokenIsDirty {
                        Button("Update token") { updateToken() }
                            .buttonStyle(.borderless)
                    }
                }
            }

            DisclosureGroup("Advanced") {
                VStack(alignment: .leading, spacing: 12) {
                    field("Social API") { TextField("https://api.example.com", text: $draft.socialAPIURL) }
                    field("Node ID") { TextField("From local pairing", text: $draft.nodeID) }
                    field("Stream URL") { TextField("Optional WebSocket URL", text: $draft.streamURL) }
                    field("Poll interval") {
                        HStack(spacing: 8) {
                            TextField("Seconds", value: $draft.pollInterval,
                                      format: .number.precision(.fractionLength(0...1)))
                                .frame(width: 65)
                            Text("seconds").foregroundStyle(.secondary)
                            Stepper("Poll interval", value: $draft.pollInterval, in: 5...600, step: 5)
                                .labelsHidden()
                        }
                    }
                    field("Context folder") { TextField("Folder path", text: $draft.contextDir) }
                    Button("Open context folder", systemImage: "folder") {
                        NSWorkspace.shared.open(URL(fileURLWithPath: (draft.contextDir as NSString).expandingTildeInPath))
                    }
                    .buttonStyle(.borderless)
                    .disabled(!FileManager.default.fileExists(atPath: (draft.contextDir as NSString).expandingTildeInPath))
                }
                .padding(.top, 12)
            }
            HStack(spacing: 10) {
                Button("Import CLI settings", systemImage: "square.and.arrow.down") { importSettings() }
                    .disabled(!config.sharedEnvFileExists)
                    .help("Read ~/.config/seagull/env into this form")
                Spacer(minLength: 0)
                Button("Test") { test() }
                    .disabled(cli == nil || !canSave || tokenIsDirty)
                    .help("Test the currently saved local connector")
                if isTesting { ProgressView().controlSize(.small) }
            }
            Text("Connection details save automatically. Update the connector token explicitly; it is stored in Keychain.")
                .font(.caption).foregroundStyle(.secondary)
            if let status { CloudSettingsStatus(message: status, isError: isError) }
        }
        .disabled(isTesting)
        .onAppear {
            draft = Draft(config: config)
            savedOrdinaryDraft = OrdinaryDraft(config: config)
            hasLoadedDraft = true
        }
        .task(id: ordinaryDraft) {
            guard hasLoadedDraft else { return }
            try? await Task.sleep(nanoseconds: 600_000_000)
            guard !Task.isCancelled else { return }
            _ = saveOrdinaryDraft()
        }
        .onDisappear {
            _ = saveOrdinaryDraft()
        }
    }

    private var canSave: Bool {
        !draft.apiURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !draft.agentHandle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var ordinaryDraft: OrdinaryDraft {
        OrdinaryDraft(draft: draft)
    }

    private var tokenIsDirty: Bool {
        draft.token.trimmingCharacters(in: .whitespacesAndNewlines) != config.token
    }

    private func field<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        CloudSettingsRow(title) {
            content().autocorrectionDisabled().cloudSettingsField()
        }
    }

    private func saveOrdinaryDraft() -> Bool {
        guard hasLoadedDraft, ordinaryDraft != savedOrdinaryDraft else { return true }
        guard canSave else {
            status = "Enter a Message API URL and Gull handle to apply these changes."
            isError = true
            return false
        }
        do {
            _ = try CloudAPI(baseURL: draft.apiURL)
            if !draft.socialAPIURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                _ = try CloudAPI(baseURL: draft.socialAPIURL)
            }
            if !draft.streamURL.isEmpty {
                let url = URL(string: draft.streamURL)
                let loopback = ["localhost", "127.0.0.1", "::1"].contains(url?.host ?? "")
                guard url?.scheme == "wss" || (url?.scheme == "ws" && loopback) else {
                    status = "Use a secure WebSocket URL, or ws:// on loopback for development."
                    isError = true
                    return false
                }
            }
        } catch {
            status = error.localizedDescription
            isError = true
            return false
        }
        config.displayName = draft.displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        config.apiURL = draft.apiURL.trimmingCharacters(in: .whitespacesAndNewlines)
        config.socialAPIURL = draft.socialAPIURL.trimmingCharacters(in: .whitespacesAndNewlines)
        config.nodeID = draft.nodeID.trimmingCharacters(in: .whitespacesAndNewlines)
        config.agentHandle = draft.agentHandle.trimmingCharacters(in: .whitespacesAndNewlines)
        config.streamURL = draft.streamURL.trimmingCharacters(in: .whitespacesAndNewlines)
        config.pollInterval = min(600, max(5, draft.pollInterval))
        config.contextDir = draft.contextDir.isEmpty ? GullsConfig.contextDirectory(for: config.profileID).path : draft.contextDir
        savedOrdinaryDraft = OrdinaryDraft(config: config)
        status = "Connection saved."
        isError = false
        return true
    }

    private func updateToken() {
        let token = draft.token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard token != config.token else { return }
        guard config.setToken(token) else {
            status = "Keychain could not save this credential. The connection was not changed."
            isError = true
            return
        }
        draft.token = config.token
        status = "Connector token updated."
        isError = false
    }

    private func test() {
        guard let cli, saveOrdinaryDraft() else { return }
        guard !tokenIsDirty else {
            status = "Update the connector token before testing."
            isError = true
            return
        }
        let environment = config.cliEnvironment()
        isTesting = true
        status = nil
        Task {
            defer { isTesting = false }
            do {
                let agent = try await cli.whoami(environment: environment)
                status = "Connected as \(agent.displayName ?? agent.handle ?? config.agentHandle)."
                isError = false
            } catch {
                status = error.localizedDescription
                isError = true
            }
        }
    }

    private func importSettings() {
        guard let text = try? String(contentsOf: GullsConfig.sharedEnvFile, encoding: .utf8) else {
            status = "Could not read the CLI settings file."
            isError = true
            return
        }
        let values = GullsConfig.parseEnvFile(text)
        draft.apiURL = values["SEAGULL_API_URL"] ?? draft.apiURL
        draft.socialAPIURL = values["SEAGULL_SOCIAL_API_URL"] ?? draft.socialAPIURL
        draft.nodeID = values["SEAGULL_NODE_ID"] ?? draft.nodeID
        draft.agentHandle = values["SEAGULL_AGENT_HANDLE"] ?? draft.agentHandle
        draft.token = values["SEAGULL_CONNECTOR_TOKEN"] ?? draft.token
        draft.streamURL = values["SEAGULL_STREAM_URL"] ?? draft.streamURL
        draft.contextDir = values["SEAGULL_AGENT_CONTEXT_DIR"] ?? draft.contextDir
        if let raw = values["SEAGULL_AGENT_POLL_INTERVAL"], let interval = Double(raw), interval > 0 {
            draft.pollInterval = interval
        }
        status = values["SEAGULL_CONNECTOR_TOKEN"] == nil
            ? "CLI settings imported. Ordinary settings will save automatically."
            : "CLI settings imported. Ordinary settings will save automatically; select Update token to apply the credential."
        isError = false
    }

    private struct Draft: Equatable {
        var displayName = ""
        var apiURL = ""
        var socialAPIURL = ""
        var nodeID = ""
        var agentHandle = ""
        var token = ""
        var streamURL = ""
        var pollInterval = GullsConfig.defaultPollInterval
        var contextDir = ""

        init() {}
        init(config: GullsConfig) {
            displayName = config.displayName
            apiURL = config.apiURL
            socialAPIURL = config.socialAPIURL
            nodeID = config.nodeID
            agentHandle = config.agentHandle
            token = config.token
            streamURL = config.streamURL
            pollInterval = config.pollInterval
            contextDir = config.contextDir
        }
    }

    private struct OrdinaryDraft: Hashable {
        var displayName = ""
        var apiURL = ""
        var socialAPIURL = ""
        var nodeID = ""
        var agentHandle = ""
        var streamURL = ""
        var pollInterval = GullsConfig.defaultPollInterval
        var contextDir = ""

        init() {}

        init(config: GullsConfig) {
            displayName = config.displayName
            apiURL = config.apiURL
            socialAPIURL = config.socialAPIURL
            nodeID = config.nodeID
            agentHandle = config.agentHandle
            streamURL = config.streamURL
            pollInterval = config.pollInterval
            contextDir = config.contextDir
        }

        init(draft: Draft) {
            displayName = draft.displayName
            apiURL = draft.apiURL
            socialAPIURL = draft.socialAPIURL
            nodeID = draft.nodeID
            agentHandle = draft.agentHandle
            streamURL = draft.streamURL
            pollInterval = draft.pollInterval
            contextDir = draft.contextDir
        }
    }
}
