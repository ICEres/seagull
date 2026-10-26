import Foundation

/// Minimal local transport for Codex app-server.
///
/// This is intentionally transport-only. It does not start threads, execute
/// turns, log in, or grant permissions. Callers own those product decisions.
/// App-server requests from Codex are surfaced through `onRequest` so the Mac
/// approval UI can decide how to answer them.
@MainActor
final class CodexAppServer {
    static let shared = CodexAppServer()

    typealias NotificationHandler = (String, [String: Any]) -> Void
    /// Receives `(requestID, params, method)` for server requests that require
    /// a client response, such as command or file-change approval.
    typealias RequestHandler = (Any, [String: Any], String) -> Void

    var onNotification: NotificationHandler?
    var onRequest: RequestHandler?
    var onDisconnect: (() -> Void)?
    var isConnected: Bool { process?.isRunning == true && isInitialized }
    /// The executable selected by this transport. Readiness checks use this
    /// value so preflight cannot inspect a different global Codex binary.
    var executableURLForReadiness: URL? {
        executableURL ?? Self.findExecutable(fileManager: fileManager)
    }

    private static let maximumLineBytes = 4 * 1024 * 1024
    private static let requestTimeout: TimeInterval = 30

    private struct Pending {
        let continuation: CheckedContinuation<[String: Any], Error>
        let timeout: DispatchWorkItem
    }

    private enum Failure: Error, LocalizedError {
        case unavailable(String)
        case launch(String)
        case protocolError(String)
        case requestTimedOut(String)
        case server(Int, String)

        var errorDescription: String? {
            switch self {
            case .unavailable(let message), .launch(let message), .protocolError(let message),
                 .requestTimedOut(let message): return message
            case .server(let code, let message): return "Codex app-server error \(code): \(message)"
            }
        }
    }

    private let fileManager: FileManager
    private let executableURL: URL?
    private let launchArguments: (() throws -> [String])?
    private var process: Process?
    private var input: FileHandle?
    private var output: BoundedLineCollector?
    private var errors: PipeCollector?
    private var pending: [Int: Pending] = [:]
    private var nextID = 1
    private var isInitialized = false
    private var initializationTask: Task<Void, Error>?
    private var generation = 0
    private let lineDelivery = OrderedLineDelivery()

    init(executableURL: URL? = nil, fileManager: FileManager = .default,
         launchArguments: (() throws -> [String])? = nil) {
        self.executableURL = executableURL
        self.fileManager = fileManager
        self.launchArguments = launchArguments
    }

    func request(_ method: String, params: [String: Any] = [:]) async throws -> [String: Any] {
        try await ensureReady()
        return try await sendRequest(method, params: params)
    }

    func notify(_ method: String, params: [String: Any] = [:]) throws {
        try ensureProcess()
        try write(["method": method, "params": params])
    }

    func respond(id: Any, result: [String: Any]) throws {
        guard process?.isRunning == true, input != nil else {
            throw Failure.unavailable("The Codex connection is no longer active.")
        }
        guard JSONSerialization.isValidJSONObject(result) else {
            throw Failure.protocolError("Codex response contains values that are not JSON encodable.")
        }
        var message: [String: Any] = ["result": result]
        if let id = id as? String { message["id"] = id }
        else if let id = id as? Int { message["id"] = id }
        else { throw Failure.protocolError("Codex request id must be a string or integer.") }
        try write(message)
    }

    func reject(id: Any, message: String) throws {
        guard id is String || id is Int else { return }
        try write(["id": id, "error": ["code": -32601, "message": message]])
    }

    func shutdown() {
        isInitialized = false
        initializationTask?.cancel()
        initializationTask = nil
        generation &+= 1
        output?.cancel()
        errors?.cancel()
        output = nil
        errors = nil
        input = nil
        let child = process
        process = nil
        failPending(Failure.unavailable("Codex app-server was stopped. You can still open the task in Codex."))
        if let child, child.isRunning { child.terminate() }
        onDisconnect?()
    }

    private func ensureReady() async throws {
        if isInitialized, process?.isRunning == true { return }
        try ensureProcess()
        guard !isInitialized else { return }
        if let initializationTask {
            try await initializationTask.value
            return
        }
        let task = Task { @MainActor [weak self] in
            guard let self else { throw Failure.unavailable("Codex app-server was released.") }
            try await self.initializeProtocol()
        }
        initializationTask = task
        do {
            try await task.value
            initializationTask = nil
        } catch {
            initializationTask = nil
            throw error
        }
    }

