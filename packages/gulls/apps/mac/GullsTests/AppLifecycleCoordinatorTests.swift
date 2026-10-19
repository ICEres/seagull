import XCTest
@testable import Gulls

@MainActor
final class AppLifecycleCoordinatorTests: XCTestCase {
    private final class MemoryTokenStore: GullsTokenStore {
        func token(for profileID: String) -> String? { nil }
        func legacyToken() -> String? { nil }
        @discardableResult
        func setToken(_ token: String, for profileID: String) -> Bool { true }
    }

    func testTestHostStartDoesNotStartPollingOrCloudSync() async {
        let suiteName = "lifecycle-tests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }

        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: MemoryTokenStore())
        let workspace = GullsWorkspace(
            connections: connections,
            cli: nil,
            notifier: Notifier(),
            notifiedDirectory: FileManager.default.temporaryDirectory
                .appendingPathComponent("lifecycle-\(UUID().uuidString)"),
            localControlDefaults: defaults
        )
        let account = CloudAccountStore(defaults: defaults, cli: nil, sharedSessionURL: nil)
        let coordinator = AppLifecycleCoordinator(workspace: workspace, account: account, isTestHost: true)

        coordinator.start()
        XCTAssertTrue(coordinator.isRunning)
        XCTAssertFalse(workspace.inboxes.values.contains { $0.isMonitoring })

        await coordinator.stop()
        XCTAssertFalse(coordinator.isRunning)
    }

    func testConfigurationErrorPreservesHealthyProfileRuntimeStatus() async throws {
        let suiteName = "lifecycle-runtime-tests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        defaults.set([GullsConfig.defaultProfileID, "invalid"], forKey: "gull.profileIDs")

        let temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("lifecycle-runtime-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)

        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: MemoryTokenStore())
        for config in connections.profiles {
            config.apiURL = "https://api.example.test"
            config.agentHandle = "@\(config.profileID):gulls.ai"
            config.contextDir = temporaryDirectory.appendingPathComponent(config.profileID).path
        }
        let validRevision = connections.profiles[0].connectionRevision
        let invalidRevision = connections.profiles[1].connectionRevision
        let binary = temporaryDirectory.appendingPathComponent("gulls")
        let script = """
        while IFS= read -r line; do
            id=$(printf '%s' "$line" | /usr/bin/plutil -extract id raw -o - - 2>/dev/null)
            operation=$(printf '%s' "$line" | /usr/bin/plutil -extract operation raw -o - - 2>/dev/null)
            if [ "$operation" = "configure" ]; then
                printf '{"version":1,"event":"inbox","profile_id":"default","revision":"\(validRevision)","status":"connected","inbox":{"items":[]}}\\n'
                printf '{"version":1,"event":"inbox","profile_id":"invalid","revision":"\(invalidRevision)","status":"unavailable","error":"invalid profile"}\\n'
                printf '{"version":1,"id":"%s","exit_code":2,"stdout":"","stderr":"one profile is invalid"}\\n' "$id"
            else
                printf '{"version":1,"id":"%s","exit_code":0,"stdout":"{}","stderr":""}\\n' "$id"
            fi
        done
        """
        try ("#!/bin/bash\n" + script).write(to: binary, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)

        let cli = GullsCLI(executableURL: binary)
        addTeardownBlock {
            await cli.stopRuntime()
            try? FileManager.default.removeItem(at: temporaryDirectory)
        }
        let workspace = GullsWorkspace(
            connections: connections,
            cli: cli,
            notifier: Notifier(),
            notifiedDirectory: temporaryDirectory.appendingPathComponent("notified"),
            localControlDefaults: defaults
        )

        await workspace.reconcile()
        for _ in 0..<100 {
            if workspace.inboxes[GullsConfig.defaultProfileID]?.runtimeStatus == "connected",
               workspace.inboxes["invalid"]?.runtimeStatus == "unavailable" {
                break
            }
            try await Task.sleep(for: .milliseconds(10))
        }

        XCTAssertEqual(workspace.inboxes[GullsConfig.defaultProfileID]?.runtimeStatus, "connected")
        XCTAssertEqual(workspace.inboxes["invalid"]?.runtimeStatus, "unavailable")
        XCTAssertTrue(workspace.runtimeError?.contains("one profile is invalid") == true)
    }
}
