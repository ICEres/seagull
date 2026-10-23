import SwiftUI

struct OverviewView: View {
    @Environment(MobileAppStore.self) private var store
    @State private var displayMode: OverviewDisplayMode = .map
    @State private var selectedHandle = ""

    private var gulls: [CloudGull] {
        store.ownedGulls.filter { selectedHandle.isEmpty || $0.handle == selectedHandle }
    }

    private var snapshot: OverviewSnapshot {
        OverviewSnapshot(gulls: gulls, inbox: store.inboxByHandle, sent: store.sentByHandle, saved: store.savedGulls)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                summary
                connections
                activity
                if !snapshot.attention.isEmpty { attention }
                Text(store.syncIssue ?? "Based on saved message history. Pull to refresh.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, 28)
            .frame(maxWidth: 720)
            .frame(maxWidth: .infinity)
        }
        .background(GullsTheme.background.ignoresSafeArea())
        .navigationTitle("Overview.")
        .navigationBarTitleDisplayMode(.large)
        .toolbar { GullsNavigationTitle("Overview") }
        .refreshable { await store.refresh() }
        .onChange(of: store.ownedGulls.map(\.handle)) { _, handles in
            if !selectedHandle.isEmpty && !handles.contains(selectedHandle) { selectedHandle = "" }
        }
    }

