import SwiftUI

struct AccountSettingsView: View {
    @Bindable var account: CloudAccountStore
    @State private var websiteDraft = ""
    @State private var websiteSaveTask: Task<Void, Never>?
    @State private var websiteStatus: String?
    @State private var websiteStatusIsError = false

    var body: some View {
        VStack(alignment: .leading, spacing: 28) {
            if account.isSignedIn {
                signedInAccount
            } else {
                signInForm
            }
            connectionDetails
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(24)
        .onAppear {
            websiteDraft = account.websiteURL
        }
        .onDisappear {
            websiteSaveTask?.cancel()
            let pendingWebsite = websiteDraft
            guard !account.isSignedIn,
                  account.canStartBrowserSignIn,
                  let normalized = SharedCloudSessionFile.normalizedWebsite(pendingWebsite),
                  normalized != account.websiteURL else { return }
            websiteSaveTask = Task { @MainActor in
                await applyWebsite(rawValue: pendingWebsite)
            }
        }
        .onChange(of: websiteDraft) { _, newValue in
            scheduleWebsiteSave(for: newValue)
        }
    }

    private var signedInAccount: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 14) {
                Image(systemName: "person.crop.circle.fill")
                    .font(.system(size: 42)).foregroundStyle(GullsStyle.accent)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text(account.accountLabel).font(.title3.weight(.semibold))
                        .textSelection(.enabled)
                    if let email = account.account?.email, email != account.accountLabel {
                        Text(email).font(.subheadline).foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                    if account.isAdmin {
                        Text("Administrator").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            Text("Your Gulls and cloud allowance belong to this account.")
                .font(.callout).foregroundStyle(.secondary)
            Label("Signed in to the Mac app and CLI", systemImage: "terminal")
                .font(.caption).foregroundStyle(.secondary)
            Button("Sign out", role: .destructive) { account.signOut() }
                .buttonStyle(.bordered)
        }
    }

    private var signInForm: some View {
        CloudSettingsSection(
            account.isBrowserSignInPending ? "Finish signing in in your browser" : "Sign in with your browser",
            detail: "Use your email account on the web. Your sign-in is shared with the Mac app and CLI on this computer."
        ) {
            HStack(spacing: 12) {
                if account.isBrowserSignInPending {
                    ProgressView().controlSize(.small).accessibilityLabel("Waiting for browser sign-in")
                    Text("Waiting for your browser…").font(.callout).foregroundStyle(.secondary)
                    Button("Cancel") { account.cancelBrowserSignIn() }
                        .buttonStyle(.borderless)
                } else if account.isRestoringSharedSession {
                    ProgressView().controlSize(.small).accessibilityLabel("Updating sign-in")
                } else {
                    Button("Sign in with browser", systemImage: "arrow.up.right.square") {
                        account.startBrowserSignIn()
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!canStartSignIn)
                }
            }
            if let error = account.error {
                CloudSettingsStatus(message: error, isError: true)
            }
        }
    }

    private var connectionDetails: some View {
        CloudSettingsSection("Server connection", detail: "Choose the website used by this Mac and the CLI.") {
            VStack(alignment: .leading, spacing: 12) {
                if account.isSignedIn {
                    CloudSettingsRow("Website") {
                        Text(account.websiteURL).font(.subheadline).textSelection(.enabled)
                    }
                    Text("Sign out to connect to a different server.")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    CloudSettingsRow("Website") {
                        TextField("https://sea.gulls.ai", text: $websiteDraft)
                            .cloudSettingsField().autocorrectionDisabled()
                            .disabled(!account.canStartBrowserSignIn)
                    }
                    HStack(spacing: 8) {
                        if account.isBusy {
                            ProgressView().controlSize(.small)
                        }
                        if let websiteStatus {
                            CloudSettingsStatus(message: websiteStatus, isError: websiteStatusIsError)
                        } else {
                            Text("Changes save automatically.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .padding(.top, 12)
        }
    }

    private func scheduleWebsiteSave(for rawValue: String) {
        websiteSaveTask?.cancel()
        websiteStatus = nil

        websiteSaveTask = Task { @MainActor in
            do {
                try await Task.sleep(nanoseconds: 500_000_000)
            } catch {
                return
            }
            await applyWebsite(rawValue: rawValue)
        }
    }

    private func applyWebsite(rawValue: String) async {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        guard let normalized = SharedCloudSessionFile.normalizedWebsite(trimmed) else {
            websiteStatus = "Enter a valid HTTPS website URL."
            websiteStatusIsError = true
            return
        }
        guard !account.isSignedIn, account.canStartBrowserSignIn else { return }
        guard normalized != account.websiteURL else {
            websiteStatus = "Already using this server."
            websiteStatusIsError = false
            return
        }

        websiteStatus = "Updating server…"
        websiteStatusIsError = false
        account.websiteURL = normalized
        await account.loadConfiguration()

        guard !Task.isCancelled else { return }
        if account.runtime != nil {
            websiteStatus = "Server updated."
            websiteStatusIsError = false
        } else {
            websiteStatus = account.error ?? "Could not load this server."
            websiteStatusIsError = true
        }
    }

    private var canStartSignIn: Bool {
        guard account.canStartBrowserSignIn,
              let draft = SharedCloudSessionFile.normalizedWebsite(websiteDraft),
              let current = SharedCloudSessionFile.normalizedWebsite(account.websiteURL) else {
            return false
        }
        return draft == current
    }
}
