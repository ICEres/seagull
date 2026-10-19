import CryptoKit
import Darwin
import Foundation
import Observation

@MainActor
@Observable
final class LocalControlStore {
    static let maximumRequestBytes = 256 * 1024
    static let maximumFileBytes = 1024 * 1024
    static let maximumOutputBytes = 64 * 1024
    static let maximumResultBytes = 8 * 1024 * 1024
    static let commandTimeout: Duration = .seconds(60)

    let config: GullsConfig
    private let defaults: UserDefaults
    private let fileManager = FileManager.default

    var enabled: Bool {
        didSet { defaults.set(enabled, forKey: keys.enabled) }
    }

    var allowedFolders: [String] {
        didSet {
            let normalized = normalizedFolders(allowedFolders)
            if normalized != allowedFolders { allowedFolders = normalized }
            defaults.set(allowedFolders, forKey: keys.allowedFolders)
        }
    }

    private(set) var pendingRequests: [LocalActionRequest] = []
    private(set) var recentResults: [LocalActionResult] = []
    private(set) var isRunning = false
    private(set) var error: String?

    private var loadedConnectionRevision: String
    private var runningExecution: LocalProcessExecution?
    private var activeRequestID: String?

    private let keys: Keys

    init(config: GullsConfig, defaults: UserDefaults = .standard) {
        self.config = config
        self.defaults = defaults
        self.keys = Keys(profileID: config.profileID)
        self.enabled = defaults.object(forKey: keys.enabled) == nil
            ? false
            : defaults.bool(forKey: keys.enabled)
        self.allowedFolders = defaults.stringArray(forKey: keys.allowedFolders) ?? []
        self.loadedConnectionRevision = config.connectionRevision
        self.allowedFolders = normalizedFolders(self.allowedFolders)
    }

    var actionsDirectory: URL {
        URL(fileURLWithPath: expanded(config.contextDir))
            .appendingPathComponent("local-actions", isDirectory: true)
    }

    var requestsDirectory: URL { actionsDirectory.appendingPathComponent("requests", isDirectory: true) }
    var resultsDirectory: URL { actionsDirectory.appendingPathComponent("results", isDirectory: true) }

    func addFolder(_ url: URL) {
        guard let root = canonicalDirectory(url) else {
            error = "Choose an existing folder."
            return
        }
        allowedFolders = normalizedFolders(allowedFolders + [root.path])
        error = nil
    }

    func removeFolder(_ path: String) {
        let canonical = canonicalDirectory(URL(fileURLWithPath: expanded(path)))?.path
        allowedFolders.removeAll { $0 == canonical || $0 == path }
    }

    /// Reads requests and results only. It never executes a request.
    func refresh() {
        loadedConnectionRevision = config.connectionRevision
        guard fileManager.fileExists(atPath: requestsDirectory.path)
                || fileManager.fileExists(atPath: resultsDirectory.path) else {
            pendingRequests = []
            recentResults = []
            error = nil
            return
        }
        error = nil
        recoverClaims()

        var loaded: [LocalActionRequest] = []
        var problems: [String] = error.map { [$0] } ?? []
        let resultIDs = Set(resultFiles().compactMap { resultID(from: $0) })
        let claimedIDs = Set(claimFiles().compactMap { claimID(from: $0) })

        for url in requestFiles() {
            guard let fileID = requestID(from: url), UUID(uuidString: fileID) != nil else {
                problems.append("\(url.lastPathComponent): request filename is invalid")
                continue
            }
            guard let values = try? url.resourceValues(forKeys: [.fileSizeKey]),
                  let size = values.fileSize, size <= Self.maximumRequestBytes else {
                problems.append("\(url.lastPathComponent): request is too large")
                continue
            }
            guard let data = try? Data(contentsOf: url) else {
                problems.append("\(url.lastPathComponent): request could not be read")
                continue
            }
            guard let request = try? JSONDecoder().decode(LocalActionRequest.self, from: data) else {
                problems.append("\(url.lastPathComponent): request schema is invalid")
                continue
            }
            guard request.requestID == fileID else {
                problems.append("\(url.lastPathComponent): request filename does not match request_id")
                continue
            }
            guard request.gullHandle == config.agentHandle,
                  isValidShape(request) else {
                problems.append("\(url.lastPathComponent): request is not valid for this Gull")
                continue
            }
            guard !resultIDs.contains(request.requestID), !claimedIDs.contains(request.requestID) else { continue }

            var reviewed = request
            captureReviewMetadata(&reviewed)
            reviewed.reviewedRequestDigest = request.canonicalDigest
            reviewed.reviewedConnectionRevision = config.connectionRevision
            loaded.append(reviewed)
        }

        pendingRequests = loaded.sorted(by: requestIsEarlier)
        recentResults = loadResults()
        error = problems.isEmpty ? nil : problems.joined(separator: "\n")
    }

