import SwiftUI

/// Inline Settings section for the optional Codex capability.
///
/// Codex is enabled per local Gull, while working folders remain task-scoped.
struct CodexCapabilitySettingsView: View {
    @Bindable var tasks: CodexTaskStore
    let cli: GullsCLI?

    @State private var showingNewTask = false
    @State private var expandedTaskID: String?
    @State private var taskError: String?
    @State private var reviewRequest: LocalActionRequest?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(tasks: CodexTaskStore, cli: GullsCLI?) {
        self.tasks = tasks
        self.cli = cli
    }

    private var genericTasks: [CodexTask] {
        Array(tasks.tasks.filter { $0.request.deliveryID == nil }.prefix(3))
    }

    var body: some View {
        CloudSettingsSection("Codex", detail: "Use Codex as an optional capability for this Gull. Projects and folders are chosen per task.") {
            CloudSettingsRow("Use Codex on this Mac", detail: "Codex uses its own account; this does not grant local file permissions.") {
                Toggle("Use Codex on this Mac", isOn: Binding(
                    get: { tasks.config.codexEnabled },
                    set: {
                        tasks.config.codexEnabled = $0
                        if !$0 { tasks.suspendExecution() }
                    }
                ))
                .labelsHidden()
            }

            HStack(spacing: 10) {
                Button("New task…", systemImage: "plus") {
                    taskError = nil
                    showingNewTask = true
                }
                .buttonStyle(.bordered)
                .disabled(!tasks.config.codexEnabled || cli == nil)
                if cli == nil {
                    Text("The bundled Gulls CLI is unavailable.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if let lastError = tasks.lastError {
                CloudSettingsStatus(message: lastError, isError: true)
            }

            if let taskError {
                CloudSettingsStatus(message: taskError, isError: true)
            }

            if genericTasks.isEmpty {
                Text("No standalone tasks yet.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Recent tasks")
                        .font(.subheadline.weight(.medium))
                    ForEach(genericTasks) { task in
                        taskRow(task)
                    }
                }
            }
        }
        .task { tasks.refresh() }
        .sheet(isPresented: $showingNewTask) {
            if let cli {
                CodexTaskSetupView(tasks: tasks, cli: cli)
            }
        }
        .sheet(item: $reviewRequest) { request in
            if let control = tasks.localControl {
                LocalActionReviewView(control: control, request: request) { reviewRequest = nil }
            }
        }
    }

    private func taskRow(_ task: CodexTask) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Button {
                withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.18)) {
                    expandedTaskID = expandedTaskID == task.id ? nil : task.id
                }
            } label: {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Image(systemName: statusSymbol(for: task))
                        .foregroundStyle(statusColor(for: task))
                        .frame(width: 18)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(verbatim: task.request.goal)
                            .font(.subheadline)
                            .lineLimit(2)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        HStack(spacing: 8) {
                            Text(statusLabel(for: task))
                            if let folder = task.request.workingDirectory, !folder.isEmpty {
                                Text(verbatim: folder.components(separatedBy: "/").last ?? folder)
                            }
                            Text(CloudSettingsDate.label(task.request.createdAt))
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                    Image(systemName: expandedTaskID == task.id ? "chevron.up" : "chevron.down")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if expandedTaskID == task.id {
                VStack(alignment: .leading, spacing: 8) {
                    if task.execution != nil {
                        CodexTaskResultView(task: task, onOpen: {
                            do { try tasks.open(task); taskError = nil }
                            catch { taskError = error.localizedDescription }
                        }, onContinue: { followUp in
                            Task {
                                do { try await tasks.run(task, followUp: followUp) }
                                catch { taskError = error.localizedDescription }
                            }
                        }, onStop: {
                            Task { await tasks.stop(task) }
                        }, onApprove: {
                            if let id = task.execution?.approvalID {
                                reviewRequest = tasks.localControl?.pendingRequests.first { $0.id == id }
                            }
                        }, onDecline: { tasks.decline(task) })
                    } else if let result = task.result {
                        Text(verbatim: result.content)
                            .font(.callout)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    } else if let resultError = task.resultError {
                        CloudSettingsStatus(message: resultError, isError: true)
                    } else {
                        Text("Ready to start in Gulls or open in Codex.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                    Button("Open task in Codex") {
                        do { try tasks.open(task); taskError = nil }
                        catch { taskError = error.localizedDescription }
                    }
                    .buttonStyle(.borderless)
                    .disabled(!tasks.config.codexEnabled || cli == nil)
                }
                .padding(.leading, 28)
                .padding(.bottom, 6)
            }
        }
        .padding(.vertical, 7)
    }

    private func statusLabel(for task: CodexTask) -> String {
        if let execution = task.execution {
            switch execution.status {
            case .starting: return "Starting in Gulls"
            case .working: return "Working in Gulls"
            case .needsApproval: return "Needs your approval"
            case .draftReady: return "Draft ready"
            case .interrupted: return "Stopped"
            case .failed: return "Failed"
            }
        }
        if task.result != nil { return "Draft ready" }
        if task.resultError != nil { return "Could not read draft" }
        return "Waiting for draft"
    }

    private func statusSymbol(for task: CodexTask) -> String {
        if let execution = task.execution {
            switch execution.status {
            case .starting, .working: return "circle.dotted"
            case .needsApproval: return "hand.raised.fill"
            case .draftReady: return "checkmark.circle.fill"
            case .interrupted: return "stop.circle"
            case .failed: return "exclamationmark.triangle.fill"
            }
        }
        if task.result != nil { return "checkmark.circle.fill" }
        if task.resultError != nil { return "exclamationmark.triangle.fill" }
        return "clock"
    }

    private func statusColor(for task: CodexTask) -> Color {
        if let execution = task.execution {
            switch execution.status {
            case .starting, .working: return GullsStyle.accent
            case .needsApproval: return .orange
            case .draftReady: return .green
            case .interrupted: return .secondary
            case .failed: return .red
            }
        }
        if task.result != nil { return .green }
        if task.resultError != nil { return .orange }
        return .secondary
    }
}
