import Foundation
import XCTest
@testable import Gulls

final class CodexWorkQueueTests: XCTestCase {
    private let baseDate = Date(timeIntervalSince1970: 1_000)

    private func task(_ id: String, status: CodexTaskExecution.Status = .queued,
                      createdOffset: TimeInterval, queuedOffset: TimeInterval? = nil,
                      context: String? = "context-a", conversation: String? = "conversation-a",
                      publication: CodexWorkRecord.Publication = .ready,
                      route: CodexTaskRoute? = .embedded,
                      predecessor: String? = nil) -> CodexTask {
        let request = CodexTaskRequest(
            version: 1, taskID: id, profileID: "profile", gullHandle: "@gull:gulls.ai",
            connectionRevision: "revision", deliveryID: nil, threadID: nil, goal: id,
            workingDirectory: nil, contextPath: nil, createdAt: "2026-10-24T00:00:00Z"
        )
        var work = CodexWorkRecord(
            taskID: id, profileID: "profile", connectionRevision: "revision",
            apiBaseURL: "https://gulls.example", requestDigest: "request-(id)",
            conversationKey: conversation, sourceMessageID: nil, sourceDeliveryID: nil,
            ownerRequestID: "owner-(id)", deduplicationKey: "dedupe-(id)",
            instructionsDigest: "instructions", snapshotDigest: "snapshot",
            cliExecutablePath: "/Applications/Gulls.app/Contents/Resources/gulls",
            createdAt: baseDate.addingTimeInterval(createdOffset), publication: publication,
            route: route, contextID: context, predecessorTaskID: predecessor
        )
        work.queuedAt = queuedOffset.map { baseDate.addingTimeInterval($0) }
        return CodexTask(request: request, result: nil, resultError: nil,
                         execution: CodexTaskExecution(status: status), work: work)
    }

    private func selectedID(_ tasks: [CodexTask]) -> String? {
        CodexWorkQueue.next(in: tasks)?.id
    }

    func testSelectsReadyEmbeddedWorkInFIFOOrder() {
        let later = task("later", createdOffset: 2, queuedOffset: 2)
        let first = task("first", createdOffset: 1, queuedOffset: 1)
        XCTAssertEqual(selectedID([later, first]), "first")
    }

    func testQueuedTieUsesTaskIDDeterministically() {
        let beta = task("beta", createdOffset: 1, queuedOffset: 1)
        let alpha = task("alpha", createdOffset: 1, queuedOffset: 1)
        XCTAssertEqual(selectedID([beta, alpha]), "alpha")
    }

    func testActiveAndApprovalPredecessorsBlockSameContext() {
        for status in [CodexTaskExecution.Status.starting, .working, .needsApproval] {
            let predecessor = task("predecessor", status: status, createdOffset: 1)
            let candidate = task("candidate", createdOffset: 2)
            XCTAssertNil(selectedID([candidate, predecessor]), "\(status) must block its successor")
        }
    }

    func testFailedAndInterruptedPredecessorsBlockWithoutExplicitFollowUp() {
        for status in [CodexTaskExecution.Status.failed, .interrupted] {
            let predecessor = task("predecessor", status: status, createdOffset: 1)
            let candidate = task("candidate", createdOffset: 2)
            XCTAssertNil(selectedID([candidate, predecessor]), "\(status) must block an unrelated successor")
        }
    }

    func testExplicitFollowUpBypassesFailedAndInterruptedPredecessor() {
        for status in [CodexTaskExecution.Status.failed, .interrupted] {
            let predecessor = task("predecessor", status: status, createdOffset: 1)
            let followUp = task("follow-up", createdOffset: 2, predecessor: predecessor.id)
            XCTAssertEqual(selectedID([followUp, predecessor]), followUp.id)
        }
    }

    func testExplicitFollowUpNeverBypassesUncertainOrNeedsApproval() {
        for status in [CodexTaskExecution.Status.uncertain, .needsApproval] {
            let predecessor = task("predecessor", status: status, createdOffset: 1)
            let followUp = task("follow-up", createdOffset: 2, predecessor: predecessor.id)
            XCTAssertNil(selectedID([followUp, predecessor]), "\(status) must remain blocking")
        }
    }

    func testUncertainSameConversationBlocksAcrossContexts() {
        let uncertain = task("uncertain", status: .uncertain, createdOffset: 1,
                             context: "old-context", conversation: "shared-conversation")
        let candidate = task("candidate", createdOffset: 2,
                             context: "new-context", conversation: "shared-conversation")
        XCTAssertNil(selectedID([candidate, uncertain]))
    }

    func testDifferentConversationIsEligibleDespiteUncertainPredecessor() {
        let uncertain = task("uncertain", status: .uncertain, createdOffset: 1,
                             context: "old-context", conversation: "conversation-a")
        let candidate = task("candidate", createdOffset: 2,
                             context: "new-context", conversation: "conversation-b")
        XCTAssertEqual(selectedID([candidate, uncertain]), candidate.id)
    }

    func testCancelledPredecessorReleasesCandidate() {
        let cancelled = task("cancelled", status: .cancelled, createdOffset: 1)
        let candidate = task("candidate", createdOffset: 2)
        XCTAssertEqual(selectedID([candidate, cancelled]), candidate.id)
    }

    func testPreparedOrExternalWorkIsNeverDispatched() {
        let prepared = task("prepared", createdOffset: 1, publication: .prepared)
        let external = task("external", createdOffset: 2, route: .external)
        XCTAssertNil(selectedID([prepared, external]))
    }
}
