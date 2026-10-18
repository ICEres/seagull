import SwiftUI

// Rule-based draft-reply flow. Mirrors the CLI's two-step safety design:
// generate first (no side effects), send only on an explicit approve.
// `draft-reply --approve` re-generates from the message as it stands now, so
// the approval carries the digest of the draft that was displayed and the CLI
// refuses to send anything that no longer matches it. What was reviewed is
// what is sent, or nothing is.
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
            header
            content
            actionBar
        }
        .padding(24)
        .frame(minWidth: 500, idealWidth: 560, maxWidth: 620)
        .task { await generate() }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "wand.and.stars")
                .font(.title3)
                .foregroundStyle(GullsStyle.accent)
                .frame(width: 34, height: 34)
                .gullsGlass(cornerRadius: 10)

            VStack(alignment: .leading, spacing: 3) {
                Text("Review draft reply")
                    .font(.title3.weight(.semibold))
                Text("Check the exact message before it is sent.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var actionBar: some View {
        HStack(spacing: 10) {
            Spacer()
            Button("Close") { dismiss() }
                .keyboardShortcut(.cancelAction)
                .buttonStyle(.bordered)
            approveButton
        }
        .padding(.top, 4)
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .loading:
            ProgressView("Generating draft from response rules…")
                .frame(maxWidth: .infinity, minHeight: 150)
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
            DisclosureGroup("Delivery details") {
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 5) {
                    GridRow {
                        Text("Outcome")
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
                .padding(.top, 8)
            }
            .font(.subheadline.weight(.medium))
            .foregroundStyle(.secondary)

            if let draft = result.draft {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(sent ? "Message sent" : "Exact message to send")
                            .font(.headline)
                        Spacer()
                        Text(sent ? "Approved" : "Not sent")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(sent ? GullsStyle.accent : .secondary)
                    }

                    ScrollView {
                        Text(draft)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(minHeight: 96, maxHeight: 220)
                    .padding(14)
                    .background(GullsStyle.canvas, in: RoundedRectangle(cornerRadius: 12))
                }
                .padding(.top, 4)
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
                Task { await approve() }
            }
            .keyboardShortcut(.defaultAction)
            .buttonStyle(.borderedProminent)
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

    private func approve() async {
        guard case .generated(let current) = phase else { return }
        phase = .approving(current)
        do {
            // Approve the draft that is on screen, not whatever regenerating
            // produces now: the digest travels with the approval and the CLI
            // refuses to send if the two no longer agree.
            let result = try await store.draftReply(
                for: deliveryID,
                approve: true,
                expectDraft: current.draftSha256
            )
            if !result.draftSent {
                draftMismatchWarning = "No draft was sent — the outcome on approve was “\(result.outcome)”."
            }
            phase = .sent(result)
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }
}
