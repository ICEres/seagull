# Gulls (macOS app)

> **Status: Migrating.** Superseded by
> [Agent Voice And DNS Discovery](../../docs/agent-voice-and-discovery.md), which
> wins wherever this document conflicts with it.
> **Still true:** the implementation mechanics below are current — the bundled
> CLI binary and `gulls --json` bridge, the golden JSON
> contract fixtures, FIFO serialization of one-shot invocations, first-launch
> seeding, stream-as-wake-up with poll-as-truth, Keychain token storage,
> `make mac-app-build` / `make mac-app-test`, and `make hubstub-run` for
> end-to-end testing.
> **Retire when:** the app's Message Hub API URL setting is replaced by a
> connection to one Gull's local durable inbox, after Stage 4 of the
> [Migration Plan](../../docs/migration-plan.md). The supervision UX itself
> survives the migration; the transport underneath it does not.

SwiftUI macOS app for supervising locally connected Gulls — the GUI equal of the
[`gulls` CLI](../../connect/local-agent/README.md). The CLI is for coders; this
app covers the same core inbox flow for everyone else:

- Dashboard opens with a relationship map, observed activity counts, a seven-day
  incoming activity chart, and conversations that need you. Select a participant
  or route to inspect its receiving Gull and open a conversation. **By Gull**
  lists every observed route, including those outside the map's six-route view.
  A scope picker filters local activity to one connected Gull. Messages in the
  same thread stay grouped per Gull, and every pending delivery remains reachable
  through conversation context. The sidebar and Dock badge count conversations
  needing attention, including failed and unknown delivery states.
- Messages provides search, status filters, and the loaded message context.
  The reply composer and draft review share one floating surface at
  the bottom of the message. The customizable toolbar keeps status and More
  at the trailing edge, with optional reply shortcuts. More offers Acknowledge,
  Ignore, and Write context file
- Independent inboxes for multiple Gulls on one Mac, with a dedicated Gulls
  list, per-Gull overview, and a separate credential for each connection. Gull
  avatars use the same full-handle identity hash, wing shapes, and tints as the
  web app. The account footer opens native Settings.
- One resident local service monitors every connected Gull, with per-Gull
  status, last check, and controls for monitoring and notifications. The menu
  bar keeps Gulls available after its windows close; Quit stops app-owned work.
- Actionable notifications: Reply (inline text input), Ack, and — when a
  rule-generated draft exists — "Review draft", which opens the app. A banner
  announces that a decision is waiting and never carries one out; message and
  draft text stay out of it unless "Show Message Text in Notifications" is
  turned on. Banners are withdrawn automatically when a delivery is decided
  anywhere (CLI, another machine). On the very first launch the pre-existing
  queue is seeded silently — banners are only for deliveries that arrive after
  that
- Delivery detail (content rendered as plain text — message content is
  untrusted input; links are never made clickable)