    func approve(_ request: LocalActionRequest) async {
        guard !isRunning else { return }
        guard config.connectionRevision == loadedConnectionRevision else {
            error = "This request belongs to an older local connection. Refresh before reviewing it."
            refresh()
            return
        }
        guard enabled else {
            error = "Local control is disabled for this Gull."
            return
        }
        guard pendingRequests.contains(where: { $0.requestID == request.requestID }) else {
            error = "This request is no longer pending."
            refresh()
            return
        }
        guard let fresh = readRequest(request.requestID),
              fresh.gullHandle == config.agentHandle,
              isValidShape(fresh),
              request.reviewedRequestDigest == fresh.canonicalDigest else {
            await finish(request: request, status: .rejected, error: "The reviewed request changed. Review it again.")
            return
        }

        var reviewedRequest = fresh
        captureReviewMetadata(&reviewedRequest)
        guard request.reviewedConnectionRevision == config.connectionRevision,
              reviewedRequest.reviewedOriginalExists == request.reviewedOriginalExists,
              reviewedRequest.reviewedOriginalReadable == request.reviewedOriginalReadable,
              reviewedRequest.reviewedOriginalHash == request.reviewedOriginalHash else {
            await finish(request: request, status: .rejected, error: "The file changed after review. Review it again.")
            return
        }
        if fresh.kind == .writeFile {
            guard request.reviewedOriginalExists != true || request.reviewedOriginalReadable == true else {
                await finish(request: request, status: .rejected, error: "The existing target is not a reviewable UTF-8 file.")
                return
            }
            let currentHash = fileHash(for: fresh.path)
            guard currentHash == request.reviewedOriginalHash else {
                await finish(request: request, status: .rejected, error: "The target file changed after review.")
                return
            }
        }
        let resultDirectoryAtStart = resultsDirectory
        let claimPathAtStart = claimURL(fresh.requestID)
        guard claim(at: claimPathAtStart) else {
            error = "This request is already being handled."
            refresh()
            return
        }

        isRunning = true
        activeRequestID = fresh.requestID
        defer {
            isRunning = false
            activeRequestID = nil
            runningExecution = nil
        }

        let result: LocalActionResult
        let executionRequest = fresh.kind == .writeFile ? reviewedRequest : fresh
        switch executionRequest.kind {
        case .readFile:
            result = executeRead(executionRequest)
        case .writeFile:
            result = executeWrite(executionRequest)
        case .command:
            result = await executeCommand(executionRequest)
        }
        if await persist(result, requestID: fresh.requestID, destinationDirectory: resultDirectoryAtStart) {
            removeClaim(at: claimPathAtStart)
        }
    }

    func reject(_ request: LocalActionRequest) {
        guard !isRunning else {
            error = "Stop the running local action before rejecting it."
            return
        }
        guard pendingRequests.contains(where: { $0.requestID == request.requestID }) else {
            refresh()
            return
        }
        Task { await finish(request: request, status: .rejected, error: "Rejected by owner.") }
    }

    func stop(forTermination: Bool = false) {
        runningExecution?.terminate(reason: .cancelled, immediately: forTermination)
    }

    private func finish(
        request: LocalActionRequest,
        status: LocalActionResultStatus,
        error message: String
    ) async {
        guard !resultExists(request.requestID) else {
            refresh()
            return
        }
        let result = LocalActionResult(
            requestID: request.requestID,
            gullHandle: request.gullHandle,
            status: status,
            completedAt: Self.timestamp(),
            error: message
        )
        await persist(result, requestID: request.requestID)
    }

