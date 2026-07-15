import SwiftUI

// Rule-based draft-reply flow. Mirrors the CLI's two-step safety design:
// generate first (no side effects), send only on an explicit approve. Note
// `draft-reply --approve` re-generates the draft server-rules-fresh, so after
// sending we compare the sent draft with the one that was displayed and warn
// if they differ.
struct DraftReplyView: View {
    @Bindable var store: InboxStore
    let deliveryID: String
    @Environment(\.dismiss) private var dismiss

    @State private var phase: Phase = .loading
    @State private var draftMismatchWarning: String?

    enum Phase {
        case loading
        case generated(DraftReplyResult)
        case approving(DraftReplyResult)
        case sent(DraftReplyResult)
        case failed(String)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Draft reply")
                .font(.headline)
            content
            HStack {
                Spacer()
                Button("Close") { dismiss() }
                    .keyboardShortcut(.cancelAction)
                approveButton
            }
        }
        .padding()
        .frame(minWidth: 460)
        .task { await generate() }
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .loading:
            ProgressView("Generating draft from response rules…")
                .frame(maxWidth: .infinity, minHeight: 120)
        case .generated(let result), .approving(let result):
            resultDetails(result, sent: false)
        case .sent(let result):
            resultDetails(result, sent: true)
        case .failed(let message):
            Label(message, systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.red)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, minHeight: 120)
        }
    }

    private func resultDetails(_ result: DraftReplyResult, sent: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 2) {
                GridRow {
                    Text("Outcome").gridColumnAlignment(.trailing)
                    Text(result.outcome).fontWeight(.medium)
                }
                if let reason = result.reason {
                    GridRow {
                        Text("Reason")
                        Text(reason)
                    }
                }
                if let rules = result.appliedRules {
                    GridRow {
                        Text("Rules")
                        Text(rulesSummary(rules))
                    }
                }
                if let labels = result.triggerLabels, !labels.isEmpty {
                    GridRow {
                        Text("Triggers")
                        Text(labels.joined(separator: ", "))
                    }
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            if let draft = result.draft {
                Text(sent ? "Draft (approved and sent):" : "Draft (not sent):")
                    .font(.subheadline.weight(.medium))
                ScrollView {
                    Text(draft)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(minHeight: 80, maxHeight: 200)
                .padding(8)
                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
            } else {
                Text("No draft generated — nothing will be sent.")
                    .foregroundStyle(.secondary)
            }

            if let warning = draftMismatchWarning {
                Label(warning, systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
            if sent {
                Label("Delivery decision submitted.", systemImage: "checkmark.circle.fill")
                    .font(.caption)
                    .foregroundStyle(.green)
            }
        }
    }

    @ViewBuilder
    private var approveButton: some View {
        switch phase {
        case .generated(let result) where result.draft != nil:
            Button("Approve & send") {
                Task { await approve(displayedDraft: result.draft) }
            }
            .keyboardShortcut(.defaultAction)
        case .approving:
            ProgressView().controlSize(.small)
        default:
            EmptyView()
        }
    }

    private func rulesSummary(_ rules: [String: JSONValue]) -> String {
        ["source", "reply_posture", "max_reply_chars"]
            .compactMap { key in rules[key].map { "\(key)=\($0.displayText)" } }
            .joined(separator: "; ")
    }

    private func generate() async {
        do {
            let result = try await store.draftReply(for: deliveryID, approve: false)
            phase = .generated(result)
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    private func approve(displayedDraft: String?) async {
        guard case .generated(let current) = phase else { return }
        phase = .approving(current)
        do {
            let result = try await store.draftReply(for: deliveryID, approve: true)
            if let sentDraft = result.draft, let displayedDraft, sentDraft != displayedDraft {
                draftMismatchWarning = "The sent draft differs from the one shown: response rules changed between generate and approve."
            }
            if !result.draftSent {
                draftMismatchWarning = "No draft was sent — the outcome on approve was “\(result.outcome)”."
            }
            phase = .sent(result)
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }
}
