import Foundation
import XCTest
@testable import Gulls

@MainActor
final class GullDirectoryStoreTests: XCTestCase {
    private func defaults() throws -> UserDefaults {
        let suite = "gull-directory-tests.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suite) else { throw XCTSkip("Unable to create isolated defaults") }
        return defaults
    }

    private func profile(handle: String = "@Atlas:Northstar.Example", name: String? = "Atlas",
                         capabilities: [String] = ["Research"]) -> GullPublicProfile {
        GullPublicProfile(agentID: "agent-atlas", handle: handle, displayName: name,
                           capabilities: capabilities, status: "active", updatedAt: nil)
    }

    func testSavedGullsSurviveStoreRecreationAndKeepPrivateLabels() throws {
        let defaults = try defaults()
        let store = GullDirectoryStore(defaults: defaults)
        let saved = try store.save(profile(), userID: "user-a", websiteURL: "https://SEA.GULLS.AI/")
        XCTAssertEqual(saved.handle, "@atlas:northstar.example")
        XCTAssertEqual(saved.displayName, "Atlas")

        let labeled = try store.updateLabels([" Project A ", "reading", "project a"], for: saved.handle,
                                             userID: "user-a", websiteURL: "https://sea.gulls.ai")
        XCTAssertEqual(labeled.labels, ["Project A", "reading"])

        let reloaded = GullDirectoryStore(defaults: defaults)
        let records = reloaded.records(for: "user-a", websiteURL: "https://sea.gulls.ai/")
        XCTAssertEqual(records.count, 1)
        XCTAssertEqual(records.first?.labels, ["Project A", "reading"])
    }

    func testUpsertDeduplicatesCanonicalHandlesAndPreservesLocalChoices() throws {
        let defaults = try defaults()
        let store = GullDirectoryStore(defaults: defaults)
        let first = try store.save(profile(), userID: "user-a", websiteURL: "https://sea.gulls.ai")
        _ = try store.updateLabels(["Keep"], for: first.handle, userID: "user-a", websiteURL: "https://sea.gulls.ai")
        _ = try store.updateDisplayName("My Atlas", for: first.handle, userID: "user-a", websiteURL: "https://sea.gulls.ai")

        let refreshed = try store.save(profile(handle: "@atlas:northstar.example", name: "Atlas v2", capabilities: ["Writing"]),
                                       userID: "user-a", websiteURL: "https://sea.gulls.ai/")
        XCTAssertEqual(store.records(for: "user-a", websiteURL: "https://sea.gulls.ai").count, 1)
        XCTAssertEqual(refreshed.displayName, "My Atlas")
        XCTAssertEqual(refreshed.labels, ["Keep"])
        XCTAssertEqual(refreshed.declaredCapabilities, ["Writing"])
    }

    func testSameAgentWithNewAddressKeepsLabelsAndCustomName() throws {
        let defaults = try defaults()
        let store = GullDirectoryStore(defaults: defaults)
        let first = try store.save(profile(handle: "@atlas:northstar.example"), userID: "user-a", websiteURL: "https://sea.gulls.ai")
        _ = try store.updateLabels(["Keep"], for: first.handle, userID: "user-a", websiteURL: "https://sea.gulls.ai")
        _ = try store.updateDisplayName("My Atlas", for: first.handle, userID: "user-a", websiteURL: "https://sea.gulls.ai")

        let refreshed = try store.save(profile(handle: "@atlas:other.example", name: "Atlas refreshed"),
                                       userID: "user-a", websiteURL: "https://sea.gulls.ai")
        let records = store.records(for: "user-a", websiteURL: "https://sea.gulls.ai")
        XCTAssertEqual(records.count, 1)
        XCTAssertEqual(refreshed.handle, "@atlas:other.example")
        XCTAssertEqual(refreshed.id, "agent-atlas")
        XCTAssertEqual(refreshed.labels, ["Keep"])
        XCTAssertEqual(refreshed.displayName, "My Atlas")
    }

    func testPublicRefreshClearsEmptyCapabilitiesButObservedRelationshipPreservesThem() throws {
        let defaults = try defaults()
        let store = GullDirectoryStore(defaults: defaults)
        _ = try store.save(profile(capabilities: ["Research"]), userID: "user-a", websiteURL: "https://sea.gulls.ai")
        let relationship = DashboardRelationship(
            id: "agent:agent-atlas", profileID: "owned", ownedGullHandle: "@me:gulls.ai",
            ownedGullDisplayName: "Me", counterpartID: "agent:agent-atlas", counterpart: "Atlas",
            counterpartHandle: "@atlas:northstar.example", groups: [], deliveryCount: 0,
            attentionCount: 0, updatedAt: nil
        )
        let observed = try store.save(relationship, userID: "user-a", websiteURL: "https://sea.gulls.ai")
        XCTAssertEqual(observed.declaredCapabilities, ["Research"])

        let cleared = try store.save(profile(capabilities: []), userID: "user-a", websiteURL: "https://sea.gulls.ai")
        XCTAssertTrue(cleared.declaredCapabilities.isEmpty)
    }

    func testAccountsAndWebsiteOriginsAreIsolated() throws {
        let defaults = try defaults()
        let store = GullDirectoryStore(defaults: defaults)
        _ = try store.save(profile(handle: "@atlas:northstar.example"), userID: "user-a", websiteURL: "https://sea.gulls.ai")
        _ = try store.save(profile(handle: "@mira:fieldnotes.example"), userID: "user-b", websiteURL: "https://sea.gulls.ai")
        _ = try store.save(profile(handle: "@atlas:northstar.example"), userID: "user-a", websiteURL: "https://other.example")

        XCTAssertEqual(store.records(for: "user-a", websiteURL: "https://sea.gulls.ai").map(\.handle), ["@atlas:northstar.example"])
        XCTAssertEqual(store.records(for: "user-b", websiteURL: "https://sea.gulls.ai").map(\.handle), ["@mira:fieldnotes.example"])
        XCTAssertEqual(store.records(for: "user-a", websiteURL: "https://other.example").map(\.handle), ["@atlas:northstar.example"])
    }

    func testInvalidHandlesAreRejectedAndRemovalIsScoped() throws {
        let defaults = try defaults()
        let store = GullDirectoryStore(defaults: defaults)
        XCTAssertThrowsError(try store.save(profile(handle: "atlas.example"), userID: "user-a", websiteURL: "https://sea.gulls.ai")) { error in
            XCTAssertEqual(error as? SavedGullError, .invalidHandle)
        }
        _ = try store.save(profile(), userID: "user-a", websiteURL: "https://sea.gulls.ai")
        XCTAssertThrowsError(try store.remove("@atlas:northstar.example", userID: "user-b", websiteURL: "https://sea.gulls.ai")) { error in
            XCTAssertEqual(error as? SavedGullError, .notFound)
        }
        XCTAssertEqual(store.records(for: "user-a", websiteURL: "https://sea.gulls.ai").count, 1)
        try store.remove("@ATLAS:NORTHSTAR.EXAMPLE", userID: "user-a", websiteURL: "https://sea.gulls.ai/")
        XCTAssertTrue(store.records(for: "user-a", websiteURL: "https://sea.gulls.ai").isEmpty)
    }
}
