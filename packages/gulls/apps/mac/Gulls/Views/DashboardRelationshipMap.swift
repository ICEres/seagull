import SwiftUI

/// A shared-node map of relationships observed in the currently loaded inbox
/// window. The projection owns identity and counting rules; this view only
/// arranges those facts into a small, selectable diagram.
struct DashboardRelationshipMap: View {
    let snapshot: DashboardRelationshipSnapshot
    let accountName: String
    let selectedRelationshipID: String?
    let onSelect: (DashboardRelationship) -> Void
    var compact: Bool = false

    private let routeLimit = 6
    private let ownNodeLimit = 4
    @State private var hoveredNodeID: String?

    private var orderedRelationships: [DashboardRelationship] {
        snapshot.relationships.sorted { lhs, rhs in
            switch (lhs.updatedAt, rhs.updatedAt) {
            case let (left?, right?) where left != right: return left > right
            case (_?, nil): return true
            case (nil, _?): return false
            default:
                if lhs.attentionCount != rhs.attentionCount {
                    return lhs.attentionCount > rhs.attentionCount
                }
                return lhs.id < rhs.id
            }
        }
    }

    private var visibleRelationships: [DashboardRelationship] {
        var routes = Array(orderedRelationships.prefix(routeLimit))
        if let selectedRelationshipID,
           !routes.contains(where: { $0.id == selectedRelationshipID }),
           let selected = snapshot.relationships.first(where: { $0.id == selectedRelationshipID }) {
            if routes.isEmpty { return [selected] }
            routes[routes.count - 1] = selected
        }
        return routes
    }

    private var visibleOwnHandles: [String] {
        var handles = visibleRelationships.map(\.ownedGullHandle).uniquedPreservingOrder().sorted()
        if handles.count > ownNodeLimit,
           let selected = visibleRelationships.first(where: { $0.id == selectedRelationshipID })?.ownedGullHandle,
           !handles.prefix(ownNodeLimit).contains(selected) {
            handles[ownNodeLimit - 1] = selected
        }
        return Array(handles.prefix(ownNodeLimit).sorted())
    }

    private var visibleCounterpartIDs: [String] {
        visibleRelationships
            .sorted {
                let left = ($0.counterpart.lowercased(), $0.counterpartID)
                let right = ($1.counterpart.lowercased(), $1.counterpartID)
                return left < right
            }
            .map(\.counterpartID)
            .uniquedPreservingOrder()
    }

    private var renderedRelationships: [DashboardRelationship] {
        visibleRelationships.filter {
            visibleOwnHandles.contains($0.ownedGullHandle)
                && visibleCounterpartIDs.contains($0.counterpartID)
        }
    }

    private var diagramHeight: CGFloat {
        let peerCount = max(visibleCounterpartIDs.count, 1)
        let ownCount = max(visibleOwnHandles.count, 1)
        return min(430, max(330, CGFloat(max(peerCount, ownCount)) * 56 + 92))
    }

    var body: some View {
        if renderedRelationships.isEmpty {
            emptyState
        } else {
            diagram
        }
    }

