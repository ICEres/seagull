import CryptoKit
import XCTest
@testable import Gulls

final class CodexTurnRecoveryTests: XCTestCase {
    private let threadID = "thread-1"
    private let turnID = "turn-1"
    private let nonce = "nonce-1"
    private let input = "Gulls private turn: nonce-1\nDraft a reply."

    private func digest(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func response(turns: [[String: Any]]) -> [String: Any] {
        ["thread": ["id": threadID, "turns": turns]]
    }

    private func turn(status: String = "completed", id: String = "turn-1",
                      items: [[String: Any]], error: [String: Any]? = nil,
                      itemsView: String? = nil, completedAt: Any? = nil) -> [String: Any] {
        var value: [String: Any] = ["id": id, "status": status, "items": items]
        if let error { value["error"] = error }
        if let itemsView { value["itemsView"] = itemsView }
        if let completedAt { value["completedAt"] = completedAt }
        return value
    }

    private func userItem(_ text: String = "Gulls private turn: nonce-1\nDraft a reply.") -> [String: Any] {
        ["id": "user-1", "type": "userMessage", "content": [["type": "text", "text": text]]]
    }

    private func agentItem(_ text: String) -> [String: Any] {
        ["id": "agent-1", "type": "agentMessage", "text": text]
    }

    private func agentItem(_ text: String, phase: String) -> [String: Any] {
        ["id": "agent-1", "type": "agentMessage", "text": text, "phase": phase]
    }

    private func execution(turnID: String? = "turn-1") -> CodexTaskExecution {
        CodexTaskExecution(status: .uncertain, codexThreadID: threadID, turnID: turnID)
    }

    func testMatchesExactTurnIDAndReturnsDraft() throws {
        let turn = turn(items: [userItem(), agentItem("final answer")])
        let result = try CodexTurnRecovery.resolve(thread: response(turns: [turn]), expectedThreadID: threadID,
                                                    execution: execution(), nonce: nil, inputDigest: nil)
        XCTAssertEqual(result.status, .draftReady)
        XCTAssertEqual(result.output, "final answer")
    }

    func testMatchesNonceAndInputDigestWhenTurnIDIsUnknown() throws {
        let turn = turn(items: [userItem(), agentItem("proofed answer")])
        let result = try CodexTurnRecovery.resolve(thread: response(turns: [turn]), expectedThreadID: threadID,
                                                    execution: execution(turnID: nil), nonce: nonce, inputDigest: digest(input))
        XCTAssertEqual(result.status, .draftReady)
        XCTAssertEqual(result.output, "proofed answer")
    }

    func testRecordedTurnIDDoesNotFallBackToNonceMatchForAnotherTurn() {
        let turn = turn(id: "different-turn", items: [userItem(), agentItem("answer")])
        XCTAssertThrowsError(try CodexTurnRecovery.resolve(thread: response(turns: [turn]), expectedThreadID: threadID,
                                                           execution: execution(), nonce: nonce, inputDigest: digest(input))) { error in
            XCTAssertEqual(error as? CodexTurnRecovery.Failure, .noMatchingTurn)
        }
    }

    func testRejectsNoMatchAndWrongThread() {
        XCTAssertThrowsError(try CodexTurnRecovery.resolve(thread: response(turns: []), expectedThreadID: threadID,
                                                           execution: execution(), nonce: nil, inputDigest: nil)) { error in
            XCTAssertEqual(error as? CodexTurnRecovery.Failure, .noMatchingTurn)
        }
        XCTAssertThrowsError(try CodexTurnRecovery.resolve(thread: response(turns: []), expectedThreadID: "other",
                                                           execution: execution(), nonce: nil, inputDigest: nil)) { error in
            XCTAssertEqual(error as? CodexTurnRecovery.Failure,
                           .wrongThread(expected: "other", actual: threadID))
        }
    }

    func testInProgressTurnRemainsUncertainWithPartialOutput() throws {
        let turn = turn(status: "inProgress", items: [userItem(), agentItem("partial")])
        let result = try CodexTurnRecovery.resolve(thread: response(turns: [turn]), expectedThreadID: threadID,
                                                    execution: execution(), nonce: nil, inputDigest: nil)
        XCTAssertEqual(result.status, .uncertain)
        XCTAssertEqual(result.output, "partial")
        XCTAssertTrue(result.error?.contains("still in progress") == true)
    }

    func testFailedAndInterruptedTurnsPreserveTerminalState() throws {
        let failed = turn(status: "failed", items: [userItem()], error: ["message": "provider failed"])
        let interrupted = turn(status: "interrupted", items: [userItem()])
        let failedResult = try CodexTurnRecovery.resolve(thread: response(turns: [failed]), expectedThreadID: threadID,
                                                          execution: execution(), nonce: nil, inputDigest: nil)
        let interruptedResult = try CodexTurnRecovery.resolve(thread: response(turns: [interrupted]), expectedThreadID: threadID,
                                                               execution: execution(), nonce: nil, inputDigest: nil)
        XCTAssertEqual(failedResult.status, .failed)
        XCTAssertEqual(failedResult.error, "provider failed")
        XCTAssertEqual(interruptedResult.status, .interrupted)
    }

    func testCompletedTurnWithoutFinalOutputIsRejected() {
        let turn = turn(items: [userItem()])
        XCTAssertThrowsError(try CodexTurnRecovery.resolve(thread: response(turns: [turn]), expectedThreadID: threadID,
                                                           execution: execution(), nonce: nil, inputDigest: nil)) { error in
            XCTAssertEqual(error as? CodexTurnRecovery.Failure, .completedTurnHasNoFinalAssistantText)
        }
    }

    func testToolOnlyCompletionRequiresPersistedPublicSubmission() throws {
        let completed = turn(items: [userItem()], itemsView: "full")
        let recovered = try CodexTurnRecovery.resolve(thread: response(turns: [completed]),
            expectedThreadID: threadID, execution: execution(), nonce: nil, inputDigest: nil,
            publicReplySubmitted: true)
        XCTAssertEqual(recovered.status, .draftReady)
        XCTAssertTrue(recovered.output.contains("submitted"))
        XCTAssertFalse(recovered.output.contains("sent"))
        let partial = turn(items: [userItem()], itemsView: "partial")
        XCTAssertThrowsError(try CodexTurnRecovery.resolve(thread: response(turns: [partial]),
            expectedThreadID: threadID, execution: execution(), nonce: nil, inputDigest: nil,
            publicReplySubmitted: true))
    }

    func testCommentaryOnlyCompletedTurnIsRejected() {
        let turn = turn(items: [userItem(), agentItem("progress", phase: "commentary")])
        XCTAssertThrowsError(try CodexTurnRecovery.resolve(thread: response(turns: [turn]), expectedThreadID: threadID,
                                                           execution: execution(), nonce: nil, inputDigest: nil)) { error in
            XCTAssertEqual(error as? CodexTurnRecovery.Failure, .completedTurnHasNoFinalAssistantText)
        }
    }

    func testCompletedTurnWithFinalAnswerPrefersItOverCommentary() throws {
        let turn = turn(items: [userItem(), agentItem("progress", phase: "commentary"),
                                agentItem("final", phase: "final_answer")])
        let result = try CodexTurnRecovery.resolve(thread: response(turns: [turn]), expectedThreadID: threadID,
                                                    execution: execution(), nonce: nil, inputDigest: nil)
        XCTAssertEqual(result.output, "final")
    }

    func testPartiallyLoadedCompletedTurnIsRejected() {
        let turn = turn(items: [userItem(), agentItem("final")], itemsView: "summary")
        XCTAssertThrowsError(try CodexTurnRecovery.resolve(thread: response(turns: [turn]), expectedThreadID: threadID,
                                                           execution: execution(), nonce: nil, inputDigest: nil)) { error in
            XCTAssertEqual(error as? CodexTurnRecovery.Failure, .completedTurnItemsIncomplete)
        }
    }

    func testCompletedTurnRequiresNonemptyTrimmedOutputAndUsesObservedTime() throws {
        let empty = turn(items: [userItem(), agentItem(" \n\t")])
        XCTAssertThrowsError(try CodexTurnRecovery.resolve(thread: response(turns: [empty]), expectedThreadID: threadID,
                                                           execution: execution(), nonce: nil, inputDigest: nil)) { error in
            XCTAssertEqual(error as? CodexTurnRecovery.Failure, .completedTurnHasNoFinalAssistantText)
        }

        let completed = turn(items: [userItem(), agentItem("answer")])
        let result = try CodexTurnRecovery.resolve(thread: response(turns: [completed]), expectedThreadID: threadID,
                                                    execution: execution(), nonce: nil, inputDigest: nil)
        XCTAssertNotNil(result.completedAt)
    }

    func testOutputLimitIsEnforced() {
        let oversized = String(repeating: "x", count: CodexTurnRecovery.maximumOutputBytes + 1)
        let turn = turn(items: [userItem(), agentItem(oversized)])
        XCTAssertThrowsError(try CodexTurnRecovery.resolve(thread: response(turns: [turn]), expectedThreadID: threadID,
                                                           execution: execution(), nonce: nil, inputDigest: nil)) { error in
            XCTAssertEqual(error as? CodexTurnRecovery.Failure, .outputTooLarge)
        }
    }
}
