import Foundation
import Darwin

/// A profile registered with the resident Go runtime.
struct RuntimeProfile: Codable, Equatable, @unchecked Sendable {
    let id: String
    let revision: String
    let environment: [String: String]
    let pollInterval: Double
    let monitoring: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case revision
        case environment
        case pollInterval = "poll_interval"
        case monitoring
    }

    init(id: String, revision: String = "", environment: [String: String], pollInterval: Double,
         monitoring: Bool) {
        self.id = id
        self.revision = revision
        self.environment = environment
        self.pollInterval = pollInterval
        self.monitoring = monitoring
    }

    init(id: String, revision: String = "", environment: GullsCLI.Environment,
         pollInterval: Double, monitoring: Bool) {
        self.init(id: id, revision: revision, environment: environment.runtimeEnvironment,
                  pollInterval: pollInterval, monitoring: monitoring)
    }
}

extension GullsCLI.Environment {
    /// Environment values sent inside a runtime profile. The token remains in
    /// the private app-to-child pipe and is never included in diagnostics.
    fileprivate var runtimeEnvironment: [String: String] {
        var values = processEnvironment()
        values.removeValue(forKey: "HOME")
        values.removeValue(forKey: "PATH")
        return values
    }
}

enum RuntimeEventStatus: String, Codable {
    case connecting
    case connected
    case reconnecting
    case paused
    case authorizationRequired = "authorization_required"
    case unavailable
}

/// Events delivered by the resident runtime. `inbox` is the complete inbox
/// response for the profile, when the event carries one.
struct RuntimeEvent: Decodable, @unchecked Sendable {
    let profileID: String
    let revision: String?
    let inbox: InboxResponse?
    let checkedAt: String?
    let status: RuntimeEventStatus
    let error: String?

    enum CodingKeys: String, CodingKey {
        case profileID = "profile_id"
        case revision
        case inbox
        case checkedAt = "checked_at"
        case status
        case error
    }

    init(profileID: String, revision: String? = nil, status: RuntimeEventStatus,
         inbox: InboxResponse? = nil, checkedAt: String? = nil, error: String? = nil) {
        self.profileID = profileID
        self.revision = revision
        self.inbox = inbox
        self.checkedAt = checkedAt
        self.status = status
        self.error = error
    }
}

private struct RuntimeRequest: Encodable {
    let version = 1
    let id: String
    let operation: String
    let profiles: [RuntimeProfile]?
    let profileID: String?
    let revision: String?
    let arguments: [String]?

    enum CodingKeys: String, CodingKey {
        case version, id, operation, profiles
        case profileID = "profile_id"
        case revision, arguments
    }
}

private struct RuntimeResponse: Decodable {
    let version: Int
    let id: String
    let exitCode: Int
    let stdout: String
    let stderr: String

    enum CodingKeys: String, CodingKey {
        case version, id
        case exitCode = "exit_code"
        case stdout, stderr
    }
}

private final class OrderedLineDispatcher: @unchecked Sendable {
    private let lock = NSLock()
    private var tail: Task<Void, Never>?

    func submit(_ line: Data, handler: @escaping @Sendable (Data) async -> Void) {
        lock.lock()
        let previous = tail
        let next = Task {
            _ = await previous?.value
            await handler(line)
        }
        tail = next
        lock.unlock()
    }
}

