import SwiftUI

struct DashboardRelationshipDetailView: View {
    let relationship: DashboardRelationship
    let relationships: [DashboardRelationship]
    let onSelect: (DashboardRelationship) -> Void
    let onOpen: (DashboardConversationGroup) -> Void
    var compact = false
    let onClose: () -> Void

    @State private var showingAllGroups = false

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 20 : 26) {
            header
            routeSection(for: relationship)
            summarySection(for: relationship)
            latestSection(for: relationship)
            conversationsSection(for: relationship)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Relationship details")
        .onChange(of: relationship.id) { _, _ in
            showingAllGroups = false
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            GullAvatar(handle: relationship.counterpartHandle ?? relationship.counterpart, size: compact ? 26 : 30)
            VStack(alignment: .leading, spacing: 2) {
                GullsPageTitle(shortCounterpartLabel(for: relationship))
                    .font(compact ? .headline.weight(.semibold) : .title3.weight(.semibold))
                    .lineLimit(1)
                if let handle = relationship.counterpartHandle,
                   handle != shortCounterpartLabel(for: relationship) {
                    Text(handle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 8)
            if let updatedAt = relationship.updatedAt {
                Text(updatedAt.formatted(.relative(presentation: .named)))
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
            Button(action: onClose) {
                Label("Close relationship details", systemImage: "xmark")
                    .labelStyle(.iconOnly)
            }
            .buttonStyle(.borderless)
            .help("Close relationship details")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func routeSection(for relationship: DashboardRelationship) -> some View {
        let routes = relationships
            .filter { $0.counterpartID == relationship.counterpartID }
            .sorted { routeName($0) < routeName($1) }

        if routes.count > 1 {
            section("Routes", detail: "Observed receiving paths") {
                ScrollView(.horizontal) {
                    HStack(spacing: 8) {
                        ForEach(routes) { route in
                            Button {
                                onSelect(route)
                            } label: {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(routeName(route))
                                        .font(.subheadline.weight(.medium))
                                        .lineLimit(1)
                                        .truncationMode(.middle)
                                    Text("\(route.counterpart) → \(route.ownedGullDisplayName ?? route.ownedGullHandle)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                        .truncationMode(.middle)
                                }
                                .frame(maxWidth: 150, alignment: .leading)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 8)
                                .background(
                                    RoundedRectangle(cornerRadius: 10)
                                        .fill(route.id == relationship.id
                                              ? GullsStyle.accent.opacity(0.14)
                                              : GullsStyle.field)
                                )
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Route to \(routeName(route))")
                            .accessibilityAddTraits(route.id == relationship.id ? .isSelected : [])
                        }
                    }
                }
                .scrollIndicators(.never)
            }
        }
    }

    private func summarySection(for relationship: DashboardRelationship) -> some View {
        section("Observed activity") {
            VStack(alignment: .leading, spacing: 12) {
                routeLine(for: relationship)
                HStack(spacing: 0) {
                    metric("Received", value: relationship.deliveryCount)
                    metric("Conversations", value: relationship.groups.count)
                    metric("Review", value: relationship.attentionCount)
                }
                statusLine(for: relationship)
            }
        }
    }

    private func latestSection(for relationship: DashboardRelationship) -> some View {
        let latest = latestReceivedItem(for: relationship)
        return section("Latest incoming", detail: latestDate(latest?.item)) {
            VStack(alignment: .leading, spacing: 12) {
                Text(latest?.item.bodyText ?? "No inline content available.")
                    .font(.body)
                    .foregroundStyle(.primary)
                    .lineLimit(4)
                    .textSelection(.enabled)
                if let group = latest?.group {
                    Button("Open conversation") { onOpen(group) }
                        .buttonStyle(.borderless)
                        .foregroundStyle(GullsStyle.accent)
                }
            }
        }
    }

    private func conversationsSection(for relationship: DashboardRelationship) -> some View {
        let groups = showingAllGroups ? relationship.groups : Array(relationship.groups.prefix(4))
        return section("Conversations", detail: "Loaded conversations") {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(groups) { group in
                    Button { onOpen(group) } label: {
                        HStack(alignment: .top, spacing: 10) {
                            Circle()
                                .fill(stateColor(group.state))
                                .frame(width: 7, height: 7)
                                .padding(.top, 6)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(group.title)
                                    .font(.subheadline.weight(.medium))
                                    .lineLimit(2)
                                HStack(spacing: 6) {
                                    Text(stateLabel(group.state))
                                    if let updatedAt = group.updatedAt {
                                        Text("· \(updatedAt.formatted(.relative(presentation: .named)))")
                                    }
                                }
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 8)
                            Image(systemName: "chevron.right")
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.vertical, 10)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
                if relationship.groups.count > 4 {
                    Button(showingAllGroups ? "Show less" : "Show all \(relationship.groups.count)") {
                        showingAllGroups.toggle()
                    }
                    .buttonStyle(.borderless)
                    .foregroundStyle(GullsStyle.accent)
                    .padding(.top, 12)
                }
            }
        }
    }

    private func section<Content: View>(_ title: String, detail: String? = nil,
                                        @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(title)
                    .font((compact ? Font.subheadline : Font.headline).weight(.semibold))
                if let detail {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            content()
        }
    }

    private func routeLine(for relationship: DashboardRelationship) -> some View {
        HStack(spacing: 8) {
            Text(relationship.counterpart)
            Image(systemName: "arrow.right")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(relationship.ownedGullDisplayName ?? relationship.ownedGullHandle)
        }
        .font(.subheadline.weight(.medium))
        .foregroundStyle(.primary)
    }

    private func metric(_ title: String, value: Int) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value.formatted())
                .font(.title3.weight(.semibold))
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func statusLine(for relationship: DashboardRelationship) -> some View {
        let inProgress = relationship.groups.filter { $0.state == .inProgress }.count
        let handled = relationship.groups.filter { $0.state == .handled }.count
        return Text("\(relationship.attentionCount) need review · \(inProgress) in progress · \(handled) handled")
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    private func shortCounterpartLabel(for relationship: DashboardRelationship) -> String {
        let value = relationship.counterpartHandle ?? relationship.counterpart
        let local = value.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: true).first.map(String.init) ?? value
        return local.trimmingCharacters(in: CharacterSet(charactersIn: "@ "))
    }

    private func routeName(_ relationship: DashboardRelationship) -> String {
        relationship.ownedGullDisplayName ?? relationship.ownedGullHandle
    }

    private func latestReceivedItem(for relationship: DashboardRelationship) -> (item: InboxItem, group: DashboardConversationGroup)? {
        relationship.groups
            .flatMap { group in group.items.map { (item: $0, group: group) } }
            .max { lhs, rhs in
                let left = receivedDate(for: lhs.item)
                let right = receivedDate(for: rhs.item)
                if left != right { return (left ?? .distantPast) < (right ?? .distantPast) }
                return lhs.item.id < rhs.item.id
            }
    }

    private func receivedDate(for item: InboxItem) -> Date? {
        if let raw = item.delivery.createdAt, let date = GullsDates.parse(raw) { return date }
        return item.message?.createdAt.flatMap(GullsDates.parse)
    }

    private func latestDate(_ item: InboxItem?) -> String {
        guard let item, let date = receivedDate(for: item) else { return "Date unavailable" }
        return date.formatted(.relative(presentation: .named))
    }

    private func stateLabel(_ state: DashboardGroupState) -> String {
        switch state {
        case .needsAttention: return "Needs review"
        case .inProgress: return "In progress"
        case .handled: return "Handled"
        }
    }

    private func stateColor(_ state: DashboardGroupState) -> Color {
        switch state {
        case .needsAttention: return GullsStyle.accent
        case .inProgress: return .orange
        case .handled: return .secondary
        }
    }
}
