import Foundation

/// The result of the local Codex checks that can be performed without
/// starting a model turn. The state is deliberately small so settings and
/// task dispatch can present the same recovery action.
enum CodexReadinessState: Equatable {
    case ready
    case codexNotInstalled
    case signInRequired
    case unsupportedVersion(installed: String?, minimum: String)
    case connectionFailed(String)
}

struct CodexReadinessReport: Equatable {
    let state: CodexReadinessState
    let executablePath: String?
    let version: String?
    let modelIDs: [String]

    var isReady: Bool {
        if case .ready = state { return true }
        return false
    }

    var statusLabel: String {
        switch state {
        case .ready: return "Ready"
        case .codexNotInstalled: return "Codex not installed"
        case .signInRequired: return "Sign in required"
        case .unsupportedVersion: return "Unsupported version"
        case .connectionFailed: return "Connection failed"
        }
    }

    var message: String {
        switch state {
        case .ready:
            return version.map { "Codex \($0) is ready." } ?? "Codex is ready."
        case .codexNotInstalled:
            return "Install Codex CLI to enable local Codex tasks."
        case .signInRequired:
            return "Sign in to Codex before starting a local task."
        case .unsupportedVersion(let installed, let minimum):
            if let installed {
                return "Codex \(installed) is not supported. Install \(minimum) or newer."
            }
            return "This Codex version is not supported. Install \(minimum) or newer."
        case .connectionFailed(let detail):
            return detail
        }
    }
}

/// Checks the installed Codex CLI and the app-server protocol without
/// reading auth files or making a paid model request.
@MainActor
final class CodexReadiness {
    nonisolated static let minimumSupportedVersion = "0.146.0"

    private let server: CodexAppServer
    private let ownsServer: Bool
    private let executableURL: URL?
    private let fileManager: FileManager
    private let minimumVersion: String
    private let versionCheckTimeoutNanoseconds: UInt64

    init(
        server: CodexAppServer? = nil,
        executableURL: URL? = nil,
        fileManager: FileManager = .default,
        minimumVersion: String = CodexReadiness.minimumSupportedVersion,
        versionCheckTimeout: TimeInterval = 5,
        codexHome: URL? = nil
    ) {
        if let server {
            self.server = server
            self.ownsServer = false
        } else {
            let policy = CodexRuntimePolicy(codexHome: codexHome,
                                            tempRoot: fileManager.temporaryDirectory,
                                            fileManager: fileManager)
            self.server = CodexAppServer(executableURL: executableURL,
                                         fileManager: fileManager,
                                         launchArguments: { try policy.startupArguments() })
            self.ownsServer = true
        }
        self.executableURL = executableURL
        self.fileManager = fileManager
        self.minimumVersion = minimumVersion
        self.versionCheckTimeoutNanoseconds = UInt64(max(0.1, versionCheckTimeout) * 1_000_000_000)
    }