    private var diagram: some View {
        VStack(alignment: .leading, spacing: 6) {
            GeometryReader { proxy in
            let layout = DashboardRelationshipGraphLayout(
                size: proxy.size,
                ownHandles: visibleOwnHandles,
                counterpartIDs: visibleCounterpartIDs,
                relationships: renderedRelationships
            )
            ZStack {
                DashboardRelationshipEdges(layout: layout, selectedRelationshipID: selectedRelationshipID)
                    .allowsHitTesting(false)

                ForEach(visibleOwnHandles, id: \.self) { handle in
                    if let point = layout.ownPoints[handle] {
                        let nodeID = "own:\(handle)"
                        let isSelected = snapshot.relationships.contains {
                            $0.id == selectedRelationshipID && $0.ownedGullHandle == handle
                        }
                        Button {
                            if let relationship = renderedRelationships.first(where: { $0.ownedGullHandle == handle }) {
                                onSelect(relationship)
                            }
                        } label: {
                            RelationshipNode(
                                avatar: .gull(handle),
                                title: layout.ownLabel(for: handle),
                                isSelected: isSelected,
                                isHovered: hoveredNodeID == nodeID
                            )
                        }
                        .buttonStyle(RelationshipNodeButtonStyle())
                        .frame(width: 84, height: 68, alignment: .top)
                        // Layout points are avatar centers; the fixed node
                        // frame keeps two-line labels below the route.
                        .position(CGPoint(x: point.x, y: point.y + 18))
                        .onHover { isHovered in
                            hoveredNodeID = isHovered ? nodeID : nil
                        }
                        .accessibilityLabel("Local Gull \(layout.ownLabel(for: handle))")
                        .accessibilityHint("Select its newest observed relationship")
                        .accessibilityAddTraits(isSelected ? .isSelected : [])
                    }
                }

                ForEach(visibleCounterpartIDs, id: \.self) { counterpartID in
                    if let point = layout.counterpartPoints[counterpartID],
                       let relationship = renderedRelationships.first(where: { $0.counterpartID == counterpartID }) {
                        let nodeID = "counterpart:\(counterpartID)"
                        let isSelected = snapshot.relationships.contains {
                            $0.id == selectedRelationshipID && $0.counterpartID == counterpartID
                        }
                        Button {
                            onSelect(layout.selectedRelationship(for: counterpartID, preferredID: selectedRelationshipID))
                        } label: {
                            RelationshipNode(
                                avatar: .gull(relationship.counterpartHandle ?? counterpartID),
                                title: participantLabel(relationship),
                                isSelected: isSelected,
                                isHovered: hoveredNodeID == nodeID
                            )
                        }
                        .buttonStyle(RelationshipNodeButtonStyle())
                        .frame(width: 84, height: 68, alignment: .top)
                        .position(CGPoint(x: point.x, y: point.y + 18))
                        .onHover { isHovered in
                            hoveredNodeID = isHovered ? nodeID : nil
                        }
                        .accessibilityLabel("Participant \(relationship.counterpart), connected to \(relationship.deliveryCount) deliveries")
                        .accessibilityHint("Select this participant's newest observed route")
                        .accessibilityAddTraits(isSelected ? .isSelected : [])
                        .help(relationship.counterpartHandle ?? relationship.counterpart)
                    }
                }

                ForEach(Array(renderedRelationships.enumerated()), id: \.element.id) { index, relationship in
                    let point = layout.edgeHitPoint(for: relationship, index: index)
                    Button { onSelect(relationship) } label: {
                        Color.clear.frame(width: 42, height: 42).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .position(point)
                    .accessibilityLabel(edgeAccessibilityLabel(relationship))
                    .accessibilityHint("Select this route")
                }

                ownerRoot(layout: layout)
            }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(height: diagramHeight)
            relationshipLegend
            if snapshot.relationships.count > renderedRelationships.count {
                Text("Showing \(renderedRelationships.count) of \(snapshot.relationships.count) routes · use By Gull to inspect the rest")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, 2)
            }
        }
        .accessibilityElement(children: .contain)
    }

    private var relationshipLegend: some View {
        HStack(spacing: 12) {
            LegendItem(dashed: true, title: "On this Mac")
            LegendItem(dashed: false, title: "Incoming")
        }
        .font(.caption2)
        .foregroundStyle(.tertiary)
        .fixedSize(horizontal: false, vertical: true)
    }

    private func ownerRoot(layout: DashboardRelationshipGraphLayout) -> some View {
        let point = CGPoint(x: max(28, layout.size.width * 0.10), y: 22)
        return VStack(spacing: 3) {
                HumanBadge(name: accountName, size: compact ? 24 : 28)
                Text("You").font(.caption2.weight(.medium)).foregroundStyle(.primary)
            }
        .frame(width: 56)
        .position(point)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accountName.isEmpty ? "You" : "You, \(accountName)")
        .accessibilityHint("Supervises Gulls connected on this Mac")
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("No relationships observed in the loaded deliveries.")
                .font(.subheadline).foregroundStyle(.secondary)
            Text("Gulls connected on this Mac")
                .font(.caption.weight(.medium)).foregroundStyle(.secondary)
            if snapshot.gulls.isEmpty {
                Text("New incoming routes will appear here as messages arrive.")
                    .font(.caption).foregroundStyle(.tertiary)
            } else {
                ForEach(snapshot.gulls.prefix(ownNodeLimit)) { gull in
                    HStack(spacing: 8) {
                        GullAvatar(handle: gull.handle, size: 24)
                        Text(gull.displayName ?? gull.handle).font(.subheadline).lineLimit(1)
                        Spacer(minLength: 4)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("Connected Gull \(gull.displayName ?? gull.handle)")
                }
            }
        }
        .padding(.top, 2)
    }

