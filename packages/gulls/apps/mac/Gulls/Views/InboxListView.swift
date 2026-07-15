import SwiftUI

struct InboxListView: View {
    @Bindable var store: InboxStore

    var body: some View {
        List(selection: $store.selectedDeliveryID) {
            ForEach(store.items) { item in
                InboxRow(item: item)
                    .tag(item.id)
            }
        }
        .overlay {
            if store.items.isEmpty {
                ContentUnavailableView(
                    "Inbox is empty",
                    systemImage: "tray",
                    description: Text(emptyDescription)
                )
            }
        }
    }

    private var emptyDescription: String {
        if let lastRefresh = store.lastRefresh {
            return "Last checked \(lastRefresh.formatted(date: .omitted, time: .shortened))."
        }
        return store.config.isConfigured ? "Refreshing…" : "Configure the Message Hub in Settings first."
    }
}

private struct InboxRow: View {
    let item: InboxItem

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(item.senderDisplay)
                    .font(.headline)
                    .lineLimit(1)
                Spacer()
                StatusBadge(status: item.delivery.status)
            }
            // Untrusted content: render as plain text only.
            Text(item.bodyText ?? "(no inline content)")
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            if let created = item.message?.createdAt ?? item.delivery.createdAt {
                Text(Self.displayDate(created))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 3)
    }

    static func displayDate(_ raw: String) -> String {
        guard let date = ISO8601DateFormatter().date(from: raw) else { return raw }
        return date.formatted(.relative(presentation: .named))
    }
}

struct StatusBadge: View {
    let status: String?

    var body: some View {
        Text(status ?? "unknown")
            .font(.caption2.weight(.medium))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.18), in: Capsule())
            .foregroundStyle(color)
    }

    private var color: Color {
        switch status {
        case "delivered": return .blue
        case "replied": return .green
        case "acked": return .teal
        case "ignored": return .gray
        case "failed": return .red
        default: return .secondary
        }
    }
}
