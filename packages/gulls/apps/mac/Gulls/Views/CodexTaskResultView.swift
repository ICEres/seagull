import SwiftUI

/// Presentation for a Codex handoff. Delegated inbound work has a separate
/// Gull-owned publication lifecycle; standalone tasks retain the draft UI.
struct CodexTaskResultView: View {
    let task: CodexTask
    var gullName: String = "Gull"
    var onUseDraft: (() -> Void)? = nil
    var onOpen: (() -> Void)? = nil
    var onContinue: ((String) -> Void)? = nil
    var onStop: (() -> Void)? = nil
    var onApprove: (() -> Void)? = nil
    var onDecline: (() -> Void)? = nil
    var onCheckStatus: (() -> Void)? = nil
    var onApproveReply: (() -> Void)? = nil
    var onCheckReplyStatus: (() -> Void)? = nil
    var onTakeOverReply: (() -> Void)? = nil

    @State private var isExpanded = false
    @State private var followUp = ""
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var hasLongDraft: Bool {
        guard let content = task.result?.content else { return false }
        return content.count > 700 || content.split(separator: "\n").count > 9
    }

    private var canOpenExternalCodex: Bool {
        task.work?.route != .embedded
    }

    private var canUseDraft: Bool {
        guard task.result != nil, task.resultError == nil else { return false }
        switch task.work?.draftDisposition {
        case .sent, .discarded, .superseded:
            return false
        case .available, .used, nil:
            return true
        }
    }

    private var dispositionLabel: String? {
        switch task.work?.draftDisposition {
        case .available: return "Draft available"
        case .used: return "Draft in composer"
        case .sent: return "Draft sent"
        case .discarded: return "Draft discarded"
        case .superseded: return "Draft superseded"
        case nil: return nil
        }
    }

