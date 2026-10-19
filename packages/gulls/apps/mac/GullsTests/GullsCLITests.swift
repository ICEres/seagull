import XCTest
import Darwin
@testable import Gulls

// Exercises the Process bridge against fake `gulls` shell scripts: argument
// ordering, environment passing, exit-code mapping, and large-output draining.
final class GullsCLITests: XCTestCase {

    private final class RuntimeEventRecorder: @unchecked Sendable {
        private let lock = NSLock()
        private(set) var events: [RuntimeEvent] = []

        func append(_ event: RuntimeEvent) {
            lock.lock()
            events.append(event)
            lock.unlock()
        }
    }

    private var tmp: URL!

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("GullsCLITests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tmp)
    }

    private func makeFakeBinary(script: String, runtimeSocketURL: URL? = nil) throws -> GullsCLI {
        let url = tmp.appendingPathComponent("gulls")
        try ("#!/bin/bash\n" + script).write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        return GullsCLI(executableURL: url, runtimeSocketURL: runtimeSocketURL)
    }

    private func makeEnvironment(token: String? = "secret-token") -> GullsCLI.Environment {
        GullsCLI.Environment(
            apiURL: "https://api.example.test",
            agentHandle: "@worker:gulls.ai",
            token: token,
            contextDir: tmp.appendingPathComponent("context")
        )
    }

    private func makeRuntimeProfile(environment: GullsCLI.Environment,
                                    revision: String = "rev-1") -> RuntimeProfile {
        RuntimeProfile(id: "profile-a", revision: revision, environment: environment,
                       pollInterval: 1, monitoring: true)
    }

    private func makeRuntimeFixture(_ behavior: String = "normal", pidFile: URL? = nil) throws -> GullsCLI {
        let pidScript = pidFile.map { "echo $$ > \"\($0.path)\"" } ?? ""
        let restoreMarker = tmp.appendingPathComponent("restore-marker").path
        return try makeFakeBinary(script: """
        \(pidScript)
        while IFS= read -r line; do
            id=$(printf '%s' "$line" | /usr/bin/plutil -extract id raw -o - - 2>/dev/null)
            operation=$(printf '%s' "$line" | /usr/bin/plutil -extract operation raw -o - - 2>/dev/null)
            if [ "$operation" = "configure" ]; then
                if [ "\(behavior)" = "restore-config-error" ] && [ -f "\(restoreMarker)" ]; then
                    printf '{"version":1,"id":"%s","exit_code":1,"stdout":"","stderr":"restore failed"}\\n' "$id"
                    continue
                fi
            fi
            if [ "$operation" = "command" ] && { [ "\(behavior)" = "crash" ] || [ "\(behavior)" = "restore-config-error" ]; }; then
                if [ "\(behavior)" = "restore-config-error" ]; then
                    touch "\(restoreMarker)"
                fi
                kill $$
            fi
            printf '{"version":1,"id":"%s","exit_code":0,"stdout":"{}","stderr":""}\\n' "$id"
        done
        """, runtimeSocketURL: tmp.appendingPathComponent("runtime.sock"))
    }

    func testRuntimeRoutesRegisteredProfileCommandsThroughPersistentChild() async throws {
        let cli = try makeRuntimeFixture()
        let environment = makeEnvironment()
        let profile = makeRuntimeProfile(environment: environment)
        try await cli.configureRuntime([profile])
        defer { Task { await cli.stopRuntime() } }

        var routedEnvironment = environment
        routedEnvironment.profileID = profile.id
        routedEnvironment.connectionRevision = profile.revision
        let data = try await cli.run(["inbox"], environment: routedEnvironment)
        XCTAssertEqual(String(decoding: data, as: UTF8.self), "{}")
    }