    private func edgeAccessibilityLabel(_ relationship: DashboardRelationship) -> String {
        let peer = relationship.counterpartHandle ?? relationship.counterpart
        let target = relationship.ownedGullDisplayName ?? relationship.ownedGullHandle
        var label = "Route from participant \(peer) to local Gull \(target), \(relationship.deliveryCount) deliveries"
        if relationship.attentionCount > 0 { label += ", \(relationship.attentionCount) need attention" }
        return label
    }

    private func participantLabel(_ relationship: DashboardRelationship) -> String {
        guard let handle = relationship.counterpartHandle else { return relationship.counterpart }
        return handle.split(separator: ":", maxSplits: 1).first.map(String.init) ?? handle
    }
}

private struct DashboardRelationshipGraphLayout {
    let size: CGSize
    let ownPoints: [String: CGPoint]
    let counterpartPoints: [String: CGPoint]
    let ownLabels: [String: String]
    let relationships: [DashboardRelationship]

    init(size: CGSize, ownHandles: [String], counterpartIDs: [String], relationships: [DashboardRelationship]) {
        self.size = size
        self.relationships = relationships
        let top: CGFloat = 78
        let bottom = max(top, size.height - 54)
        ownPoints = Self.points(for: ownHandles, x: max(62, size.width * 0.23), top: top, bottom: bottom)
        counterpartPoints = Self.points(for: counterpartIDs, x: min(size.width - 62, size.width * 0.77), top: top, bottom: bottom)
        ownLabels = Dictionary(uniqueKeysWithValues: ownHandles.map { handle in
            let relationship = relationships.first(where: { $0.ownedGullHandle == handle })
            return (handle, relationship?.ownedGullDisplayName ?? handle)
        })
    }

    func ownLabel(for handle: String) -> String { ownLabels[handle] ?? handle }

    func selectedRelationship(for counterpartID: String, preferredID: String?) -> DashboardRelationship {
        if let preferredID, let preferred = relationships.first(where: { $0.id == preferredID && $0.counterpartID == counterpartID }) {
            return preferred
        }
        return relationships.filter { $0.counterpartID == counterpartID }
            .sorted { ($0.updatedAt ?? .distantPast) > ($1.updatedAt ?? .distantPast) }
            .first ?? relationships[0]
    }

    func edgeHitPoint(for relationship: DashboardRelationship, index: Int) -> CGPoint {
        guard let source = counterpartPoints[relationship.counterpartID], let target = ownPoints[relationship.ownedGullHandle] else {
            return CGPoint(x: size.width / 2, y: 100 + CGFloat(index) * 12)
        }
        let midpoint = CGPoint(x: (source.x + target.x) / 2, y: (source.y + target.y) / 2)
        return CGPoint(x: midpoint.x, y: midpoint.y + CGFloat(index % 3 - 1) * 10)
    }

    private static func points(for keys: [String], x: CGFloat, top: CGFloat, bottom: CGFloat) -> [String: CGPoint] {
        guard !keys.isEmpty else { return [:] }
        let step = keys.count == 1 ? 0 : (bottom - top) / CGFloat(keys.count - 1)
        return Dictionary(uniqueKeysWithValues: keys.enumerated().map { index, key in
            (key, CGPoint(x: x, y: top + CGFloat(index) * step))
        })
    }
}

private struct DashboardRelationshipEdges: View {
    let layout: DashboardRelationshipGraphLayout
    let selectedRelationshipID: String?

    var body: some View {
        Canvas { context, _ in
            drawOwnership(in: &context)
            for relationship in layout.relationships { drawRoute(relationship, in: &context) }
        }
        .accessibilityHidden(true)
    }

    private func drawOwnership(in context: inout GraphicsContext) {
        let root = CGPoint(x: max(28, layout.size.width * 0.10), y: 35)
        for target in layout.ownPoints.values {
            var path = Path()
            path.move(to: root)
            path.addCurve(to: target, control1: CGPoint(x: root.x + 12, y: root.y + 14), control2: CGPoint(x: target.x - 28, y: target.y - 18))
            context.stroke(path, with: .color(.secondary.opacity(0.38)), style: StrokeStyle(lineWidth: 1, lineCap: .round, dash: [2, 4]))
        }
    }

