import SwiftUI

struct AIUsageSettingsView: View {
    @Bindable var account: CloudAccountStore
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isRefreshing = false
    @State private var refreshMessage: String?
    @State private var showingAllActivity = false
    @State private var showingAllowanceHistory = false

    private let activityLimit = 4
    private let allowanceHistoryLimit = 4

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            CloudSettingsSection("Allowance", detail: "Cloud processing credits shared by your account.") {
                HStack {
                    if isRefreshing {
                        ProgressView()
                            .controlSize(.small)
                        Text("Refreshing…")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else if let refreshMessage {
                        Label(refreshMessage, systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.red)
                            .fixedSize(horizontal: false, vertical: true)
                            .multilineTextAlignment(.leading)
                            .layoutPriority(1)
                    }
                    Spacer()
                    Button {
                        Task { await refresh() }
                    } label: {
                        Label("Refresh", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.borderless)
                    .disabled(isRefreshing)
                }

                if let usage = account.aiUsage {
                    usageSummary(usage)
                } else if isRefreshing {
                    ProgressView("Loading allowance…")
                } else {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Usage is unavailable", systemImage: "exclamationmark.triangle")
                            .font(.subheadline.weight(.medium))
                        Text(refreshMessage ?? account.error ?? "Try refreshing to load your allowance.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            if let usage = account.aiUsage {
                CloudSettingsSection("Usage by Gull", detail: "Each Gull’s share of all recorded tokens.") {
                    let totalTokens = usage.usage.reduce(0) { $0 + tokenCount($1) }
                    if usage.usage.isEmpty {
                        emptyState("No Gull usage yet", detail: "AI activity will appear here after a cloud reply.")
                    } else {
                        ForEach(Dictionary(grouping: usage.usage, by: \.agentID).sorted {
                            $0.value.reduce(0) { $0 + tokenCount($1) } > $1.value.reduce(0) { $0 + tokenCount($1) }
                        }, id: \.key) { agentID, records in
                            gullUsageRow(agentID, records: records, totalTokens: totalTokens)
                        }
                    }
                }
                CloudSettingsSection("Recent activity") {
                    let activity = usage.usage.sorted { ($0.createdAt ?? "") > ($1.createdAt ?? "") }
                    if activity.isEmpty {
                        emptyState("No recent activity", detail: "Your latest AI requests will appear here.")
                    } else {
                        ForEach(showingAllActivity ? activity : Array(activity.prefix(activityLimit))) { item in
                            usageRow(gullName(for: item.agentID), detail: "\(item.model) · \(readableDate(item.createdAt))", value: "\(tokenCount(item).formatted()) tokens")
                        }
                        if activity.count > activityLimit {
                            Button(showingAllActivity ? "Show less" : "Show all \(activity.count) requests") {
                                if reduceMotion {
                                    showingAllActivity.toggle()
                                } else {
                                    withAnimation(.easeInOut(duration: 0.18)) {
                                        showingAllActivity.toggle()
                                    }
                                }
                            }
                            .buttonStyle(.borderless)
                            .font(.caption.weight(.medium))
                        }
                    }
                }
                CloudSettingsSection("Allowance history", detail: "Credit changes granted to or used by this account.") {
                    let history = usage.entries.sorted { ($0.createdAt ?? "") > ($1.createdAt ?? "") }
                    if history.isEmpty {
                        emptyState("No allowance history", detail: "Credit changes will appear here when available.")
                            .padding(.top, 4)
                    } else {
                        ForEach(showingAllowanceHistory ? history : Array(history.prefix(allowanceHistoryLimit))) { item in
                            usageRow(item.reason, detail: readableDate(item.createdAt), value: "\(item.creditDelta >= 0 ? "+" : "")\(item.creditDelta) credits")
                        }
                        if history.count > allowanceHistoryLimit {
                            Button(showingAllowanceHistory ? "Show less" : "Show all \(history.count) changes") {
                                if reduceMotion {
                                    showingAllowanceHistory.toggle()
                                } else {
                                    withAnimation(.easeInOut(duration: 0.18)) {
                                        showingAllowanceHistory.toggle()
                                    }
                                }
                            }
                            .buttonStyle(.borderless)
                            .font(.caption.weight(.medium))
                        }
                    }
                }
            }
        }
        .padding(24)
        .task(id: account.sessionID) { await refresh() }
    }

    private func usageSummary(_ usage: CloudAIUsageSummary) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            CloudAllowanceProgress(
                title: "Credits remaining",
                available: usage.balance.availableCredits,
                total: usage.entries.reduce(0) { $0 + max($1.creditDelta, 0) }
            )
            HStack(spacing: 28) {
                metric("Tokens processed", value: usage.usage.reduce(0) { $0 + tokenCount($1) }.formatted())
                metric("Requests", value: usage.usage.count.formatted())
            }
        }
    }

    private func gullUsageRow(_ agentID: String, records: [CloudUsageRecord], totalTokens: Int) -> some View {
        let tokens = records.reduce(0) { $0 + tokenCount($1) }
        let share = Double(tokens) / Double(max(totalTokens, 1))
        let name = gullName(for: agentID)
        return VStack(alignment: .leading, spacing: 5) {
            usageRow(name, detail: "\(records.count) \(records.count == 1 ? "request" : "requests") · \(share.formatted(.percent.precision(.fractionLength(0)))) of tokens", value: "\(tokens.formatted()) tokens")
            ProgressView(value: share)
                .progressViewStyle(CloudUsageProgressStyle())
                .accessibilityLabel("\(name), share of total tokens")
                .accessibilityValue("\(tokens.formatted()) of \(totalTokens.formatted()) tokens")
        }
        .padding(.vertical, 3)
    }

    private func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        refreshMessage = nil
        defer { isRefreshing = false }
        let usageLoaded = await account.refreshAIUsage()
        await account.refreshGulls()
        if !usageLoaded {
            refreshMessage = account.error ?? "Could not load usage."
        }
    }

    private func tokenCount(_ record: CloudUsageRecord) -> Int {
        record.totalTokens ?? record.inputTokens + record.outputTokens
    }

    private func gullName(for agentID: String) -> String {
        guard let gull = account.ownedGulls.first(where: { $0.id == agentID }) else { return agentID }
        let name = gull.displayName?.trimmingCharacters(in: .whitespacesAndNewlines)
        return name?.isEmpty == false ? name! : gull.handle
    }

    private func readableDate(_ value: String?) -> String {
        CloudSettingsDate.label(value)
    }

    private func emptyState(_ title: String, detail: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.subheadline.weight(.medium))
            Text(detail).font(.caption).foregroundStyle(.secondary)
        }
    }

    private func metric(_ title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(value).font(.title3.weight(.semibold))
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
    }

    private func usageRow(_ title: String, detail: String, value: String) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.medium))
                Text(detail).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(value).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
        }
        .padding(.vertical, 3)
    }
}