    private func executeRead(_ request: LocalActionRequest) -> LocalActionResult {
        guard let file = checkedFileURL(request.path, allowMissing: false) else {
            return failure(request, "The file is outside the selected folders or is unavailable.")
        }
        do {
            let values = try file.resourceValues(forKeys: [.fileSizeKey])
            guard let size = values.fileSize, size <= Self.maximumFileBytes else {
                return failure(request, "The file is larger than 1 MiB.")
            }
            let data = try Data(contentsOf: file)
            guard data.count <= Self.maximumFileBytes else {
                return failure(request, "The file is larger than 1 MiB.")
            }
            guard let content = String(data: data, encoding: .utf8) else {
                return failure(request, "Only UTF-8 text files can be read.")
            }
            return LocalActionResult(
                requestID: request.requestID,
                gullHandle: request.gullHandle,
                status: .succeeded,
                completedAt: Self.timestamp(),
                content: content
            )
        } catch {
            return failure(request, error.localizedDescription)
        }
    }

    private func executeWrite(_ request: LocalActionRequest) -> LocalActionResult {
        guard let file = checkedFileURL(request.path, allowMissing: true) else {
            return failure(request, "The file is outside the selected folders or is unavailable.")
        }
        guard let content = request.content, let data = content.data(using: .utf8),
              data.count <= Self.maximumFileBytes else {
            return failure(request, "The file content is missing or larger than 1 MiB.")
        }
        guard fileHash(for: request.path) == request.reviewedOriginalHash else {
            return rejected(request, "The target file changed after review.")
        }
        do {
            let temporary = file.deletingLastPathComponent()
                .appendingPathComponent(".\(request.requestID).tmp")
            try data.write(to: temporary, options: [.atomic])
            if fileManager.fileExists(atPath: file.path) {
                _ = try fileManager.replaceItemAt(file, withItemAt: temporary)
            } else {
                try fileManager.moveItem(at: temporary, to: file)
            }
            return LocalActionResult(
                requestID: request.requestID,
                gullHandle: request.gullHandle,
                status: .succeeded,
                completedAt: Self.timestamp()
            )
        } catch {
            return failure(request, error.localizedDescription)
        }
    }

    private func executeCommand(_ request: LocalActionRequest) async -> LocalActionResult {
        guard let executable = request.executable,
              executable.hasPrefix("/"),
              fileManager.isExecutableFile(atPath: executable),
              let workingDirectory = checkedDirectoryURL(request.workingDirectory) else {
            return rejected(request, "The executable or working directory is invalid.")
        }
        let execution = LocalProcessExecution(
            executable: executable,
            arguments: request.arguments ?? [],
            workingDirectory: workingDirectory,
            outputLimit: Self.maximumOutputBytes
        )
        runningExecution = execution
        let processTask = Task { await execution.start() }
        let timeoutTask = Task {
            try? await Task.sleep(for: Self.commandTimeout)
            if !Task.isCancelled { execution.terminate(reason: .timeout) }
        }
        let output = await processTask.value
        timeoutTask.cancel()

        let status: LocalActionResultStatus
        let message: String?
        switch output.reason {
        case .completed:
            status = output.exitCode == 0 ? .succeeded : .failed
            message = output.exitCode == 0 ? nil : "Command exited with code \(output.exitCode)."
        case .timeout:
            status = .failed
            message = "Command timed out after 60 seconds."
        case .cancelled:
            status = .cancelled
            message = "Command cancelled."
        case .launchFailure:
            status = .failed
            message = output.error ?? "Command could not be started."
        }
        return LocalActionResult(
            requestID: request.requestID,
            gullHandle: request.gullHandle,
            status: status,
            completedAt: Self.timestamp(),
            stdout: output.stdout,
            stderr: output.stderr,
            exitCode: output.exitCode,
            error: message ?? output.error
        )
    }