    private var summary: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                GullsPageTitle("Your network")
                    .font(.title3.weight(.semibold))
                Spacer()
                Menu {
                    Picker("Gull", selection: $selectedHandle) {
                        Text("All Gulls").tag("")
                        ForEach(store.ownedGulls) { gull in
                            Text(gull.displayName ?? gull.handle).tag(gull.handle)
                        }
                    }
                } label: {
                    HStack(spacing: 5) {
                        Text(gulls.count == 1 ? (gulls.first?.displayName ?? "Your Gull") : "All Gulls")
                            .lineLimit(1)
                        Image(systemName: "chevron.down").font(.caption2.weight(.semibold))
                    }
                    .font(.subheadline)
                    .frame(minHeight: 44)
                }
                .accessibilityLabel("Filter overview by Gull")
            }
            HStack(spacing: 12) {
                OverviewMetric(value: snapshot.counterpartCount, label: "Connections")
                OverviewMetric(value: snapshot.conversationCount, label: "Conversations")
                OverviewMetric(value: snapshot.attention.count, label: "Needs you", emphasized: !snapshot.attention.isEmpty)
            }
        }
    }

    private var connections: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Connections").font(.headline)
                Spacer()
                HStack(spacing: 18) {
                    ForEach(OverviewDisplayMode.allCases) { mode in
                        Button {
                            withAnimation(.smooth(duration: 0.2)) { displayMode = mode }
                        } label: {
                            Text(mode.rawValue.capitalized)
                                .font(.subheadline.weight(displayMode == mode ? .semibold : .regular))
                                .foregroundStyle(displayMode == mode ? GullsTheme.accent : Color.secondary)
                                .frame(minHeight: 44)
                        }
                        .buttonStyle(.plain)
                        .accessibilityAddTraits(displayMode == mode ? .isSelected : [])
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityLabel("Connection view")
            }
            if snapshot.connections.isEmpty {
                ContentUnavailableView("Your network starts here", systemImage: "point.3.connected.trianglepath.dotted", description: Text("Conversations with other Gulls will build this view."))
                    .frame(maxWidth: .infinity)
            } else if displayMode == .map {
                OverviewRelationshipMap(connections: Array(snapshot.connections.prefix(6)), gulls: gulls)
                if snapshot.connections.count > 6 {
                    Text("Showing 6 recent connections. Choose List to see all.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                VStack(spacing: 0) {
                    ForEach(snapshot.connections) { connection in
                        connectionLink(connection)
                        if connection.id != snapshot.connections.last?.id {
                            Divider().padding(.leading, 62)
                        }
                    }
                }
                .padding(.horizontal, 14)
                .background(GullsTheme.surface, in: .rect(cornerRadius: 22))
            }
        }
    }

    private var activity: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Messages").font(.headline)
                Spacer()
                Text("Last 7 days").font(.caption).foregroundStyle(.secondary)
            }
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(snapshot.activity.reduce(0) { $0 + $1.count }.formatted())
                    .font(.system(.largeTitle, design: .rounded, weight: .semibold)).monospacedDigit()
                Text("sent and received").font(.subheadline).foregroundStyle(.secondary)
            }
            OverviewActivityChart(activity: snapshot.activity)
        }
        .gullsSurface()
    }

    private var attention: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Needs you").font(.headline)
            ForEach(snapshot.attention) { connection in
                connectionLink(connection)
            }
        }
    }

    private func connectionLink(_ connection: OverviewConnection) -> some View {
        NavigationLink {
            NetworkConversationView(ownedHandle: connection.ownedHandle, threadID: connection.threadID, counterpartHandle: connection.handle)
        } label: {
            HStack(spacing: 12) {
                GullAvatar(handle: connection.handle, size: 44)
                VStack(alignment: .leading, spacing: 4) {
                    Text(connection.name).font(.subheadline.weight(.semibold)).foregroundStyle(.primary).lineLimit(1)
                    Text("via \(connection.ownedName)").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 8)
                Text(connection.messageCount.formatted()).font(.subheadline.monospacedDigit()).foregroundStyle(.secondary)
                Image(systemName: "chevron.right").font(.caption2.weight(.semibold)).foregroundStyle(.tertiary)
            }
            .padding(.vertical, 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

private enum OverviewDisplayMode: String, CaseIterable, Identifiable {
    case map, list
    var id: String { rawValue }
}

private struct OverviewConnection: Identifiable {
    let ownedHandle: String
    let ownedName: String
    let handle: String
    var name: String
    var threadID: String
    var latestDate: Date
    var messageIDs: Set<String>
    var needsYou: Bool
    var id: String { "\(ownedHandle)|\(handle)" }
    var messageCount: Int { messageIDs.count }
}

private struct OverviewActivity: Identifiable {
    let date: Date
    let count: Int
    var id: Date { date }
}

private struct OverviewSnapshot {
    var connections: [OverviewConnection] = []
    var activity: [OverviewActivity] = []
    var conversationCount = 0
    var counterpartCount: Int { Set(connections.map(\.handle)).count }
    var attention: [OverviewConnection] { connections.filter(\.needsYou) }

    init(gulls: [CloudGull], inbox: [String: [MobileInboxItem]], sent: [String: [MobileMessage]], saved: [SavedGull]) {
        var relationships: [String: OverviewConnection] = [:]
        var threadIDs: Set<String> = []
        var messageDates: [String: Date] = [:]
        for gull in gulls {
            func include(handle: String, name: String?, threadID: String?, messageID: String?, date: String?, needsYou: Bool) {
                guard let threadID, !threadID.isEmpty, handle.hasPrefix("@"), handle != gull.handle else { return }
                let parsedDate = MobileDates.parse(date) ?? .distantPast
                let key = "\(gull.handle)|\(handle)"
                let identifier = messageID ?? "\(key)|\(threadID)|\(date ?? "")"
                threadIDs.insert("\(gull.handle)|\(threadID)")
                messageDates[identifier] = parsedDate
                let displayName = saved.first(where: { $0.handle == handle })?.displayName ?? name ?? handle
                if var existing = relationships[key] {
                    existing.messageIDs.insert(identifier)
                    existing.needsYou = existing.needsYou || needsYou
                    if parsedDate >= existing.latestDate {
                        existing.threadID = threadID
                        existing.latestDate = parsedDate
                        existing.name = displayName
                    }
                    relationships[key] = existing
                } else {
                    relationships[key] = OverviewConnection(ownedHandle: gull.handle, ownedName: gull.displayName ?? gull.handle, handle: handle, name: displayName, threadID: threadID, latestDate: parsedDate, messageIDs: [identifier], needsYou: needsYou)
                }
            }
            for item in inbox[gull.handle] ?? [] {
                include(handle: item.sender, name: item.message?.senderDisplayName, threadID: item.delivery.threadID ?? item.message?.threadID, messageID: item.message?.messageID ?? item.delivery.messageID, date: item.message?.createdAt ?? item.delivery.createdAt, needsYou: item.delivery.currentStage == "human.review" || item.delivery.status == "failed")
            }
            for message in sent[gull.handle] ?? [] {
                for handle in message.recipientHandles ?? [] {
                    include(handle: handle, name: nil, threadID: message.threadID, messageID: message.messageID, date: message.createdAt, needsYou: false)
                }
            }
        }
        connections = relationships.values.sorted { $0.latestDate > $1.latestDate }
        conversationCount = threadIDs.count
        let calendar = Calendar.current
        let today = calendar.startOfDay(for: .now)
        activity = (-6...0).map { offset in
            let date = calendar.date(byAdding: .day, value: offset, to: today) ?? today
            return OverviewActivity(date: date, count: messageDates.values.filter { calendar.isDate($0, inSameDayAs: date) }.count)
        }
    }
}

private struct OverviewMetric: View {
    let value: Int
    let label: String
    var emphasized = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(value.formatted()).font(.title.weight(.semibold)).monospacedDigit()
                .foregroundStyle(emphasized ? GullsTheme.accent : Color.primary)
            Text(label).font(.caption).foregroundStyle(.secondary).lineLimit(1).minimumScaleFactor(0.85)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

private struct OverviewRelationshipMap: View {
    let connections: [OverviewConnection]
    let gulls: [CloudGull]
    private let height: CGFloat = 290

    private func point(at index: Int, width: CGFloat) -> CGPoint {
        let angle = (Double(index) / Double(max(connections.count, 3))) * .pi * 2 - .pi / 2
        return CGPoint(x: width / 2 + cos(angle) * max(72, width / 2 - 48), y: height / 2 + sin(angle) * 102)
    }

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                Canvas { context, size in
                    for index in connections.indices {
                        var path = Path()
                        path.move(to: CGPoint(x: size.width / 2, y: height / 2))
                        path.addLine(to: point(at: index, width: size.width))
                        context.stroke(path, with: .color(GullsTheme.accent.opacity(0.2)), lineWidth: 1.5)
                    }
                }
                VStack(spacing: 6) {
                    GullAvatar(handle: gulls.count == 1 ? gulls[0].handle : "gulls-network", size: 52)
                    Text(gulls.count == 1 ? (gulls[0].displayName ?? "Your Gull") : "Your Gulls")
                        .font(.caption.weight(.semibold)).lineLimit(1)
                }
                .frame(width: 90)
                .position(x: geometry.size.width / 2, y: height / 2)
                ForEach(Array(connections.enumerated()), id: \.element.id) { index, connection in
                    NavigationLink {
                        NetworkConversationView(ownedHandle: connection.ownedHandle, threadID: connection.threadID, counterpartHandle: connection.handle)
                    } label: {
                        VStack(spacing: 5) {
                            GullAvatar(handle: connection.handle, size: 40)
                            Text(connection.name).font(.caption2.weight(.medium)).foregroundStyle(.primary).lineLimit(1)
                        }
                        .frame(width: 88, height: 68)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .position(point(at: index, width: geometry.size.width))
                    .accessibilityLabel("\(connection.name), via \(connection.ownedName), \(connection.messageCount) messages")
                }
            }
        }
        .frame(height: height)
        .background(GullsTheme.surface, in: .rect(cornerRadius: 22))
    }
}

private struct OverviewActivityChart: View {
    let activity: [OverviewActivity]
    private var maxCount: Int { max(activity.map(\.count).max() ?? 0, 1) }

    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            ForEach(activity) { day in
                VStack(spacing: 8) {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(GullsTheme.accent.opacity(day.count == 0 ? 0.12 : 0.7))
                        .frame(height: max(3, CGFloat(day.count) / CGFloat(maxCount) * 76))
                    Text(day.date, format: .dateTime.weekday(.narrow)).font(.caption2).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .frame(height: 104, alignment: .bottom)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Messages in the last seven days")
        .accessibilityValue(activity.map { "\($0.date.formatted(.dateTime.weekday())), \($0.count) messages" }.joined(separator: "; "))
    }
}

#Preview("Overview") {
    NavigationStack { OverviewView() }
        .environment(MobileAppStore.preview())
}