    func check() async -> CodexReadinessReport {
        defer {
            if ownsServer { server.shutdown() }
        }
        guard let executable = executableURL ?? server.executableURLForReadiness,
              fileManager.isExecutableFile(atPath: executable.path) else {
            return CodexReadinessReport(
                state: .codexNotInstalled,
                executablePath: nil,
                version: nil,
                modelIDs: []
            )
        }

        let version: String
        do {
            version = try await Self.readVersion(
                executable: executable,
                timeoutNanoseconds: versionCheckTimeoutNanoseconds
            )
        } catch {
            return CodexReadinessReport(
                state: .connectionFailed("Could not run Codex to read its version: \(error.localizedDescription)"),
                executablePath: executable.path,
                version: nil,
                modelIDs: []
            )
        }

        guard Self.isSupported(version: version, minimum: minimumVersion) else {
            return CodexReadinessReport(
                state: .unsupportedVersion(installed: version, minimum: minimumVersion),
                executablePath: executable.path,
                version: version,
                modelIDs: []
            )
        }

        do {
            let account = try await server.request("account/read", params: [:])
            guard let requiresAuthentication = account["requiresOpenaiAuth"] as? Bool else {
                return CodexReadinessReport(
                    state: .unsupportedVersion(installed: version, minimum: minimumVersion),
                    executablePath: executable.path,
                    version: version,
                    modelIDs: []
                )
            }
            let hasAccount = account["account"] is [String: Any]
            if requiresAuthentication && !hasAccount {
                return CodexReadinessReport(
                    state: .signInRequired,
                    executablePath: executable.path,
                    version: version,
                    modelIDs: []
                )
            }

            let models = try await server.request("model/list", params: [
                "includeHidden": false,
                "limit": 100
            ])
            guard let modelIDs = Self.modelIDs(from: models) else {
                return CodexReadinessReport(
                    state: .unsupportedVersion(installed: version, minimum: minimumVersion),
                    executablePath: executable.path,
                    version: version,
                    modelIDs: []
                )
            }
            guard !modelIDs.isEmpty else {
                return CodexReadinessReport(
                    state: .connectionFailed("Codex returned no available models."),
                    executablePath: executable.path,
                    version: version,
                    modelIDs: []
                )
            }

            return CodexReadinessReport(
                state: .ready,
                executablePath: executable.path,
                version: version,
                modelIDs: modelIDs
            )
        } catch {
            let message = error.localizedDescription
            if Self.isAuthenticationError(message) {
                return CodexReadinessReport(
                    state: .signInRequired,
                    executablePath: executable.path,
                    version: version,
                    modelIDs: []
                )
            }
            if Self.isUnsupportedProtocolError(message) {
                return CodexReadinessReport(
                    state: .unsupportedVersion(installed: version, minimum: minimumVersion),
                    executablePath: executable.path,
                    version: version,
                    modelIDs: []
                )
            }
            return CodexReadinessReport(
                state: .connectionFailed(message),
                executablePath: executable.path,
                version: version,
                modelIDs: []
            )
        }
    }

    static func isSupported(version: String, minimum: String) -> Bool {
        guard let installed = semanticVersion(version), let required = semanticVersion(minimum) else {
            return false
        }
        return installed.lexicographicallyPrecedes(required) == false
    }

