import XCTest
@testable import Gulls

// Exercises the Process bridge against fake `gulls` shell scripts: argument
// ordering, environment passing, exit-code mapping, and large-output draining.
final class GullsCLITests: XCTestCase {

    private var tmp: URL!

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("GullsCLITests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tmp)
    }

    private func makeFakeBinary(script: String) throws -> GullsCLI {
        let url = tmp.appendingPathComponent("gulls")
        try ("#!/bin/bash\n" + script).write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        return GullsCLI(executableURL: url)
    }

    private func makeEnvironment(token: String? = "secret-token") -> GullsCLI.Environment {
        GullsCLI.Environment(
            apiURL: "https://api.example.test",
            agentHandle: "@worker:gulls.ai",
            token: token,
            contextDir: tmp.appendingPathComponent("context")
        )
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
}
