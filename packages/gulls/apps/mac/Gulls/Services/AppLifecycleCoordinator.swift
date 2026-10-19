import AppKit
import Foundation
import Observation

/// Owns work that must continue while the workspace window is closed.
/// There is one coordinator per app, so all Gull profiles share one lifecycle.
@MainActor
@Observable
final class AppLifecycleCoordinator {
    let workspace: GullsWorkspace
    let account: CloudAccountStore
    let isTestHost: Bool

    @ObservationIgnored private var configurationTask: Task<Void, Never>?
    @ObservationIgnored private var localRefreshTask: Task<Void, Never>?
    @ObservationIgnored private var accountSyncTask: Task<Void, Never>?
    @ObservationIgnored private var lifecycleGeneration = UUID()
    @ObservationIgnored private var workspaceObservers: [NSObjectProtocol] = []
    private(set) var isRunning = false

    init(workspace: GullsWorkspace, account: CloudAccountStore, isTestHost: Bool = false) {
        self.workspace = workspace
        self.account = account
        self.isTestHost = isTestHost
    }

    func start() {
        guard !isRunning else { return }
        isRunning = true
        lifecycleGeneration = UUID()
        guard !isTestHost else { return }
        installWorkspaceObservers()

        Task { @MainActor [weak self] in
            guard let self, self.isRunning else { return }
            self.observeConfiguration()
            await self.workspace.reconcile()
        }

        localRefreshTask = Task { @MainActor [weak self] in
            while let self, self.isRunning, !Task.isCancelled {
                self.workspace.refreshLocalActions()
                try? await Task.sleep(for: .seconds(2))
            }
        }

        accountSyncTask = Task { @MainActor [weak self] in
            while let self, self.isRunning, !Task.isCancelled {
                await self.account.synchronizeSharedSession()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    /// Stops app-owned work and asks the shared CLI actor to terminate its
    /// long-lived runtime. The CLI stop is intentionally awaited by callers.
    func stop() async {
        guard isRunning else { return }
        prepareToStop()
        workspace.stopAll()
        await workspace.cli?.stopRuntime()
    }

    /// Synchronous bounded shutdown used by `willTerminate`. Waiting here is
    /// safe because the CLI bridge is an independent actor, not MainActor.
    func stopForTermination(timeout: Duration = .seconds(2)) {
        guard isRunning else { return }
        prepareToStop()
        workspace.stopAll(forTermination: true)
        guard let cli = workspace.cli else { return }
        let finished = DispatchSemaphore(value: 0)
        Task.detached(priority: .userInitiated) {
            await cli.stopRuntime()
            finished.signal()
        }
        let seconds = max(0, timeout.components.seconds)
        let attoseconds = max(0, timeout.components.attoseconds)
        let interval = DispatchTimeInterval.nanoseconds(
            Int(min(Int64.max, seconds * 1_000_000_000 + attoseconds / 1_000_000_000))
        )
        _ = finished.wait(timeout: .now() + interval)
    }

    private func prepareToStop() {
        isRunning = false
        lifecycleGeneration = UUID()
        configurationTask?.cancel()
        localRefreshTask?.cancel()
        accountSyncTask?.cancel()
        configurationTask = nil
        localRefreshTask = nil
        accountSyncTask = nil
        for observer in workspaceObservers {
            NSWorkspace.shared.notificationCenter.removeObserver(observer)
        }
        workspaceObservers.removeAll()
    }

    private func observeConfiguration() {
        guard isRunning, !isTestHost else { return }
        let generation = lifecycleGeneration
        withObservationTracking({ [workspace] in
            _ = workspace.configurationKey
        }, onChange: { [weak self] in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.configurationTask?.cancel()
                self.configurationTask = Task { @MainActor [weak self] in
                    guard let self, self.isRunning, self.lifecycleGeneration == generation else { return }
                    // Re-arm before the debounce so changes made during the
                    // debounce or reconcile schedule another pass.
                    self.observeConfiguration()
                    try? await Task.sleep(for: .milliseconds(300))
                    guard self.isRunning, self.lifecycleGeneration == generation, !Task.isCancelled else { return }
                    await self.workspace.reconcile()
                }
            }
        })
    }

    private func installWorkspaceObservers() {
        let center = NSWorkspace.shared.notificationCenter
        workspaceObservers.append(center.addObserver(
            forName: NSWorkspace.willSleepNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.isRunning else { return }
                self.workspace.stopAll()
            }
        })
        workspaceObservers.append(center.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.isRunning else { return }
                await self.workspace.reconcile()
                self.workspace.refreshLocalActions()
            }
        })
    }
}
