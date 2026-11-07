import XCTest
@testable import Gulls

final class DashboardModelsTests: XCTestCase {

    private func item(
        _ id: String,
        status: String? = "delivered",
        threadID: String? = nil,
        sender: String = "plover",
        body: String? = "Please review this",
        intent: String? = nil,
        updatedAt: String? = nil,
        currentStage: String? = nil
    ) throws -> InboxItem {
        var delivery = "\"delivery_id\": \"\(id)\""
        if let status { delivery += ", \"status\": \"\(status)\"" }
        if let threadID { delivery += ", \"thread_id\": \"\(threadID)\"" }
        if let updatedAt { delivery += ", \"updated_at\": \"\(updatedAt)\"" }
        if let currentStage { delivery += ", \"current_stage\": \"\(currentStage)\"" }
        var message = ""
        if let body {
            let threadField = threadID.map { ", \"thread_id\": \"\($0)\"" } ?? ""
            let intentField = intent.map { ", \"intent\": \"\($0)\"" } ?? ""
            message = ", \"message\": {\"sender_handle\": \"\(sender)\", \"content_inline\": \"\(body)\"\(threadField)\(intentField)}"
        }
        return try JSONDecoder().decode(InboxItem.self, from: Data("{\"delivery\": {\(delivery)}\(message)}".utf8))
    }

    private func profile(_ id: String, handle: String = "test2", items: [InboxItem]) -> DashboardProfileInput {
        DashboardProfileInput(profileID: id, handle: handle, displayName: id.capitalized, items: items)
    }

    func testSameThreadIsolatedPerOwnedGull() throws {
        let first = try item("d1", threadID: "thread-1", updatedAt: "2026-10-18T10:00:00Z")
        let second = try item("d2", threadID: "thread-1", updatedAt: "2026-10-18T11:00:00Z")

        let snapshot = DashboardProjector.makeSnapshot(from: [
            profile("local-a", items: [first]),
            profile("local-b", handle: "studio", items: [second])
        ])

        XCTAssertEqual(snapshot.allGroups.count, 2)
        XCTAssertEqual(Set(snapshot.allGroups.map(\.profileID)), Set(["local-a", "local-b"]))
        XCTAssertEqual(Set(snapshot.allGroups.map(\.threadID)), Set(["thread-1"]))
    }

    func testThreadGroupingFallsBackToDeliveryID() throws {
        let first = try item("d1", threadID: "thread-1", updatedAt: "2026-10-18T10:00:00Z")
        let second = try item("d2", updatedAt: "2026-10-18T11:00:00Z")
        let third = try item("d3", updatedAt: "2026-10-18T12:00:00Z")

        let snapshot = DashboardProjector.makeSnapshot(from: [profile("local-a", items: [first, second, third])])

        XCTAssertEqual(snapshot.allGroups.count, 3)
        XCTAssertEqual(snapshot.allGroups.map(\.id).filter { $0.contains("delivery:") }.count, 2)
    }

    func testIndependentPendingDeliveriesRemainInOneGroup() throws {
        let pendingOne = try item("d1", status: "delivered", threadID: "thread-1", updatedAt: "2026-10-18T10:00:00Z")
        let pendingTwo = try item("d2", status: "pending_action", threadID: "thread-1", sender: "orchid", body: "Approve the release", updatedAt: "2026-10-18T11:00:00Z")
        let handled = try item("d3", status: "acked", threadID: "thread-1", sender: "cedar", body: "Release approved", updatedAt: "2026-10-18T12:00:00Z")

        let group = try XCTUnwrap(DashboardModelsTests.snapshot([pendingOne, pendingTwo, handled]).needsAttention.first)
        XCTAssertEqual(group.items.map(\.id), ["d3", "d2", "d1"])
        XCTAssertEqual(group.attentionItems.map(\.id), ["d2", "d1"])
        XCTAssertEqual(group.attentionCount, 2)
        XCTAssertEqual(group.primaryItem.id, "d2")
        XCTAssertEqual(group.title, "Approve the release")
        XCTAssertEqual(group.counterpart, "orchid")
        XCTAssertEqual(group.snippet, "Approve the release")
    }

    func testOrderingAndStatesAreDeterministic() throws {
        let handled = try item("handled", status: "acked", threadID: "handled", updatedAt: "2026-10-18T12:00:00Z")
        let active = try item("active", status: "processing", threadID: "active", updatedAt: "2026-10-18T13:00:00Z")
        let replied = try item("replied", status: "replied", threadID: "replied", updatedAt: "2026-10-18T13:30:00Z")
        let failed = try item("failed", status: "failed", threadID: "failed", updatedAt: "2026-10-18T14:00:00Z")
        let snapshot = DashboardModelsTests.snapshot([handled, active, replied, failed])

        XCTAssertEqual(snapshot.needsAttention.map(\.threadID), ["failed"])
        XCTAssertEqual(snapshot.inProgress.map(\.threadID), ["active"])
        XCTAssertEqual(snapshot.handled.map(\.threadID), ["replied", "handled"])
        XCTAssertEqual(snapshot.attentionCount, 1)
    }