    private func drawRoute(_ relationship: DashboardRelationship, in context: inout GraphicsContext) {
        guard let source = layout.counterpartPoints[relationship.counterpartID], let target = layout.ownPoints[relationship.ownedGullHandle] else { return }
        let selected = relationship.id == selectedRelationshipID
        let start = CGPoint(x: source.x - 35, y: source.y)
        let end = CGPoint(x: target.x + 35, y: target.y)
        let bend = max(34, (start.x - end.x) * 0.38)
        var path = Path()
        path.move(to: start)
        path.addCurve(to: end, control1: CGPoint(x: start.x - bend, y: start.y), control2: CGPoint(x: end.x + bend, y: end.y))
        context.stroke(path, with: .color(selected ? GullsStyle.accent : .secondary.opacity(0.46)), style: StrokeStyle(lineWidth: selected ? 2.2 : 1.2, lineCap: .round))
        var arrow = Path()
        arrow.move(to: end)
        arrow.addLine(to: CGPoint(x: end.x + 7, y: end.y - 4))
        arrow.move(to: end)
        arrow.addLine(to: CGPoint(x: end.x + 7, y: end.y + 4))
        context.stroke(arrow, with: .color(selected ? GullsStyle.accent : .secondary.opacity(0.46)), style: StrokeStyle(lineWidth: selected ? 2.2 : 1.2, lineCap: .round, lineJoin: .round))
    }
}

private struct RelationshipNode: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    enum Avatar { case gull(String) }
    let avatar: Avatar
    let title: String
    let isSelected: Bool
    let isHovered: Bool

    var body: some View {
        VStack(spacing: 4) {
            avatarView
            Text(title)
                .font(.caption.weight(.medium))
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .frame(width: 80)
                .truncationMode(.middle)
        }
        .frame(width: 84, height: 68, alignment: .top)
        .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: isSelected)
        .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: isHovered)
    }

    private var avatarView: some View {
        Group {
            switch avatar {
            case let .gull(handle):
                GullAvatar(handle: handle, size: 32)
            }
        }
        .background {
            Circle()
                .fill(isHovered && !isSelected ? GullsStyle.field : .clear)
                .frame(width: 36, height: 36)
        }
        .overlay {
            Circle().stroke(
                isSelected ? GullsStyle.accent.opacity(0.55) : isHovered ? Color.primary.opacity(0.18) : .clear,
                lineWidth: isSelected ? 1.2 : 0.8
            )
            .frame(width: 36, height: 36)
        }
    }
}

private struct RelationshipNodeButtonStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(!reduceMotion && configuration.isPressed ? 0.98 : 1)
    }
}

private struct LegendItem: View {
    let dashed: Bool
    let title: String

    var body: some View {
        HStack(spacing: 4) {
            Canvas { context, size in
                var path = Path()
                path.move(to: CGPoint(x: 0, y: size.height / 2))
                path.addLine(to: CGPoint(x: size.width, y: size.height / 2))
                context.stroke(
                    path,
                    with: .color(.secondary.opacity(0.7)),
                    style: StrokeStyle(lineWidth: 1, lineCap: .round, dash: dashed ? [2, 3] : [])
                )
            }
            .frame(width: 20, height: 8)
            Text(title)
                .lineLimit(1)
        }
        .accessibilityElement(children: .combine)
    }
}

private struct HumanBadge: View {
    let name: String
    let size: CGFloat

    private var initials: String {
        let words = name.split(whereSeparator: { $0 == " " || $0 == "_" || $0 == "-" })
        let letters = words.prefix(2).compactMap { $0.first }
        return letters.isEmpty ? "Y" : String(letters).uppercased()
    }

    var body: some View {
        Circle().fill(GullsStyle.accent.opacity(0.16)).overlay {
            Text(initials).font(.system(size: size * 0.34, weight: .semibold, design: .rounded)).foregroundStyle(GullsStyle.accent)
        }.frame(width: size, height: size).accessibilityHidden(true)
    }
}

private extension Array where Element: Equatable {
    func uniquedPreservingOrder() -> [Element] {
        reduce(into: []) { result, value in if !result.contains(value) { result.append(value) } }
    }
}
