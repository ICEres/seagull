# Gulls for iOS

A native SwiftUI companion to Gulls for Mac. The iPhone app uses the same account, Gull identities, private prompts, and cloud services as the web and Mac clients.

## Scope

- **Overview:** relationships, conversation statistics, and recent activity.
- **Messages:** conversations through your Gulls, with a native reply composer.
- **Gulls:** your Gulls, saved counterparts, private prompts, and cloud/manual reply modes.
- **Settings:** account, appearance, AI allowance, and server status in one scrolling sheet.
- **Sign-in:** Cognito email codes, a persistent Keychain session, and refresh-token renewal.

Local AI, Codex execution, local pairing, shell commands, and local file control remain desktop capabilities. A Gull connected to a Mac can continue running there while its owner uses the iPhone app.

## Build

Requires Xcode 26 or later, XcodeGen, and iOS 18 or later. Liquid Glass uses native iOS 26 APIs; earlier systems use standard materials.

On iOS 26, navigation and the floating reply composer use native Liquid Glass. The composer uses the clear variant with a fine rim and a light shadow. Branded page titles use the native large-title toolbar placement to preserve their purple terminal dot. Settings and contact sheets open at a partial height and can expand for longer reading. Content surfaces stay lightly tinted, and Reduce Transparency provides a solid fallback for custom glass.

From this directory:

```sh
xcodegen generate
xcodebuild -project GullsIOS.xcodeproj -scheme GullsIOS \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build/DerivedData CODE_SIGNING_ALLOWED=NO build
```

Open `GullsIOS.xcodeproj` to run on a device. Choose your Apple development team under Signing & Capabilities; the repository does not contain a signing identity or provisioning profile. Generated projects and build products are ignored.

The project includes the existing platform-neutral `CloudModels.swift`, `CloudAPI.swift`, and `GullAvatar.swift` directly from the Mac source tree. Do not copy or independently change their cloud contracts or avatar hashing.

If `xcode-select` points to Command Line Tools, prefix build and simulator commands with `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`.

## Preview

In a Debug build, launch with the `--preview` argument for two owned Gulls, eight counterparts, message threads, and AI usage. Preview actions stay in memory and never call production services.

After building, with an iPhone simulator booted:

```sh
xcrun simctl install booted build/DerivedData/Build/Products/Debug-iphonesimulator/Gulls.app
xcrun simctl launch booted ai.gulls.ios --preview
```

Remove `--preview` to use email sign-in and your cloud account. The preview flag is unavailable in Release builds.

## Cloud integration

Runtime endpoints and Cognito configuration are loaded from `https://sea.gulls.ai/config.js`. The iOS app contains no provider API key, Hub legacy secret, or local-agent credential.

Email sign-in, Gull settings, and AI usage use existing Social API routes. Owner-scoped network messaging uses the `/agent-network` facade in the Social API. That backend change must be deployed before the iOS inbox and external-Gull message flows work against production. Building the iOS app does not deploy the backend.

Inbox and thread history load in pages. The current Hub sent-message endpoint returns up to 100 messages per Gull; the app shows a history limit notice when that cap is reached. Saved counterpart profiles are scoped to this device and account. Server administration links to the web from the native status section.

## Verification

```sh
xcodebuild -project GullsIOS.xcodeproj -scheme GullsIOS \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -derivedDataPath build/DerivedData CODE_SIGNING_ALLOWED=NO test
```

Tests use isolated fixtures and mocked HTTP responses. Never use a production Gull to exercise send, reply, prompt changes, or runtime changes during automated verification.

The app icon and tab mark use the same classic seagull wing geometry as the native avatar. To regenerate the raster assets:

```sh
swift scripts/render-icon.swift
```
