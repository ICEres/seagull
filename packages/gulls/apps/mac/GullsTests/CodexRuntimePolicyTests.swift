import Foundation
import XCTest
@testable import Gulls

@MainActor
final class CodexRuntimePolicyTests: XCTestCase {
    private var roots: [URL] = []

    override func tearDown() {
        roots.forEach { try? FileManager.default.removeItem(at: $0) }
        roots.removeAll()
    }

    func testExplicitCatalogIsCopiedAsTextOnlyWithoutChangingSource() throws {
        let home = try makeRoot()
        let scratch = try makeRoot()
        let source = home.appendingPathComponent("catalog.json")
        let original = try catalog(slug: "writer", includeInstructions: true)
        try original.write(to: source)
        try "model_catalog_json = \"catalog.json\"\n".write(to: home.appendingPathComponent("config.toml"), atomically: true, encoding: .utf8)

        let policy = CodexRuntimePolicy(codexHome: home, tempRoot: scratch)
        let args = try policy.startupArguments()
        let output = try catalogURL(from: args)
        let transformed = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: output)) as? [String: Any])
        let model = try XCTUnwrap((transformed["models"] as? [[String: Any]])?.first)
        XCTAssertEqual(model["input_modalities"] as? [String], ["text"])
        XCTAssertEqual(model["supports_parallel_tool_calls"] as? Bool, false)
        XCTAssertEqual(model["base_instructions"] as? String, "template")
        XCTAssertEqual(policy.modelIDs, ["writer"])
        XCTAssertEqual(try Data(contentsOf: source), original)
        for feature in ["shell_tool", "hooks", "browser_use", "computer_use", "workspace_dependencies"] {
            let index = try XCTUnwrap(args.firstIndex(of: feature))
            XCTAssertEqual(args[index - 1], "--disable")
        }
        XCTAssertTrue(args.contains { $0 == "web_search=\"disabled\"" })
        XCTAssertEqual(try permissions(of: output), 0o600)
        XCTAssertEqual(try permissions(of: output.deletingLastPathComponent()), 0o700)
    }

    func testLiteralAndBasicPathsRespectCommentsAndRootTableBoundary() throws {
        let home = try makeRoot()
        let scratch = try makeRoot()
        try catalog(slug: "literal").write(to: home.appendingPathComponent("literal.json"))
        try catalog(slug: "table").write(to: home.appendingPathComponent("table.json"))
        try "model_catalog_json = 'literal.json' # inline comment\n[model]\nmodel_catalog_json = \"table.json\"\n".write(to: home.appendingPathComponent("config.toml"), atomically: true, encoding: .utf8)
        let policy = CodexRuntimePolicy(codexHome: home, tempRoot: scratch)
        _ = try policy.startupArguments()
        XCTAssertEqual(policy.modelIDs, ["literal"])
    }

    func testFallsBackToModelsCacheAndRejectsUnsupportedOrBadCatalogs() throws {
        let home = try makeRoot()
        let scratch = try makeRoot()
        try catalog(slug: "cached").write(to: home.appendingPathComponent("models_cache.json"))
        let policy = CodexRuntimePolicy(codexHome: home, tempRoot: scratch)
        _ = try policy.startupArguments()
        XCTAssertEqual(policy.modelIDs, ["cached"])

        try "model_catalog_json = {bad}\n".write(to: home.appendingPathComponent("config.toml"), atomically: true, encoding: .utf8)
        XCTAssertThrowsError(try CodexRuntimePolicy(codexHome: home, tempRoot: scratch).startupArguments())
        try "model_catalog_json = \"bad.json\"\n".write(to: home.appendingPathComponent("config.toml"), atomically: true, encoding: .utf8)
        try "{\"models\":[{\"slug\":\"same\"},{\"slug\":\"same\"}]}".write(to: home.appendingPathComponent("bad.json"), atomically: true, encoding: .utf8)
        XCTAssertThrowsError(try CodexRuntimePolicy(codexHome: home, tempRoot: scratch).startupArguments())
    }

    func testEscapedBasicPathAndRepeatedStartup() throws {
        let home = try makeRoot()
        let scratch = try makeRoot()
        let filename = "models\"#one.json"
        try catalog(slug: "writer").write(to: home.appendingPathComponent(filename))
        let encodedPath = String(decoding: try JSONEncoder().encode(filename), as: UTF8.self)
        try "model_catalog_json = \(encodedPath) # catalog\n".write(
            to: home.appendingPathComponent("config.toml"), atomically: true, encoding: .utf8)
        let policy = CodexRuntimePolicy(codexHome: home, tempRoot: scratch)
        let previous = try catalogURL(from: policy.startupArguments()).deletingLastPathComponent()
        let current = try catalogURL(from: policy.startupArguments())
        XCTAssertFalse(FileManager.default.fileExists(atPath: previous.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: current.path))
        XCTAssertEqual(policy.modelIDs, ["writer"])
    }

    private func makeRoot() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("codex-policy-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        roots.append(url)
        return url
    }

    private func catalog(slug: String, includeInstructions: Bool = false) throws -> Data {
        var model: [String: Any] = ["slug": slug, "display_name": slug]
        if includeInstructions { model["model_messages"] = ["instructions_template": "template"] }
        return try JSONSerialization.data(withJSONObject: ["models": [model]], options: [])
    }

    private func catalogURL(from args: [String]) throws -> URL {
        let value = try XCTUnwrap(args.first { $0.hasPrefix("model_catalog_json=") })
        let path = String(value.dropFirst("model_catalog_json=\"".count).dropLast())
        return URL(fileURLWithPath: path)
    }

    private func permissions(of url: URL) throws -> Int {
        let values = try FileManager.default.attributesOfItem(atPath: url.path)
        return Int((values[.posixPermissions] as? NSNumber)?.intValue ?? 0)
    }
}