    @discardableResult
    private func persist(
        _ result: LocalActionResult,
        requestID: String,
        destinationDirectory: URL? = nil
    ) async -> Bool {
        do {
            let directory = destinationDirectory ?? resultsDirectory
            try createDirectories(actionsDirectory: directory.deletingLastPathComponent())
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            let destination = directory.appendingPathComponent("\(requestID).json")
            let data = try JSONEncoder().encode(result)
            try data.write(to: destination, options: [.atomic])
            try fileManager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path)
            let isCurrentOrigin = result.gullHandle == config.agentHandle
                && directory.standardizedFileURL == resultsDirectory.standardizedFileURL
            if isCurrentOrigin {
                pendingRequests.removeAll { $0.requestID == requestID }
                recentResults.removeAll { $0.requestID == requestID }
                recentResults.insert(result, at: 0)
                if recentResults.count > 50 { recentResults.removeLast(recentResults.count - 50) }
            }
            error = nil
            return true
        } catch {
            self.error = "Could not save local action result: \(error.localizedDescription)"
            return false
        }
    }

    private func recoverClaims() {
        guard let files = try? fileManager.contentsOfDirectory(
            at: requestsDirectory,
            includingPropertiesForKeys: nil
        ) else { return }
        for claim in files where claim.pathExtension == "claim" {
            let id = claim.deletingPathExtension().lastPathComponent
            if id == activeRequestID { continue }
            guard !resultExists(id) else {
                try? fileManager.removeItem(at: claim)
                continue
            }
            guard let request = readRequest(id) else { continue }
            guard request.gullHandle == config.agentHandle else { continue }
            let result = LocalActionResult(
                requestID: id,
                gullHandle: request.gullHandle,
                status: .failed,
                completedAt: Self.timestamp(),
                error: "The previous local action was interrupted and was not replayed."
            )
            do {
                try createDirectories(actionsDirectory: actionsDirectory)
                let data = try JSONEncoder().encode(result)
                try data.write(to: resultURL(id), options: [.atomic])
                try fileManager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: resultURL(id).path)
                if resultExists(id) { try? fileManager.removeItem(at: claim) }
            } catch {
                self.error = "Could not recover interrupted local action: \(error.localizedDescription)"
            }
        }
    }

    private func captureReviewMetadata(_ request: inout LocalActionRequest) {
        guard request.kind == .writeFile else { return }
        guard let file = checkedFileURL(request.path, allowMissing: true) else {
            request.reviewedOriginalExists = nil
            request.reviewedOriginalReadable = nil
            request.reviewedOriginalHash = nil
            request.reviewedOriginalContent = nil
            return
        }
        guard fileManager.fileExists(atPath: file.path) else {
            request.reviewedOriginalExists = false
            request.reviewedOriginalReadable = true
            request.reviewedOriginalHash = nil
            request.reviewedOriginalContent = nil
            return
        }
        request.reviewedOriginalExists = true
        guard let values = try? file.resourceValues(forKeys: [.fileSizeKey]),
              let size = values.fileSize,
              size <= Self.maximumFileBytes,
              let data = try? Data(contentsOf: file),
              data.count <= Self.maximumFileBytes,
              let content = String(data: data, encoding: .utf8) else {
            request.reviewedOriginalReadable = false
            request.reviewedOriginalHash = nil
            request.reviewedOriginalContent = nil
            return
        }
        request.reviewedOriginalReadable = true
        request.reviewedOriginalHash = digest(data)
        request.reviewedOriginalContent = content
    }

    private func readRequest(_ id: String) -> LocalActionRequest? {
        guard UUID(uuidString: id) != nil else { return nil }
        guard let values = try? requestURL(id).resourceValues(forKeys: [.fileSizeKey]),
              let size = values.fileSize,
              size <= Self.maximumRequestBytes else { return nil }
        guard let data = try? Data(contentsOf: requestURL(id)) else { return nil }
        return try? JSONDecoder().decode(LocalActionRequest.self, from: data)
    }

    private func loadResults() -> [LocalActionResult] {
        resultFiles().compactMap { url in
            guard let id = resultID(from: url),
                  let values = try? url.resourceValues(forKeys: [.fileSizeKey]),
                  let size = values.fileSize,
                  size <= Self.maximumResultBytes,
                  let data = try? Data(contentsOf: url),
                  let result = try? JSONDecoder().decode(LocalActionResult.self, from: data),
                  result.requestID == id,
                  result.gullHandle == config.agentHandle else {
                return nil
            }
            return result
        }
        .sorted { $0.completedAt > $1.completedAt }
        .prefix(50)
        .map { $0 }
    }

    private func requestFiles() -> [URL] {
        directoryFiles(requestsDirectory).filter { $0.pathExtension == "json" }
    }

    private func claimFiles() -> [URL] {
        directoryFiles(requestsDirectory).filter { $0.pathExtension == "claim" }
    }

    private func requestID(from url: URL) -> String? {
        let id = url.deletingPathExtension().lastPathComponent
        return UUID(uuidString: id) == nil ? nil : id
    }

    private func resultFiles() -> [URL] {
        directoryFiles(resultsDirectory).filter { $0.pathExtension == "json" }
    }

    private func directoryFiles(_ directory: URL) -> [URL] {
        (try? fileManager.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.fileSizeKey])) ?? []
    }

    private func createDirectories(actionsDirectory: URL) throws {
        let requests = actionsDirectory.appendingPathComponent("requests", isDirectory: true)
        let results = actionsDirectory.appendingPathComponent("results", isDirectory: true)
        try fileManager.createDirectory(at: actionsDirectory, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: requests, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: results, withIntermediateDirectories: true)
        try fileManager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: actionsDirectory.path)
        try fileManager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: requests.path)
        try fileManager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: results.path)
    }

    private func claim(at url: URL) -> Bool {
        let descriptor = Darwin.open(url.path, O_WRONLY | O_CREAT | O_EXCL, 0o600)
        guard descriptor >= 0 else { return false }
        Darwin.close(descriptor)
        return true
    }

    private func removeClaim(at url: URL) {
        try? fileManager.removeItem(at: url)
    }

    private func resultExists(_ id: String) -> Bool {
        fileManager.fileExists(atPath: resultURL(id).path)
    }

    private func requestURL(_ id: String) -> URL {
        requestsDirectory.appendingPathComponent("\(id).json")
    }

    private func resultURL(_ id: String) -> URL {
        resultsDirectory.appendingPathComponent("\(id).json")
    }

    private func claimURL(_ id: String) -> URL {
        requestsDirectory.appendingPathComponent("\(id).claim")
    }

    private func resultID(from url: URL) -> String? {
        let id = url.deletingPathExtension().lastPathComponent
        return UUID(uuidString: id) == nil ? nil : id
    }

    private func claimID(from url: URL) -> String? {
        let id = url.deletingPathExtension().lastPathComponent
        return UUID(uuidString: id) == nil ? nil : id
    }

    private func isValidShape(_ request: LocalActionRequest) -> Bool {
        switch request.kind {
        case .command:
            guard let executable = request.executable,
                  executable.hasPrefix("/"),
                  let directory = request.workingDirectory,
                  directory.hasPrefix("/") else { return false }
            return request.path == nil && request.content == nil
                && fileManager.isExecutableFile(atPath: executable)
        case .readFile:
            return request.path?.hasPrefix("/") == true
                && request.executable == nil
                && request.workingDirectory == nil
                && request.content == nil
        case .writeFile:
            return request.path?.hasPrefix("/") == true
                && request.content != nil
                && request.executable == nil
                && request.workingDirectory == nil
        }
    }

    private func checkedDirectoryURL(_ raw: String?) -> URL? {
        guard let raw, let url = absoluteURL(raw) else { return nil }
        let canonical = url.resolvingSymlinksInPath().standardizedFileURL
        guard fileManager.fileExists(atPath: canonical.path),
              isDirectory(canonical),
              isInsideAllowedFolder(canonical) else { return nil }
        return canonical
    }

    private func checkedFileURL(_ raw: String?, allowMissing: Bool) -> URL? {
        guard let raw, let url = absoluteURL(raw) else { return nil }
        let parent = url.deletingLastPathComponent().resolvingSymlinksInPath().standardizedFileURL
        guard fileManager.fileExists(atPath: parent.path),
              isDirectory(parent),
              isInsideAllowedFolder(parent) else { return nil }
        let canonical = parent.appendingPathComponent(url.lastPathComponent)
            .resolvingSymlinksInPath().standardizedFileURL
        if fileManager.fileExists(atPath: canonical.path) {
            guard isInsideAllowedFolder(canonical) else { return nil }
            guard !isDirectory(canonical) else { return nil }
        } else if !allowMissing {
            return nil
        }
        return canonical
    }

    private func canonicalDirectory(_ url: URL) -> URL? {
        let canonical = url.resolvingSymlinksInPath().standardizedFileURL
        guard fileManager.fileExists(atPath: canonical.path), isDirectory(canonical) else { return nil }
        return canonical
    }

    private func isInsideAllowedFolder(_ url: URL) -> Bool {
        let path = url.standardizedFileURL.path
        return allowedFolders.contains { root in
            let rootPath = URL(fileURLWithPath: expanded(root)).resolvingSymlinksInPath().standardizedFileURL.path
            return path == rootPath || path.hasPrefix(rootPath + "/")
        }
    }

    private func fileHash(for raw: String?) -> String? {
        guard let file = checkedFileURL(raw, allowMissing: false),
              let values = try? file.resourceValues(forKeys: [.fileSizeKey]),
              let size = values.fileSize,
              size <= Self.maximumFileBytes,
              let data = try? Data(contentsOf: file),
              data.count <= Self.maximumFileBytes else { return nil }
        return digest(data)
    }

    private func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func normalizedFolders(_ folders: [String]) -> [String] {
        var seen = Set<String>()
        return folders.compactMap { folder in
            guard let canonical = canonicalDirectory(URL(fileURLWithPath: expanded(folder))),
                  seen.insert(canonical.path).inserted else { return nil }
            return canonical.path
        }
    }

    private func absoluteURL(_ raw: String) -> URL? {
        let value = expanded(raw)
        guard value.hasPrefix("/") else { return nil }
        return URL(fileURLWithPath: value)
    }

    private func expanded(_ path: String) -> String {
        (path as NSString).expandingTildeInPath
    }

    private func isDirectory(_ url: URL) -> Bool {
        (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
    }

    private func requestIsEarlier(_ lhs: LocalActionRequest, _ rhs: LocalActionRequest) -> Bool {
        (GullsDates.parse(lhs.createdAt) ?? .distantFuture,
         lhs.requestID) < (GullsDates.parse(rhs.createdAt) ?? .distantFuture,
                           rhs.requestID)
    }

    private func failure(_ request: LocalActionRequest, _ message: String) -> LocalActionResult {
        LocalActionResult(
            requestID: request.requestID,
            gullHandle: request.gullHandle,
            status: .failed,
            completedAt: Self.timestamp(),
            error: message
        )
    }

    private func rejected(_ request: LocalActionRequest, _ message: String) -> LocalActionResult {
        LocalActionResult(
            requestID: request.requestID,
            gullHandle: request.gullHandle,
            status: .rejected,
            completedAt: Self.timestamp(),
            error: message
        )
    }

    private static func timestamp() -> String {
        ISO8601DateFormatter().string(from: Date())
    }

    private struct Keys {
        let enabled: String
        let allowedFolders: String

        init(profileID: String) {
            let prefix = "gull.profile.\(profileID).localControl."
            enabled = prefix + "enabled"
            allowedFolders = prefix + "allowedFolders"
        }
    }
}

