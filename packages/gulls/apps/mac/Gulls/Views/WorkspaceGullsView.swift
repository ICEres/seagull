import SwiftUI

/// The owned Gull list used by the workspace's middle column.
///
/// This view only presents connection state. Selection and settings remain the
/// responsibility of the parent workspace.
struct WorkspaceGullsView: View {
    let stores: [InboxStore]
    let selectedProfileID: String?
    let attentionCounts: [String: Int]
    let compact: Bool
    let onSelect: (String) -> Void
    let onSettings: () -> Void

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    private var configuredStores: [InboxStore] {
        stores.filter { $0.config.isConfigured }
    }

    var body: some View {
        if #available(macOS 26.0, *), !reduceTransparency {
            content
                .safeAreaBar(edge: .top, spacing: compact ? 8 : 12) { header }
                .gullsScrollEdges()
        } else {
            content
                .safeAreaInset(edge: .top, spacing: 0) {
                    header.background(GullsStyle.canvas)
                }
                .gullsScrollEdges()
        }
    }

    private var content: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: compact ? 3 : 5) {
                if configuredStores.isEmpty {
                    emptyState
                } else {
                    ForEach(configuredStores, id: \.config.profileID) { store in
                        gullRow(store)
                    }
                }
            }
            .padding(.horizontal, compact ? 10 : 14)
            .padding(.vertical, compact ? 12 : 16)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .frame(minWidth: 260, maxWidth: .infinity, maxHeight: .infinity)
        .background(GullsStyle.canvas)
        .gullsHiddenScrollbars()
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            GullsPageTitle("Gulls")
                .font((compact ? Font.headline : .title2).weight(.semibold))
            Text("\(configuredStores.count)")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            Spacer(minLength: 8)
        }
        .padding(.horizontal, compact ? 14 : 20)
        .padding(.vertical, compact ? 10 : 12)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 10) {
            GullWing(name: .classic)
                .stroke(
                    GullsStyle.accent,
                    style: StrokeStyle(lineWidth: 2.2, lineCap: .round, lineJoin: .round)
                )
                .frame(width: 36, height: 18)
            Text("No Gulls connected")
                .font(.subheadline.weight(.semibold))
            Text("Connect a Gull to see its messages and status here.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Button("Open Settings", action: onSettings)
                .buttonStyle(.bordered)
                .tint(GullsStyle.accent)
                .controlSize(.small)
        }
        .padding(compact ? 14 : 18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(GullsStyle.field, in: RoundedRectangle(cornerRadius: 12))
        .padding(.top, 6)
    }

    private func gullRow(_ store: InboxStore) -> some View {
        let profileID = store.config.profileID
        let handle = store.config.agentHandle.isEmpty ? profileID : store.config.agentHandle
        let name = displayName(for: store)
        let selected = selectedProfileID == profileID
        let attention = attentionCounts[profileID] ?? 0

        return Button {
            onSelect(profileID)
        } label: {
            HStack(alignment: .center, spacing: compact ? 9 : 11) {
                GullAvatar(handle: handle, size: compact ? 28 : 32)

                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(name)
                            .font(.subheadline.weight(selected ? .semibold : .medium))
                            .lineLimit(1)
                        Spacer(minLength: 4)
                        if attention > 0 {
                            Text("\(attention)")
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(GullsStyle.accent)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(GullsStyle.accent.opacity(0.12), in: Capsule())
                        }
                    }
                    Text(handle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Text(transportState(for: store))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .foregroundStyle(Color.primary)
            .padding(.horizontal, compact ? 10 : 12)
            .padding(.vertical, compact ? 9 : 11)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                if selected {
                    RoundedRectangle(cornerRadius: 10)
                        .fill(GullsStyle.accent.opacity(0.12))
                }
            }
            .contentShape(RoundedRectangle(cornerRadius: 10))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityLabel(
            attention > 0
                ? "\(name), \(attention) need attention, \(transportState(for: store))"
                : "\(name), \(transportState(for: store))"
        )
    }

    private func displayName(for store: InboxStore) -> String {
        let candidates = [
            store.config.displayName,
            store.agent?.displayName,
            store.agent?.handle,
            store.config.agentHandle
        ]
        return candidates.compactMap { $0 }.first { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            ?? "Your Gull"
    }

    private func transportState(for store: InboxStore) -> String {
        if !store.config.isConfigured { return "Needs setup" }
        if !store.isCurrent { return "Connection changed" }
        if store.lastError != nil { return "Connection issue" }
        if !store.monitoringEnabled { return "Monitoring paused" }
        if store.isRefreshing { return "Refreshing" }

        switch store.streamState {
        case .connected:
            return "Connected"
        case .connecting:
            return "Connecting"
        case .down:
            return "Polling fallback"
        case .failed:
            return "Connection issue"
        case .off:
            return store.isMonitoring ? "Monitoring" : "Ready"
        }
    }
}
