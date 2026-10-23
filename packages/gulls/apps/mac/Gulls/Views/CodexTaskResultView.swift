import SwiftUI

/// Review-only presentation for a Codex handoff. Sending remains owned by the
/// existing reply composer and always requires an explicit user action.
struct CodexTaskResultView: View {
    let task: CodexTask
    var onUseDraft: (() -> Void)? = nil
    var onOpen: (() -> Void)? = nil
    var onContinue: ((String) -> Void)? = nil
    var onStop: (() -> Void)? = nil
    var onApprove: (() -> Void)? = nil
    var onDecline: (() -> Void)? = nil

    @State private var isExpanded = false
    @State private var followUp = ""
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var hasLongDraft: Bool {
        guard let content = task.result?.content else { return false }
        return content.count > 700 || content.split(separator: "\n").count > 9
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            if let execution = task.execution {
                liveExecution(execution)
            } else if let result = task.result {
                Text(verbatim: result.content)
                    .font(.body)
                    .textSelection(.enabled)
                    .lineLimit(isExpanded || !hasLongDraft ? nil : 9)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if hasLongDraft {
                    Button(isExpanded ? "Show less" : "Show more") {
                        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.18)) { isExpanded.toggle() }
                    }
                    .buttonStyle(.borderless)
                }

                HStack(spacing: 10) {
                    if let onUseDraft {
                        Button("Use draft", action: onUseDraft)
                            .buttonStyle(.borderedProminent)
                            .tint(GullsStyle.accent)
                    }
                    if let onOpen {
                        Button(result.codexThreadID == nil ? "Open in Codex" : "Continue in Codex", action: onOpen)
                            .buttonStyle(.borderless)
                    }
                }
            } else if let resultError = task.resultError {
                Text(verbatim: resultError)
                    .font(.callout)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
                if let onOpen {
                    Button("Open in Codex", action: onOpen)
                        .buttonStyle(.borderless)
                }
            } else {
                Text("The result will appear here when Codex returns a draft.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                if let onOpen {
                    Button("Open in Codex", action: onOpen)
                        .buttonStyle(.borderless)
                }
            }
        }
        .padding(14)
        .background(GullsStyle.field, in: RoundedRectangle(cornerRadius: 14))
        .overlay {
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.75)
        }
    }

    @ViewBuilder
    private func liveExecution(_ execution: CodexTaskExecution) -> some View {
        if !execution.output.isEmpty {
            Text(verbatim: execution.output)
                .font(.callout)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        if let error = execution.error, !error.isEmpty {
            Text(verbatim: error)
                .font(.callout)
                .foregroundStyle(.red)
                .textSelection(.enabled)
        }
        if execution.status == .needsApproval {
            VStack(alignment: .leading, spacing: 6) {
                Text(execution.approvalSummary ?? "Codex needs approval")
                    .font(.callout.weight(.medium))
                if let details = execution.approvalDetails, !details.isEmpty {
                    Text(verbatim: details)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                }
                HStack(spacing: 10) {
                    if let onApprove {
                        Button("Review operation…", action: onApprove)
                            .buttonStyle(.borderedProminent)
                            .tint(GullsStyle.accent)
                    }
                    if let onDecline {
                        Button("Decline", role: .destructive, action: onDecline)
                            .buttonStyle(.bordered)
                    }
                }
            }
            .padding(10)
            .background(GullsStyle.canvas, in: RoundedRectangle(cornerRadius: 10))
        }
        if execution.status == .draftReady, let onUseDraft {
            Button("Use draft", action: onUseDraft)
                .buttonStyle(.borderedProminent)
                .tint(GullsStyle.accent)
        }
        if !execution.isActive, let onContinue {
            HStack(spacing: 8) {
                TextField("Add a follow-up", text: $followUp, axis: .vertical)
                    .textFieldStyle(.plain)
                    .lineLimit(1...4)
                    .padding(.horizontal, 9)
                    .padding(.vertical, 7)
                    .background(GullsStyle.canvas, in: RoundedRectangle(cornerRadius: 9))
                    .overlay {
                        RoundedRectangle(cornerRadius: 9)
                            .strokeBorder(Color.primary.opacity(0.12), lineWidth: 0.75)
                    }
                Button("Continue") {
                    let value = followUp.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !value.isEmpty else { return }
                    onContinue(value)
                    followUp = ""
                }
                .buttonStyle(.borderedProminent)
                .tint(GullsStyle.accent)
                .disabled(followUp.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        if let onOpen {
            Button(execution.codexThreadID == nil ? "Open in Codex" : "Continue in Codex", action: onOpen)
                .buttonStyle(.borderless)
        }
    }

    private func executionStatus(_ execution: CodexTaskExecution) -> String {
        switch execution.status {
        case .starting: return "Starting in Codex…"
        case .working: return "Working in Codex…"
        case .needsApproval: return "Needs your approval"
        case .draftReady: return "Draft ready"
        case .interrupted: return "Stopped"
        case .failed: return "Codex could not finish"
        }
    }

    private var header: some View {
        HStack(spacing: 8) {
            GullsAIIcon()
            Text("Codex draft")
                .font(.subheadline.weight(.semibold))
            Spacer(minLength: 8)
            if let execution = task.execution {
                Text(executionStatus(execution))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if execution.isActive, let onStop {
                    Button("Stop", action: onStop).buttonStyle(.borderless)
                }
            } else if let completedAt = task.result?.completedAt {
                Text(CloudSettingsDate.label(completedAt))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("Awaiting draft")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
