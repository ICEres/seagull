import Foundation

struct DashboardActivityDay: Identifiable, Equatable {
    let date: Date
    let receivedCount: Int

    var id: Date { date }
}

enum DashboardActivityProjector {
    /// Counts received deliveries observed in the local inbox snapshots. The
    /// window is calendar based, while event timestamps remain absolute dates.
    static func makeDays(from profiles: [DashboardProfileInput],
                         now: Date = Date(),
                         calendar: Calendar = .current) -> [DashboardActivityDay] {
        let today = calendar.startOfDay(for: now)
        let starts = (-6...0).compactMap { calendar.date(byAdding: .day, value: $0, to: today) }
        guard starts.count == 7 else { return [] }
        let end = calendar.date(byAdding: .day, value: 1, to: today) ?? now
        var counts = Dictionary(uniqueKeysWithValues: starts.map { ($0, 0) })
        var seenByProfile: [String: Set<String>] = [:]

        for profile in profiles {
            var seen = seenByProfile[profile.profileID, default: []]
            for item in profile.items {
                guard seen.insert(item.id).inserted else { continue }
                guard let eventDate = receivedDate(for: item), eventDate <= now else { continue }
                guard eventDate >= starts[0], eventDate < end else { continue }
                let day = calendar.startOfDay(for: eventDate)
                if counts[day] != nil { counts[day, default: 0] += 1 }
            }
            seenByProfile[profile.profileID] = seen
        }

        return starts.map { DashboardActivityDay(date: $0, receivedCount: counts[$0, default: 0]) }
    }

    private static func receivedDate(for item: InboxItem) -> Date? {
        if let raw = item.delivery.createdAt, let date = GullsDates.parse(raw) { return date }
        if let raw = item.message?.createdAt, let date = GullsDates.parse(raw) { return date }
        return nil
    }
}
