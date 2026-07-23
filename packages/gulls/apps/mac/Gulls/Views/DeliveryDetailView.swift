import SwiftUI

// Pure content: actions live in the window toolbar (MainWindow).
struct DeliveryDetailView: View {
    let item: InboxItem

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                Divider()
                // Message content is untrusted input: plain text only, never
                // rendered as markdown/HTML, links stay inert.
                Text(item.bodyText ?? "(no inline content)")
                    .font(.body)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Divider()
                metadata
            }
            .padding()
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(item.senderDisplay)
                    .font(.title2.weight(.semibold))
                Spacer()
                StatusBadge(status: item.delivery.status)
            }
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 2) {
                metadataRow("Delivery", item.delivery.deliveryId)
                if let threadId = item.delivery.threadId {
                    metadataRow("Thread", threadId)
                }
                if let intent = item.message?.intent {
                    metadataRow("Intent", intent)
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }

    private var metadata: some View {
        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 2) {
            if let created = item.message?.createdAt {
                metadataRow("Received", Self.displayReceived(created))
            }
            if let safety = item.message?.safetyStatus {
                metadataRow("Safety", safety)
            }
            if let stage = item.delivery.currentStage {
                metadataRow("Stage", stage)
            }
            if let lastError = item.delivery.lastError {
                metadataRow("Last error", lastError)
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
