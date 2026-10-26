import AppKit
import SwiftUI

/// Starts one Codex task with optional, task-scoped working context.
///
/// A folder selected here is deliberately transient. It is never written to a
/// Gull profile, so the same Gull can work across different folders.
struct CodexTaskSetupView: View {
    @Environment(\.dismiss) private var dismiss
    @Bindable var tasks: CodexTaskStore
    let cli: GullsCLI
    let inbox: InboxStore?
    let item: InboxItem?

    private let sourceThreadID: String?
    // Captured once when the sheet is created. A reconnect must not redirect
    // the task to a different local Gull while context is being prepared.
    @State private var sourceProfileID: String
    @State private var sourceConnectionRevision: String

    @State private var goal: String
    @State private var workingDirectory: URL?
    @State private var showingFolderPicker = false
    @State private var error: String?
    @State private var isLaunching = false
    @State private var launchTask: Task<Void, Never>?
    @State private var ownerRequestID = UUID().uuidString
    @State private var readinessReport: CodexReadinessReport?
    @State private var isCheckingReadiness = false

    init(tasks: CodexTaskStore, cli: GullsCLI, inbox: InboxStore? = nil, item: InboxItem? = nil) {
        self.tasks = tasks
        self.cli = cli
        self.inbox = inbox
        self.item = item
        sourceThreadID = item?.delivery.threadId ?? item?.message?.threadId
        _sourceProfileID = State(initialValue: inbox?.config.profileID ?? tasks.config.profileID)
        _sourceConnectionRevision = State(initialValue: inbox?.config.connectionRevision ?? tasks.config.connectionRevision)
        _goal = State(initialValue: item == nil ? "" : "Reply to this message as this Gull.")
    }

    private var isIncomingTask: Bool { item != nil }

    private var sourceName: String {
        firstNonEmpty(tasks.config.displayName, tasks.config.agentHandle) ?? "This Gull"
    }

    private var recipientName: String {
        item?.senderDisplay ?? "No message selected"
    }

    private var hasExistingConversation: Bool {
        guard let sourceThreadID, !sourceThreadID.isEmpty else { return false }
        return tasks.hasConversation(threadID: sourceThreadID)
    }

    private var canLaunch: Bool {
        tasks.config.codexEnabled
            && !isLaunching
            && !goal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && goal.utf8.count <= CodexTaskStore.maximumGoalBytes
            && (!isIncomingTask || inbox != nil)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            header
            taskDetails
            contextPicker
            if let error {
                CloudSettingsStatus(message: error, isError: true)
            }
            footer
        }
        .padding(24)
        .frame(minWidth: 460, idealWidth: 520, maxWidth: 620)
        .background(GullsStyle.canvas)
        .onAppear { tasks.refresh() }
        .task { await refreshReadiness() }
        .onDisappear { launchTask?.cancel() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 10) {
                GullsAIIcon()
                Text(isIncomingTask ? "Let \(sourceName) handle this" : "New Codex task")
                    .font(.title2.weight(.semibold))
            }
            Text(hasExistingConversation
                 ? "Continue the private Codex context for this conversation. The Gull will deliver a public reply using its configured reply mode."
                 : (isIncomingTask
                    ? (tasks.config.sendRepliesAutomatically
                       ? "Codex works privately for this Gull. Its submitted reply will be sent automatically."
                       : "Let \(sourceName) handle this. Its reply will wait here for your approval before sending.")
                    : "Run Codex here for a private task and review the result when it finishes."))
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var taskDetails: some View {
        CloudSettingsSection("Task", detail: isIncomingTask ? "Review the request before starting." : "Give Codex a goal for this task.") {
            if isIncomingTask {
                detailRow("Gull", sourceName, symbol: "person.crop.circle")
                detailRow("From", recipientName, symbol: "person")
            }
            VStack(alignment: .leading, spacing: 7) {
                Text("Goal")
                    .font(.subheadline.weight(.medium))
                TextEditor(text: $goal)
                    .font(.body)
                    .scrollContentBackground(.hidden)
                    .scrollIndicators(.never)
                    .accessibilityLabel("Task goal")
                    .frame(minHeight: 76, maxHeight: 130)
                    .padding(8)
                    .background(GullsStyle.field, in: RoundedRectangle(cornerRadius: 11))
                    .overlay {
                        RoundedRectangle(cornerRadius: 11)
                            .strokeBorder(Color.primary.opacity(0.12), lineWidth: 0.75)
                    }
            }
        }
    }

