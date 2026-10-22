import SwiftUI

struct GullsView: View {
    @Environment(MobileAppStore.self) private var store
    @State private var searchText = ""
    @State private var selectedOwned: CloudGull?
    @State private var selectedSaved: SavedGull?
    @State private var showingAdd = false

    private var owned: [CloudGull] { filter(store.ownedGulls) }
    private var saved: [SavedGull] {
        guard !searchText.isEmpty else { return store.savedGulls }
        return store.savedGulls.filter { $0.displayName.localizedCaseInsensitiveContains(searchText) || $0.handle.localizedCaseInsensitiveContains(searchText) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                section("My Gulls", empty: "Your cloud Gulls will appear here.") {
                    ForEach(owned) { gull in
                        Button { selectedOwned = gull } label: { OwnedGullRow(gull: gull) }.buttonStyle(.plain)
                    }
                }
                section("Other Gulls", empty: "Save a Gull by handle to keep it here.") {
                    ForEach(saved) { gull in
                        Button { selectedSaved = gull } label: { SavedGullRow(gull: gull) }.buttonStyle(.plain)
                    }
                }
            }
            .padding(.horizontal, 20).padding(.vertical, 16)
        }
        .background(GullsTheme.background)
        .navigationTitle("Gulls.").navigationBarTitleDisplayMode(.large)
        .searchable(text: $searchText, prompt: "Search Gulls")
        .toolbar {
            GullsNavigationTitle("Gulls")
            ToolbarItem(placement: .topBarTrailing) {
                Button { showingAdd = true } label: { Image(systemName: "plus") }.accessibilityLabel("Save a Gull")
            }
        }
        .sheet(item: $selectedOwned) { OwnedGullDetail(gull: $0) }
        .sheet(item: $selectedSaved) { SavedGullDetail(gull: $0).presentationDetents([.medium, .large]) }
        .sheet(isPresented: $showingAdd) { AddGullView().presentationDetents([.medium, .large]) }
        .task {
            _ = await store.refreshGulls()
        }
        .refreshable { _ = await store.refreshGulls() }
    }

    @ViewBuilder
    private func section<Content: View>(_ title: String, empty: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            GullsPageTitle(title).font(.title3.weight(.semibold))
            VStack(spacing: 0) {
                if (title == "My Gulls" ? owned.isEmpty : saved.isEmpty) {
                    Text(empty).font(.subheadline).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading).padding(18)
                } else { content() }
            }
            .background(GullsTheme.surface, in: .rect(cornerRadius: 22))
        }
    }

    private func filter(_ gulls: [CloudGull]) -> [CloudGull] {
        guard !searchText.isEmpty else { return gulls }
        return gulls.filter { ($0.displayName ?? $0.handle).localizedCaseInsensitiveContains(searchText) || $0.handle.localizedCaseInsensitiveContains(searchText) }
    }
}

