import SwiftUI

// Pure content: actions live in the window toolbar (MainWindow).
struct DeliveryDetailView: View {
    let item: InboxItem

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                header
                // Message content is untrusted input: plain text only, never
                // rendered as markdown/HTML, links stay inert.
                Text(item.bodyText ?? "(no inline content)")
                    .font(.body)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(20)
                    .background(GullsStyle.field, in: RoundedRectangle(cornerRadius: 16))
                if let lastError = item.delivery.lastError {
                    Label(lastError, systemImage: "exclamationmark.triangle")
                        .font(.callout)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                }
                DisclosureGroup("Message details") {
                    metadata.padding(.top, 10)
                }
                .font(.subheadline)
                .foregroundStyle(.secondary)
            }
            .frame(maxWidth: 760, alignment: .leading)
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(GullsStyle.canvas)
    }

    private var header: some View {
        HStack(spacing: 12) {
            WingAvatar(identity: item.senderDisplay, size: 40)
            VStack(alignment: .leading, spacing: 5) {
                Text(item.senderDisplay)
                    .font(.title3.weight(.semibold))
                if let created = item.message?.createdAt ?? item.delivery.createdAt {
                    Text(Self.displayReceived(created))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            StatusBadge(status: item.delivery.status)
        }
    }

    private var metadata: some View {
        Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 8) {
            metadataRow("Delivery", item.delivery.deliveryId)
            if let threadId = item.delivery.threadId {
                metadataRow("Thread", threadId)
            }
            if let intent = item.message?.intent {
                metadataRow("Intent", intent)
            }
            if let safety = item.message?.safetyStatus {
                metadataRow("Safety", safety)
            }
            if let stage = item.delivery.currentStage {
                metadataRow("Stage", stage)
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func metadataRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label).gridColumnAlignment(.trailing)
            Text(value).textSelection(.enabled)
        }
    }

    static func displayReceived(_ raw: String) -> String {
        guard let date = GullsDates.parse(raw) else { return raw }
        return date.formatted(date: .abbreviated, time: .standard)
    }
}