    func testRuntimeCrashFailsPendingCommandWithoutOneShotFallback() async throws {
        let cli = try makeRuntimeFixture("crash")
        let environment = makeEnvironment()
        let profile = makeRuntimeProfile(environment: environment)
        try await cli.configureRuntime([profile])
        defer { Task { await cli.stopRuntime() } }

        var routedEnvironment = environment
        routedEnvironment.profileID = profile.id
        routedEnvironment.connectionRevision = profile.revision
        do {
            _ = try await cli.run(["reply", "delivery_1", "hello"], environment: routedEnvironment)
            XCTFail("expected runtime failure")
        } catch {
            XCTAssertTrue(error.localizedDescription.lowercased().contains("unavailable"),
                          "unexpected failure: \(error)")
        }
    }

    func testRuntimeRestoreConfigurationFailureIsSurfaced() async throws {
        let cli = try makeRuntimeFixture("restore-config-error")
        let unavailable = expectation(description: "runtime restore failure is reported")
        let recorder = RuntimeEventRecorder()
        try await cli.startRuntime { event in
            recorder.append(event)
            if event.status == .unavailable,
               event.error?.contains("restore") == true {
                unavailable.fulfill()
            }
        }
        addTeardownBlock {
            await cli.stopRuntime()
        }
        let environment = makeEnvironment()
        let profile = makeRuntimeProfile(environment: environment)
        try await cli.configureRuntime([profile])
        var routed = environment
        routed.profileID = profile.id
        routed.connectionRevision = profile.revision
        do {
            _ = try await cli.run(["reply", "delivery_1", "hello"], environment: routed)
            XCTFail("expected fixture child crash")
        } catch {
            // The in-flight request must fail; the recovery configuration is
            // deliberately attempted asynchronously and must not be replayed.
        }
        await fulfillment(of: [unavailable], timeout: 5)
        XCTAssertTrue(recorder.events.contains { $0.status == .unavailable })
    }

    func testRefreshRecoversAfterRuntimeCrash() async throws {
        let pidFile = tmp.appendingPathComponent("restore-runtime.pid")
        let cli = try makeRuntimeFixture("restore-config-error", pidFile: pidFile)
        let unavailable = expectation(description: "bounded restore attempts exhausted")
        try await cli.startRuntime { event in
            if event.status == .unavailable,
               event.error?.contains("stopped unexpectedly") == true {
                unavailable.fulfill()
            }
        }
        addTeardownBlock {
            await cli.stopRuntime()
        }
        let environment = makeEnvironment()
        let profile = makeRuntimeProfile(environment: environment)
        try await cli.configureRuntime([profile])
        var routed = environment
        routed.profileID = profile.id
        routed.connectionRevision = profile.revision
        do { _ = try await cli.run(["reply", "delivery_1", "hello"], environment: routed) } catch { }
        await fulfillment(of: [unavailable], timeout: 5)
        let pidString = try await waitForTextFile(pidFile)
        let pid = pid_t(try XCTUnwrap(Int32(pidString.trimmingCharacters(in: .whitespacesAndNewlines))))
        XCTAssertNotEqual(kill(pid, 0), 0, "exhausted runtime child should be absent")
        try FileManager.default.removeItem(at: tmp.appendingPathComponent("restore-marker"))
        try await cli.refreshRuntime(profileID: profile.id)

        await cli.stopRuntime()
        do {
            try await cli.refreshRuntime(profileID: profile.id)
            XCTFail("explicit stop must prevent refresh relaunch")
        } catch {
            XCTAssertTrue(error.localizedDescription.lowercased().contains("unavailable"))
        }
    }

    func testRuntimeRejectsStaleConnectionRevision() async throws {
        let cli = try makeRuntimeFixture()
        let environment = makeEnvironment()
        let profile = makeRuntimeProfile(environment: environment, revision: "current")
        try await cli.configureRuntime([profile])
        defer { Task { await cli.stopRuntime() } }

        var stale = environment
        stale.profileID = profile.id
        stale.connectionRevision = "stale"
        do {
            _ = try await cli.run(["reply", "delivery_1", "hello"], environment: stale)
            XCTFail("expected stale revision rejection")
        } catch let failure as GullsCLI.Failure {
            guard case .configuration = failure else {
                XCTFail("unexpected failure: \(failure)")
                return
            }
        }
    }

