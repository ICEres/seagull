import Foundation

/// Builds a private, text-only Codex app-server runtime without changing the
/// owner's Codex configuration or reading authentication material.
@MainActor
final class CodexRuntimePolicy {
    enum Failure: Error, LocalizedError {
        case invalid(String)

        var errorDescription: String? {
            if case .invalid(let message) = self { return message }
            return nil
        }
    }

    private let codexHome: URL
    private let tempRoot: URL
    private let fileManager: FileManager
    private var runtimeDirectory: URL?
    private(set) var modelIDs = Set<String>()

    init(codexHome: URL? = nil, tempRoot: URL? = nil, fileManager: FileManager = .default) {
        self.fileManager = fileManager
        self.codexHome = codexHome ?? fileManager.homeDirectoryForCurrentUser.appendingPathComponent(".codex")
        self.tempRoot = tempRoot ?? fileManager.temporaryDirectory
    }

    deinit {
        if let runtimeDirectory { try? fileManager.removeItem(at: runtimeDirectory) }
    }

    func startupArguments() throws -> [String] {
        let sourceURL = try catalogURL()
        let data = try Data(contentsOf: sourceURL)
        let catalog = try makeCatalog(from: data)
        if let previous = runtimeDirectory { try? fileManager.removeItem(at: previous) }
        let directory = tempRoot.appendingPathComponent("gulls-codex-runtime-\(UUID().uuidString)", isDirectory: true)
        do {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true,
                                            attributes: [.posixPermissions: 0o700])
            let output = directory.appendingPathComponent("models.json")
            let outputData = try JSONSerialization.data(withJSONObject: catalog, options: [.sortedKeys])
            guard fileManager.createFile(atPath: output.path, contents: outputData,
                                         attributes: [.posixPermissions: 0o600]) else {
                throw Failure.invalid("Could not create the private Codex model catalog.")
            }
            runtimeDirectory = directory
            modelIDs = Set((catalog["models"] as! [[String: Any]]).compactMap { $0["slug"] as? String })

            let pathValue = output.path.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
            let disabled = ["apps", "code_mode", "code_mode_host", "image_generation", "multi_agent",
                            "plugins", "shell_tool", "unified_exec", "hooks", "shell_snapshot",
                            "workspace_dependencies", "browser_use", "browser_use_external",
                            "browser_use_full_cdp_access", "computer_use", "tool_suggest", "skill_search",
                            "request_permissions_tool", "default_mode_request_user_input"]
            return ["-c", "model_catalog_json=\"\(pathValue)\"", "-c", "web_search=\"disabled\""]
                + disabled.flatMap { ["--disable", $0] }
        } catch {
            try? fileManager.removeItem(at: directory)
            throw error
        }
    }

    private func catalogURL() throws -> URL {
        let config = codexHome.appendingPathComponent("config.toml")
        if fileManager.fileExists(atPath: config.path) {
            let text = try String(contentsOf: config, encoding: .utf8)
            if let raw = try declaredCatalogPath(in: text) {
                let expanded = (raw as NSString).expandingTildeInPath
                return URL(fileURLWithPath: expanded, relativeTo: codexHome).standardizedFileURL
            }
        }
        let fallback = codexHome.appendingPathComponent("models_cache.json")
        guard fileManager.fileExists(atPath: fallback.path) else {
            throw Failure.invalid("Codex model catalog is unavailable.")
        }
        return fallback
    }

    private func declaredCatalogPath(in text: String) throws -> String? {
        for line in text.split(whereSeparator: \.isNewline) {
            let trimmed = stripComment(String(line)).trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.hasPrefix("[") { break }
            guard trimmed.hasPrefix("model_catalog_json") else { continue }
            let parts = trimmed.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard parts.count == 2, parts[0].trimmingCharacters(in: .whitespaces) == "model_catalog_json" else {
                throw Failure.invalid("The model_catalog_json setting is invalid.")
            }
            let value = parts[1].trimmingCharacters(in: .whitespaces)
            guard value.count >= 2, (value.first == "\"" && value.last == "\"") || (value.first == "'" && value.last == "'") else {
                throw Failure.invalid("The model_catalog_json setting must be a quoted path.")
            }
            let body = String(value.dropFirst().dropLast())
            if value.first == "'" { return body }
            let encoded = Data(("\"" + body + "\"").utf8)
            guard let decoded = try? JSONDecoder().decode(String.self, from: encoded) else {
                throw Failure.invalid("The model_catalog_json path is not valid TOML.")
            }
            return decoded
        }
        return nil
    }

    private func stripComment(_ line: String) -> String {
        var quote: Character?
        var escaped = false
        for (index, character) in line.enumerated() {
            if quote == "\"" {
                if escaped { escaped = false; continue }
                if character == "\\" { escaped = true; continue }
            }
            if character == "\"" || character == "'" {
                if quote == nil { quote = character } else if quote == character { quote = nil }
            } else if character == "#" && quote == nil { return String(line.prefix(index)) }
        }
        return line
    }

    private func makeCatalog(from data: Data) throws -> [String: Any] {
        guard var root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              var models = root["models"] as? [[String: Any]], !models.isEmpty else {
            throw Failure.invalid("The Codex model catalog has no models.")
        }
        var ids = Set<String>()
        for index in models.indices {
            guard let slug = models[index]["slug"] as? String,
                  slug.range(of: "^[A-Za-z0-9][A-Za-z0-9._/-]*$", options: .regularExpression) != nil,
                  ids.insert(slug).inserted else { throw Failure.invalid("The Codex model catalog contains invalid or duplicate model IDs.") }
            models[index]["input_modalities"] = ["text"]
            if models[index]["supports_parallel_tool_calls"] == nil { models[index]["supports_parallel_tool_calls"] = false }
            if models[index]["base_instructions"] == nil {
                models[index]["base_instructions"] = (models[index]["model_messages"] as? [String: Any])?["instructions_template"] as? String
                    ?? "You are a helpful assistant. Follow the user's request and return a concise result."
            }
        }
        root["models"] = models
        return root
    }
}