private struct OwnedGullRow: View {
    let gull: CloudGull
    var body: some View {
        HStack(spacing: 14) {
            GullAvatar(handle: gull.handle, size: 46)
            VStack(alignment: .leading, spacing: 4) {
                Text(gull.displayName?.isEmpty == false ? gull.displayName! : gull.handle).font(.body.weight(.semibold)).foregroundStyle(.primary)
                Text(gull.handle).font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer(); Image(systemName: "chevron.right").foregroundStyle(.tertiary)
        }.padding(16).contentShape(Rectangle())
    }
}

private struct SavedGullRow: View {
    let gull: SavedGull
    var body: some View {
        HStack(spacing: 14) {
            GullAvatar(handle: gull.handle, size: 46)
            VStack(alignment: .leading, spacing: 4) {
                Text(gull.displayName).font(.body.weight(.semibold)).foregroundStyle(.primary)
                Text(gull.handle).font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer(); Image(systemName: "bookmark.fill").foregroundStyle(GullsTheme.accent)
        }.padding(16).contentShape(Rectangle())
    }
}

private struct OwnedGullDetail: View {
    @Environment(MobileAppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let gull: CloudGull
    @State private var displayName: String
    @State private var bio: String
    @State private var prompt = ""
    @State private var selectedMode: CloudRuntimeMode = .cloud
    @State private var isLoading = true
    @State private var saveState: GullSaveState = .idle
    @State private var loadError: String?
    @State private var saveTask: Task<Void, Never>?
    @State private var isSavingRequest = false
    @State private var isFinishing = false
    @State private var runtimeSelectionWasEdited = false
    @State private var loadedPrompt = false
    @State private var loadedName: String
    @State private var loadedBio: String
    @State private var loadedPromptText = ""
    @State private var loadedMode: CloudRuntimeMode = .cloud

    init(gull: CloudGull) {
        self.gull = gull
        _displayName = State(initialValue: gull.displayName ?? "")
        _bio = State(initialValue: gull.bio ?? "")
        _loadedName = State(initialValue: gull.displayName ?? "")
        _loadedBio = State(initialValue: gull.bio ?? "")
    }

    private var hasChanges: Bool {
        loadedPrompt && (displayName != loadedName || bio != loadedBio || prompt != loadedPromptText || (runtimeSelectionWasEdited && selectedMode != loadedMode))
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    HStack(spacing: 14) {
                        GullAvatar(handle: gull.handle, size: 68)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(gull.displayName?.isEmpty == false ? gull.displayName! : gull.handle).font(.title2.weight(.semibold))
                            Text(gull.handle).font(.subheadline).foregroundStyle(.secondary)
                        }
                    }
                    if let loadError { ErrorCard(message: loadError) { Task { await load() } } }
                    VStack(alignment: .leading, spacing: 14) {
                        Text("Profile").font(.headline)
                        TextField("Display name", text: $displayName).textFieldStyle(.plain).padding(12).background(GullsTheme.incoming, in: .rect(cornerRadius: 12)).disabled(isLoading || isFinishing)
                        TextField("Bio", text: $bio, axis: .vertical).lineLimit(2...4).textFieldStyle(.plain).padding(12).background(GullsTheme.incoming, in: .rect(cornerRadius: 12)).disabled(isLoading || isFinishing)
                    }
                    .padding(18)
                    .background(GullsTheme.surface, in: .rect(cornerRadius: 20))
                    VStack(alignment: .leading, spacing: 14) {
                        Text("Private reply instructions").font(.headline)
                        Text("These private instructions guide this Gull's cloud AI replies.").font(.subheadline).foregroundStyle(.secondary)
                        TextEditor(text: $prompt).frame(minHeight: 140).padding(8).scrollContentBackground(.hidden).background(GullsTheme.surface, in: .rect(cornerRadius: 14)).overlay(alignment: .topLeading) { if prompt.isEmpty { Text("Private prompt").foregroundStyle(.tertiary).padding(16).allowsHitTesting(false) } }.disabled(isLoading || isFinishing)
                        Picker("Reply mode", selection: $selectedMode) {
                            if selectedMode == .local { Text("On Mac").tag(CloudRuntimeMode.local) }
                            Text("Cloud").tag(CloudRuntimeMode.cloud)
                            Text("Manual").tag(CloudRuntimeMode.manual)
                        }.pickerStyle(.segmented).disabled(isLoading || isFinishing)
                        if !isLoading, loadedMode == .local {
                            Label("Local on Mac", systemImage: "desktopcomputer")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text("This Gull is currently running locally on your Mac. Choosing Cloud or Manual here will change its cloud setting.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        saveStatus
                    }
                    .padding(18)
                    .background(GullsTheme.surface, in: .rect(cornerRadius: 20))
                }.padding(20)
            }
            .navigationTitle("Your Gull").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { saveTask?.cancel(); Task { await flushAndDismiss() } }.disabled(isLoading || isSavingRequest || isFinishing) } }
        }
        .gullsSheet()
        .task { await load() }
        .interactiveDismissDisabled(hasChanges || isSavingRequest || isFinishing)
        .onChange(of: displayName) { _, _ in scheduleSave() }
        .onChange(of: bio) { _, _ in scheduleSave() }
        .onChange(of: prompt) { _, _ in scheduleSave() }
        .onChange(of: selectedMode) { _, _ in
            guard loadedPrompt else { return }
            runtimeSelectionWasEdited = true
            scheduleSave()
        }
    }

    @ViewBuilder private var saveStatus: some View {
        switch saveState {
        case .idle: EmptyView()
        case .saving: Label("Saving…", systemImage: "arrow.triangle.2.circlepath").foregroundStyle(.secondary)
        case .saved: Label("Saved", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
        case .failed(let message):
            ErrorCard(message: message) { Task { await save() } }
            Button("Discard unsaved changes", role: .destructive) {
                saveTask?.cancel()
                dismiss()
            }
            .disabled(isSavingRequest || isFinishing)
        }
    }

    private func load() async {
        isLoading = true; loadError = nil
        do {
            async let promptValue = store.loadPrompt(for: gull)
            async let runtimeValue = store.loadRuntime(for: gull)
            let (newPrompt, runtime) = try await (promptValue, runtimeValue)
            guard !Task.isCancelled else { return }
            prompt = newPrompt; loadedPromptText = newPrompt; loadedPrompt = true
            loadedMode = runtime.mode
            selectedMode = runtime.mode
            loadedName = displayName; loadedBio = bio
        } catch { loadError = error.localizedDescription }
        isLoading = false
    }

    private func scheduleSave() {
        guard loadedPrompt, !isSavingRequest else { return }
        saveTask?.cancel()
        saveState = .idle
        saveTask = Task { try? await Task.sleep(for: .milliseconds(650)); guard !Task.isCancelled else { return }; await save() }
    }

    private func save() async {
        guard loadedPrompt, hasChanges || runtimeSelectionWasEdited else { return }
        guard !isSavingRequest else { return }
        isSavingRequest = true
        saveState = .saving
        let snapshotName = displayName
        let snapshotBio = bio
        let snapshotPrompt = prompt
        let snapshotMode = selectedMode
        let nameChanged = snapshotName != loadedName
        let bioChanged = snapshotBio != loadedBio
        let promptChanged = snapshotPrompt != loadedPromptText
        let modeChanged = runtimeSelectionWasEdited && snapshotMode != loadedMode
        do {
            if nameChanged || bioChanged { try await store.updateGull(gull, displayName: snapshotName.nilIfBlank, bio: snapshotBio.nilIfBlank) }
            if promptChanged { try await store.savePrompt(for: gull, instructions: snapshotPrompt) }
            if modeChanged { _ = try await store.setRuntime(for: gull, mode: snapshotMode) }
            if displayName == snapshotName { loadedName = snapshotName }
            if bio == snapshotBio { loadedBio = snapshotBio }
            if prompt == snapshotPrompt { loadedPromptText = snapshotPrompt }
            if selectedMode == snapshotMode {
                if modeChanged { loadedMode = snapshotMode }
                runtimeSelectionWasEdited = false
            }
            isSavingRequest = false
            if hasChanges || runtimeSelectionWasEdited {
                saveState = .idle
                scheduleSave()
            } else {
                saveState = .saved
            }
        } catch {
            isSavingRequest = false
            saveState = .failed(error.localizedDescription)
        }
    }

    private func flushAndDismiss() async {
        isFinishing = true
        defer { isFinishing = false }
        await save()
        if case .failed = saveState { return }
        dismiss()
    }
}