    func testRemovedRuntimeProfileCannotFallBackToOneShotCLI() async throws {
        let cli = try makeRuntimeFixture()
        let environment = makeEnvironment()
        let profile = makeRuntimeProfile(environment: environment)
        try await cli.configureRuntime([profile])
        // An empty configuration removes the active profile while the CLI
        // remains alive. Its ID must still be treated as runtime-managed.
        try await cli.configureRuntime([])
        defer { Task { await cli.stopRuntime() } }

        var removed = environment
        removed.profileID = profile.id
        removed.connectionRevision = profile.revision
        do {
            _ = try await cli.run(["reply", "delivery_1", "hello"], environment: removed)
            XCTFail("expected removed profile to remain unavailable")
        } catch let failure as GullsCLI.Failure {
            guard case .runtime = failure else {
                XCTFail("unexpected failure: \(failure)")
                return
            }
        }
    }

    func testStoppingRuntimeExitsOwnedChild() async throws {
        let pidFile = tmp.appendingPathComponent("runtime.pid")
        let cli = try makeRuntimeFixture(pidFile: pidFile)
        let environment = makeEnvironment()
        try await cli.configureRuntime([makeRuntimeProfile(environment: environment)])
        let pidText = try await waitForTextFile(pidFile)
        let pid = pid_t(try XCTUnwrap(Int32(pidText.trimmingCharacters(in: .whitespacesAndNewlines))))

        await cli.stopRuntime()
        for _ in 0..<30 {
            if kill(pid, 0) != 0 { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("runtime child remained alive after stopRuntime")
    }

    func testBundledRuntimeV1InteropAndSocketStatus() async throws {
        guard let executable = Bundle.main.url(forResource: "gulls", withExtension: nil) else {
            throw XCTSkip("The bundled gulls binary is unavailable in this test bundle")
        }
        let shortDirectory = URL(fileURLWithPath: "/tmp/grt-\(UUID().uuidString.prefix(8))",
                                 isDirectory: true)
        try FileManager.default.createDirectory(at: shortDirectory, withIntermediateDirectories: true)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: shortDirectory.path)
        let socket = shortDirectory.appendingPathComponent("runtime.sock")
        let cli = GullsCLI(executableURL: executable, runtimeSocketURL: socket)
        addTeardownBlock {
            await cli.stopRuntime()
            try? FileManager.default.removeItem(at: shortDirectory)
        }
        var first = makeEnvironment(token: "sga_test_token_one")
        first.contextDir = tmp.appendingPathComponent("bundled-context-a")
        var second = makeEnvironment(token: "sga_test_token_two")
        second.contextDir = tmp.appendingPathComponent("bundled-context-b")
        let profiles = [
            RuntimeProfile(id: "bundled-a", revision: "revision-a", environment: first,
                           pollInterval: 30, monitoring: false),
            RuntimeProfile(id: "bundled-b", revision: "revision-b", environment: second,
                           pollInterval: 30, monitoring: false),
        ]
        try await cli.configureRuntime(profiles)

        var routed = first
        routed.profileID = profiles[0].id
        routed.connectionRevision = profiles[0].revision
        let versionData = try await cli.run(["version"], environment: routed)
        XCTAssertEqual(try JSONDecoder().decode(VersionInfo.self, from: versionData).program, "gulls")

        do {
            _ = try await cli.run(["inbox", "--limit", "1"], environment: routed)
            XCTFail("expected missing-cache inbox error")
        } catch let failure as GullsCLI.Failure {
            guard case .runtime = failure else {
                XCTFail("unexpected inbox failure: \(failure)")
                return
            }
        }

        do {
            _ = try await cli.run(["not-a-real-command"], environment: routed)
            XCTFail("expected bundled runtime command failure")
        } catch let failure as GullsCLI.Failure {
            guard case .runtime = failure else {
                XCTFail("unexpected failure: \(failure)")
                return
            }
        }

        do {
            _ = try await cli.run(["inbox", "--limit", "0"], environment: routed)
            XCTFail("expected bundled runtime usage failure")
        } catch let failure as GullsCLI.Failure {
            guard case .configuration = failure else {
                XCTFail("unexpected usage failure: \(failure)")
                return
            }
        }

        var statusEnvironment = ProcessInfo.processInfo.environment
        statusEnvironment["SEAGULL_RUNTIME_SOCKET"] = socket.path
        let status = Process()
        status.executableURL = executable
        status.arguments = ["--json", "runtime", "status"]
        status.environment = statusEnvironment
        let output = Pipe()
        status.standardOutput = output
        status.standardError = Pipe()
        let (statusCode, statusData, _) = try await runAndCollect(status, output: output)
        XCTAssertEqual(statusCode, 0)
        XCTAssertTrue(String(decoding: statusData, as: UTF8.self).contains("bundled-a"))
        XCTAssertTrue(String(decoding: statusData, as: UTF8.self).contains("bundled-b"))
        XCTAssertFalse(String(decoding: statusData, as: UTF8.self).contains("sga_test_token"))

        await cli.stopRuntime()
        for _ in 0..<30 where FileManager.default.fileExists(atPath: socket.path) {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: socket.path))
    }