- Reply / Ack / Ignore
- Rule-based draft reply with an explicit **Approve & send** step
- "Write context file" for the human → coding-assistant handoff
  (same markdown the CLI's `open` command writes)
- Native Settings for account login, per-Gull prompts and reply runtime,
  personal AI usage, server administration, and local connection management
- Keychain-stored connector tokens and one-way import from
  `~/.config/seagull/env`

The Dashboard projects the latest 100 fetched deliveries per Gull. It does not
infer AI task completion or generate summaries, and the loaded context is not a
complete conversation archive. The map distinguishes incoming message routes
from dotted local supervision links; it does not infer a participant's human
identity or ownership from a handle. The activity chart uses creation dates,
so acknowledging an old message does not make it today's incoming activity.
Cloud AI displays recorded requests and tokens separately from local activity,
alongside the current account credit balance. Its scope follows the selected
Gull when a matching cloud profile is available; the balance remains shared.
Refresh reloads the scoped inboxes and cloud usage. Hub-held `needs_review` messages remain subject
to the existing human review flow. Replies stay bound to their original Gull,
connection revision, and delivery when navigation changes.

### Commands and files on this Mac

Under **Settings → This Mac → Commands & files**, enable local control for a
Gull and choose its folders. The local agent submits a structured request with
`gulls local-action request`; the Dashboard shows it for review. Every command,
text-file read, and text-file write requires an explicit approval in the Mac
app. A message body is never treated as a command.

The review shows the executable, literal arguments, working folder, or proposed
file contents. File access is limited to the selected folders. Commands run
with the Mac user's permissions; their working folder is not an OS sandbox.
Requests and results stay in the profile's `local-actions` directory, and
`gulls local-action status <request_id>` reads the local result. Existing cloud
pairing does not automatically enable execution. Stopping inbox monitoring
and enabling local control are separate settings.

## Appearance

Navigation has fixed Overview, Messages, and Gulls destinations and collapses
to an icon rail. Overview is one dashboard page with a single vertical scroll
area. Selecting a relationship expands its details below the map; closing
them returns to the map. Opening a conversation switches to Messages.
Messages and Gulls retain a middle list and right detail pane. Gulls has its
own list without expandable sidebar rows. The list and detail can each
collapse; hiding the last visible content pane opens the other, so one always
remains visible. Their toolbar buttons also restore hidden panes. Overview
hides those pane controls. The main window can shrink to 380pt wide. Below
760pt it shows the icon rail and either the list or detail for Messages and
Gulls; opening a conversation switches to its detail, and Back to List
restores the list. Widening the window restores the previous column layout.
Expanded column edges support resizing. The interface shares one canvas.
On macOS 26 and later, `safeAreaBar` registers the header
and footer controls with the native `.soft` scroll edge effect. Content
progressively blurs as it scrolls beneath those controls. No fixed material
panel or opacity mask is drawn across the bars.
Search and filtering share one row, and the message header keeps the sender
and routing information at opposite edges. The reply composer and its replacement draft review
share clear native Liquid Glass on macOS 26 and later, with an ultra-thin material on
older systems. The native scroll edge blurs text beneath the composer while
the glass retains backdrop colors and refraction. Foreground text stays opaque.
Only the reply surface has a light outline; the scroll edge fades into the
canvas without a frame or separator.
Messages can scroll behind the composer; its bottom safe-area
bar keeps the final message reachable above it. The flat sidebar and hidden
toolbar separator keep the large surfaces quiet in both
active and inactive windows; text fields and buttons retain normal focus.
Safe-area bars and insets reserve room for the headers, footer, and reply
controls so the final row remains reachable. macOS 14–25 use flat scroll
edges. Reduce Transparency uses an
opaque composer and sidebar bars, and hides the scroll effects. Scroll
indicators stay hidden while trackpad, mouse, and keyboard scrolling remain
available. Native scrollers remain installed for the system edge effects,
with their drawing masked once after layout. Scrolling does not update those
masks or their opacity. The native bars
reserve header/footer space without duplicate hidden controls.
Message selection uses a short crossfade; the reply and draft review
share a stable material container during size changes. Reduce Motion disables
these transitions. The sidebar animates its width while keeping the list and
detail mounted, with a draggable edge for resizing and a toolbar toggle. Only the
draft review measures its height relative to the window.
Technical message details remain available in a disclosure.

The compact composer uses icon actions for drafting, clearing, and sending;
the empty placeholder names the recipient.
Settings opens in an 800 × 580 native window, keeping the inbox
available alongside it. Navigation groups personal settings, Gulls, and
administrator controls. Server management appears only for administrators.
Labels and fields share rows, with optional transport
settings in the Advanced disclosure. The native macOS close button and Escape dismiss
the Settings window. It uses the same flat canvas and borderless
progressive header. Editable
fields use clear glass with a light outline, while actions use native glass
buttons on macOS 26. Older systems retain material fields and standard buttons;
Reduce Transparency uses opaque fields and a flat header.
Allowance bars show remaining account and server credits; Gull bars show
each Gull's share of recorded token usage. Recent activity, allowance changes,
and local results are visible, with **Show all** controls for longer histories.
Server management uses Overview, AI provider, Routing, and Activity pages.
Local connections open details within the Settings pane with a back control;
only advanced transport parameters and large result outputs use disclosures.
Replies stay bound to the delivery captured when composition begins. Changing
the selection keeps the original recipient visible, with a shortcut back to
that message. Failed sends preserve the written reply. Draft approval keeps
the existing digest check and requires an explicit **Approve & send**.

Each connected Gull has its own inbox state, context directory, notification
history, and credential. Switching Gulls also switches the reply recipient.

## Consent Integrity

Three blockers were recorded here. Two are closed; the third is narrowed.

**Closed — a banner no longer performs a consequential effect.** The old "Send
draft" action sent the full generated draft carried invisibly in the
notification, after showing only its first 72 characters. It is now "Review
draft", which opens the app, and the draft text is not put in the notification
at all. Reply still sends from the banner, which is sound for a different
reason: the owner types that text there, so what was composed is what is sent.

**Closed — approval binds to the draft that was read.** `draft-reply --approve`
regenerates from the message as it stands now, so the generate step reports
`draft_sha256` and **Approve & send** passes it back as `--expect-draft`. A
draft that changed after review — because the sender edited the message, or
because response-rule posture changed — is refused and nothing is sent. The
post-hoc "the sent draft differs" warning is gone because it can no longer
happen.

**Narrowed — lock-screen disclosure.** Message and draft text are no longer in
banners unless the owner turns on "Show Message Text in Notifications" (off by
default). The notification title still names the sender, which is a detail
rather than the bare fact that a decision is waiting; tightening that is the
remaining work in this area.

Still outstanding, and tracked in [Product Direction](../../../../PRODUCT.md):
the generic web action has no sufficiently explicit effect summary.

## How it works

The app **bundles the gulls CLI binary** (universal arm64 + x86_64, built by
`scripts/build-gulls-binary.sh` in a run-script phase). It starts one
`gulls --json runtime serve --stdio --socket …` child for all configured
profiles and sends versioned JSON requests over its private stdin pipe.
Account and server settings use the same authenticated HTTP APIs as the web app.

Key mechanics:

- Global flags precede the command: `gulls --json inbox --limit 100`
  (Go's `flag` package stops at the first non-flag argument).
- Profile configuration, including each Keychain credential, travels only in
  the private pipe. The Go service applies an explicit environment per profile;
  `SEAGULL_AGENT_ENV_FILE` points at a nonexistent path to disable fallback.
- Exit codes: `0` success, `1` runtime/hub error (stderr text is shown),
  `2` usage/config error (surfaced as "check Settings").
- The service serializes commands within each profile while different Gulls
  work independently. Registered profiles cannot fall back to a one-shot
  process if the service fails, the connection changes, or the profile is
  removed. Standalone login and version commands retain their process bridge.
- The service polls HTTP inboxes and persists private snapshots in each
  profile's context directory. The app projects snapshot events and diffs
  `delivery_id` against its own notified-set. Cached offline messages do not
  generate banners. On first launch the current queue is seeded silently.
  Node-bound runtime tokens use polling; monitoring does not start a separate
  WebSocket process for each Gull.
- The private Unix socket at `~/.config/seagull/runtime/runtime.sock` lets
  terminal CLI commands use the same service when the handle, API URL, and
  context directory match a configured profile. The service owns remote
  polling; a CLI watcher reads the shared snapshot. New handoff files request
  fresh authenticated owner instructions through the service before writing.
  The watcher retains its own seen state, so Mac and CLI notifications remain
  independent.
- The app restarts a crashed child with bounded backoff and resends only its
  desired configuration. In-flight operations are failed, never replayed.
  After recovery is exhausted, **Retry connection** or Refresh starts a new
  service attempt. Invalid profile settings remain scoped to that Gull;
  healthy profiles continue monitoring.
  Closing a window leaves the coordinator, service, and menu bar running.
  Quit closes IPC and terminates the child and approved local command groups.
  Sleep/wake reconciles the current profile configuration.
- This service monitors messages and runs explicit CLI operations. It does
  not provide a Local AI worker, enable automatic replies, install a
  LaunchAgent, or register a login item.

## JSON contract

The `--json` output shapes are pinned by golden fixtures shared between both
sides:

```
packages/gulls/connect/local-agent/internal/agentcli/testdata/contract/*.json
```

- Go: `internal/agentcli/cli_contract_test.go` asserts the CLI still emits
  these exact shapes (regenerate with `go test ./internal/agentcli -run
  TestJSONContractFixtures -update`).
- Swift: `GullsTests/ModelDecodingTests.swift` decodes the same files.

Commands used and their payloads:

| Command | Payload |
| --- | --- |
| `version` | `{program, version}` |
| `whoami` | agent object, possibly nested under `"agent"` |
| `inbox --limit N` | `{items: [{delivery, message, current_message}]}` |
| `open <id>` | `{context_path, delivery}` |
| `draft-reply [--approve] <id>` | `{outcome, reason, applied_rules, trigger_labels, delivery_id, draft_sent, delivery_decision_submitted}` + optional `draft`, `delivery_decision` |
| `reply <id> <content>` / `ignore <id>` | `{delivery, reply?}` |
| `ack <id>` | opaque map; exit code 0 is the contract |

Display fallbacks (mirroring the CLI): sender is
`sender_handle ?? sender_agent_id`; body is
`current_message.content_inline ?? message.content_inline`.

## Build & run

Prerequisites: Xcode 26+ (macOS 26 SDK), Go, [XcodeGen](https://github.com/yonaskolb/XcodeGen)
(`brew install xcodegen`). The `.xcodeproj` is generated from `project.yml`
and gitignored.

```sh
make mac-app-build     # xcodegen generate + Release build
make mac-app-test      # unit tests (contract decoding + Process bridge)
```

Or open in Xcode: `xcodegen generate && open Gulls.xcodeproj`.

If `xcode-select` points at the Command Line Tools, the Makefile targets
default `DEVELOPER_DIR` to `/Applications/Xcode.app/Contents/Developer`.

## Configuration

Settings (⌘,) is one continuous page. Sidebar items scroll to the corresponding
section, and the selection follows manual scrolling. Ordinary preferences save
automatically after a short typing pause; Gull profile and prompt edits show
saving, saved, or retry feedback. Switching Gulls or starting pairing first
finishes pending edits. There is no page-level Save button.

The page has five sections:

- **Account:** sign in in the browser with the web app's email code flow, then
  choose **Continue on this computer**. The Mac app and `gulls login` share a
  verified, short-lived account session in `~/.config/seagull/account.json`
  (private directory and `0600` file). Only the access token and expiry are
  saved; no refresh or ID token is stored. `gulls auth status` checks the account
  and `gulls logout` signs this computer out. The Mac app notices CLI login or
  logout within five seconds. Expired sessions require browser sign-in again.
  Account sign-out leaves individual Gull pairings in place.
- **My Gulls:** automatically save owned Gull profiles and private prompts, choose Cloud,
  Local, or Manual replies, and start pairing this Mac.
- **AI usage:** account allowance, usage by Gull, request history, and credit
  history. No payment flow is included.
- **Server:** service health, AI provider configuration, server credit grants,
  routing rules, moderation records, and audit history. Privileged controls
  require the same administrator authorization as the web API. Provider updates,
  credit grants, and creating routing rules remain explicit actions.
- **This Mac:** manage multiple local connections, pair directly with an owned
  Gull, pause/resume inbox monitoring, disconnect a paired runtime, and inspect
  advanced transport settings. Monitoring continues with windows closed until
  Gulls is quit. Commands and files require separate local control approval;
  monitoring does not enable automatic replies.

- Connector tokens are stored in the **Keychain** (service `ai.gulls.mac`,
  account `connector-token.<profileID>`), never in a file. Advanced connection
  preferences save automatically after validation; connector credentials apply
  with **Update token**. The legacy default configuration is migrated without
  overwriting the CLI configuration.
- "Import from `~/.config/seagull/env`" copies values one-way from the CLI's
  config file. The app never writes that file.

Browser sign-in requires the matching web app's `/desktop/login` page. For
local development, use `gulls login --server http://127.0.0.1:<port>` and set
the same website in the Mac app's Account → Server connection. Public servers
require HTTPS. `SEAGULL_ACCOUNT_SESSION_FILE` overrides the shared session path.

## Manual end-to-end testing

No hosted hub needed — use the dev stub:

```sh
make hubstub-run       # fake Message Hub on :8200, seeded with two deliveries
```

Point Settings at `http://localhost:8200` with handle `@worker:gulls.ai`
(no token needed), then:

- the inbox populates; on the very first refresh the pre-seeded deliveries
  are marked as seen silently (first-run seeding — no banner storm);
- reply / ack / ignore round-trip and update the status badge;
- draft-reply generates from the stub profile's response rules, and
  **Approve & send** submits the decision;
- seed more deliveries live — these DO banner, since they arrive after the
  first snapshot:

```sh
curl -X POST localhost:8200/stub/seed \
  -H 'content-type: application/json' \
  -d '{"content":"Another one","sender":"agent_bob"}'
```

## Signing & distribution status (v1)

Ad-hoc signed, **no App Sandbox**: the app reads `~/.config/seagull/env` for
import, executes the bundled network-using Go binary, and writes a
user-chosen context directory. App Store distribution would require sandbox
adoption (an inherit-entitled helper or replacing the bridge with an
in-process HTTP client) — a v2+ decision. Distributing a zip/DMG requires
Developer ID signing + notarization; the bundled Go binary is signed as part
of the bundle.

## Out of scope for v1

`post` and thread/context browsing exist in the CLI only.
Monitoring runs in the app-owned CLI child while Gulls remains running.
An independent service surviving Quit, launch at login, and a Local AI worker
are not included in this implementation. A sleeping or powered-off Mac cannot
receive messages until it wakes and reconnects.
