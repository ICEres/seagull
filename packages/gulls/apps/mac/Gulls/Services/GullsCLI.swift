import Foundation

// Bridge to the bundled gulls CLI. Every call shells out to
// `gulls --json <command> ...` (global flags must precede the command — the
// Go flag package stops parsing at the first non-flag argument) and decodes
// stdout with the Codable models pinned by the shared contract fixtures.
//
// One-shot commands are strictly serialized (FIFO). Actor isolation alone is
// not enough: actors are reentrant, so a second call would enter while the
// first is suspended waiting on its subprocess. Since the CLI reads and
// writes shared files under the context dir, `run` chains each invocation on
// the previous one. The long-lived `stream` subprocess is exempt — it only
// reads, and serializing it would block every command behind it.
actor GullsCLI {

    // Explicit subprocess environment built from app settings. The env-file
    // fallback is disabled by pointing SEAGULL_AGENT_ENV_FILE at a path that
    // never exists, so app config is the only config the subprocess sees
    // (same pattern as the CLI's own e2e tests).
    struct Environment {
        var apiURL: String
        var agentHandle: String
        var token: String?
        var contextDir: URL
        var streamURL: String = ""

        func processEnvironment() -> [String: String] {
            var env: [String: String] = [
                "HOME": NSHomeDirectory(),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            ]
            env["SEAGULL_API_URL"] = apiURL
            env["SEAGULL_AGENT_HANDLE"] = agentHandle
            if let token, !token.isEmpty {
                env["SEAGULL_CONNECTOR_TOKEN"] = token
            }
            env["SEAGULL_AGENT_CONTEXT_DIR"] = contextDir.path
            env["SEAGULL_AGENT_ENV_FILE"] = contextDir.appendingPathComponent(".env-file-disabled").path
            if !streamURL.isEmpty {
                env["SEAGULL_STREAM_URL"] = streamURL
            }
            return env
        }
    }

    enum Failure: Error, LocalizedError {
        case launch(String)
        case configuration(String)   // exit code 2: usage/config — point the user at Settings
        case runtime(String)         // exit code 1: runtime/HTTP error from the hub
        case decoding(command: String, underlying: Error)

        var errorDescription: String? {
            switch self {
            case .launch(let message):
                return "Could not run the bundled gulls CLI: \(message)"
            case .configuration(let message):
                return "Configuration problem — check Settings. \(message)"
            case .runtime(let message):
                return message
            case .decoding(let command, let underlying):
                return "Unexpected \(command) output from the gulls CLI: \(underlying.localizedDescription)"
            }
        }
    }

    private let executableURL: URL
    private let decoder = JSONDecoder()

    // Tail of the FIFO command chain; each `run` awaits the previous one.
    private var commandTail: Task<Void, Never>?

    init(executableURL: URL) {
        self.executableURL = executableURL
    }

    static func bundled() -> GullsCLI? {
        guard let url = Bundle.main.url(forResource: "gulls", withExtension: nil) else {
            return nil
        }
        return GullsCLI(executableURL: url)
    }

    // MARK: - Typed commands

    func version() async throws -> VersionInfo {
        // `version` needs no hub config; run with a minimal environment.
        let environment = Environment(
            apiURL: "http://localhost:0",
            agentHandle: "@version:gulls.ai",
            token: nil,
            contextDir: FileManager.default.temporaryDirectory
        )
        return try await runDecoding(["version"], environment: environment)
    }

    func whoami(environment: Environment) async throws -> Agent {
        let response: WhoamiResponse = try await runDecoding(["whoami"], environment: environment)
        return response.agent
    }

    func inbox(limit: Int = 20, environment: Environment) async throws -> [InboxItem] {
        let response: InboxResponse = try await runDecoding(
            ["inbox", "--limit", String(limit)],
            environment: environment
        )
        return response.items
    }

    func openDelivery(id: String, environment: Environment) async throws -> OpenResult {
        try await runDecoding(["open", id], environment: environment)
    }

    func draftReply(id: String, approve: Bool, environment: Environment) async throws -> DraftReplyResult {
        var command = ["draft-reply"]
        if approve {
            command.append("--approve")
        }
        command.append(id)
        return try await runDecoding(command, environment: environment)
    }

    func reply(id: String, content: String, environment: Environment) async throws -> DecisionResult {
        try await runDecoding(["reply", id, content], environment: environment)
    }

    func ack(id: String, environment: Environment) async throws {
        // Ack output is an opaque hub map; exit code 0 is the contract.
        _ = try await run(["ack", id], environment: environment)
    }

    func ignore(id: String, environment: Environment) async throws -> DecisionResult {
        try await runDecoding(["ignore", id], environment: environment)
    }

    // MARK: - Streaming (long-running `gulls stream`)

    // Handle for a running stream subprocess: NDJSON lines as they arrive,
    // plus a terminate control. The subprocess handles its own WebSocket
    // reconnects; it only exits on SIGTERM (clean) or a fatal error. A fatal
    // exit throws .configuration for exit code 2 (bad URL/token/scope — the
    // caller should stop retrying) and .runtime otherwise.
    struct StreamHandle {
        let lines: AsyncThrowingStream<Data, Error>
        let terminate: @Sendable () -> Void
    }

    func openStream(environment: Environment) throws -> StreamHandle {
        let (process, stdoutPipe, stderrPipe) = Self.makeProcess(
            executableURL: executableURL,
            command: ["stream"],
            environment: environment
        )

        let stderrCollector = PipeCollector(handle: stderrPipe.fileHandleForReading)
        let terminated = TerminationFlag()

        let lines = AsyncThrowingStream<Data, Error> { continuation in
            let lineCollector = LineCollector(handle: stdoutPipe.fileHandleForReading) { line in
                continuation.yield(line)
            }
            process.terminationHandler = { finished in
                lineCollector.finish()
                let stderr = stderrCollector.finish()
                if finished.terminationStatus == 0 || terminated.isSet {
                    continuation.finish()
                } else {
                    let message = String(decoding: stderr, as: UTF8.self)
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                    let text = message.isEmpty ? "stream exited unexpectedly" : message
                    let failure: Failure = finished.terminationStatus == 2
                        ? .configuration(text)
                        : .runtime(text)
                    continuation.finish(throwing: failure)
                }
            }
            continuation.onTermination = { _ in
                terminated.set()
                if process.isRunning {
                    process.terminate()
                }
            }
        }

        do {
            try process.run()
        } catch {
            throw Failure.launch(error.localizedDescription)
        }

        return StreamHandle(
            lines: lines,
            terminate: {
                terminated.set()
                if process.isRunning {
                    process.terminate()
                }
            }
        )
    }

    // MARK: - Process plumbing

    private func runDecoding<T: Decodable>(_ command: [String], environment: Environment) async throws -> T {
        let data = try await run(command, environment: environment)
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw Failure.decoding(command: command.first ?? "?", underlying: error)
        }
    }

    func run(_ command: [String], environment: Environment) async throws -> Data {
        let previous = commandTail
        let executableURL = self.executableURL
        let task = Task<Data, Error> {
            _ = await previous?.value
            return try await Self.execute(command, executableURL: executableURL, environment: environment)
        }
        commandTail = Task { _ = try? await task.value }
        return try await task.value
    }

    private static func execute(
        _ command: [String],
        executableURL: URL,
        environment: Environment
    ) async throws -> Data {
        let (process, stdoutPipe, stderrPipe) = makeProcess(
            executableURL: executableURL,
            command: command,
            environment: environment
        )

        // Drain pipes as data arrives — waiting for termination before reading
        // deadlocks once output exceeds the 64KB pipe buffer.
        let stdoutCollector = PipeCollector(handle: stdoutPipe.fileHandleForReading)
        let stderrCollector = PipeCollector(handle: stderrPipe.fileHandleForReading)

        let status: Int32
        do {
            status = try await withCheckedThrowingContinuation { continuation in
                process.terminationHandler = { finished in
                    continuation.resume(returning: finished.terminationStatus)
                }
                do {
                    try process.run()
                } catch {
                    process.terminationHandler = nil
                    continuation.resume(throwing: Failure.launch(error.localizedDescription))
                }
            }
        } catch {
            _ = stdoutCollector.finish()
            _ = stderrCollector.finish()
            throw error
        }

        let stdout = stdoutCollector.finish()
        let stderr = stderrCollector.finish()

        switch status {
        case 0:
            return stdout
        case 2:
            throw Failure.configuration(trimmedText(stderr))
        default:
            throw Failure.runtime(trimmedText(stderr))
        }
    }

    private static func makeProcess(
        executableURL: URL,
        command: [String],
        environment: Environment
    ) -> (process: Process, stdout: Pipe, stderr: Pipe) {
        try? FileManager.default.createDirectory(at: environment.contextDir, withIntermediateDirectories: true)

        let process = Process()
        process.executableURL = executableURL
        process.arguments = ["--json"] + command
        process.environment = environment.processEnvironment()
        process.currentDirectoryURL = environment.contextDir

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe
        process.standardInput = FileHandle.nullDevice
        return (process, stdoutPipe, stderrPipe)
    }

    private static func trimmedText(_ data: Data) -> String {
        String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

// Splits a file handle's output into newline-delimited chunks and emits each
// complete line as it arrives — the streaming variant of PipeCollector.
private final class LineCollector: @unchecked Sendable {
    private let handle: FileHandle
    private let lock = NSLock()
    private var buffer = Data()
    private let onLine: @Sendable (Data) -> Void

    init(handle: FileHandle, onLine: @escaping @Sendable (Data) -> Void) {
        self.handle = handle
        self.onLine = onLine
        handle.readabilityHandler = { [weak self] readHandle in
            self?.consume(readHandle.availableData)
        }
    }

    private func consume(_ chunk: Data) {
        var completeLines: [Data] = []
        lock.lock()
        buffer.append(chunk)
        while let newline = buffer.firstIndex(of: UInt8(ascii: "\n")) {
            let line = buffer.subdata(in: buffer.startIndex..<newline)
            buffer.removeSubrange(buffer.startIndex...newline)
            if !line.isEmpty {
                completeLines.append(line)
            }
        }
        lock.unlock()
        for line in completeLines {
            onLine(line)
        }
    }

    func finish() {
        handle.readabilityHandler = nil
        if let remaining = try? handle.readToEnd(), !remaining.isEmpty {
            consume(remaining)
        }
        // Flush a trailing unterminated line, if any.
        lock.lock()
        let tail = buffer
        buffer.removeAll()
        lock.unlock()
        if !tail.isEmpty {
            onLine(tail)
        }
    }
}

// Simple thread-safe latch marking an intentional terminate() so a SIGTERM
// exit is not reported as a stream failure.
private final class TerminationFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false

    var isSet: Bool {
        lock.lock()
        defer { lock.unlock() }
        return value
    }

    func set() {
        lock.lock()
        value = true
        lock.unlock()
    }
}

// Accumulates a file handle's output off the actor without racing the
// readability callback queue.
private final class PipeCollector: @unchecked Sendable {
    private let handle: FileHandle
    private let lock = NSLock()
    private var data = Data()

    init(handle: FileHandle) {
        self.handle = handle
        handle.readabilityHandler = { [weak self] readHandle in
            let chunk = readHandle.availableData
            guard let self else { return }
            self.lock.lock()
            self.data.append(chunk)
            self.lock.unlock()
        }
    }

    func finish() -> Data {
        handle.readabilityHandler = nil
        // Pick up anything buffered between the last callback and termination.
        if let remaining = try? handle.readToEnd(), !remaining.isEmpty {
            lock.lock()
            data.append(remaining)
            lock.unlock()
        }
        lock.lock()
        defer { lock.unlock() }
        return data
    }
}
