import SwiftUI

struct InboxListView: View {
    @Bindable var store: InboxStore
    var connections: LocalConnectionsStore? = nil
    @Environment(\.openSettings) private var openSettings
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    @ViewBuilder
    var body: some View {
        if #available(macOS 26.0, *), !reduceTransparency {
            inboxList
                .gullsSafeAreaBar(edge: .top, spacing: 16) {
                    sidebarHeader
                }
                .gullsSafeAreaBar(edge: .bottom, spacing: 16) {
                    accountFooter
                }
                .gullsScrollEdges()
        } else {
            inboxList
                .safeAreaInset(edge: .top, spacing: 0) {
                    sidebarHeader
                        .background(GullsStyle.canvas)
                }
                .safeAreaInset(edge: .bottom, spacing: 0) {
                    accountFooter
                        .background(GullsStyle.canvas)
                }
                .gullsScrollEdges()
        }
    }

    private var inboxList: some View {
        let items = store.filteredItems
        return List(selection: $store.selectedDeliveryID) {
            ForEach(items) { item in
                InboxRow(item: item)
                    .tag(item.id)
                    .listRowSeparator(.hidden)
            }
        }
        .listStyle(.sidebar)
        .scrollContentBackground(.hidden)
        .gullsHiddenScrollbars()
        .overlay {
            if items.isEmpty {
                ContentUnavailableView(emptyTitle, systemImage: "tray", description: Text(emptyDescription))
                    .allowsHitTesting(false)
            }
        }
    }

    private var sidebarHeader: some View {
        HStack(spacing: 12) {
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

            Menu {
                Picker("Filter", selection: $store.filter) {
                    ForEach(InboxStore.InboxFilter.allCases) { filter in
                        Text(filter.rawValue).tag(filter)
                    }
                }
            } label: {
                Label("Filter inbox", systemImage: "line.3.horizontal.decrease")
                    .labelStyle(.iconOnly)
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .help("Filter: \(store.filter.rawValue)")
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var accountFooter: some View {
        HStack(spacing: 10) {
            WingAvatar(identity: store.config.agentHandle, size: 26)
            if let connections, connections.profiles.count > 1 {
                Menu {
                    ForEach(connections.profiles, id: \.profileID) { config in
                        Button {
                            connections.select(profileID: config.profileID)
                        } label: {
                            if config.profileID == connections.selectedProfileID {
                                Label(firstNonEmpty(config.displayName, config.agentHandle) ?? "New Gull", systemImage: "checkmark")
                            } else {
                                Text(firstNonEmpty(config.displayName, config.agentHandle) ?? "New Gull")
                            }
                        }
                    }
                } label: {
                    accountIdentity
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .help("Switch Gull")
            } else {
                accountIdentity
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
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var accountIdentity: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(firstNonEmpty(store.config.displayName, store.agent?.displayName, store.agent?.handle,
                               store.config.agentHandle) ?? "Your Gull")
                .font(.subheadline.weight(.medium))
                .lineLimit(1)
            Text(store.config.isConfigured
                 ? (store.config.monitoringEnabled ? "On this Mac" : "Monitoring paused")
                 : "Open Settings to connect")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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
        if !store.config.isConfigured { return "Open Settings to connect your Gull." }
        if !store.config.monitoringEnabled { return "Inbox monitoring is paused." }
        if store.cli == nil { return "The bundled CLI is unavailable. Check Settings." }
        return "Checking for deliveries…"
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
