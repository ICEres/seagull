import XCTest
@testable import Gulls

final class DashboardRelationshipModelsTests: XCTestCase {
    private func item(_ id: String, status: String? = "delivered", threadID: String? = nil,
                      sender: String? = "plover", senderAgentID: String? = nil,
                      body: String? = "Review this", updatedAt: String? = nil) throws -> InboxItem {
        var delivery = "\"delivery_id\": \"\(id)\""
        if let status { delivery += ", \"status\": \"\(status)\"" }
        if let threadID { delivery += ", \"thread_id\": \"\(threadID)\"" }
        if let senderAgentID { delivery += ", \"sender_agent_id\": \"\(senderAgentID)\"" }
        if let updatedAt { delivery += ", \"updated_at\": \"\(updatedAt)\"" }
        var messageFields = [String]()
        if let sender { messageFields.append("\"sender_handle\": \"\(sender)\"") }
        if let senderAgentID { messageFields.append("\"sender_agent_id\": \"\(senderAgentID)\"") }
        if let threadID { messageFields.append("\"thread_id\": \"\(threadID)\"") }
        if let body { messageFields.append("\"content_inline\": \"\(body)\"") }
        let message = messageFields.isEmpty ? "" : ", \"message\": {\(messageFields.joined(separator: ", "))}"
        return try JSONDecoder().decode(InboxItem.self, from: Data("{\"delivery\": {\(delivery)}\(message)}".utf8))
    }

    private func profile(_ id: String, handle: String = "test2", items: [InboxItem]) -> DashboardProfileInput {
        DashboardProfileInput(profileID: id, handle: handle, displayName: id.capitalized, items: items)
    }

    func testSplitsMultiSenderThreadIntoRouteGroups() throws {
        let first = try item("a", status: "delivered", threadID: "t", sender: "atlas", updatedAt: "2026-10-18T10:00:00Z")
        let second = try item("b", status: "acked", threadID: "t", sender: "lumen", updatedAt: "2026-10-18T11:00:00Z")
        let result = DashboardRelationshipProjector.makeSnapshot(from: [profile("one", items: [first, second])])
        XCTAssertEqual(result.conversationCount, 1)
        XCTAssertEqual(result.relationships.count, 2)
        XCTAssertEqual(Set(result.relationships.flatMap { $0.groups }.map(\.items.count)), [1])
        XCTAssertEqual(result.relationships.first { $0.counterpart == "atlas" }?.groups.first?.primaryItem.id, "a")
    }

    func testDuplicateDeliveriesDoNotInflateCounts() throws {
        let item = try item("same", status: "delivered", threadID: "t", updatedAt: "2026-10-18T10:00:00Z")
        let result = DashboardRelationshipProjector.makeSnapshot(from: [profile("one", items: [item, item])])
        XCTAssertEqual(result.deliveryCount, 1)
        XCTAssertEqual(result.conversationCount, 1)
        XCTAssertEqual(result.relationships.first?.deliveryCount, 1)
    }

    func testProfilesAndThreadsRemainIsolated() throws {
        let first = try item("a", status: "delivered", threadID: "same", sender: "atlas")
        let second = try item("b", status: "delivered", threadID: "same", sender: "atlas")
        let result = DashboardRelationshipProjector.makeSnapshot(from: [
            profile("one", items: [first]), profile("two", handle: "studio", items: [second])
        ])
        XCTAssertEqual(result.conversationCount, 2)
        XCTAssertEqual(result.relationships.count, 2)
        XCTAssertEqual(Set(result.relationships.map(\.profileID)), ["one", "two"])
    }

    func testUnknownSendersStaySeparateAndUseHonestLabel() throws {
        let first = try item("a", sender: nil)
        let second = try item("b", sender: nil)
        let result = DashboardRelationshipProjector.makeSnapshot(from: [profile("one", items: [first, second])])
        XCTAssertEqual(result.relationships.count, 2)
        XCTAssertTrue(result.relationships.allSatisfy { $0.counterpart == "Unknown participant" })
        XCTAssertEqual(result.counterpartCount, 2)
    }

    func testHandleAliasMergesWithObservedAgentIdentityWithinOneGull() throws {
        let identified = try item("identified", status: "delivered", threadID: "t", sender: "atlas", senderAgentID: "agent-1")
        let aliased = try item("aliased", status: "delivered", threadID: "t", sender: "atlas")
        let result = DashboardRelationshipProjector.makeSnapshot(from: [profile("one", items: [identified, aliased])])
        XCTAssertEqual(result.relationships.count, 1)
        XCTAssertEqual(result.relationships.first?.counterpartID, "agent:agent-1")
        XCTAssertEqual(result.relationships.first?.deliveryCount, 2)
    }