    private func initializeProtocol() async throws {
        let result = try await sendRequest("initialize", params: [
            "clientInfo": [
                "name": "gulls",
                "title": "Gulls",
                "version": "0.1.0"
            ],
            "capabilities": [
                "experimentalApi": true
            ]
        ])
        guard result["platformFamily"] != nil || result["platformOs"] != nil else {
            throw Failure.protocolError("Codex app-server returned an invalid initialize response.")
        }
        try write(["method": "initialized"])
        isInitialized = true
    }

    private func ensureProcess() throws {
        if process?.isRunning == true, input != nil { return }
        guard let executable = executableURL ?? Self.findExecutable(fileManager: fileManager) else {
            throw Failure.unavailable("Codex app-server is unavailable. You can still open the task in Codex.")
        }

        generation &+= 1
        let launchGeneration = generation
        isInitialized = false

        let child = Process()
        child.executableURL = executable
        child.arguments = ["app-server", "--listen", "stdio://"] + (try launchArguments?() ?? [])
        child.environment = safeEnvironment()
        child.currentDirectoryURL = fileManager.homeDirectoryForCurrentUser

        let stdout = Pipe()
        let stderr = Pipe()
        child.standardOutput = stdout
        child.standardError = stderr
        child.standardInput = Pipe()
        let lines = BoundedLineCollector(handle: stdout.fileHandleForReading, maximumLineBytes: Self.maximumLineBytes, onFailure: { [weak self] message in
            Task { @MainActor [weak self] in
                self?.failTransport(Failure.protocolError(message), generation: launchGeneration)
            }
        }) { [weak self] line in
            self?.lineDelivery.submit(line) { [weak self] line in
                Task { @MainActor [weak self] in
                    self?.receive(line, generation: launchGeneration)
                }
            }
        }
        let diagnostics = PipeCollector(handle: stderr.fileHandleForReading)
        child.terminationHandler = { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.generation == launchGeneration else { return }
                self.process = nil
                self.input = nil
                self.isInitialized = false
                self.output?.cancel()
                self.output = nil
                self.errors?.cancel()
                self.errors = nil
                self.failPending(Failure.unavailable("Codex app-server stopped. You can still open the task in Codex."))
                self.onDisconnect?()
            }
        }
        do { try child.run() }
        catch { lines.cancel(); diagnostics.cancel(); throw Failure.launch(error.localizedDescription) }
        process = child
        input = (child.standardInput as? Pipe)?.fileHandleForWriting
        output = lines
        errors = diagnostics
    }

    private func sendRequest(_ method: String, params: [String: Any]) async throws -> [String: Any] {
        try ensureProcess()
        let id = nextID
        nextID += 1
        let item = try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<[String: Any], Error>) in
                let timeout = DispatchWorkItem { [weak self] in
                    Task { @MainActor [weak self] in
                        guard let self, let pending = self.pending.removeValue(forKey: id) else { return }
                        pending.continuation.resume(throwing: Failure.requestTimedOut("Codex app-server request timed out: \(method)."))
                    }
                }
                pending[id] = Pending(continuation: continuation, timeout: timeout)
                DispatchQueue.main.asyncAfter(deadline: .now() + Self.requestTimeout, execute: timeout)
                do { try write(["id": id, "method": method, "params": params]) }
                catch {
                    timeout.cancel()
                    pending.removeValue(forKey: id)
                    continuation.resume(throwing: error)
                }
            }
        }, onCancel: { [weak self] in
            Task { @MainActor [weak self] in
                guard let self, let pending = self.pending.removeValue(forKey: id) else { return }
                pending.timeout.cancel()
                pending.continuation.resume(throwing: CancellationError())
            }
        })
        return item
    }

    private func receive(_ line: Data, generation: Int) {
        guard self.generation == generation else { return }
        guard let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else {
            failTransport(Failure.protocolError("Codex app-server returned malformed JSON."), generation: generation)
            return
        }
        if let id = object["id"] as? Int, let pending = pending.removeValue(forKey: id) {
            pending.timeout.cancel()
            if let error = object["error"] as? [String: Any] {
                pending.continuation.resume(throwing: Failure.server(error["code"] as? Int ?? -1, error["message"] as? String ?? "Unknown error"))
            } else {
                pending.continuation.resume(returning: object["result"] as? [String: Any] ?? [:])
            }
            return
        }
        // A caller may cancel or time out after the app-server has accepted
        // the request but before its response arrives. That response is still
        // valid JSON-RPC, but there is no continuation left to resume. Ignore
        // only well-formed, uncorrelated responses; malformed messages must
        // continue through the fail-closed protocol path below.
        let hasResult = object.keys.contains("result")
        let hasError = object["error"] is [String: Any]
        let isResponse = (hasResult != hasError)
            && object["method"] == nil
            && object["params"] == nil
        if isResponse, (object["id"] is Int || object["id"] is String) {
            return
        }
        guard let method = object["method"] as? String else {
            failTransport(Failure.protocolError("Codex app-server returned an invalid JSON-RPC message."), generation: generation)
            return
        }
        let params = object["params"] as? [String: Any] ?? [:]
        if let id = object["id"], !(id is NSNull) { onRequest?(id, params, method) }
        else { onNotification?(method, params) }
    }

    private func failTransport(_ error: Error, generation: Int) {
        guard self.generation == generation else { return }
        self.generation &+= 1
        isInitialized = false
        initializationTask?.cancel()
        initializationTask = nil
        output?.cancel()
        errors?.cancel()
        output = nil
        errors = nil
        input = nil
        let child = process
        process = nil
        failPending(error)
        if let child, child.isRunning { child.terminate() }
        onDisconnect?()
    }

    private func write(_ object: [String: Any]) throws {
        guard JSONSerialization.isValidJSONObject(object), let input else {
            throw Failure.protocolError("Codex app-server message is not valid JSON.")
        }
        var data = try JSONSerialization.data(withJSONObject: object, options: [])
        data.append(0x0A)
        try input.write(contentsOf: data)
    }

    private func failPending(_ error: Error) {
        let current = pending.values
        pending.removeAll()
        for item in current { item.timeout.cancel(); item.continuation.resume(throwing: error) }
    }

    private func safeEnvironment() -> [String: String] {
        [
            "HOME": fileManager.homeDirectoryForCurrentUser.path,
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:\(fileManager.homeDirectoryForCurrentUser.path)/.local/bin:/opt/homebrew/bin:/usr/local/bin",
            "TMPDIR": NSTemporaryDirectory()
        ]
    }

    static func findExecutable(fileManager: FileManager = .default) -> URL? {
        let candidates = [
            fileManager.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/codex"),
            URL(fileURLWithPath: "/opt/homebrew/bin/codex"),
            URL(fileURLWithPath: "/usr/local/bin/codex")
        ]
        return candidates.first { fileManager.isExecutableFile(atPath: $0.path) }
    }
}