    func testUnknownAndMissingStatusesStayActionable() throws {
        let unknown = try item("unknown", status: "future_state", threadID: "unknown")
        let missing = try item("missing", status: nil, threadID: "missing")
        let snapshot = DashboardModelsTests.snapshot([unknown, missing])

        XCTAssertEqual(snapshot.needsAttention.count, 2)
        XCTAssertEqual(snapshot.attentionCount, 2)
    }

    func testUnknownStatusWithActiveStageStaysActionable() throws {
        let future = try item("future", status: "future_state", threadID: "future", currentStage: "processing")
        let missing = try item("missing", status: nil, threadID: "missing", currentStage: "processing")
        let snapshot = DashboardModelsTests.snapshot([future, missing])

        XCTAssertEqual(snapshot.needsAttention.count, 2)
        XCTAssertTrue(snapshot.inProgress.isEmpty)
    }

    func testProtocolIntentDoesNotBecomeWorkTitle() throws {
        let question = try item(
            "question",
            status: "delivered",
            threadID: "question-thread",
            body: "Can you confirm the launch window?",
            intent: "question"
        )
        let group = try XCTUnwrap(DashboardModelsTests.snapshot([question]).needsAttention.first)

        XCTAssertEqual(group.title, "Can you confirm the launch window?")
    }

    func testTerminalStatusWinsOverStaleActiveStage() throws {
        let replied = try item("replied", status: "replied", threadID: "replied", currentStage: "processing")
        let acked = try item("acked", status: "acked", threadID: "acked", currentStage: "sending")
        let snapshot = DashboardModelsTests.snapshot([replied, acked])

        XCTAssertTrue(snapshot.needsAttention.isEmpty)
        XCTAssertTrue(snapshot.inProgress.isEmpty)
        XCTAssertEqual(snapshot.handled.map(\.threadID), ["acked", "replied"])
    }

    func testBlankThreadIDFallsBackAndThreadNamespaceDoesNotCollide() throws {
        let fallback = try item("x", threadID: "   ")
        let realThread = try item("other", threadID: "delivery:x")
        let snapshot = DashboardModelsTests.snapshot([fallback, realThread])

        XCTAssertEqual(snapshot.allGroups.count, 2)
        XCTAssertTrue(snapshot.allGroups.contains { $0.id == "local-a:delivery:x" })
        XCTAssertTrue(snapshot.allGroups.contains { $0.id == "local-a:thread:delivery:x" })
    }

    func testProjectionCacheInvalidatesSameCountPayloadAndStatusChanges() throws {
        let oldItem = try item("d1", status: "delivered", threadID: "thread-1", body: "Old request")
        let newItem = try item("d1", status: "acked", threadID: "thread-1", body: "Updated request")
        let cache = DashboardProjectionCache()

        let initialProfile = profile("local-a", items: [oldItem])
        _ = cache.relationships(from: [initialProfile])
        let updatedProfile = profile("local-a", items: [newItem])
        let updatedSnapshot = cache.snapshot(from: [updatedProfile])
        let updatedRelationships = cache.relationships(from: [updatedProfile])

        XCTAssertTrue(updatedSnapshot.needsAttention.isEmpty)
        XCTAssertEqual(updatedSnapshot.handled.first?.title, "Updated request")
        XCTAssertEqual(updatedRelationships.attentionCount, 0)
        XCTAssertEqual(updatedRelationships.relationships.first?.groups.first?.latestItem.bodyText, "Updated request")
    }

    func testProjectionCacheRefreshesGullMetadataAndRemovesProfiles() throws {
        let message = try item("d1", threadID: "thread-1")
        let cache = DashboardProjectionCache()

        _ = cache.snapshot(from: [profile("local-a", handle: "old-handle", items: [message])])
        let renamed = profile("local-a", handle: "new-handle", items: [message])
        let renamedRelationships = cache.relationships(from: [renamed])

        XCTAssertEqual(renamedRelationships.gulls.first?.handle, "new-handle")
        XCTAssertEqual(renamedRelationships.relationships.first?.ownedGullHandle, "new-handle")

        let removedSnapshot = cache.snapshot(from: [])
        let removedRelationships = cache.relationships(from: [])
        XCTAssertTrue(removedSnapshot.allGroups.isEmpty)
        XCTAssertTrue(removedRelationships.relationships.isEmpty)
        XCTAssertTrue(removedRelationships.gulls.isEmpty)
    }

    func testProjectionCacheSupportsEitherProjectionAsFirstAccess() throws {
        let message = try item("d1", status: "delivered", threadID: "thread-1")
        let profile = self.profile("local-a", items: [message])
        let cache = DashboardProjectionCache()

        let relationships = cache.relationships(from: [profile])
        let snapshot = cache.snapshot(from: [profile])

        XCTAssertEqual(relationships.conversationCount, snapshot.allGroups.count)
        XCTAssertEqual(relationships.deliveryCount, 1)
        XCTAssertEqual(snapshot.attentionCount, 1)
    }

    private static func snapshot(_ items: [InboxItem]) -> DashboardSnapshot {
        DashboardProjector.makeSnapshot(from: [
            DashboardProfileInput(profileID: "local-a", handle: "test2", displayName: "Test2", items: items)
        ])
    }
}
