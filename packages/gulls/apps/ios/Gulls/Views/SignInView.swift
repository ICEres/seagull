import SwiftUI

struct SignInView: View {
    @Environment(MobileAppStore.self) private var store
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var focusedField: Field?

    private enum Field { case email, code }

    private var validEmail: Bool {
        let email = store.email.trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = email.split(separator: "@", omittingEmptySubsequences: false)
        return parts.count == 2 && !parts[0].isEmpty && parts[1].contains(".") && !email.contains(where: \.isWhitespace)
    }

    private var canSubmit: Bool {
        !store.isBusy && (store.challengePending ? store.code.trimmingCharacters(in: .whitespacesAndNewlines).count >= 6 : validEmail)
    }

    private var loginHandle: String {
        let name = store.email.trimmingCharacters(in: .whitespacesAndNewlines)
            .split(separator: "@", omittingEmptySubsequences: false).first.map(String.init) ?? ""
        return "@\(name.isEmpty ? "you" : name)"
    }

    var body: some View {
        @Bindable var store = store

        VStack(spacing: 0) {
            HStack(spacing: 8) {
                GullWing(name: .classic)
                    .stroke(.primary, style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
                    .frame(width: 24, height: 12)
                    .accessibilityHidden(true)
                GullsPageTitle("Gulls")
                    .font(.headline.weight(.bold))
                Spacer()
            }
            .padding(.horizontal, 28)
            .padding(.vertical, 16)

            ScrollView {
                VStack(spacing: 0) {
                    GullsPageTitle(store.challengePending ? "Check your inbox" : "Your sky is waiting")
                        .font(.largeTitle.weight(.bold))
                        .tracking(-0.8)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)

                    Text(store.challengePending ? "We sent a code to \(store.email)." : "Sign in to talk to your flock.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 10)
                        .padding(.bottom, 36)

                    HStack(spacing: 12) {
                        Group {
                            if store.challengePending {
                                TextField("Email code", text: $store.code)
                                    .textContentType(.oneTimeCode)
                                    .keyboardType(.numberPad)
                                    .focused($focusedField, equals: .code)
                                    .font(.body.monospacedDigit())
                                    .accessibilityLabel("Email verification code")
                                    .accessibilityIdentifier("verification-code")
                            } else {
                                TextField("Email address", text: $store.email)
                                    .textContentType(.emailAddress)
                                    .keyboardType(.emailAddress)
                                    .textInputAutocapitalization(.never)
                                    .autocorrectionDisabled()
                                    .focused($focusedField, equals: .email)
                                    .font(.body.weight(.medium))
                                    .accessibilityLabel("Email address")
                                    .accessibilityIdentifier("email-address")
                            }
                        }
                        .textFieldStyle(.plain)
                        .submitLabel(.go)
                        .onSubmit { if canSubmit { signIn() } }
                        .disabled(store.isBusy)

                        Button(action: signIn) {
                            Group {
                                if store.isBusy {
                                    ProgressView().tint(.white)
                                } else {
                                    Image(systemName: "arrow.up")
                                        .font(.body.weight(.semibold))
                                }
                            }
                            .foregroundStyle(.white)
                            .frame(width: 44, height: 44)
                            .background(canSubmit || store.isBusy ? GullsTheme.accent : Color.primary.opacity(0.16), in: .circle)
                            .contentShape(.circle)
                        }
                        .buttonStyle(.plain)
                        .disabled(!canSubmit)
                        .accessibilityLabel(store.challengePending ? "Sign in" : "Send sign-in code")
                        .accessibilityIdentifier("sign-in-submit")
                    }
                    .padding(.leading, 20)
                    .padding(.trailing, 8)
                    .padding(.vertical, 8)
                    .gullsGlass(cornerRadius: 20)
                    .overlay(alignment: .topTrailing) {
                        HStack(alignment: .bottom, spacing: 6) {
                            GullWing(name: .classic)
                                .stroke(style: StrokeStyle(lineWidth: 2.1, lineCap: .round, lineJoin: .round))
                                .foregroundStyle(validEmail || store.isBusy ? GullsTheme.accent : Color.primary)
                                .frame(width: 24, height: 10.5)
                                .scaleEffect(x: 1, y: store.isBusy && !reduceMotion ? 0.56 : 1, anchor: .bottom)
                                .rotationEffect(.degrees(store.isBusy && !reduceMotion ? -5 : 0), anchor: .bottom)
                                .offset(y: store.isBusy && !reduceMotion ? -5 : 0)
                                .animation(
                                    store.isBusy && !reduceMotion
                                        ? .easeInOut(duration: 0.42).repeatForever(autoreverses: true)
                                        : .easeOut(duration: 0.18),
                                    value: store.isBusy && !reduceMotion
                                )
                            Text(loginHandle)
                                .font(.caption2.weight(.bold))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        .frame(maxWidth: 220, alignment: .trailing)
                        .padding(.trailing, 22)
                        .alignmentGuide(.top) { $0[.bottom] - 2 }
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                    }

                    if let error = store.error {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(.red)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.top, 12)
                            .accessibilityIdentifier("sign-in-error")
                        if store.canRetryRestore {
                            Button("Retry connection") { Task { await store.prepare() } }
                                .frame(minHeight: 44)
                        }
                    } else {
                        Text(store.isBusy ? (store.challengePending ? "Signing in…" : "Sending code…") : (store.challengePending ? "Enter the code from your email." : "We'll email you a one-time code."))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.top, 12)
                    }

                    Group {
                        if store.challengePending {
                            Button("Use another email") {
                                store.cancelChallenge()
                                focusedField = .email
                            }
                            .disabled(store.isBusy)
                        } else {
                            Link("New here? Create your flock →", destination: URL(string: store.websiteURL + "/register")!)
                        }
                    }
                    .font(.footnote.weight(.semibold))
                    .frame(minHeight: 44)
                    .padding(.top, 16)
                }
                .frame(maxWidth: 400)
                .padding(.horizontal, 28)
                .padding(.vertical, 32)
                .frame(maxWidth: .infinity)
            }
            .defaultScrollAnchor(.center, for: .alignment)
            .scrollIndicators(.hidden)
            .scrollDismissesKeyboard(.interactively)
        }
        .background(GullsTheme.background.ignoresSafeArea())
        .onChange(of: store.challengePending) { _, pending in
            focusedField = pending ? .code : .email
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