    private func canContinue(_ status: CodexTaskExecution.Status) -> Bool {
        switch status {
        case .queued, .starting, .working, .needsApproval:
            return false
        case .draftReady, .interrupted, .failed, .cancelled:
            return true
        case .uncertain:
            return false
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if task.reply == nil { header }
            if task.reply != nil {
                delegatedReply
            } else if let execution = task.execution {
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
                    if let onUseDraft, canUseDraft {
                        Button("Use draft", action: onUseDraft)
                            .buttonStyle(.borderedProminent)
                            .tint(GullsStyle.accent)
                    }
                    if let onOpen, canOpenExternalCodex {
                        Button(result.codexThreadID == nil ? "Copy handoff & open Codex" : "Copy handoff & continue in Codex", action: onOpen)
                            .buttonStyle(.borderless)
                    }
                }
                if let dispositionLabel {
                    Text(dispositionLabel)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } else if let resultError = task.resultError {
                Text(verbatim: resultError)
                    .font(.callout)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
                if let onOpen, canOpenExternalCodex {
                    Button("Copy handoff & open Codex", action: onOpen)
                        .buttonStyle(.borderless)
                }
            } else {
                Text("The result will appear here when Codex returns a draft.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                if let onOpen, canOpenExternalCodex {
                    Button("Copy handoff & open Codex", action: onOpen)
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
    private var delegatedReply: some View {
        if let reply = task.reply {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    GullWing(name: .classic)
                        .stroke(style: StrokeStyle(lineWidth: 1.7, lineCap: .round, lineJoin: .round))
                        .frame(width: 22, height: 15)
                        .foregroundStyle(GullsStyle.accent)
                    Text("\(gullName) reply")
                        .font(.subheadline.weight(.semibold))
                    Spacer(minLength: 8)
                    Text(replyStatusLabel(reply.status))
                        .font(.caption)
                        .foregroundStyle(replyStatusColor(reply.status))
                    if task.execution?.isActive == true || task.execution?.status == .queued,
                       let onStop {
                        Button("Stop", action: onStop).buttonStyle(.borderless)
                    }
                }
                if reply.status != .sent, let content = reply.content, !content.isEmpty {
                    Text(verbatim: content)
                        .font(.body)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else if reply.status == .waitingForReply,
                          task.execution?.isActive == true {
                    Label("Working on a reply…", systemImage: "ellipsis.circle")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                } else if reply.status == .waitingForReply {
                    Label("No public reply submitted yet", systemImage: "questionmark.circle")
                        .font(.callout)
                        .foregroundStyle(.orange)
                }
                if let error = reply.error, !error.isEmpty {
                    Text(verbatim: error)
                        .font(.callout)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                }
                if let error = task.execution?.error ?? task.resultError, !error.isEmpty {
                    Text(verbatim: error).font(.callout).foregroundStyle(.red).textSelection(.enabled)
                }
                if task.execution?.status == .uncertain, let onCheckStatus {
                    Button("Check work status", action: onCheckStatus).buttonStyle(.bordered)
                }
                HStack(spacing: 10) {
                    if reply.canApprove, let onApproveReply {
                        Button("Approve & send", action: onApproveReply)
                            .buttonStyle(.borderedProminent)
                            .tint(GullsStyle.accent)
                    }
                    if reply.status == .uncertain, let onCheckReplyStatus {
                        Button("Check send status", action: onCheckReplyStatus)
                            .buttonStyle(.bordered)
                    }
                    if reply.canTakeOver, let onTakeOverReply {
                        Button("Take over", action: onTakeOverReply)
                            .buttonStyle(.borderless)
                    }
                }
                if let execution = task.execution, execution.status == .needsApproval {
                    VStack(alignment: .leading, spacing: 7) {
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
                if let execution = task.execution,
                   canContinue(execution.status),
                   let onContinue,
                   reply.status != .sent,
                   reply.status != .revoked, !reply.deliveryUnresolved {
                    HStack(spacing: 8) {
                        TextField("Add a follow-up", text: $followUp, axis: .vertical)
                            .textFieldStyle(.plain)
                            .lineLimit(1...4)
                            .padding(.horizontal, 9)
                            .padding(.vertical, 7)
                            .background(GullsStyle.canvas, in: RoundedRectangle(cornerRadius: 9))
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
                if let messageID = reply.messageID, reply.status == .sent {
                    Label("Sent as \(gullName) · \(messageID.prefix(8))", systemImage: "checkmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let output = task.execution?.output ?? task.result?.content, !output.isEmpty {
                    DisclosureGroup("Private work") {
                        Text(verbatim: output)
                            .font(.caption)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.top, 5)
                    }
                    .font(.caption)
                }
                if let onOpen, canOpenExternalCodex, reply.canTakeOver {
                    Button("Continue in Codex", action: onOpen).buttonStyle(.borderless)
                }
            }
        }
    }

    private func replyStatusLabel(_ status: GullReplyPublication.Status) -> String {
        switch status {
        case .waitingForReply:
            if task.execution?.status == .queued { return "Queued" }
            return task.execution?.isActive == true ? "Working" : "Awaiting reply"
        case .needsReview: return "Needs review"
        case .readyToSend: return "Ready to send"
        case .sending: return "Sending…"
        case .uncertain: return "Checking send"
        case .sent: return "Sent"
        case .revoked: return "Taken over"
        case .failed: return "Failed"
        }
    }

    private func replyStatusColor(_ status: GullReplyPublication.Status) -> Color {
        switch status {
        case .sent: return .green
        case .needsReview, .uncertain: return .orange
        case .failed: return .red
        case .revoked: return .secondary
        default: return GullsStyle.accent
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
        if let resultError = task.resultError, !resultError.isEmpty {
            Text(verbatim: resultError)
                .font(.callout)
                .foregroundStyle(.red)
                .textSelection(.enabled)
        }
        if let error = execution.error, !error.isEmpty {
            Text(verbatim: error)
                .font(.callout)
                .foregroundStyle(.red)
                .textSelection(.enabled)
        }
        if execution.status == .uncertain {
            VStack(alignment: .leading, spacing: 7) {
                Label("Codex may have accepted this turn. Check its state before starting another attempt.", systemImage: "questionmark.circle")
                    .font(.caption)
                    .foregroundStyle(.orange)
                if let onCheckStatus {
                    Button("Check status", action: onCheckStatus)
                        .buttonStyle(.bordered)
                }
            }
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
        if execution.status == .draftReady, let onUseDraft, canUseDraft {
            Button("Use draft", action: onUseDraft)
                .buttonStyle(.borderedProminent)
                .tint(GullsStyle.accent)
        }
        if execution.status == .draftReady, let dispositionLabel {
            Text(dispositionLabel)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        if canContinue(execution.status), let onContinue {
            HStack(spacing: 8) {
                TextField(execution.status == .uncertain ? "Describe a new attempt" : "Add a follow-up", text: $followUp, axis: .vertical)
                    .textFieldStyle(.plain)
                    .lineLimit(1...4)
                    .padding(.horizontal, 9)
                    .padding(.vertical, 7)
                    .background(GullsStyle.canvas, in: RoundedRectangle(cornerRadius: 9))
                    .overlay {
                        RoundedRectangle(cornerRadius: 9)
                            .strokeBorder(Color.primary.opacity(0.12), lineWidth: 0.75)
                    }
                Button(execution.status == .uncertain ? "Start new attempt" : "Continue") {
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
        if let onOpen, canOpenExternalCodex {
            Button(execution.codexThreadID == nil ? "Copy handoff & open Codex" : "Copy handoff & continue in Codex", action: onOpen)
                .buttonStyle(.borderless)
        }
    }

    private func executionStatus(_ execution: CodexTaskExecution) -> String {
        switch execution.status {
        case .queued: return "Queued"
        case .starting: return "Starting in Codex…"
        case .working: return "Working in Codex…"
        case .needsApproval: return "Needs your approval"
        case .draftReady: return "Draft ready"
        case .interrupted: return "Stopped"
        case .uncertain: return "Needs review"
        case .cancelled: return "Cancelled"
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
                if execution.status == .queued, let onStop {
                    Button("Cancel", action: onStop).buttonStyle(.borderless)
                } else if execution.isActive, let onStop {
                    Button("Stop", action: onStop).buttonStyle(.borderless)
                }
            } else if task.reply != nil {
                Text("Gull-owned reply")
                    .font(.caption)
                    .foregroundStyle(.secondary)
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
