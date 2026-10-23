import SwiftUI

struct GullProfileView: View {
    let handle: String
    let owned: WorkspaceOwnedGull?
    let fallbackName: String?
    @Bindable var directory: GullDirectoryStore
    let userID: String?
    let websiteURL: String
    let messageAPIURL: String?
    let groups: [DashboardConversationGroup]
    let startedConversations: [GullConversation]
    let senders: [GullConversationSender]
    let compact: Bool
    let onOpen: (DashboardConversationGroup) -> Void
    let onOpenStarted: (GullConversation) -> Void
    let onStart: (GullConversationSender, String, String?) -> Void
    let onMessages: () -> Void
    let onSettings: () -> Void

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @State private var publicProfile: GullPublicProfile?
    @State private var isRefreshing = false
    @State private var error: String?
    @State private var labelText = ""
    @State private var senderID = ""

    private var saved: SavedGull? {
        guard let userID else { return nil }
        return directory.records(for: userID, websiteURL: websiteURL).first { $0.handle == handle }
    }

    private var displayName: String {
        firstNonEmpty(owned?.displayName, saved?.displayName, publicProfile?.displayName, fallbackName)
            ?? SavedGull.defaultDisplayName(for: handle)
    }

    private var capabilities: [String] {
        SavedGull.normalizedLabels(owned?.capabilities ?? publicProfile?.capabilities ?? saved?.declaredCapabilities ?? [])
    }

    private var visibleStarted: [GullConversation] {
        startedConversations.filter { conversation in
            !groups.contains { $0.profileID == conversation.senderProfileID && $0.threadID == conversation.threadID && $0.threadID != nil }
        }
    }

