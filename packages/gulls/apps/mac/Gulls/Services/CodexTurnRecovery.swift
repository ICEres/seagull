import CryptoKit
import Foundation

/// Resolves an uncertain Codex dispatch from a `thread/read` response.
///
/// Recovery is deliberately proof based: a response is usable only when it
/// identifies the expected thread and either the recorded turn ID or the
/// recorded nonce plus input digest identifies exactly one turn.
enum CodexTurnRecovery {
    static let maximumOutputBytes = 128 * 1024

    enum Failure: LocalizedError, Equatable {
        case malformedResponse(String)
        case wrongThread(expected: String, actual: String?)
        case noMatchingTurn
        case ambiguousMatch
        case outputTooLarge
        case completedTurnHasNoFinalAssistantText
        case completedTurnItemsIncomplete

        var errorDescription: String? {
            switch self {
            case .malformedResponse(let detail): return "Codex thread response is malformed: \(detail)"
            case .wrongThread(let expected, let actual):
                let actualDescription = actual ?? "missing"
                return "Codex thread response is for the wrong thread (expected \(expected), got \(actualDescription))."
            case .noMatchingTurn:
                return "The Codex response does not prove which submitted turn belongs to this task."
            case .ambiguousMatch:
                return "The Codex response matches more than one submitted turn. Recovery was stopped."
            case .outputTooLarge:
                return "The Codex response exceeds the 128 KiB recovery limit."
            case .completedTurnHasNoFinalAssistantText:
                return "Codex marked the turn completed, but no final assistant message was returned."
            case .completedTurnItemsIncomplete:
                return "Codex marked the turn completed, but its message items were only partially loaded."
            }
        }
    }

    static func resolve(thread: [String: Any], expectedThreadID: String,
                        execution: CodexTaskExecution, nonce: String?,
                        inputDigest: String?, publicReplySubmitted: Bool = false) throws -> CodexTaskExecution {
        let object: [String: Any]
        if let nested = thread["thread"] as? [String: Any] {
            object = nested
        } else {
            object = thread
        }

        let actualThreadID = object["id"] as? String
        guard actualThreadID == expectedThreadID else {
            throw Failure.wrongThread(expected: expectedThreadID, actual: actualThreadID)
        }
        guard let turns = object["turns"] as? [[String: Any]] else {
            throw Failure.malformedResponse("missing turns")
        }

        var matches: [[String: Any]] = []
        if let turnID = execution.turnID {
            // A recorded turn ID is stronger evidence than the input proof. If
            // it is absent from the response, do not silently adopt another
            // turn that happens to contain the same nonce.
            matches.append(contentsOf: turns.filter { $0["id"] as? String == turnID })
        } else if let nonce, let inputDigest {
            for turn in turns where hasSubmittedInput(turn, nonce: nonce, digest: inputDigest) {
                if !matches.contains(where: { ($0["id"] as? String) == (turn["id"] as? String) }) {
                    matches.append(turn)
                }
            }
        }

        guard !matches.isEmpty else { throw Failure.noMatchingTurn }
        guard matches.count == 1 else { throw Failure.ambiguousMatch }
        guard let status = matches[0]["status"] as? String else {
            throw Failure.malformedResponse("matching turn is missing status")
        }

        var recovered = execution
        let turn = matches[0]
        if let turnID = turn["id"] as? String { recovered.turnID = turnID }
        recovered.codexThreadID = actualThreadID

        switch status {
        case "inProgress":
            recovered.status = .uncertain
            recovered.error = "The Codex turn is still in progress. Review it before starting another attempt."
            recovered.output = try boundedAssistantText(in: turn, allowEmpty: true)
            return recovered
        case "failed":
            recovered.status = .failed
            recovered.error = turnErrorMessage(in: turn) ?? "Codex turn failed."
            recovered.completedAt = timestampString(turn["completedAt"] as? NSNumber) ?? recovered.completedAt
            return recovered
        case "interrupted":
            recovered.status = .interrupted
            recovered.error = turnErrorMessage(in: turn) ?? "Codex turn was interrupted."
            recovered.completedAt = timestampString(turn["completedAt"] as? NSNumber) ?? recovered.completedAt
            return recovered
        case "completed":
            guard (turn["itemsView"] as? String ?? "full") == "full" else {
                throw Failure.completedTurnItemsIncomplete
            }
            let output = try boundedAssistantText(in: turn, allowEmpty: publicReplySubmitted, finalOnly: true)
            recovered.status = .draftReady
            recovered.output = output.isEmpty && publicReplySubmitted
                ? "Public reply submitted to Gulls. Delivery is tracked separately." : output
            recovered.error = nil
            recovered.completedAt = timestampString(turn["completedAt"] as? NSNumber)
                ?? ISO8601DateFormatter().string(from: Date())
            return recovered
        default:
            throw Failure.malformedResponse("unknown turn status \(status)")
        }
    }

    private static func hasSubmittedInput(_ turn: [String: Any], nonce: String, digest: String) -> Bool {
        guard let items = turn["items"] as? [[String: Any] ] else { return false }
        for item in items where item["type"] as? String == "userMessage" {
            guard let content = item["content"] as? [[String: Any]] else { continue }
            for part in content where part["type"] as? String == "text" {
                guard let text = part["text"] as? String, text.contains(nonce) else { continue }
                let hash = SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
                if hash == digest { return true }
            }
        }
        return false
    }

    private static func boundedAssistantText(in turn: [String: Any], allowEmpty: Bool,
                                             finalOnly: Bool = false) throws -> String {
        guard let items = turn["items"] as? [[String: Any]] else {
            if allowEmpty { return "" }
            throw Failure.completedTurnHasNoFinalAssistantText
        }
        let messages = items.filter { $0["type"] as? String == "agentMessage" }
        let nonEmpty: ([String: Any]) -> Bool = { item in
            guard let value = item["text"] as? String else { return false }
            return !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        let eligible: [[String: Any]]
        if finalOnly {
            // Prefer an explicitly terminal answer even when a legacy message
            // without a phase appears later in the item list.
            let finalAnswers = messages.filter { ($0["phase"] as? String) == "final_answer" && nonEmpty($0) }
            let legacy = messages.filter { $0["phase"] == nil && nonEmpty($0) }
            eligible = finalAnswers.isEmpty ? legacy : finalAnswers
        } else {
            eligible = messages.filter(nonEmpty)
        }
        let text = eligible.compactMap { $0["text"] as? String }.last ?? ""
        if !allowEmpty && text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw Failure.completedTurnHasNoFinalAssistantText
        }
        guard text.utf8.count <= maximumOutputBytes else { throw Failure.outputTooLarge }
        return text
    }

    private static func turnErrorMessage(in turn: [String: Any]) -> String? {
        guard let error = turn["error"] as? [String: Any] else { return nil }
        return error["message"] as? String
    }

    private static func timestampString(_ value: NSNumber?) -> String? {
        guard let value else { return nil }
        let date = Date(timeIntervalSince1970: value.doubleValue)
        return ISO8601DateFormatter().string(from: date)
    }
}