private enum LocalProcessEndReason {
    case completed
    case timeout
    case cancelled
    case launchFailure
}

private struct LocalProcessOutput {
    let reason: LocalProcessEndReason
    let stdout: String?
    let stderr: String?
    let exitCode: Int32
    let error: String?
}

private final class LocalProcessExecution: @unchecked Sendable {
    private let process: Process
    private let stdoutPipe = Pipe()
    private let stderrPipe = Pipe()
    private let stdout: BoundedOutput
    private let stderr: BoundedOutput
    private let lock = NSLock()
    private var continuation: CheckedContinuation<LocalProcessOutput, Never>?
    private var endReason: LocalProcessEndReason?
    private var didFinish = false
    private var processGroupID: pid_t?

    init(executable: String, arguments: [String], workingDirectory: URL, outputLimit: Int) {
        process = Process()
        stdout = BoundedOutput(limit: outputLimit)
        stderr = BoundedOutput(limit: outputLimit)
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.currentDirectoryURL = workingDirectory
        process.environment = [
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": NSHomeDirectory(),
            "LANG": "en_US.UTF-8"
        ]
    }

    func start() async -> LocalProcessOutput {
        await withTaskCancellationHandler(operation: {
            await withCheckedContinuation { continuation in
                stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                    self?.stdout.append(handle.availableData)
                }
                stderrPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                    self?.stderr.append(handle.availableData)
                }
                process.standardOutput = stdoutPipe
                process.standardError = stderrPipe
                process.standardInput = FileHandle.nullDevice
                process.terminationHandler = { [weak self] process in
                    self?.finish(exitCode: process.terminationStatus, error: nil)
                }

                lock.lock()
                self.continuation = continuation
                if endReason != nil {
                    lock.unlock()
                    finish(exitCode: -1, error: "Command cancelled.")
                    return
                }
                do {
                    try process.run()
                    let pid = process.processIdentifier
                    if pid > 0, Darwin.getpgid(pid) == pid { processGroupID = pid }
                    lock.unlock()
                } catch {
                    lock.unlock()
                    finish(exitCode: -1, error: error.localizedDescription, reason: .launchFailure)
                }
            }
        }, onCancel: {
            terminate(reason: .cancelled)
        })
    }

    func terminate(reason: LocalProcessEndReason, immediately: Bool = false) {
        lock.lock()
        if endReason == nil { endReason = reason }
        let running = process.isRunning
        let pid = process.processIdentifier
        let groupID = processGroupID
        lock.unlock()
        // App termination cannot depend on a delayed escalation task: it may
        // exit before that task runs. Kill only the group this command owns.
        if immediately {
            if let groupID { _ = Darwin.kill(-groupID, SIGKILL) }
            else if running, pid > 0 { _ = Darwin.kill(pid, SIGKILL) }
            return
        }
        guard running else { return }
        if let groupID {
            _ = Darwin.kill(-groupID, SIGTERM)
        } else {
            process.terminate()
        }
        Task.detached {
            try? await Task.sleep(for: .milliseconds(250))
            // The direct child may already have exited while descendants
            // still hold its output pipes. Cancel the owned group as well.
            if let groupID { _ = Darwin.kill(-groupID, SIGKILL); return }
            let stillRunning = self.lock.withLock { !self.didFinish && self.process.isRunning }
            if stillRunning, pid > 0 { _ = Darwin.kill(pid, SIGKILL) }
        }
    }

    private func finish(
        exitCode: Int32,
        error: String?,
        reason: LocalProcessEndReason? = nil
    ) {
        lock.lock()
        guard !didFinish else {
            lock.unlock()
            return
        }
        didFinish = true
        if let reason { endReason = reason }
        let finalReason = endReason ?? .completed
        let continuation = self.continuation
        self.continuation = nil
        lock.unlock()

        stdoutPipe.fileHandleForReading.readabilityHandler = nil
        stderrPipe.fileHandleForReading.readabilityHandler = nil
        drain(stdoutPipe.fileHandleForReading, into: stdout)
        drain(stderrPipe.fileHandleForReading, into: stderr)
        let output = LocalProcessOutput(
            reason: finalReason,
            stdout: stdout.string,
            stderr: stderr.string,
            exitCode: exitCode,
            error: error
        )
        continuation?.resume(returning: output)
    }

    private func drain(_ handle: FileHandle, into output: BoundedOutput) {
        let descriptor = handle.fileDescriptor
        let flags = Darwin.fcntl(descriptor, F_GETFL)
        if flags >= 0 { _ = Darwin.fcntl(descriptor, F_SETFL, flags | O_NONBLOCK) }
        var buffer = [UInt8](repeating: 0, count: 4096)
        while true {
            let count = buffer.withUnsafeMutableBytes { bytes in
                Darwin.read(descriptor, bytes.baseAddress, bytes.count)
            }
            if count > 0 {
                output.append(Data(buffer[0..<count]))
            } else {
                return
            }
        }
    }
}

private final class BoundedOutput: @unchecked Sendable {
    private let limit: Int
    private let lock = NSLock()
    private var data = Data()

    init(limit: Int) { self.limit = limit }

    func append(_ chunk: Data) {
        guard !chunk.isEmpty else { return }
        lock.lock()
        defer { lock.unlock() }
        guard data.count < limit else { return }
        data.append(chunk.prefix(limit - data.count))
    }

    var string: String? {
        lock.lock()
        defer { lock.unlock() }
        guard !data.isEmpty else { return nil }
        return String(data: data, encoding: .utf8) ?? String(decoding: data, as: UTF8.self)
    }
}
