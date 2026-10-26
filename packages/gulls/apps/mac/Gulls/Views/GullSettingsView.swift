import SwiftUI

struct GullSettingsView: View {
    @Bindable var account: CloudAccountStore
    var workspace: GullsWorkspace?
    var onPair: ((CloudAgentProfile) -> Void)?

    @State private var selectedID: String?
    @State private var displayName = ""
    @State private var bio = ""
    @State private var prompt = ""
    @State private var promptLoaded = false
    @State private var savedDisplayName = ""
    @State private var savedBio = ""
    @State private var savedPrompt = ""
    @State private var pendingSelectionID: String?
    @State private var pendingPairGullID: String?
    @State private var status: String?
    @State private var statusIsError = false
    @State private var isSaving = false
    @State private var debounceTask: Task<Void, Never>?
    @State private var saveQueued = false
    @State private var editRevision = 0
    @State private var saveState: SaveState = .idle
    @State private var runtimeModes: [String: CloudRuntimeMode] = [:]
    @State private var runtimeLoading: Set<String> = []
    @State private var runtimeSaving: Set<String> = []
    @State private var loadID = UUID()
    @State private var isLoading = false

    private enum SaveState {
        case idle
        case saving
        case saved
        case failed(String)
    }

    init(
        account: CloudAccountStore,
        workspace: GullsWorkspace? = nil,
        onPair: ((CloudAgentProfile) -> Void)? = nil
    ) {
        self.account = account
        self.workspace = workspace
        self.onPair = onPair
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            CloudSettingsSection("Your Gulls", detail: "Profile, private reply instructions, and runtime mode.") {
                if account.ownedGulls.isEmpty {
                    if isLoading {
                        ProgressView("Loading your Gulls…")
                    } else {
                        if let status, statusIsError {
                            CloudSettingsStatus(message: status, isError: true)
                        } else {
                            Text("No Gull profiles yet.").foregroundStyle(.secondary)
                        }
                        Button("Refresh") { Task { await refresh() } }
                    }
                } else {
                    HStack(spacing: 12) {
                        Picker("Gull", selection: Binding(
                            get: { selectedID ?? account.ownedGulls.first?.id ?? "" },
                            set: { value in requestSelect(value) }
                        )) {
                            ForEach(account.ownedGulls) { gull in
                                Text(gull.displayName ?? gull.handle).tag(gull.id)
                            }
                        }
                        .labelsHidden()
                        .frame(maxWidth: 260, alignment: .leading)
                        .disabled(isSaving || selectedID.map { runtimeSaving.contains($0) } == true)
                        .task(id: account.sessionID) { select(selectedID ?? account.ownedGulls.first?.id, force: true) }
                        Spacer(minLength: 0)
                        saveIndicator
                    }

                    if let gull = selectedGull {
                        gullEditor(gull)
                    }
                }
            }
        }
        .padding(24)
        .task(id: account.sessionID) { await refresh() }
        .onChange(of: displayName) { _, _ in scheduleAutosaveIfNeeded() }
        .onChange(of: bio) { _, _ in scheduleAutosaveIfNeeded() }
        .onChange(of: prompt) { _, _ in scheduleAutosaveIfNeeded() }
        .onDisappear { flushAutosave() }
    }

    private var selectedGull: CloudAgentProfile? {
        guard let selectedID else { return nil }
        return account.ownedGulls.first { $0.id == selectedID }
    }

    private var hasUnsavedChanges: Bool {
        promptLoaded && (displayName != savedDisplayName || bio != savedBio || prompt != savedPrompt)
    }

    private func requestSelect(_ id: String?) {
        guard id != selectedID, hasUnsavedChanges else {
            select(id)
            return
        }
        pendingSelectionID = id
        flushAutosave()
    }

    private func select(_ id: String?, force: Bool = false) {
        guard force || !hasUnsavedChanges else { return }
        debounceTask?.cancel()
        debounceTask = nil
        saveQueued = false
        pendingSelectionID = nil
        pendingPairGullID = nil
        saveState = .idle
        loadID = UUID()
        selectedID = id
        displayName = ""
        bio = ""
        savedDisplayName = ""
        savedBio = ""
        prompt = ""
        savedPrompt = ""
        promptLoaded = false
        runtimeLoading.removeAll()
        guard let gull = account.ownedGulls.first(where: { $0.id == id }) else { return }
        displayName = gull.displayName ?? ""
        bio = gull.bio ?? ""
        savedDisplayName = displayName
        savedBio = bio
        runtimeModes[gull.id] = nil
        runtimeLoading.insert(gull.id)
        status = nil
        let selectedAgentID = gull.id
        let requestID = loadID
        let sessionID = account.sessionID
        Task { @MainActor in
            do {
                let instructions = try await account.loadPrompt(for: gull)
                guard selectedID == selectedAgentID, loadID == requestID, account.sessionID == sessionID else { return }
                prompt = instructions
                savedPrompt = instructions
                promptLoaded = true
                let runtime = try await account.loadRuntime(for: gull)
                guard selectedID == selectedAgentID, loadID == requestID, account.sessionID == sessionID else { return }
                runtimeModes[selectedAgentID] = runtime.mode
                runtimeLoading.remove(selectedAgentID)
            } catch {
                guard selectedID == selectedAgentID, loadID == requestID, account.sessionID == sessionID else { return }
                runtimeLoading.remove(selectedAgentID)
                status = error.localizedDescription
                statusIsError = true
            }
        }
    }

    @ViewBuilder
    private func gullEditor(_ gull: CloudAgentProfile) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Profile")
                .font(.subheadline.weight(.semibold))
                .padding(.top, 6)
            CloudSettingsRow("Handle", detail: gull.handle) {
                Text(gull.statusLabel)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
            }

            CloudSettingsRow("Display name") {
                TextField("Optional", text: $displayName)
                    .accessibilityLabel("Display name")
                    .cloudSettingsField()
                    .frame(maxWidth: 300)
                    .disabled(!promptLoaded || runtimeSaving.contains(gull.id))
            }
            CloudSettingsRow("Bio") {
                TextField("Optional", text: $bio)
                    .accessibilityLabel("Bio")
                    .cloudSettingsField()
                    .frame(maxWidth: 300)
                    .disabled(!promptLoaded || runtimeSaving.contains(gull.id))
            }
            Text("Private reply instructions")
                .font(.subheadline.weight(.semibold))
                .padding(.top, 6)
            VStack(alignment: .leading, spacing: 7) {
                Text("Only this Gull uses these instructions. They apply to its next reply.")
                    .font(.caption).foregroundStyle(.secondary)
                TextEditor(text: $prompt)
                    .accessibilityLabel("Private reply instructions")
                    .font(.body)
                    .frame(minHeight: 90, maxHeight: 140)
                    .scrollContentBackground(.hidden)
                    .scrollIndicators(.never)
                    .padding(8)
                    .gullsGlass(cornerRadius: 11)
                    .overlay {
                        RoundedRectangle(cornerRadius: 11)
                            .strokeBorder(Color.primary.opacity(0.12), lineWidth: 0.75)
                    }
                    .disabled(!promptLoaded || runtimeSaving.contains(gull.id))
            }

            Text("Reply mode")
                .font(.subheadline.weight(.semibold))
                .padding(.top, 6)
            CloudSettingsRow("Reply runtime", detail: runtimeLoading.contains(gull.id) ? "Checking…" : "Changes apply immediately · " + (runtimeModes[gull.id].map(runtimeDescription) ?? "Unavailable")) {
                Picker("Reply runtime", selection: Binding<CloudRuntimeMode?>(
                    get: { runtimeModes[gull.id] },
                    set: { value in
                        guard let value else { return }
                        Task { await saveRuntime(gull, mode: value) }
                    }
                )) {
                    if runtimeModes[gull.id] == nil {
                        Text(runtimeLoading.contains(gull.id) ? "Checking…" : "Unavailable")
                            .tag(CloudRuntimeMode?.none)
                    }
                    ForEach(CloudRuntimeMode.allCases, id: \.self) { mode in
                        Text(mode.label).tag(Optional(mode))
                    }
                }
                .labelsHidden()
                .frame(width: 180)
                .disabled(isSaving || runtimeLoading.contains(gull.id) || runtimeSaving.contains(gull.id) || runtimeModes[gull.id] == nil)
            }
            if let local = localConfig(for: gull), let tasks = workspace?.codexTasks[local.profileID] {
                Text("On this Mac")
                    .font(.subheadline.weight(.semibold))
                    .padding(.top, 6)
                CloudSettingsRow(
                    "Send replies automatically",
                    detail: local.sendRepliesAutomatically
                        ? "Replies submitted by this Gull's agent are sent automatically."
                        : "Delegated replies wait for your approval before sending."
                ) {
                    Toggle("Send replies automatically", isOn: Binding(
                        get: { local.sendRepliesAutomatically },
                        set: { value in
                            do {
                                try tasks.setSendRepliesAutomatically(value)
                            } catch {
                                status = error.localizedDescription
                                statusIsError = true
                            }
                        }
                    ))
                    .labelsHidden()
                }
                Text("Applies to work handed to this Gull on this Mac. Existing replies waiting for review stay in review.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if onPair != nil {
                Button("Pair this Mac") { requestPair(gull) }
                    .buttonStyle(.bordered)
                    .disabled(isSaving || runtimeSaving.contains(gull.id))
                    .help(hasUnsavedChanges ? "Finish saving Gull changes before pairing this Mac" : "Pair this Gull with the Mac")
            }
            if let status {
                CloudSettingsStatus(message: status, isError: statusIsError)
            }
        }
    }

    private func localConfig(for gull: CloudAgentProfile) -> GullsConfig? {
        guard let socialURL = account.runtime?.socialAPIURL,
              let server = try? CodexWorkRecord.normalizedAPIURL(socialURL) else { return nil }
        return workspace?.connections.profiles.first { config in
            guard config.isLocallyPaired,
                  (try? CodexWorkRecord.normalizedAPIURL(config.socialAPIURL)) == server else { return false }
            return config.agentHandle.caseInsensitiveCompare(gull.handle) == .orderedSame
                || config.agentHandle.caseInsensitiveCompare("@\(gull.handle)") == .orderedSame
        }
    }

    @ViewBuilder
    private var saveIndicator: some View {
        switch saveState {
        case .idle:
            EmptyView()
        case .saving:
            HStack(spacing: 7) {
                ProgressView().controlSize(.small)
                Text("Saving…")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        case .saved:
            Label("Saved", systemImage: "checkmark")
                .font(.caption)
                .foregroundStyle(.secondary)
        case .failed(let message):
            HStack(spacing: 8) {
                CloudSettingsStatus(message: message, isError: true)
                Button("Retry") { flushAutosave() }
                    .buttonStyle(.borderless)
                    .font(.caption.weight(.medium))
            }
        }
    }

    private func scheduleAutosaveIfNeeded() {
        guard promptLoaded, selectedGull != nil else { return }
        guard hasUnsavedChanges || isSaving || saveQueued else { return }
        editRevision += 1
        saveQueued = true
        if !isSaving { saveState = .idle }
        debounceTask?.cancel()
        debounceTask = Task { @MainActor in
            do {
                try await Task.sleep(for: .milliseconds(750))
            } catch {
                return
            }
            startQueuedSaveIfNeeded()
        }
    }

    private func flushAutosave() {
        guard promptLoaded, selectedGull != nil else { return }
        guard hasUnsavedChanges || saveQueued else { return }
        saveQueued = true
        debounceTask?.cancel()
        startQueuedSaveIfNeeded()
    }

    private func enqueueAutosave() {
        debounceTask?.cancel()
        debounceTask = Task { @MainActor in
            do {
                try await Task.sleep(for: .milliseconds(200))
            } catch {
                return
            }
            startQueuedSaveIfNeeded()
        }
    }

    private func startQueuedSaveIfNeeded() {
        guard !isSaving, saveQueued, promptLoaded, let gull = selectedGull else { return }
        saveQueued = false
        let revision = editRevision
        let nameToSave = displayName
        let bioToSave = bio
        let promptToSave = prompt
        let sessionID = account.sessionID
        isSaving = true
        saveState = .saving
        Task { @MainActor in
            await saveDraft(
                for: gull,
                name: nameToSave,
                bio: bioToSave,
                prompt: promptToSave,
                revision: revision,
                sessionID: sessionID
            )
        }
    }

    private func saveDraft(
        for gull: CloudAgentProfile,
        name: String,
        bio: String,
        prompt: String,
        revision: Int,
        sessionID: UUID
    ) async {
        guard selectedID == gull.id, promptLoaded, account.sessionID == sessionID, account.isSignedIn else {
            isSaving = false
            return
        }
        do {
            try await account.updateGull(gull, displayName: name, bio: bio)
            guard account.sessionID == sessionID, account.isSignedIn else {
                isSaving = false
                return
            }
            try await account.savePrompt(for: gull, instructions: prompt)
        } catch {
            isSaving = false
            guard selectedID == gull.id, account.sessionID == sessionID else { return }
            if revision != editRevision {
                saveQueued = true
                enqueueAutosave()
            } else {
                saveState = .failed(error.localizedDescription)
            }
            return
        }
        isSaving = false
        guard selectedID == gull.id, account.sessionID == sessionID else { return }
        if editRevision == revision {
            savedDisplayName = name
            savedBio = bio
            savedPrompt = prompt
            saveState = .saved
            if let pendingSelectionID {
                self.pendingSelectionID = nil
                select(pendingSelectionID, force: true)
            } else if pendingPairGullID == gull.id {
                pendingPairGullID = nil
                onPair?(gull)
            }
        } else {
            saveQueued = true
            enqueueAutosave()
        }
    }

    private func requestPair(_ gull: CloudAgentProfile) {
        guard let onPair else { return }
        guard hasUnsavedChanges else {
            onPair(gull)
            return
        }
        pendingPairGullID = gull.id
        flushAutosave()
    }

    private func saveRuntime(_ gull: CloudAgentProfile, mode: CloudRuntimeMode) async {
        guard !runtimeSaving.contains(gull.id), !isSaving else { return }
        runtimeSaving.insert(gull.id)
        defer { runtimeSaving.remove(gull.id) }
        do {
            let runtime = try await account.setRuntime(for: gull, mode: mode)
            runtimeModes[gull.id] = runtime.mode
            status = "Reply runtime updated"
            statusIsError = false
        } catch {
            status = error.localizedDescription
            statusIsError = true
        }
    }

    private func runtimeDescription(_ mode: CloudRuntimeMode) -> String {
        switch mode {
        case .cloud: return "Hosted AI"
        case .local: return "Paired computer"
        case .manual: return "Automatic replies paused"
        }
    }

    private func refresh() async {
        isLoading = true
        defer { isLoading = false }
        let refreshed = await account.refreshGulls()
        if refreshed {
            status = nil
            statusIsError = false
        } else {
            status = account.ownedGulls.isEmpty
                ? (account.error ?? "Could not load your Gull profiles.")
                : "Could not refresh Gull profiles. Showing the last saved list."
            statusIsError = true
        }
        let availableIDs = Set(account.ownedGulls.map(\.id))
        if let selectedID, !availableIDs.contains(selectedID) {
            select(account.ownedGulls.first?.id, force: true)
        } else if self.selectedID == nil, let firstID = account.ownedGulls.first?.id {
            select(firstID, force: true)
        }
    }
}