/// Newline collector with a hard cap on an unterminated server line. The
/// shared CLI collector predates app-server and intentionally has no cap.
private final class BoundedLineCollector: @unchecked Sendable {
    private let handle: FileHandle
    private let maximumLineBytes: Int
    private let lock = NSLock()
    private var buffer = Data()
    private let onLine: @Sendable (Data) -> Void
    private let onFailure: @Sendable (String) -> Void
    private var didFail = false

    init(handle: FileHandle, maximumLineBytes: Int,
         onFailure: @escaping @Sendable (String) -> Void,
         onLine: @escaping @Sendable (Data) -> Void) {
        self.handle = handle
        self.maximumLineBytes = maximumLineBytes
        self.onFailure = onFailure
        self.onLine = onLine
        handle.readabilityHandler = { [weak self] handle in self?.consume(handle.availableData) }
    }

    private func consume(_ chunk: Data) {
        guard !chunk.isEmpty else { return }
        var lines: [Data] = []
        var failureMessage: String?
        lock.lock()
        guard !didFail else { lock.unlock(); return }
        buffer.append(chunk)
        while let newline = buffer.firstIndex(of: 0x0A) {
            let line = buffer.subdata(in: buffer.startIndex..<newline)
            buffer.removeSubrange(buffer.startIndex...newline)
            if line.count > maximumLineBytes {
                didFail = true
                buffer.removeAll(keepingCapacity: false)
                failureMessage = "Codex app-server returned an oversized JSON-RPC line."
                break
            }
            if !line.isEmpty { lines.append(line) }
        }
        if failureMessage == nil, buffer.count > maximumLineBytes {
            didFail = true
            buffer.removeAll(keepingCapacity: false)
            failureMessage = "Codex app-server returned an oversized JSON-RPC line."
        }
        lock.unlock()
        if let failureMessage { onFailure(failureMessage) }
        lines.forEach(onLine)
    }

    func cancel() {
        handle.readabilityHandler = nil
        lock.lock(); buffer.removeAll(); lock.unlock()
    }
}

/// Serializes delivery back to the main actor so JSON-RPC lines cannot be
/// observed out of order when FileHandle callbacks overlap.
private final class OrderedLineDelivery: @unchecked Sendable {
    private let lock = NSLock()
    private var tail: Task<Void, Never>?

    func submit(_ line: Data, handler: @escaping @Sendable (Data) -> Void) {
        lock.lock()
        let previous = tail
        let next = Task {
            _ = await previous?.value
            await MainActor.run { handler(line) }
        }
        tail = next
        lock.unlock()
    }
}
