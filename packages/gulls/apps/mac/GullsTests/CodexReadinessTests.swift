import Foundation
import XCTest
@testable import Gulls

@MainActor
final class CodexReadinessTests: XCTestCase {
    private var temporaryDirectories: [URL] = []

    override func tearDown() {
        for directory in temporaryDirectories {
            try? FileManager.default.removeItem(at: directory)
        }
        temporaryDirectories.removeAll()
    }

    func testMissingCodexIsDistinctFromConnectionFailure() async {
        let executable = URL(fileURLWithPath: "/tmp/does-not-exist-\(UUID().uuidString)")
        let server = CodexAppServer(executableURL: executable)
        let readiness = CodexReadiness(server: server, executableURL: executable)
        let report = await readiness.check()

        XCTAssertEqual(report.state, .codexNotInstalled)
        XCTAssertNil(report.executablePath)
    }

    func testUnsupportedVersionIsReportedBeforeProtocolStartup() async throws {
        let executable = try makeExecutable(version: "codex-cli 0.145.9", providerRequiresAuthentication: false)
        let server = CodexAppServer(executableURL: executable)
        defer { server.shutdown() }

        let report = await CodexReadiness(server: server, executableURL: executable).check()

        XCTAssertEqual(report.state, .unsupportedVersion(installed: "codex-cli 0.145.9", minimum: CodexReadiness.minimumSupportedVersion))
        XCTAssertEqual(report.version, "codex-cli 0.145.9")
    }

    func testLoginRequirementIsReportedWithoutReadingAuthFiles() async throws {
        let executable = try makeExecutable(version: "codex-cli 0.146.0", providerRequiresAuthentication: true, hasAccount: false)
        let server = CodexAppServer(executableURL: executable)
        defer { server.shutdown() }

        let report = await CodexReadiness(server: server, executableURL: executable).check()

        XCTAssertEqual(report.state, .signInRequired)
        XCTAssertEqual(report.version, "codex-cli 0.146.0")
        XCTAssertTrue(report.modelIDs.isEmpty)
    }

    func testReadyRequiresAProtocolAndModelResponse() async throws {
        let executable = try makeExecutable(version: "codex-cli 0.146.0", providerRequiresAuthentication: false)
        let server = CodexAppServer(executableURL: executable)
        defer { server.shutdown() }

        let report = await CodexReadiness(server: server, executableURL: executable).check()

        XCTAssertEqual(report.state, .ready)
        XCTAssertEqual(report.modelIDs, ["gpt-6-luna"])
        XCTAssertEqual(report.version, "codex-cli 0.146.0")
    }

    func testConnectionFailureIsDistinctWhenCatalogIsEmpty() async throws {
        let executable = try makeExecutable(version: "codex-cli 0.146.0", providerRequiresAuthentication: false, hasModels: false)
        let server = CodexAppServer(executableURL: executable)
        defer { server.shutdown() }

        let report = await CodexReadiness(server: server, executableURL: executable).check()

        XCTAssertEqual(report.state, .connectionFailed("Codex returned no available models."))
    }

    func testHungVersionProcessTimesOutAndIsCancelled() async throws {
        let executable = try makeExecutable(
            version: "codex-cli 0.146.0",
            providerRequiresAuthentication: false,
            hangsOnVersion: true
        )
        let server = CodexAppServer(executableURL: executable)
        defer { server.shutdown() }

        let report = await CodexReadiness(
            server: server,
            executableURL: executable,
            versionCheckTimeout: 0.1
        ).check()

        XCTAssertEqual(report.statusLabel, "Connection failed")
        XCTAssertTrue(report.message.contains("did not respond"))
    }

    func testVersionComparisonAcceptsPatchUpdatesOnly() {
        XCTAssertTrue(CodexReadiness.isSupported(version: "codex-cli 0.146.1", minimum: "0.146.0"))
        XCTAssertTrue(CodexReadiness.isSupported(version: "0.147.0", minimum: "0.146.0"))
        XCTAssertFalse(CodexReadiness.isSupported(version: "codex-cli 0.145.99", minimum: "0.146.0"))
        XCTAssertFalse(CodexReadiness.isSupported(version: "development", minimum: "0.146.0"))
    }

