import XCTest
@testable import Gulls

// Decodes the same golden fixtures the CLI's contract test
// (internal/agentcli/cli_contract_test.go) writes. If the CLI's --json shape
// changes, the Go test fails; if the fixtures are regenerated, this fails —
// contract drift always breaks a test in the same commit.
final class ModelDecodingTests: XCTestCase {

    static let contractDir: URL = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent() // GullsTests
        .deletingLastPathComponent() // mac
        .deletingLastPathComponent() // apps
        .deletingLastPathComponent() // gulls
        .appendingPathComponent("connect/local-agent/internal/agentcli/testdata/contract")

    private func fixture(_ name: String) throws -> Data {
        let url = Self.contractDir.appendingPathComponent(name + ".json")
        return try Data(contentsOf: url)
    }

    private let decoder = JSONDecoder()

    func testVersionFixture() throws {
        let info = try decoder.decode(VersionInfo.self, from: fixture("version"))
        XCTAssertEqual(info.program, "gulls")
        XCTAssertFalse(info.version.isEmpty)
    }

    func testWhoamiFixtureNestedAgent() throws {
        let response = try decoder.decode(WhoamiResponse.self, from: fixture("whoami"))
        XCTAssertEqual(response.agent.handle, "@worker:gulls.ai")
        XCTAssertEqual(response.agent.status, "active")
    }

    func testWhoamiTopLevelAgentFallback() throws {
        let json = Data(#"{"handle": "@flat:gulls.ai", "status": "active"}"#.utf8)
        let response = try decoder.decode(WhoamiResponse.self, from: json)
        XCTAssertEqual(response.agent.handle, "@flat:gulls.ai")
    }

    func testInboxFixture() throws {
        let response = try decoder.decode(InboxResponse.self, from: fixture("inbox"))
        XCTAssertEqual(response.items.count, 1)
        let item = try XCTUnwrap(response.items.first)
        XCTAssertEqual(item.id, "delivery_1")
        XCTAssertEqual(item.delivery.status, "delivered")
        // No sender_handle from the hub — display must fall back to sender_agent_id.
        XCTAssertEqual(item.senderDisplay, "agent_alice")
        XCTAssertEqual(item.bodyText, "Please review the deploy notes.")
    }

    func testOpenFixture() throws {
        let result = try decoder.decode(OpenResult.self, from: fixture("open"))
        XCTAssertEqual(result.contextPath, "<CONTEXT_DIR>/delivery_1.md")
        XCTAssertEqual(result.delivery?.deliveryId, "delivery_1")
    }

    func testDraftReplyFixture() throws {
        let result = try decoder.decode(DraftReplyResult.self, from: fixture("draft_reply"))
        XCTAssertEqual(result.outcome, "draft_reply")
        XCTAssertEqual(result.draftSent, false)
        XCTAssertEqual(result.deliveryDecisionSubmitted, false)
        XCTAssertNil(result.deliveryDecision)
        XCTAssertNotNil(result.draft)
        XCTAssertEqual(result.appliedRules?["source"], .string("connector_config"))
    }

    func testDraftReplyApprovedFixture() throws {
        let result = try decoder.decode(DraftReplyResult.self, from: fixture("draft_reply_approved"))
        XCTAssertEqual(result.draftSent, true)
        XCTAssertEqual(result.deliveryDecisionSubmitted, true)
        let decision = try XCTUnwrap(result.deliveryDecision)
        XCTAssertEqual(decision.delivery.status, "replied")
        XCTAssertEqual(decision.reply?.messageId, "message_reply")
    }

    func testReplyFixture() throws {
        let result = try decoder.decode(DecisionResult.self, from: fixture("reply"))
        XCTAssertEqual(result.delivery.status, "replied")
        XCTAssertEqual(result.reply?.messageId, "message_reply")
    }

    func testIgnoreFixtureHasNullReply() throws {
        let result = try decoder.decode(DecisionResult.self, from: fixture("ignore"))
        XCTAssertEqual(result.delivery.status, "ignored")
        XCTAssertNil(result.reply)
    }

    func testWatchOnceFixture() throws {
        let result = try decoder.decode(WatchOnceResult.self, from: fixture("watch_once"))
        XCTAssertEqual(result.newCount, 1)
        XCTAssertEqual(result.contextPaths, ["<CONTEXT_DIR>/delivery_1.md"])
    }

    func testStreamLineFixtures() throws {
        let connected = try decoder.decode(StreamLine.self, from: fixture("stream_connected"))
        XCTAssertEqual(connected.type, "stream.connected")
        XCTAssertEqual(connected.url, "ws://localhost:8200/stream")

        let event = try decoder.decode(StreamLine.self, from: fixture("stream_event"))
        XCTAssertEqual(event.type, "stream.event")
        XCTAssertEqual(event.eventType, "seagull.delivery.created.v1")
        XCTAssertEqual(event.deliveryId, "delivery_1")

        let disconnected = try decoder.decode(StreamLine.self, from: fixture("stream_disconnected"))
        XCTAssertEqual(disconnected.type, "stream.disconnected")
        XCTAssertNotNil(disconnected.error)
    }

    func testEveryContractFixtureIsPresent() throws {
        // Guards against fixtures being renamed without updating these tests.
        let expected = [
            "ack", "draft_reply", "draft_reply_approved", "ignore", "inbox",
            "open", "reply", "stream_connected", "stream_disconnected",
            "stream_event", "version", "watch_once", "whoami",
        ]
        let present = try FileManager.default
            .contentsOfDirectory(atPath: Self.contractDir.path)
            .filter { $0.hasSuffix(".json") }
            .map { String($0.dropLast(5)) }
            .sorted()
        XCTAssertEqual(present, expected)
    }
}