    private static func semanticVersion(_ value: String) -> [Int]? {
        let match = value.range(of: #"\d+(?:\.\d+){0,2}"#, options: .regularExpression)
        guard let match else { return nil }
        let parts = value[match].split(separator: ".").compactMap { Int($0) }
        guard !parts.isEmpty else { return nil }
        return parts + Array(repeating: 0, count: max(0, 3 - parts.count))
    }

    private static func readVersion(executable: URL, timeoutNanoseconds: UInt64) async throws -> String {
        try await withThrowingTaskGroup(of: String.self) { group in
            group.addTask {
                try await Self.runVersionProbe(executable: executable)
            }
            group.addTask {
                try await Task.sleep(nanoseconds: timeoutNanoseconds)
                throw ReadinessError.commandTimedOut
            }
            defer { group.cancelAll() }
            return try await group.next()!
        }
    }

    private static func runVersionProbe(executable: URL) async throws -> String {
        let process = Process()
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        let cancellation = ProcessCancellation(process: process)
        let output = BoundedOutputCollector(
            handle: outputPipe.fileHandleForReading,
            maximumBytes: 64 * 1024,
            onOverflow: { cancellation.cancel() }
        )
        let errors = BoundedOutputCollector(
            handle: errorPipe.fileHandleForReading,
            maximumBytes: 64 * 1024,
            onOverflow: { cancellation.cancel() }
        )
        process.executableURL = executable
        process.arguments = ["--version"]
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        process.environment = [
            "HOME": NSHomeDirectory(),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:\(NSHomeDirectory())/.local/bin:/opt/homebrew/bin:/usr/local/bin",
            "TMPDIR": NSTemporaryDirectory()
        ]
        try await withTaskCancellationHandler(operation: {
            try process.run()
            defer {
                output.stop()
                errors.stop()
                cancellation.clear()
            }
            while process.isRunning {
                try await Task.sleep(nanoseconds: 20_000_000)
            }
        }, onCancel: {
            cancellation.cancel()
        })
        let stdout = String(data: output.finish(), encoding: .utf8) ?? ""
        let stderr = String(data: errors.finish(), encoding: .utf8) ?? ""
        if output.didOverflow || errors.didOverflow {
            throw ReadinessError.outputTooLarge
        }
        guard process.terminationStatus == 0 else {
            let detail = stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            throw ReadinessError.commandFailed(detail.isEmpty ? "exit code \(process.terminationStatus)" : detail)
        }
        let value = stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard semanticVersion(value) != nil else {
            throw ReadinessError.invalidVersion(value)
        }
        return value
    }

    private static func modelIDs(from response: [String: Any]) -> [String]? {
        guard let data = response["data"] as? [[String: Any]] else { return nil }
        return data.compactMap { model in
            if let id = model["id"] as? String, !id.isEmpty { return id }
            if let model = model["model"] as? String, !model.isEmpty { return model }
            return nil
        }
    }

    private static func isAuthenticationError(_ message: String) -> Bool {
        let value = message.lowercased()
        return value.contains("unauthorized") || value.contains("authentication")
            || value.contains("not logged in") || value.contains("login required")
            || value.contains("requires openai auth")
    }

    private static func isUnsupportedProtocolError(_ message: String) -> Bool {
        let value = message.lowercased()
        return value.contains("method not found") || value.contains("unknown method")
            || value.contains("unsupported protocol") || value.contains("invalid initialize")
    }

    private enum ReadinessError: Error, LocalizedError {
        case commandFailed(String)
        case invalidVersion(String)
        case commandTimedOut
        case outputTooLarge

        var errorDescription: String? {
            switch self {
            case .commandFailed(let message): return message
            case .invalidVersion(let value): return "Codex returned an invalid version: \(value)"
            case .commandTimedOut: return "Codex did not respond to the version check."
            case .outputTooLarge: return "Codex returned too much output for a version check."
            }
        }
    }
}

private final class ProcessCancellation: @unchecked Sendable {
    private let lock = NSLock()
    private weak var process: Process?

    init(process: Process) {
        self.process = process
    }

    func cancel() {
        lock.lock()
        let process = self.process
        lock.unlock()
        if let process, process.isRunning { process.terminate() }
    }

    func clear() {
        lock.lock()
        process = nil
        lock.unlock()
    }
}

private final class BoundedOutputCollector: @unchecked Sendable {
    private let handle: FileHandle
    private let maximumBytes: Int
    private let lock = NSLock()
    private var buffer = Data()
    private(set) var didOverflow = false

    init(handle: FileHandle, maximumBytes: Int, onOverflow: @escaping @Sendable () -> Void) {
        self.handle = handle
        self.maximumBytes = maximumBytes
        handle.readabilityHandler = { [weak self] handle in
            guard let self else { return }
            let data = handle.availableData
            guard !data.isEmpty else { return }
            self.lock.lock()
            if self.buffer.count + data.count > self.maximumBytes {
                self.didOverflow = true
                self.lock.unlock()
                onOverflow()
            } else {
                self.buffer.append(data)
                self.lock.unlock()
            }
        }
    }

    func finish() -> Data {
        stop()
        let remainder = handle.readDataToEndOfFile()
        lock.lock()
        if !remainder.isEmpty {
            if buffer.count + remainder.count > maximumBytes {
                didOverflow = true
            } else {
                buffer.append(remainder)
            }
        }
        defer { lock.unlock() }
        return buffer
    }

    func cancel() {
        stop()
        lock.lock()
        buffer.removeAll(keepingCapacity: false)
        lock.unlock()
    }

    func stop() {
        handle.readabilityHandler = nil
    }
}
