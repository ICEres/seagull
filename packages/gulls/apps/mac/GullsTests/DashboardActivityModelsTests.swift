import XCTest
@testable import Gulls

final class DashboardActivityModelsTests: XCTestCase {
    private let utc = TimeZone(secondsFromGMT: 0)!

    private func calendar() -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = utc
        return calendar
    }

    private func item(_ id: String, createdAt: String? = nil, messageCreatedAt: String? = nil,
                      updatedAt: String? = nil, sender: String = "atlas") throws -> InboxItem {
        var delivery = "\"delivery_id\": \"\(id)\", \"status\": \"acked\""
        if let createdAt { delivery += ", \"created_at\": \"\(createdAt)\"" }
        if let updatedAt { delivery += ", \"updated_at\": \"\(updatedAt)\"" }
        var message = "\"sender_handle\": \"\(sender)\""
        if let messageCreatedAt { message += ", \"created_at\": \"\(messageCreatedAt)\"" }
        return try JSONDecoder().decode(
            InboxItem.self,
            from: Data("{\"delivery\": {\(delivery)}, \"message\": {\(message)}}".utf8)
        )
    }

    private func profile(_ id: String, items: [InboxItem]) -> DashboardProfileInput {
        DashboardProfileInput(profileID: id, handle: id, displayName: nil, items: items)
    }

    func testReturnsExactlySevenCalendarDaysWithZeroes() {
        let now = date("2026-10-19T12:00:00Z")
        let days = DashboardActivityProjector.makeDays(from: [], now: now, calendar: calendar())
        XCTAssertEqual(days.count, 7)
        XCTAssertEqual(days.first?.date, date("2026-10-13T00:00:00Z"))
        XCTAssertEqual(days.last?.date, date("2026-10-19T00:00:00Z"))
        XCTAssertTrue(days.allSatisfy { $0.receivedCount == 0 })
    }

    func testCalendarBoundariesAndDateFallback() throws {
        let now = date("2026-10-19T12:00:00Z")
        let boundary = try item("boundary", createdAt: "2026-10-19T00:00:00Z")
        let fallback = try item("fallback", createdAt: "invalid", messageCreatedAt: "2026-10-18T23:59:59Z")
        let result = DashboardActivityProjector.makeDays(from: [profile("one", items: [boundary, fallback])], now: now, calendar: calendar())
        XCTAssertEqual(result[5].receivedCount, 1)
        XCTAssertEqual(result[6].receivedCount, 1)
    }

    func testDedupesPerProfileButCountsSameDeliveryIDAcrossProfiles() throws {
        let first = try item("same", createdAt: "2026-10-19T10:00:00Z")
        let duplicate = try item("same", createdAt: "2026-10-19T10:01:00Z")
        let otherProfile = try item("same", createdAt: "2026-10-19T10:02:00Z")
        let result = DashboardActivityProjector.makeDays(from: [
            profile("one", items: [first, duplicate]), profile("two", items: [otherProfile])
        ], now: date("2026-10-19T12:00:00Z"), calendar: calendar())
        XCTAssertEqual(result.last?.receivedCount, 2)
    }

    func testUpdatedAtDoesNotMoveActivityIntoToday() throws {
        let old = try item("old", createdAt: "2026-10-17T09:00:00Z", updatedAt: "2026-10-19T11:00:00Z")
        let result = DashboardActivityProjector.makeDays(from: [profile("one", items: [old])], now: date("2026-10-19T12:00:00Z"), calendar: calendar())
        XCTAssertEqual(result[4].receivedCount, 1)
        XCTAssertEqual(result[6].receivedCount, 0)
    }

    func testExcludesUndatedAndFutureEvents() throws {
        let undated = try item("undated")
        let future = try item("future", createdAt: "2026-10-19T13:00:00Z")
        let result = DashboardActivityProjector.makeDays(from: [profile("one", items: [undated, future])], now: date("2026-10-19T12:00:00Z"), calendar: calendar())
        XCTAssertTrue(result.allSatisfy { $0.receivedCount == 0 })
    }

    private func date(_ value: String) -> Date {
        XCTAssertNotNil(GullsDates.parse(value))
        return GullsDates.parse(value)!
    }
}
