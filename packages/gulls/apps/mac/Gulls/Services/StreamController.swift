import Foundation

// Owns the long-lived `gulls --json stream` subprocess: start/stop, restart
// with backoff on unexpected exits, and NDJSON event handling. Push events
// are wake-up signals only — the owner re-fetches the inbox on `onWake`
// (push = wake-up, poll = truth).
//
// Exit-code semantics: a configuration-fatal exit (CLI exit code 2 — bad
// URL, token, or scope) or a launch failure moves the controller to .failed
// and stops it, instead of respawning a subprocess that can never succeed.
// Runtime exits keep the old behavior: backoff 5s → 60s and retry.
@MainActor
final class StreamController {

    enum State: Equatable {
        case off            // not started / stopped / no stream URL configured
        case connecting
        case connected
        case down           // unexpected exit; reconnecting with backoff
        case failed(String) // configuration-fatal; not retrying
    }

    private(set) var state: State = .off {
        didSet {
            if state != oldValue {
                onStateChange?(state)
            }
        }
    }

    var onStateChange: ((State) -> Void)?
    var onWake: (() async -> Void)?
    var onError: ((String) -> Void)?

    private var task: Task<Void, Never>?
    private var terminateProcess: (@Sendable () -> Void)?

    func start(cli: GullsCLI, environment: @escaping () -> GullsCLI.Environment) {
        guard task == nil else { return }
        state = .connecting
        task = Task { [weak self] in
            var backoff: Double = 5
            while !Task.isCancelled {
                guard let self else { return }
                do {
                    let handle = try await cli.openStream(environment: environment())
                    self.terminateProcess = handle.terminate
                    for try await line in handle.lines {
                        if Task.isCancelled { break }
                        await self.handleLine(line)
                        backoff = 5
                    }
                } catch let failure as GullsCLI.Failure {
                    switch failure {
                    case .configuration, .launch:
                        self.terminateProcess = nil
                        self.state = .failed(failure.localizedDescription)
                        self.onError?(failure.localizedDescription)
                        // The cause is recoverable from Settings, so release
                        // `task`: start()'s `task == nil` guard would otherwise
                        // refuse every later restart until the app relaunches.
                        // The cancellation paths below already return with
                        // stop() having cleared it.
                        self.task = nil
                        return
                    default:
                        self.onError?(failure.localizedDescription)
                    }
                } catch {
                    self.onError?(error.localizedDescription)
                }
                self.terminateProcess = nil
                if Task.isCancelled { return }
                // Subprocess exit is unexpected (it reconnects internally);
                // restart it with backoff.
                self.state = .down
                try? await Task.sleep(for: .seconds(backoff))
                backoff = min(backoff * 2, 60)
                if Task.isCancelled { return }
                self.state = .connecting
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
        terminateProcess?()
        terminateProcess = nil
        state = .off
    }

    private func handleLine(_ line: Data) async {
        guard let parsed = try? JSONDecoder().decode(StreamLine.self, from: line) else { return }
        switch parsed.type {
        case "stream.connected":
            state = .connected
            // Reconnect catch-up: one wake covers anything missed while down.
            await onWake?()
        case "stream.event":
            await onWake?()
        case "stream.disconnected":
            state = .connecting
        default:
            break
        }
    }
}