/// Owns the one app-supervised `runtime serve --stdio` subprocess.
actor GullsRuntimeBridge {
    typealias EventHandler = @Sendable (RuntimeEvent) -> Void

    enum BridgeError: Error, LocalizedError {
        case unavailable
        case response(String)

        var errorDescription: String? {
            switch self {
            case .unavailable: return "The gulls runtime is unavailable."
            case .response(let message): return message
            }
        }
    }

    private let executableURL: URL
    private let socketURL: URL
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private var process: Process?
    private var processGroupID: pid_t?
    private var input: FileHandle?
    private var lineCollector: LineCollector?
    private var stderrCollector: PipeCollector?
    private var pending: [String: CheckedContinuation<RuntimeResponse, Error>] = [:]
    private var profiles: [RuntimeProfile] = []
    private var eventHandler: EventHandler?
    private var stopping = false
    private var restartTask: Task<Void, Never>?
    private var restartCount = 0
    private var generation = 0
    private var pendingTimeouts: [String: Task<Void, Never>] = [:]
    private let orderedLines = OrderedLineDispatcher()

    init(executableURL: URL, socketURL: URL? = nil) {
        self.executableURL = executableURL
        self.socketURL = socketURL ?? FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/seagull/runtime/runtime.sock")
    }

    func start(onEvent: @escaping EventHandler) throws {
        eventHandler = onEvent
        stopping = false
        if process?.isRunning == true { return }
        try launch()
    }

    func configure(_ profiles: [RuntimeProfile]) async throws {
        self.profiles = profiles
        if profiles.isEmpty, process?.isRunning != true { return }
        if process?.isRunning != true {
            try launch()
        }
        try validateControl(try await request(operation: "configure", profiles: profiles))
        restartCount = 0
    }

    func refresh(profileID: String) async throws {
        if process?.isRunning != true {
            guard !stopping else { throw BridgeError.unavailable }
            restartTask?.cancel()
            restartTask = nil
            try launch()
            let recoveryGeneration = generation
            do {
                try validateControl(try await request(operation: "configure", profiles: profiles))
            } catch GullsCLI.Failure.configuration {
                // Profile validation is reported by per-profile events. The
                // healthy profiles still share a usable service.
            } catch {
                if generation == recoveryGeneration { process?.terminate() }
                throw error
            }
            restartCount = 0
        }
        try validateControl(try await request(operation: "refresh", profileID: profileID))
    }

    func command(_ arguments: [String], profile: RuntimeProfile) async throws -> Data {
        let response = try await request(operation: "command", profileID: profile.id,
                                         revision: profile.revision, arguments: arguments)
        guard response.exitCode == 0 else {
            let message = Self.trimmed(response.stderr)
            throw response.exitCode == 2
                ? GullsCLI.Failure.configuration(message)
                : GullsCLI.Failure.runtime(message)
        }
        return Data(response.stdout.utf8)
    }

    func stop() async {
        stopping = true
        restartTask?.cancel()
        restartTask = nil
        let current = process
        let currentGroup = processGroupID
        process = nil
        processGroupID = nil
        input = nil
        failPending(BridgeError.unavailable)
        if let current, current.isRunning {
            // Closing stdin is the runtime's graceful shutdown signal.
            if let pipe = current.standardInput as? Pipe {
                try? pipe.fileHandleForWriting.close()
            }
            current.terminate()
        }
        // Avoid readToEnd on a live child. Wait briefly for SIGTERM, then
        // detach the readability handlers if the process is still stuck.
        if let current {
            for _ in 0..<20 {
                if !current.isRunning { break }
                try? await Task.sleep(nanoseconds: 10_000_000)
            }
        }
        if current == nil || current?.isRunning == false {
            lineCollector?.finish()
            _ = stderrCollector?.finish()
        } else {
            lineCollector?.cancel()
            stderrCollector?.cancel()
            let pid = current!.processIdentifier
            if let group = currentGroup, group == pid, getpgid(pid) == pid {
                kill(-group, SIGKILL)
            } else {
                kill(pid, SIGKILL)
            }
        }
        lineCollector = nil
        stderrCollector = nil
    }

    private func launch() throws {
        guard !stopping else { throw BridgeError.unavailable }
        let process = Process()
        process.executableURL = executableURL
        let socket = socketURL.path
        process.arguments = ["--json", "runtime", "serve", "--stdio", "--socket", socket]
        process.environment = ["HOME": NSHomeDirectory(), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"]
        process.currentDirectoryURL = FileManager.default.temporaryDirectory
        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr
        process.standardInput = Pipe()
        let collector = PipeCollector(handle: stderr.fileHandleForReading)
        let launchGeneration = generation + 1
        generation = launchGeneration
        let lines = LineCollector(handle: stdout.fileHandleForReading) { [weak self] line in
            guard let self else { return }
            self.orderedLines.submit(line) { [weak self] line in
                guard let self else { return }
                await self.receive(line, generation: launchGeneration)
            }
        }
        process.terminationHandler = { [weak self] _ in
            guard let self else { return }
            Task { await self.terminated(generation: launchGeneration) }
        }
        do {
            try process.run()
        } catch {
            lines.cancel()
            collector.cancel()
            throw GullsCLI.Failure.launch(error.localizedDescription)
        }
        self.process = process
        let pid = process.processIdentifier
        processGroupID = getpgid(pid) == pid ? pid : nil
        self.input = (process.standardInput as? Pipe)?.fileHandleForWriting
        self.lineCollector = lines
        self.stderrCollector = collector
        emitLifecycle(.connecting)
    }

    private func terminated(generation: Int) {
        guard generation == self.generation else { return }
        lineCollector?.finish()
        lineCollector = nil
        _ = stderrCollector?.finish()
        stderrCollector = nil
        input = nil
        process = nil
        processGroupID = nil
        failPending(BridgeError.unavailable)
        guard !stopping else { return }
        scheduleRestart()
    }

    private func scheduleRestart() {
        guard restartCount < 3, restartTask == nil else {
            emitLifecycle(.unavailable, error: "The gulls runtime stopped unexpectedly.")
            return
        }
        restartCount += 1
        let delay = UInt64([200, 500, 1_000][restartCount - 1]) * 1_000_000
        emitLifecycle(.reconnecting)
        restartTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: delay)
            guard !Task.isCancelled, let self else { return }
            await self.restartAfterCrash()
        }
    }

    private func restartAfterCrash() async {
        restartTask = nil
        guard !stopping else { return }
        do {
            try launch()
        } catch {
            scheduleRestart()
            return
        }
        let launchGeneration = generation
        // Restore configuration only; operations interrupted by the crash are
        // never replayed.
        guard !profiles.isEmpty else { return }
        do {
            try validateControl(try await request(operation: "configure", profiles: profiles))
        } catch GullsCLI.Failure.configuration {
            // Invalid profiles report their own errors without taking down
            // the other profiles restored by the service.
        } catch {
            restoreConfigurationFailed(generation: launchGeneration)
        }
    }

    private func restoreConfigurationFailed(generation: Int) {
        guard generation == self.generation, process?.isRunning == true else { return }
        emitLifecycle(.unavailable, error: "The gulls runtime could not restore its profiles.")
        process?.terminate()
    }

    private func request(operation: String, profiles: [RuntimeProfile]? = nil,
                         profileID: String? = nil, revision: String? = nil,
                         arguments: [String]? = nil) async throws -> RuntimeResponse {
        guard process?.isRunning == true, let input else { throw BridgeError.unavailable }
        let id = UUID().uuidString
        let request = RuntimeRequest(id: id, operation: operation, profiles: profiles,
                                     profileID: profileID, revision: revision, arguments: arguments)
        var data = try encoder.encode(request)
        data.append(0x0A)
        return try await withCheckedThrowingContinuation { continuation in
            pending[id] = continuation
            pendingTimeouts[id] = Task { [weak self] in
                try? await Task.sleep(nanoseconds: 30_000_000_000)
                guard !Task.isCancelled, let self else { return }
                await self.timeout(id: id)
            }
            do {
                try input.write(contentsOf: data)
            } catch {
                pending.removeValue(forKey: id)
                pendingTimeouts.removeValue(forKey: id)?.cancel()
                continuation.resume(throwing: error)
            }
        }
    }

    private func receive(_ line: Data, generation: Int) {
        guard generation == self.generation else { return }
        guard let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else { return }
        guard object["version"] as? Int == 1 else {
            if let id = object["id"] as? String, let continuation = pending.removeValue(forKey: id) {
                pendingTimeouts.removeValue(forKey: id)?.cancel()
                continuation.resume(throwing: BridgeError.response("The gulls runtime returned an invalid protocol version."))
            }
            return
        }
        if object["event"] as? String == "inbox" {
            guard let event = try? decoder.decode(RuntimeEvent.self, from: line) else { return }
            emit(event)
            return
        }
        guard let id = object["id"] as? String, let continuation = pending.removeValue(forKey: id) else { return }
        pendingTimeouts.removeValue(forKey: id)?.cancel()
        guard let response = try? decoder.decode(RuntimeResponse.self, from: line), response.version == 1 else {
            continuation.resume(throwing: BridgeError.response("The gulls runtime returned an invalid response."))
            return
        }
        continuation.resume(returning: response)
    }

    private func timeout(id: String) {
        guard let continuation = pending.removeValue(forKey: id) else { return }
        pendingTimeouts.removeValue(forKey: id)?.cancel()
        continuation.resume(throwing: BridgeError.response("The gulls runtime request timed out."))
    }

    private func emit(_ event: RuntimeEvent) {
        eventHandler?(event)
    }

    private func emitLifecycle(_ status: RuntimeEventStatus, error: String? = nil) {
        if profiles.isEmpty {
            emit(RuntimeEvent(profileID: "", status: status, error: error))
        } else {
            for profile in profiles {
                emit(RuntimeEvent(profileID: profile.id, revision: profile.revision,
                                  status: status, error: error))
            }
        }
    }

    private func failPending(_ error: Error) {
        let waiting = pending.values
        pending.removeAll()
        for timeout in pendingTimeouts.values { timeout.cancel() }
        pendingTimeouts.removeAll()
        for continuation in waiting { continuation.resume(throwing: error) }
    }

    private func validateControl(_ response: RuntimeResponse) throws {
        guard response.exitCode == 0 else {
            let message = Self.trimmed(response.stderr)
            throw response.exitCode == 2
                ? GullsCLI.Failure.configuration(message)
                : GullsCLI.Failure.runtime(message)
        }
    }

    private static func trimmed(_ text: String) -> String {
        let result = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return result.isEmpty ? "The gulls runtime command failed." : result
    }
}