    func testArgumentsPutGlobalJSONFlagFirstAndEnvIsPassed() async throws {
        let cli = try makeFakeBinary(script: """
        printf '{"args":"%s","api_url":"%s","handle":"%s","token":"%s","env_file":"%s"}' \
            "$*" "$SEAGULL_API_URL" "$SEAGULL_AGENT_HANDLE" "$SEAGULL_CONNECTOR_TOKEN" "$SEAGULL_AGENT_ENV_FILE"
        """)

        let data = try await cli.run(["inbox", "--limit", "20"], environment: makeEnvironment())
        let echo = try JSONDecoder().decode([String: String].self, from: data)

        XCTAssertEqual(echo["args"], "--json inbox --limit 20")
        XCTAssertEqual(echo["api_url"], "https://api.example.test")
        XCTAssertEqual(echo["handle"], "@worker:gulls.ai")
        XCTAssertEqual(echo["token"], "secret-token")
        // Env-file fallback must be neutralized with a never-existing path.
        let envFile = try XCTUnwrap(echo["env_file"])
        XCTAssertFalse(envFile.isEmpty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: envFile))
    }

    func testMissingTokenIsNotExportedAsEmptyString() async throws {
        let cli = try makeFakeBinary(script: """
        printf '{"token_set":"%s"}' "${SEAGULL_CONNECTOR_TOKEN+yes}"
        """)

        let data = try await cli.run(["whoami"], environment: makeEnvironment(token: nil))
        let echo = try JSONDecoder().decode([String: String].self, from: data)
        XCTAssertEqual(echo["token_set"], "")
    }

    func testExitCode2MapsToConfigurationFailure() async throws {
        let cli = try makeFakeBinary(script: """
        echo "config error: missing required config: SEAGULL_API_URL" >&2
        exit 2
        """)

        do {
            _ = try await cli.run(["whoami"], environment: makeEnvironment())
            XCTFail("expected configuration failure")
        } catch let failure as GullsCLI.Failure {
            guard case .configuration(let message) = failure else {
                return XCTFail("unexpected failure: \(failure)")
            }
            XCTAssertTrue(message.contains("missing required config"))
        }
    }

    func testExitCode1MapsToRuntimeFailureWithStderrText() async throws {
        let cli = try makeFakeBinary(script: """
        echo 'gulls: 404: {"error":"delivery not found"}' >&2
        exit 1
        """)

        do {
            _ = try await cli.run(["reply", "delivery_x", "hello"], environment: makeEnvironment())
            XCTFail("expected runtime failure")
        } catch let failure as GullsCLI.Failure {
            guard case .runtime(let message) = failure else {
                return XCTFail("unexpected failure: \(failure)")
            }
            XCTAssertTrue(message.contains("404"))
        }
    }

    func testLargeOutputDoesNotDeadlockThePipe() async throws {
        // Well past the 64KB pipe buffer.
        let cli = try makeFakeBinary(script: """
        printf '{"blob":"'
        head -c 200000 /dev/zero | tr '\\0' 'a'
        printf '"}'
        """)

        let data = try await cli.run(["inbox"], environment: makeEnvironment())
        XCTAssertGreaterThan(data.count, 200_000)
        XCTAssertNotNil(try? JSONDecoder().decode([String: String].self, from: data))
    }

    func testConcurrentCommandsRunStrictlySerialized() async throws {
        // Two overlapping calls: without FIFO chaining (actors are reentrant)
        // the start/end markers would interleave.
        let log = tmp.appendingPathComponent("serial.log")
        let cli = try makeFakeBinary(script: """
        echo "start $3" >> "\(log.path)"
        sleep 0.2
        echo "end $3" >> "\(log.path)"
        printf '{}'
        """)
        let environment = makeEnvironment()

        async let first = cli.run(["ack", "delivery_a"], environment: environment)
        async let second = cli.run(["ack", "delivery_b"], environment: environment)
        _ = try await (first, second)

        let lines = try String(contentsOf: log, encoding: .utf8)
            .split(separator: "\n")
            .map(String.init)
        XCTAssertEqual(lines.count, 4)
        XCTAssertTrue(lines[0].hasPrefix("start "))
        XCTAssertEqual(lines[1], lines[0].replacingOccurrences(of: "start", with: "end"))
        XCTAssertTrue(lines[2].hasPrefix("start "))
        XCTAssertEqual(lines[3], lines[2].replacingOccurrences(of: "start", with: "end"))
    }

    func testTypedInboxWrapperDecodesFixtureOutput() async throws {
        let fixture = ModelDecodingTests.contractDir.appendingPathComponent("inbox.json").path
        let cli = try makeFakeBinary(script: """
        cat "\(fixture)"
        """)

        let items = try await cli.inbox(limit: 20, environment: makeEnvironment())
        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(items.first?.id, "delivery_1")
    }

    func testStreamEmitsLinesIncrementallyAndTerminates() async throws {
        // Lines arrive over time; the third is written in two chunks without
        // a newline first, testing partial-line buffering. Then the script
        // sleeps so only terminate() can end the stream.
        let cli = try makeFakeBinary(script: """
        printf '{"type":"stream.connected","url":"ws://x"}\\n'
        sleep 0.1
        printf '{"type":"stream.event","event_type":"seagull.delivery.created.v1","delivery_id":"delivery_7"}\\n'
        sleep 0.1
        printf '{"type":"stream.ev'
        sleep 0.1
        printf 'ent","event_type":"seagull.delivery.created.v1","delivery_id":"delivery_8"}\\n'
        sleep 30
        """)

        let handle = try await cli.openStream(environment: makeEnvironment())
        var lines: [StreamLine] = []
        for try await raw in handle.lines {
            lines.append(try JSONDecoder().decode(StreamLine.self, from: raw))
            if lines.count == 3 {
                handle.terminate()
            }
        }

        XCTAssertEqual(lines.count, 3)
        XCTAssertEqual(lines[0].type, "stream.connected")
        XCTAssertEqual(lines[1].deliveryId, "delivery_7")
        XCTAssertEqual(lines[2].deliveryId, "delivery_8")
    }

    func testStreamFatalExitThrowsWithStderr() async throws {
        let cli = try makeFakeBinary(script: """
        echo "gulls: stream connect rejected (check that the connector token has the agent:inbox scope)" >&2
        exit 1
        """)

        let handle = try await cli.openStream(environment: makeEnvironment())
        do {
            for try await _ in handle.lines {}
            XCTFail("expected stream failure")
        } catch let failure as GullsCLI.Failure {
            guard case .runtime(let message) = failure else {
                return XCTFail("unexpected failure: \(failure)")
            }
            XCTAssertTrue(message.contains("agent:inbox"))
        }
    }

    func testUndecodableOutputMapsToDecodingFailure() async throws {
        let cli = try makeFakeBinary(script: """
        echo 'not json at all'
        """)

        do {
            _ = try await cli.inbox(limit: 20, environment: makeEnvironment())
            XCTFail("expected decoding failure")
        } catch let failure as GullsCLI.Failure {
            guard case .decoding = failure else {
                return XCTFail("unexpected failure: \(failure)")
            }
        }
    }

    func testOpenBrowserLoginPutsJSONAndLoginArgumentsFirst() async throws {
        let argumentsFile = tmp.appendingPathComponent("login-arguments")
        let sessionFile = tmp.appendingPathComponent("account.json")
        let cli = try makeFakeBinary(script: """
        printf '%s\\n' "$@" > "\(argumentsFile.path)"
        sleep 30
        """)

        let handle = try await cli.openBrowserLogin(
            websiteURL: "https://sea.gulls.ai",
            sessionFile: sessionFile
        )
        defer { handle.terminate() }

        let arguments = try await waitForTextFile(argumentsFile)
            .split(separator: "\n")
            .map(String.init)
        XCTAssertEqual(arguments, [
            "--json",
            "login",
            "--server",
            "https://sea.gulls.ai",
            "--session-file",
            sessionFile.path,
        ])
    }

    func testOpenBrowserLoginDoesNotExportGullCredentialEnvironment() async throws {
        let environmentFile = tmp.appendingPathComponent("login-environment")
        let cli = try makeFakeBinary(script: """
        printf '%s|%s|%s|%s' \\
            "${SEAGULL_CONNECTOR_TOKEN+set}" \\
            "${SEAGULL_SOCIAL_API_URL+set}" \\
            "${SEAGULL_NODE_ID+set}" \\
            "${SEAGULL_AGENT_HANDLE+set}" > "\(environmentFile.path)"
        sleep 30
        """)

        let handle = try await cli.openBrowserLogin(
            websiteURL: "https://sea.gulls.ai",
            sessionFile: tmp.appendingPathComponent("account.json")
        )
        defer { handle.terminate() }

        let environment = try await waitForTextFile(environmentFile)
        XCTAssertEqual(environment, "|||set")
    }

    func testWaitingBrowserLoginDoesNotBlockNormalCLICommand() async throws {
        let cli = try makeFakeBinary(script: """
        if [ "$2" = "login" ]; then
            sleep 30
        else
            printf '{"program":"gulls","version":"fixture"}'
        fi
        """)

        let login = try await cli.openBrowserLogin(
            websiteURL: "https://sea.gulls.ai",
            sessionFile: tmp.appendingPathComponent("account.json")
        )
        defer { login.terminate() }

        let version = try await cli.version()
        XCTAssertEqual(version.version, "fixture")
    }

    func testTerminatingBrowserLoginCompletesItsStream() async throws {
        let cli = try makeFakeBinary(script: """
        sleep 30
        """)
        let handle = try await cli.openBrowserLogin(
            websiteURL: "https://sea.gulls.ai",
            sessionFile: tmp.appendingPathComponent("account.json")
        )

        let finished = Task {
            for try await _ in handle.lines {}
        }
        try await Task.sleep(nanoseconds: 100_000_000)
        handle.terminate()
        try await finished.value
    }

    private func waitForTextFile(_ url: URL) async throws -> String {
        for _ in 0..<100 {
            if let data = try? Data(contentsOf: url), !data.isEmpty {
                return String(decoding: data, as: UTF8.self)
            }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTFail("Timed out waiting for \(url.lastPathComponent)")
        return ""
    }

    private func runAndCollect(_ process: Process, output: Pipe) async throws -> (Int32, Data, Data) {
        let stdout = PipeCollector(handle: output.fileHandleForReading)
        let stderr = (process.standardError as? Pipe).map { PipeCollector(handle: $0.fileHandleForReading) }
        do {
            try process.run()
            let deadline = ContinuousClock.now.advanced(by: .seconds(10))
            while process.isRunning, ContinuousClock.now < deadline {
                try await Task.sleep(for: .milliseconds(10))
            }
            guard !process.isRunning else {
                throw GullsCLI.Failure.runtime("The test CLI did not exit before its deadline.")
            }
            return (process.terminationStatus, stdout.finish(), stderr?.finish() ?? Data())
        } catch {
            if process.isRunning { kill(process.processIdentifier, SIGKILL) }
            stdout.cancel()
            stderr?.cancel()
            throw error
        }
    }
}
