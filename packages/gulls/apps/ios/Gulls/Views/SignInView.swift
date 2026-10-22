import SwiftUI

struct SignInView: View {
    @Environment(MobileAppStore.self) private var store
    @FocusState private var focusedField: Field?

    private enum Field { case email, code }

    private var validEmail: Bool {
        let email = store.email.trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = email.split(separator: "@", omittingEmptySubsequences: false)
        return parts.count == 2 && !parts[0].isEmpty && parts[1].contains(".") && !email.contains(where: \.isWhitespace)
    }

    var body: some View {
        @Bindable var store = store

        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 32) {
                    identity
                    VStack(alignment: .leading, spacing: 20) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(store.challengePending ? "Check your email" : "Welcome to Gulls")
                                .font(.title2.weight(.semibold))
                            Text(store.challengePending ? "Enter the code sent to \(store.email)." : "Sign in with your email. Your Gulls and conversations will be here.")
                                .font(.body)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }

                        if store.challengePending {
                            TextField("Verification code", text: $store.code)
                                .textContentType(.oneTimeCode)
                                .keyboardType(.numberPad)
                                .focused($focusedField, equals: .code)
                                .font(.title2.monospacedDigit())
                                .padding(16)
                                .background(GullsTheme.surface, in: .rect(cornerRadius: 16))
                                .accessibilityLabel("Email verification code")
                                .accessibilityIdentifier("verification-code")
                        } else {
                            TextField("Email address", text: $store.email)
                                .textContentType(.emailAddress)
                                .keyboardType(.emailAddress)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .submitLabel(.go)
                                .focused($focusedField, equals: .email)
                                .padding(16)
                                .background(GullsTheme.surface, in: .rect(cornerRadius: 16))
                                .accessibilityLabel("Email address")
                                .accessibilityIdentifier("email-address")
                                .onSubmit { if validEmail { signIn() } }
                        }

                        if let error = store.error {
                            Label(error, systemImage: "exclamationmark.circle")
                                .font(.callout)
                                .foregroundStyle(.red)
                                .fixedSize(horizontal: false, vertical: true)
                                .accessibilityIdentifier("sign-in-error")
                            if store.canRetryRestore {
                                Button("Retry connection") { Task { await store.prepare() } }
                                    .frame(minHeight: 44)
                            }
                        }

                        Button(action: signIn) {
                            HStack(spacing: 10) {
                                if store.isBusy { ProgressView().tint(.white) }
                                Text(store.challengePending ? "Sign in" : "Send sign-in code")
                                    .font(.body.weight(.semibold))
                            }
                            .frame(maxWidth: .infinity, minHeight: 44)
                        }
                        .buttonStyle(.borderedProminent)
                        .buttonBorderShape(.roundedRectangle(radius: 16))
                        .disabled(store.isBusy || (store.challengePending ? store.code.trimmingCharacters(in: .whitespacesAndNewlines).count < 6 : !validEmail))
                        .accessibilityIdentifier("sign-in-submit")

                        if store.challengePending {
                            Button("Use a different email") {
                                store.cancelChallenge()
                                focusedField = .email
                            }
                            .frame(minHeight: 44)
                            .disabled(store.isBusy)
                        } else {
                            HStack(spacing: 4) {
                                Text("New to Gulls?").foregroundStyle(.secondary)
                                Link("Create an account", destination: URL(string: store.websiteURL + "/register")!)
                                    .frame(minHeight: 44)
                            }
                            .font(.callout)
                        }
                    }

                    Label("Your account is shared with Gulls on Mac and the web.", systemImage: "lock")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: 440, alignment: .leading)
                .padding(.horizontal, 28)
                .padding(.vertical, 40)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(GullsTheme.background)
            .onChange(of: store.challengePending) { _, pending in
                focusedField = pending ? .code : .email
            }
        }
    }

    private var identity: some View {
        VStack(alignment: .leading, spacing: 24) {
            GullWing(name: .classic)
                .stroke(GullsTheme.accent, style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
                .frame(width: 72, height: 32)
                .accessibilityHidden(true)
            GullsPageTitle("Gulls")
                .font(.largeTitle.weight(.semibold))
        }
    }

    private func signIn() {
        focusedField = nil
        Task {
            if store.challengePending { await store.completeSignIn() }
            else { await store.beginSignIn() }
        }
    }
}
