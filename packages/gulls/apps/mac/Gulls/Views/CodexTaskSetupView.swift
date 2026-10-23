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

    private let sourceDeliveryID: String?
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

    init(tasks: CodexTaskStore, cli: GullsCLI, inbox: InboxStore? = nil, item: InboxItem? = nil) {
        self.tasks = tasks
        self.cli = cli
        self.inbox = inbox
        self.item = item
        sourceDeliveryID = item?.id
        sourceThreadID = item?.delivery.threadId ?? item?.message?.threadId
        _sourceProfileID = State(initialValue: inbox?.config.profileID ?? tasks.config.profileID)
        _sourceConnectionRevision = State(initialValue: inbox?.config.connectionRevision ?? tasks.config.connectionRevision)
        _goal = State(initialValue: item == nil ? "" : "Draft a reply to this message.")
    }

    private var isIncomingTask: Bool { item != nil }

    private var sourceName: String {
        firstNonEmpty(tasks.config.displayName, tasks.config.agentHandle) ?? "This Gull"
    }

    private var recipientName: String {
        item?.senderDisplay ?? "No message selected"
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
        .onDisappear { launchTask?.cancel() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 10) {
                GullsAIIcon()
                Text(isIncomingTask ? "Work with Codex" : "New Codex task")
                    .font(.title2.weight(.semibold))
            }
            Text("Run Codex here and review the result as a draft.")
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
            Spacer(minLength: 12)
            Button("Cancel") { launchTask?.cancel(); dismiss() }
                .keyboardShortcut(.cancelAction)
            Button { startInGulls() } label: {
                if isLaunching { ProgressView().controlSize(.small) }
                else { Text("Start in Gulls") }
            }
            .buttonStyle(.borderedProminent)
            .tint(GullsStyle.accent)
            .disabled(!canLaunch)
            Button("Open in Codex", action: openInCodex)
                .buttonStyle(.bordered)
                .disabled(!canLaunch)
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
                guard !Task.isCancelled else { return }
                var contextPath: String?
                guard tasks.config.profileID == sourceProfileID,
                      tasks.config.connectionRevision == sourceConnectionRevision else {
                    throw CodexTaskSetupError.connectionChanged
                }
                if let inbox, let deliveryID = sourceDeliveryID {
                    guard inbox.config.profileID == sourceProfileID,
                          inbox.config.connectionRevision == sourceConnectionRevision,
                          inbox.isCurrent,
                          inbox.items.contains(where: { $0.id == deliveryID }) else {
                        throw CodexTaskSetupError.connectionChanged
                    }
                    guard let opened = await inbox.writeContextFile(for: deliveryID) else {
                        throw CodexTaskSetupError.contextUnavailable
                    }
                    contextPath = opened.contextPath
                } else if isIncomingTask {
                    throw CodexTaskSetupError.contextUnavailable
                }

                guard !Task.isCancelled else { return }
                guard tasks.config.profileID == sourceProfileID,
                      tasks.config.connectionRevision == sourceConnectionRevision,
                      inbox == nil || (inbox?.isCurrent == true
                                       && inbox?.config.profileID == sourceProfileID
                                       && inbox?.config.connectionRevision == sourceConnectionRevision
                                       && sourceDeliveryID.map { deliveryID in
                                           inbox?.items.contains(where: { $0.id == deliveryID }) == true
                                       } == true) else {
                    throw CodexTaskSetupError.connectionChanged
                }
                let task = try tasks.create(
                    goal: goal.trimmingCharacters(in: .whitespacesAndNewlines),
                    workingDirectory: workingDirectory,
                    deliveryID: sourceDeliveryID,
                    threadID: sourceThreadID,
                    contextPath: contextPath,
                    cliExecutableURL: cli.executableURL
                )
                try tasks.open(task)
                dismiss()
            } catch {
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
        }
    }

    private func startInGulls() {
        guard canLaunch else { return }
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
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
        }
    }

    private func createTaskForRun() async throws -> CodexTask {
        guard tasks.config.profileID == sourceProfileID,
              tasks.config.connectionRevision == sourceConnectionRevision else {
            throw CodexTaskSetupError.connectionChanged
        }
        var contextPath: String?
        if let inbox, let deliveryID = sourceDeliveryID {
            guard inbox.isCurrent,
                  inbox.config.profileID == sourceProfileID,
                  inbox.config.connectionRevision == sourceConnectionRevision,
                  inbox.items.contains(where: { $0.id == deliveryID }),
                  let opened = await inbox.writeContextFile(for: deliveryID) else {
                throw CodexTaskSetupError.contextUnavailable
            }
            contextPath = opened.contextPath
        } else if isIncomingTask {
            throw CodexTaskSetupError.contextUnavailable
        }
        guard !Task.isCancelled else { throw CancellationError() }
        guard tasks.config.profileID == sourceProfileID,
              tasks.config.connectionRevision == sourceConnectionRevision,
              inbox == nil || (inbox?.isCurrent == true && inbox?.config.profileID == sourceProfileID
                              && inbox?.config.connectionRevision == sourceConnectionRevision) else {
            throw CodexTaskSetupError.connectionChanged
        }
        return try tasks.create(
            goal: goal.trimmingCharacters(in: .whitespacesAndNewlines),
            workingDirectory: workingDirectory,
            deliveryID: sourceDeliveryID,
            threadID: sourceThreadID,
            contextPath: contextPath,
            cliExecutableURL: cli.executableURL
        )
    }
}

private enum CodexTaskSetupError: Error, LocalizedError {
    case connectionChanged
    case contextUnavailable

    var errorDescription: String? {
        switch self {
        case .connectionChanged: return "This Gull connection changed while the task was being prepared. Refresh it and try again."
        case .contextUnavailable: return "The message context could not be prepared. The task was not opened in Codex."
        }
    }
}
