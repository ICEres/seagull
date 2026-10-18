import SwiftUI

struct InboxListView: View {
    @Bindable var store: InboxStore
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: 18) {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("Search inbox", text: $store.searchText)
                        .textFieldStyle(.plain)
                        .accessibilityLabel("Search sender or content")
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 9)
                .background(GullsStyle.field, in: Capsule())

                HStack {
                    Text("Inbox")
                        .font(.headline)
                    Spacer()
                    Picker("Filter", selection: $store.filter) {
                        ForEach(InboxStore.InboxFilter.allCases) { filter in
                            Text(filter.rawValue).tag(filter)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .controlSize(.small)
                    .fixedSize()
                    .help("Filter the inbox by delivery status")
                }
            }
            .padding(18)

            List(selection: $store.selectedDeliveryID) {
                ForEach(store.filteredItems) { item in
                    InboxRow(item: item)
                        .tag(item.id)
                        .listRowSeparator(.hidden)
                }
            }
            .listStyle(.sidebar)
            .scrollContentBackground(.hidden)
            .overlay {
                if store.filteredItems.isEmpty {
                    ContentUnavailableView(emptyTitle, systemImage: "tray", description: Text(emptyDescription))
                }
            }

            HStack(spacing: 10) {
                WingAvatar(identity: store.config.agentHandle)
                VStack(alignment: .leading, spacing: 3) {
                    Text(firstNonEmpty(store.agent?.displayName, store.agent?.handle, store.config.agentHandle) ?? "Your Gull")
                        .font(.subheadline.weight(.medium))
                        .lineLimit(1)
                    Text(store.config.isConfigured ? "On this Mac" : "Open Settings to connect")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 4)
                Button {
                    openSettings()
                } label: {
                    Label("Settings", systemImage: "gearshape")
                        .labelStyle(.iconOnly)
                }
                .buttonStyle(.borderless)
                .help("Settings (⌘,)")
            }
            .padding(18)
        }
    }

    private var emptyTitle: String {
        if store.items.isEmpty {
            return "Inbox is empty"
        }
        if !store.searchText.isEmpty {
            return "No matches"
        }
        return store.filter == .awaiting ? "Nothing awaiting you" : "Nothing here"
    }

    private var emptyDescription: String {
        if !store.items.isEmpty {
            return "\(store.items.count) deliveries in other views — change the filter or search."
        }
        if let lastRefresh = store.lastRefresh {
            return "Last checked \(lastRefresh.formatted(date: .omitted, time: .shortened))."
        }
        return store.config.isConfigured ? "Refreshing…" : "Open Settings to connect your Gull."
    }
}

private struct InboxRow: View {
    let item: InboxItem

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            WingAvatar(identity: item.senderDisplay)
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(item.senderDisplay)
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    if let created = item.message?.createdAt ?? item.delivery.createdAt {
                        Text(Self.displayDate(created))
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                    }
                }
                // Untrusted content: render as plain text only.
                Text(item.bodyText ?? "(no inline content)")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                StatusBadge(status: item.delivery.status)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, 9)
    }

    static func displayDate(_ raw: String) -> String {
        guard let date = GullsDates.parse(raw) else { return raw }
        return date.formatted(.relative(presentation: .named))
    }
}

struct StatusBadge: View {
    let status: String?

    var body: some View {
        HStack(spacing: 5) {
            Circle().fill(color).frame(width: 5, height: 5)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }

    private var label: String {
        switch status.flatMap(DeliveryStatus.init(rawValue:)) {
        case .delivered?: return "Needs reply"
        case .replied?: return "Replied"
        case .acked?: return "Acknowledged"
        case .ignored?: return "Ignored"
        case .failed?: return "Failed"
        case nil: return firstNonEmpty(status) ?? "Unknown status"
        }
    }

    private var color: Color {
        switch status.flatMap(DeliveryStatus.init(rawValue:)) {
        case .delivered?: return .blue
        case .replied?: return .green
        case .acked?: return .teal
        case .ignored?: return .gray
        case .failed?: return .red
        case nil: return .secondary
        }
    }
}
