import Foundation

/// A page returned by the local runtime's durable history query.
///
/// History is deliberately separate from the live inbox snapshot: loading
/// older rows must never create notifications or change the monitoring queue.
struct MessageHistoryResponse: Decodable, Equatable {
    let items: [InboxItem]
    let nextCursor: String?
    let total: Int?
    let syncComplete: Bool?

    enum CodingKeys: String, CodingKey {
        case items
        case nextCursor = "next_cursor"
        case total
        case syncComplete = "sync_complete"
    }
}

struct MessageHistoryDailyCount: Decodable, Equatable, Identifiable {
    let day: String
    let count: Int
    var id: String { day }
}

struct MessageHistoryRelationshipCount: Decodable, Equatable, Identifiable {
    let sender: String
    let count: Int
    var id: String { sender }
}

struct MessageHistorySummary: Decodable, Equatable {
    let totalDeliveries: Int
    let pendingDeliveries: Int
    let distinctThreads: Int
    let distinctSenders: Int
    let dailyReceived: [MessageHistoryDailyCount]
    let relationships: [MessageHistoryRelationshipCount]
    let syncComplete: Bool?

    enum CodingKeys: String, CodingKey {
        case totalDeliveries = "total_deliveries"
        case pendingDeliveries = "pending_deliveries"
        case distinctThreads = "distinct_threads"
        case distinctSenders = "distinct_senders"
        case dailyReceived = "daily_received"
        case relationships
        case syncComplete = "sync_complete"
    }

    static func aggregate(_ summaries: [MessageHistorySummary]) -> MessageHistorySummary? {
        guard !summaries.isEmpty else { return nil }
        var days: [String: Int] = [:]
        var senders: [String: Int] = [:]
        for summary in summaries {
            for day in summary.dailyReceived { days[day.day, default: 0] += day.count }
            for relationship in summary.relationships { senders[relationship.sender, default: 0] += relationship.count }
        }
        return MessageHistorySummary(
            totalDeliveries: summaries.reduce(0) { $0 + $1.totalDeliveries },
            pendingDeliveries: summaries.reduce(0) { $0 + $1.pendingDeliveries },
            distinctThreads: summaries.reduce(0) { $0 + $1.distinctThreads },
            distinctSenders: senders.count,
            dailyReceived: days.keys.sorted().map { MessageHistoryDailyCount(day: $0, count: days[$0] ?? 0) },
            relationships: senders.keys.sorted().map { MessageHistoryRelationshipCount(sender: $0, count: senders[$0] ?? 0) },
            syncComplete: summaries.allSatisfy { $0.syncComplete == true }
        )
    }
}