private struct SavedGullDetail: View {
    @Environment(MobileAppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let gull: SavedGull
    @State private var isRemoving = false
    @State private var error: String?
    @State private var showingComposer = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    HStack(spacing: 14) { GullAvatar(handle: gull.handle, size: 68); VStack(alignment: .leading, spacing: 4) { Text(gull.displayName).font(.title2.weight(.semibold)); Text(gull.handle).font(.subheadline).foregroundStyle(.secondary) } }
                    if let bio = gull.bio, !bio.isEmpty { Text(bio).font(.body).foregroundStyle(.secondary) }
                    if !gull.declaredCapabilities.isEmpty {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Capabilities").font(.headline)
                            Text(gull.declaredCapabilities.joined(separator: " · ")).font(.subheadline).foregroundStyle(.secondary)
                        }
                        .padding(18)
                        .background(GullsTheme.surface, in: .rect(cornerRadius: 20))
                    }
                    if let error { ErrorCard(message: error) { Task { await remove() } } }
                    Button { showingComposer = true } label: {
                        Label("Message this Gull", systemImage: "bubble.left.and.bubble.right")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(GullsTheme.accent)
                    Button("Remove saved Gull", role: .destructive) { Task { await remove() } }.frame(maxWidth: .infinity).buttonStyle(.bordered).disabled(isRemoving)
                }.padding(20)
            }.navigationTitle("Gull").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .gullsSheet()
        .sheet(isPresented: $showingComposer) {
            NewMessageSheet(recipientHandle: gull.handle)
        }
    }

    private func remove() async {
        isRemoving = true; error = nil
        do { try store.removeSavedGull(gull); dismiss() } catch { self.error = error.localizedDescription }
        isRemoving = false
    }
}