    var body: some View {
        Group {
            if #available(macOS 26.0, *), !reduceTransparency {
                content.gullsSafeAreaBar(edge: .top, spacing: 12) { header }
            } else {
                content.safeAreaInset(edge: .top, spacing: 0) { header.background(GullsStyle.canvas) }
            }
        }
        .gullsScrollEdges()
        .task(id: [userID ?? "", websiteURL, handle, messageAPIURL ?? ""]) { await refreshProfile() }
        .onChange(of: senders.map(\.id), initial: true) { _, ids in
            if !ids.contains(senderID) { senderID = ids.first ?? "" }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            GullAvatar(handle: handle, size: 42)
            VStack(alignment: .leading, spacing: 4) {
                GullsPageTitle(displayName).font(.title2.weight(.semibold)).lineLimit(2)
                Text(verbatim: handle)
                    .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
            }
            Spacer(minLength: 0)
            if owned == nil {
                Button(action: toggleSaved) {
                    Image(systemName: saved == nil ? "bookmark" : "bookmark.fill")
                        .foregroundStyle(saved == nil ? Color.secondary : GullsStyle.accent)
                }
                .buttonStyle(.borderless)
                .disabled(userID == nil)
                .accessibilityLabel(saved == nil ? "Save Gull" : "Remove saved Gull")
                .help(userID == nil ? "Sign in to save this Gull" : saved == nil ? "Save Gull on this Mac" : "Remove from Other Gulls")
            }
        }
        .padding(.horizontal, compact ? 14 : 28)
        .padding(.vertical, 16)
    }

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                if let owned {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(owned.status).font(.callout).foregroundStyle(.secondary)
                        HStack {
                            Button("Messages", action: onMessages)
                                .disabled(owned.profileID == nil)
                            Button("Settings", action: onSettings)
                        }
                        .buttonStyle(.bordered)
                    }
                } else {
                    composeAction
                }

                if let bio = owned?.bio ?? saved?.bio, !bio.isEmpty {
                    Text(verbatim: bio).font(.body).textSelection(.enabled)
                }
                VStack(alignment: .leading, spacing: 10) {
                    sectionTitle("Declared skills")
                    if capabilities.isEmpty {
                        Text(isRefreshing ? "Loading profile…" : "No skills declared.")
                            .font(.callout).foregroundStyle(.secondary)
                    } else {
                        ForEach(capabilities, id: \.self) { capability in
                            Text(verbatim: capability).font(.callout).textSelection(.enabled)
                        }
                    }
                }

                if owned == nil, let saved {
                    labels(saved)
                }

                VStack(alignment: .leading, spacing: 10) {
                    sectionTitle("Conversations")
                    if groups.isEmpty && visibleStarted.isEmpty {
                        Text("No conversations loaded on this Mac.")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                    ForEach(groups) { group in
                        conversationButton(title: group.title,
                                           route: "Via \(group.ownedGullDisplayName ?? group.ownedGullHandle)",
                                           snippet: group.snippet) { onOpen(group) }
                    }
                    ForEach(visibleStarted) { conversation in
                        conversationButton(title: conversation.displayName,
                                           route: "Via \(conversation.senderHandle)",
                                           snippet: conversation.threadID == nil ? "Draft conversation" : nil) {
                            onOpenStarted(conversation)
                        }
                    }
                }

                if let error {
                    Text(error).font(.caption).foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: 680, alignment: .leading)
            .padding(.horizontal, compact ? 14 : 28)
            .padding(.vertical, 22)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .gullsHiddenScrollbars()
    }

    private var composeAction: some View {
        VStack(alignment: .leading, spacing: 10) {
            if senders.isEmpty {
                Text("Connect one of your Gulls in Settings to start a conversation.")
                    .font(.callout).foregroundStyle(.secondary)
                Button("Open Settings", action: onSettings).buttonStyle(.bordered)
            } else {
                Picker("Send as", selection: $senderID) {
                    ForEach(senders) { sender in
                        Text("\(sender.displayName) · \(sender.handle)").tag(sender.id)
                    }
                }
                .pickerStyle(.menu)
                .frame(maxWidth: 340, alignment: .leading)
                Button {
                    if let sender = senders.first(where: { $0.id == senderID }) {
                        onStart(sender, displayName, publicProfile?.agentID ?? saved?.agentID)
                    }
                } label: {
                    Label("Message", systemImage: "bubble.left")
                }
                .buttonStyle(.borderedProminent)
                .tint(GullsStyle.accent)
                .disabled(userID == nil)
                if userID == nil {
                    Text("Sign in to keep conversations with your account.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func labels(_ record: SavedGull) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle("Private labels")
            ForEach(record.labels, id: \.self) { label in
                HStack(spacing: 7) {
                    Text(verbatim: label).font(.caption).lineLimit(2)
                    Button {
                        updateLabels(record.labels.filter { $0 != label })
                    } label: { Image(systemName: "xmark").font(.caption2) }
                    .buttonStyle(.borderless)
                    .accessibilityLabel("Remove label \(label)")
                }
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(GullsStyle.field, in: Capsule())
            }
            HStack(spacing: 8) {
                TextField("Add a label", text: $labelText)
                    .textFieldStyle(.plain).onSubmit { addLabel() }
                Button(action: addLabel) { Image(systemName: "plus") }
                    .buttonStyle(.borderless)
                    .disabled(labelText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityLabel("Add label")
            }
            .font(.callout)
            .padding(10)
            .background(GullsStyle.field, in: RoundedRectangle(cornerRadius: 9))
            .frame(maxWidth: 320)
            Text("Only visible to this account on this Mac.")
                .font(.caption).foregroundStyle(.tertiary)
        }
    }

    private func sectionTitle(_ text: String) -> some View {
        Text(text).font(.subheadline.weight(.semibold)).accessibilityAddTraits(.isHeader)
    }

    private func conversationButton(title: String, route: String, snippet: String?, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(verbatim: title).font(.callout.weight(.medium)).lineLimit(2)
                    Text(verbatim: route).font(.caption).foregroundStyle(.secondary)
                    if let snippet {
                        Text(verbatim: snippet).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
            }
            .padding(.vertical, 10)
            .contentShape(Rectangle())
            .foregroundStyle(Color.primary)
        }
        .buttonStyle(.plain)
    }

    private func refreshProfile() async {
        guard owned == nil, let messageAPIURL else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            let profile = try await GullPublicProfileService(apiURL: messageAPIURL).resolve(handle: handle)
            guard !Task.isCancelled else { return }
            publicProfile = profile
            if saved != nil, let userID {
                try directory.save(profile, userID: userID, websiteURL: websiteURL)
            }
            error = nil
        } catch {
            guard !Task.isCancelled else { return }
            self.error = saved == nil ? "Public profile unavailable. You can still save this address."
                : "Could not refresh. Showing the saved profile."
        }
    }

    private func toggleSaved() {
        guard let userID else { return }
        do {
            if saved != nil {
                try directory.remove(handle, userID: userID, websiteURL: websiteURL)
            } else if let publicProfile {
                try directory.save(publicProfile, userID: userID, websiteURL: websiteURL)
            } else {
                try directory.save(agentID: nil, handle: handle, displayName: fallbackName,
                                   bio: nil, declaredCapabilities: [], userID: userID, websiteURL: websiteURL)
            }
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    private func addLabel() {
        guard let saved else { return }
        updateLabels(saved.labels + [labelText])
        labelText = ""
    }

    private func updateLabels(_ labels: [String]) {
        guard let userID else { return }
        do {
            try directory.updateLabels(labels, for: handle, userID: userID, websiteURL: websiteURL)
            error = nil
        } catch { self.error = error.localizedDescription }
    }
}

struct AddGullView: View {
    let messageAPIURL: String?
    let onSave: (GullPublicProfile) throws -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var handle = ""
    @State private var isLoading = false
    @State private var error: String?
    @State private var saveTask: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            GullsPageTitle("Save a Gull").font(.title2.weight(.semibold))
            Text("Enter a Gull address to add it to Other Gulls on this Mac.")
                .font(.callout).foregroundStyle(.secondary)
            TextField("@name:server.example", text: $handle)
                .textFieldStyle(.roundedBorder)
                .onSubmit { save() }
                .accessibilityLabel("Gull address")
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button(action: save) {
                    if isLoading { ProgressView().controlSize(.small) }
                    else { Text("Add Gull") }
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(isLoading || SavedGull.canonicalHandle(handle) == nil || messageAPIURL == nil)
            }
            if messageAPIURL == nil {
                Text("Message Hub unavailable. Check the server connection in Settings.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(28)
        .frame(width: 370)
        .background(GullsStyle.canvas)
        .onDisappear { saveTask?.cancel() }
    }

    private func save() {
        guard !isLoading, let messageAPIURL, SavedGull.canonicalHandle(handle) != nil else { return }
        isLoading = true
        error = nil
        saveTask = Task {
            defer { isLoading = false }
            do {
                let profile = try await GullPublicProfileService(apiURL: messageAPIURL).resolve(handle: handle)
                guard !Task.isCancelled else { return }
                try onSave(profile)
                dismiss()
            } catch {
                guard !Task.isCancelled else { return }
                self.error = error.localizedDescription
            }
        }
    }
}
