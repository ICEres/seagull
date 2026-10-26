import Foundation
import XCTest
@testable import Gulls

@MainActor
final class CodexLiveIntegrationTests: XCTestCase {
    private final class MemoryTokens: GullsTokenStore {
        func token(for profileID: String) -> String? { nil }
        func legacyToken() -> String? { nil }
        func setToken(_ token: String, for profileID: String) -> Bool { true }
    }

    private struct LiveFailure: Error, LocalizedError {
        let errorDescription: String?
    }

    func testLiveConversationContinuityAndDraftFiles() async throws {
        guard ProcessInfo.processInfo.environment["GULLS_CODEX_LIVE_TEST"] == "1" else {
            throw XCTSkip("Opt-in only. Set GULLS_CODEX_LIVE_TEST=1 to run the live Codex smoke.")
        }
        guard let model = ProcessInfo.processInfo.environment["GULLS_CODEX_LIVE_MODEL"]?.trimmingCharacters(in: .whitespacesAndNewlines),
              !model.isEmpty else {
            throw XCTSkip("Set GULLS_CODEX_LIVE_MODEL to an available Codex catalog ID.")
        }

        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("gulls-codex-live-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let suite = "gulls-codex-live-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        let config = GullsConfig(profileID: "live-\(UUID().uuidString)", defaults: defaults,
                                  tokenStore: MemoryTokens())
        config.apiURL = "https://live.example.test"
        config.agentHandle = "@codex-live:gulls.ai"
        config.contextDir = root.appendingPathComponent("context", isDirectory: true).path
        config.codexEnabled = true

        guard model.range(of: "^[A-Za-z0-9][A-Za-z0-9._/-]*$", options: .regularExpression) != nil else {
            throw LiveFailure(errorDescription: "GULLS_CODEX_LIVE_MODEL is not a valid Codex catalog ID: \(model)")
        }
        let policy = CodexRuntimePolicy()
        let server = CodexAppServer(launchArguments: {
            try policy.startupArguments()
                + ["-c", "model=\"\(model)\"", "-c", "model_reasoning_effort=\"low\""]
        })
        var passed = false
        defer {
            server.shutdown()
            defaults.removePersistentDomain(forName: suite)
            if passed {
                try? FileManager.default.removeItem(at: root)
            } else {
                XCTContext.runActivity(named: "Preserved live test artifacts") { activity in
                    activity.add(XCTAttachment(string: root.path))
                }
            }
        }
        let readiness = CodexReadiness(server: server, executableURL: server.executableURLForReadiness)
        let report = await readiness.check()
        guard report.isReady else {
            throw LiveFailure(errorDescription: "Codex is not ready: \(report.message)")
        }
        guard report.modelIDs.contains(model) else {
            throw LiveFailure(errorDescription: "GULLS_CODEX_LIVE_MODEL is not in the available Codex catalog: \(model)")
        }

        let coordinator = CodexExecutionCoordinator(server: server, policy: policy)
        let store = CodexTaskStore(config: config, executor: coordinator)
        let marker = "GULLS_LIVE_MARKER_\(UUID().uuidString.replacingOccurrences(of: "-", with: "").uppercased())"

        let first = try store.create(
            goal: "Remember this exact synthetic marker for the next turn: \(marker). Reply only with ACK.",
            workingDirectory: nil,
            cliExecutableURL: URL(fileURLWithPath: "/usr/bin/true")
        )
        try await store.run(first)
        let firstCompleted = try await waitForDraft(store, taskID: first.id, timeout: 120)
        let firstThread = try XCTUnwrap(firstCompleted.execution?.codexThreadID)
        let firstResultURL = resultURL(for: firstCompleted, in: store)
        let firstResultData = try Data(contentsOf: firstResultURL)
        let firstResult = try JSONDecoder().decode(CodexTaskResult.self, from: firstResultData)
        XCTAssertEqual(firstResult.content.trimmingCharacters(in: .whitespacesAndNewlines), "ACK")

        let followUpGoal = "Return only the exact synthetic marker from your previous turn."
        try await store.run(firstCompleted, followUp: followUpGoal)
        let second = try XCTUnwrap(store.tasks.first { $0.request.goal == followUpGoal })
        let secondCompleted = try await waitForDraft(store, taskID: second.id, timeout: 120)
        let secondThread = try XCTUnwrap(secondCompleted.execution?.codexThreadID)
        XCTAssertEqual(secondThread, firstThread, "The follow-up must resume the original Codex thread.")

        let secondResultURL = resultURL(for: secondCompleted, in: store)
        XCTAssertNotEqual(firstResultURL, secondResultURL)
        XCTAssertTrue(FileManager.default.fileExists(atPath: firstResultURL.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: secondResultURL.path))
        XCTAssertEqual(try Data(contentsOf: firstResultURL), firstResultData,
                       "The first result file must remain immutable after the follow-up.")
        let secondResult = try JSONDecoder().decode(CodexTaskResult.self, from: Data(contentsOf: secondResultURL))
        XCTAssertEqual(secondResult.content.trimmingCharacters(in: .whitespacesAndNewlines), marker,
                       "The follow-up should return the marker from the prior turn.")
        XCTAssertEqual(secondCompleted.work?.draftDisposition ?? .available, .available)
        XCTAssertEqual(store.draftCount, 2)
        passed = true
    }

    private func waitForDraft(_ store: CodexTaskStore, taskID: String, timeout: TimeInterval) async throws -> CodexTask {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let task = store.tasks.first(where: { $0.id == taskID }) {
                switch task.execution?.status {
                case .draftReady:
                    return task
                case .failed, .uncertain, .cancelled, .interrupted:
                    throw LiveFailure(errorDescription: "Codex turn ended in \(task.execution?.status.rawValue ?? "unknown"): \(task.execution?.error ?? "no error")")
                case .queued, .starting, .working, .needsApproval, nil:
                    break
                }
            }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw LiveFailure(errorDescription: "Timed out waiting for Codex task \(taskID) to produce a draft.")
    }

    private func resultURL(for task: CodexTask, in store: CodexTaskStore) -> URL {
        store.tasksDirectory
            .appendingPathComponent(task.id, isDirectory: true)
            .appendingPathComponent("result.json")
    }
}