    func testCrossProfileHandleAliasCountsOneCounterpart() throws {
        let identified = try item("identified", status: "delivered", sender: "atlas", senderAgentID: "agent-1")
        let aliased = try item("aliased", status: "delivered", sender: "atlas")
        let result = DashboardRelationshipProjector.makeSnapshot(from: [
            profile("one", items: [identified]), profile("two", items: [aliased])
        ])
        XCTAssertEqual(result.relationships.count, 2)
        XCTAssertEqual(result.counterpartCount, 1)
        XCTAssertTrue(result.relationships.allSatisfy { $0.counterpartID == "agent:agent-1" })
    }

    func testLatestIDOnlySenderRetainsOlderObservedHandle() throws {
        let older = try item("older", status: "delivered", threadID: "t", sender: "atlas", senderAgentID: "agent-1", updatedAt: "2026-10-18T10:00:00Z")
        let latest = try item("latest", status: "acked", threadID: "t", sender: nil, senderAgentID: "agent-1", updatedAt: "2026-10-18T11:00:00Z")
        let result = DashboardRelationshipProjector.makeSnapshot(from: [profile("one", items: [older, latest])])
        XCTAssertEqual(result.relationships.first?.counterpart, "atlas")
        XCTAssertEqual(result.relationships.first?.counterpartHandle, "atlas")
    }

    func testScopePreservesGloballyObservedAliasesAndRouteIDs() throws {
        let identified = try item("identified", sender: "atlas", senderAgentID: "agent-1")
        let aliased = try item("aliased", sender: "atlas")
        let all = DashboardRelationshipProjector.makeSnapshot(from: [
            profile("one", items: [identified]), profile("two", items: [aliased])
        ])
        let scoped = all.scoped(to: "two")
        XCTAssertEqual(scoped.relationships, all.relationships.filter { $0.profileID == "two" })
        XCTAssertEqual(scoped.relationships.first?.counterpartID, "agent:agent-1")
        XCTAssertEqual(scoped.counterpartCount, 1)
        XCTAssertEqual(scoped.conversationCount, 1)
        XCTAssertEqual(scoped.deliveryCount, 1)
        XCTAssertEqual(scoped.attentionCount, 1)
        XCTAssertEqual(all.scoped(to: nil), all)
        XCTAssertTrue(all.scoped(to: "missing").relationships.isEmpty)
        XCTAssertEqual(all.scoped(to: "missing").conversationCount, 0)
    }

    func testAmbiguousHandleAliasesStaySeparate() throws {
        let first = try item("first", status: "delivered", sender: "atlas", senderAgentID: "agent-1")
        let second = try item("second", status: "delivered", sender: "atlas", senderAgentID: "agent-2")
        let handleOnly = try item("handle", status: "delivered", sender: "atlas")
        let result = DashboardRelationshipProjector.makeSnapshot(from: [
            profile("one", items: [first]), profile("two", items: [second]), profile("three", items: [handleOnly])
        ])
        XCTAssertEqual(result.counterpartCount, 3)
        XCTAssertTrue(result.relationships.contains { $0.counterpartID == "handle:atlas" })
    }

    func testEqualDatesUseDeterministicRelationshipOrder() throws {
        let first = try item("a", status: "delivered", sender: "atlas", updatedAt: "2026-10-18T10:00:00Z")
        let second = try item("b", status: "delivered", sender: "lumen", updatedAt: "2026-10-18T10:00:00Z")
        let result = DashboardRelationshipProjector.makeSnapshot(from: [profile("one", items: [first, second])])
        XCTAssertEqual(result.relationships.map(\.counterpart), ["atlas", "lumen"])
    }

    func testZeroMessageGullAndDeterministicCounts() {
        let result = DashboardRelationshipProjector.makeSnapshot(from: [profile("empty", items: [])])
        XCTAssertEqual(result.gulls, [DashboardGullSummary(id: "empty", handle: "test2", displayName: "Empty", relationshipCount: 0, conversationCount: 0, deliveryCount: 0, attentionCount: 0)])
        XCTAssertTrue(result.relationships.isEmpty)
    }
}