private struct AddGullView: View {
    @Environment(MobileAppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var handle = "@"
    @State private var profile: GullPublicProfile?
    @State private var isLoading = false
    @State private var isSaving = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) { Text("Save a Gull").font(.title2.weight(.semibold)); Text("Enter a public handle to look up its profile.").font(.subheadline).foregroundStyle(.secondary) }
                    TextField("@name:server.example", text: $handle).textInputAutocapitalization(.never).autocorrectionDisabled().textFieldStyle(.plain).padding(12).background(GullsTheme.incoming, in: .rect(cornerRadius: 12)).submitLabel(.search).onSubmit { Task { await lookup() } }
                    Button { Task { await lookup() } } label: { Label(isLoading ? "Looking up…" : "Look up", systemImage: "magnifyingglass").frame(maxWidth: .infinity) }.buttonStyle(.borderedProminent).tint(GullsTheme.accent).disabled(isLoading || SavedGull.canonicalHandle(handle) == nil)
                    if let error { ErrorCard(message: error) { Task { await lookup() } } }
                    if let profile { publicPreview(profile) }
                }.padding(20)
            }.navigationTitle("Other Gulls").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
        .gullsSheet()
    }

    private func publicPreview(_ profile: GullPublicProfile) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 14) { GullAvatar(handle: profile.handle, size: 56); VStack(alignment: .leading, spacing: 4) { Text(profile.displayName ?? SavedGull.defaultDisplayName(for: profile.handle)).font(.headline); Text(profile.handle).font(.subheadline).foregroundStyle(.secondary) } }
            if !profile.capabilities.isEmpty { Text(profile.capabilities.joined(separator: " · ")).font(.subheadline).foregroundStyle(.secondary) }
            Button { Task { await save(profile) } } label: { Label(isSaving ? "Saving…" : "Save Gull", systemImage: "bookmark").frame(maxWidth: .infinity) }.buttonStyle(.borderedProminent).tint(GullsTheme.accent).disabled(isSaving)
        }
        .padding(18)
        .background(GullsTheme.surface, in: .rect(cornerRadius: 20))
    }

    private func lookup() async {
        guard SavedGull.canonicalHandle(handle) != nil else { return }
        isLoading = true; error = nil
        do { profile = try await store.lookupPublicGull(handle: handle) } catch { profile = nil; self.error = error.localizedDescription }
        isLoading = false
    }

    private func save(_ profile: GullPublicProfile) async {
        isSaving = true; error = nil
        do {
            let saved = try SavedGull(agentID: profile.agentID, handle: profile.handle, publicDisplayName: profile.displayName, bio: nil, declaredCapabilities: profile.capabilities, customDisplayName: nil, labels: [])
            try store.saveGull(saved)
            dismiss()
        } catch { self.error = error.localizedDescription }
        isSaving = false
    }
}

private struct ErrorCard: View {
    let message: String
    let retry: () -> Void
    var body: some View {
        HStack(alignment: .top, spacing: 10) { Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange); Text(message).font(.subheadline).foregroundStyle(.secondary); Spacer(); Button("Retry", action: retry).font(.subheadline.weight(.medium)) }.padding(14).background(.orange.opacity(0.10), in: .rect(cornerRadius: 14))
    }
}

private enum GullSaveState: Equatable { case idle, saving, saved, failed(String) }

private extension String {
    var nilIfBlank: String? { let trimmed = trimmingCharacters(in: .whitespacesAndNewlines); return trimmed.isEmpty ? nil : trimmed }
}