    func testSignedInAccountCanUseProviderRequiringAuthentication() async throws {
        let executable = try makeExecutable(version: "codex-cli 0.146.0", providerRequiresAuthentication: true)
        let server = CodexAppServer(executableURL: executable)
        defer { server.shutdown() }

        let report = await CodexReadiness(server: server, executableURL: executable).check()

        XCTAssertEqual(report.state, .ready)
    }

    func testDefaultReadinessUsesPrivateCompatibleCatalogWithoutMutatingSource() async throws {
        let executable = try makeExecutable(version: "codex-cli 0.146.0",
                                            providerRequiresAuthentication: false,
                                            requiresPrivateCatalog: true)
        let codexHome = executable.deletingLastPathComponent().appendingPathComponent("codex-home", isDirectory: true)
        try FileManager.default.createDirectory(at: codexHome, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let sourceCatalog = codexHome.appendingPathComponent("models_cache.json")
        let original = Data(#"{"models":[{"slug":"gpt-6-luna","model":"gpt-6-luna"}]}"#.utf8)
        try original.write(to: sourceCatalog, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: sourceCatalog.path)

        let report = await CodexReadiness(executableURL: executable, codexHome: codexHome).check()

        XCTAssertEqual(report.state, .ready)
        XCTAssertEqual(try Data(contentsOf: sourceCatalog), original)
    }

    private func makeExecutable(
        version: String,
        providerRequiresAuthentication: Bool,
        hasAccount: Bool = true,
        hasModels: Bool = true,
        hangsOnVersion: Bool = false,
        requiresPrivateCatalog: Bool = false
    ) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("gulls-codex-readiness-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        temporaryDirectories.append(directory)

        let executable = directory.appendingPathComponent("fake-codex.py")
        let accountValue = providerRequiresAuthentication ? "True" : "False"
        let hangs = hangsOnVersion ? "True" : "False"
        let accountJSON = hasAccount
            ? "{\"type\": \"chatgpt\", \"email\": \"test@example.com\", \"planType\": \"plus\"}"
            : "None"
        let modelData = hasModels ? "[{\"id\": \"gpt-6-luna\", \"model\": \"gpt-6-luna\"}]" : "[]"
        let catalogCheck = requiresPrivateCatalog ? """
        if len(sys.argv) > 1 and sys.argv[1] == "app-server":
            catalog_arg = next((arg for arg in sys.argv if arg.startswith("model_catalog_json=")), None)
            catalog_value = catalog_arg.split("=", 1)[1] if catalog_arg else ""
            try:
                catalog_path = json.loads(catalog_value)
            except Exception:
                catalog_path = catalog_value.strip("\\\"")
            if catalog_arg is None or "gulls-codex-runtime-" not in catalog_path or not catalog_path.endswith("/models.json"):
                print("missing private model catalog", file=sys.stderr)
                sys.exit(2)
            with open(catalog_path, "r", encoding="utf-8") as handle:
                catalog = json.load(handle)
            model = catalog.get("models", [{}])[0]
            if model.get("supports_parallel_tool_calls") is not False or model.get("input_modalities") != ["text"]:
                print("private model catalog was not normalized", file=sys.stderr)
                sys.exit(2)
        """ : ""
        let source = """
        #!/usr/bin/python3
        import json
        import sys

        \(catalogCheck)
        if len(sys.argv) > 1 and sys.argv[1] == "--version":
            if \(hangs):
                import time
                while True:
                    time.sleep(1)
            print("\(version)")
            sys.exit(0)

        def send(value):
            sys.stdout.write(json.dumps(value, separators=(",", ":")) + chr(10))
            sys.stdout.flush()

        for raw in sys.stdin:
            message = json.loads(raw)
            method = message.get("method")
            ident = message.get("id")
            if method == "initialize":
                send({"id": ident, "result": {"platformFamily": "unix", "platformOs": "macos"}})
            elif method == "account/read":
                send({"id": ident, "result": {"requiresOpenaiAuth": \(accountValue), "account": \(accountJSON)}})
            elif method == "model/list":
                send({"id": ident, "result": {"data": \(modelData)}})
        """
        try Data(source.utf8).write(to: executable, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
        return executable
    }
}