    private var contextPicker: some View {
        CloudSettingsSection("Working context", detail: "Optional for a new task; use it only for this task.") {
            HStack(spacing: 10) {
                Image(systemName: "folder")
                    .foregroundStyle(.secondary)
                if let workingDirectory {
                    Text(verbatim: workingDirectory.path)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .textSelection(.enabled)
                } else {
                    Text("No folder selected")
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Button(workingDirectory == nil ? "Choose…" : "Change…") {
                    showingFolderPicker = true
                }
                .buttonStyle(.borderless)
                if workingDirectory != nil {
                    Button("Remove") { workingDirectory = nil }
                        .buttonStyle(.borderless)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .fileImporter(isPresented: $showingFolderPicker, allowedContentTypes: [.folder], allowsMultipleSelection: false) { result in
            switch result {
            case .success(let urls): workingDirectory = urls.first
            case .failure(let failure): error = failure.localizedDescription
            }
        }
    }

    private var footer: some View {
        HStack {
            if !tasks.config.codexEnabled {
                Label("Enable Codex in Settings to start a task.", systemImage: "info.circle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let readinessReport, !readinessReport.isReady {
                Label(readinessTitle(readinessReport), systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .lineLimit(2)
            }
            if isCheckingReadiness {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityLabel("Checking Codex readiness")
            }
            Spacer(minLength: 12)
            Button("Cancel") { launchTask?.cancel(); dismiss() }
                .keyboardShortcut(.cancelAction)
            Button { startInGulls() } label: {
                if isLaunching { ProgressView().controlSize(.small) }
                else { Text(tasks.isRunning ? "Queue task" : (isIncomingTask ? "Hand over" : "Start in Gulls")) }
            }
            .buttonStyle(.borderedProminent)
            .tint(GullsStyle.accent)
            .disabled(!canStartInGulls)
            Button(hasExistingConversation ? "Copy handoff & open Codex" : "Open in Codex", action: openInCodex)
                .buttonStyle(.bordered)
                .disabled(!canLaunch)
        }
    }

    private var canStartInGulls: Bool {
        canLaunch && readinessReport?.isReady == true
    }

    private func refreshReadiness() async {
        isCheckingReadiness = true
        defer { isCheckingReadiness = false }
        readinessReport = await CodexReadiness().check()
    }

    private func readinessTitle(_ report: CodexReadinessReport) -> String {
        switch report.state {
        case .ready: return "Codex ready"
        case .codexNotInstalled: return "Codex is not installed"
        case .signInRequired: return "Sign in to Codex before starting here"
        case .unsupportedVersion: return "Update Codex before starting here"
        case .connectionFailed(let message): return message
        }
    }

    private func detailRow(_ label: String, _ value: String, symbol: String) -> some View {
        HStack(spacing: 9) {
            Image(systemName: symbol)
                .frame(width: 18)
                .foregroundStyle(.secondary)
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(verbatim: value)
                .font(.subheadline.weight(.medium))
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: 0)
        }
    }

    private func openInCodex() {
        guard canLaunch else { return }
        error = nil
        isLaunching = true
        launchTask = Task { @MainActor in
            defer { isLaunching = false }
            do {
                let task = try await createTaskForRun()
                try tasks.open(task)
                dismiss()
            } catch is CancellationError {
                return
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func startInGulls() {
        guard canStartInGulls else { return }
        error = nil
        isLaunching = true
        launchTask = Task { @MainActor in
            defer { isLaunching = false }
            do {
                let task = try await createTaskForRun()
                try await tasks.run(task)
                dismiss()
            } catch is CancellationError {
                return
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func createTaskForRun() async throws -> CodexTask {
        try await tasks.prepareTask(
            goal: goal.trimmingCharacters(in: .whitespacesAndNewlines),
            workingDirectory: workingDirectory,
            cli: cli,
            inbox: inbox,
            item: item,
            sourceProfileID: sourceProfileID,
            sourceConnectionRevision: sourceConnectionRevision,
            ownerRequestID: ownerRequestID
        )
    }
}
