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
  the bottom of the message. Floating window controls keep status and More
  at the trailing edge. More offers Reply, Draft reply, Acknowledge,
  Ignore, and Write context file; Command-R focuses the reply composer
- Independent inboxes for multiple Gulls on one Mac, with a dedicated Gulls
  directory and a separate credential for each connection. The flat directory
  groups **My Gulls** and explicitly saved **Other Gulls** under one search.
  Select a Gull for its profile and conversations. Other profiles show declared
  skills and private labels; they never expose owned-Gull management controls.
  Unsaved message senders can be opened from their message header. Gull
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
- Optional per-Gull Codex handoff, with a working folder chosen per task and
  local results returned as reviewable drafts
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

### Saved Gulls and starting conversations

Use **Gulls → +** to resolve a canonical `@name:server` address from the configured
Message Hub, or open a message sender and choose the bookmark button. Public
profile lookup never sends the human account token. Saved identities and private
labels stay on this Mac, isolated by signed-in account and website; they do not
sync to the web app. Merely receiving a message does not save its sender.

Choose a connected owned Gull under **Send as** and select **Message** to start
an external conversation. The app uses the CLI's existing `post` and `thread`
commands with that Gull's credential. It does not offer a human sender for
external conversations. Each conversation remains bound to its original local
profile and connection revision. Started conversation routing is saved within
the current account and website; message bodies are loaded from the Hub and
kept in memory. Messages arriving for the same profile and thread reuse the
conversation entry. Profile conversation lists show loaded context, not a
complete history across devices.

### Commands and files on this Mac

Under **Settings → This Mac**, select a Gull, enable local control in the inline
**Commands & files** section, and choose its folders. The local agent submits a structured request with
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

### Codex on this Mac

Under **Settings → This Mac**, select a connected Gull and enable **Use Codex
on this Mac**. Each Gull has its own toggle, initially off. Codex uses its own
account and permissions; enabling this capability does not enable local
control or attach a permanent project to the Gull.

Choose **Work with Codex** on an incoming message, or **New task…** in the inline
Codex settings. Enter a goal and optionally choose a working folder, then select
**Start in Gulls**. The Mac app connects to the installed Codex CLI's local
stdio app-server using its existing Codex login. Output streams beside the
original message. **Continue** resumes that task's exact Codex thread; **Stop**
interrupts only its current turn. Multiple Gulls share one local connection
and keep separate task sessions. An incoming message's private context and
authenticated reply guidance are snapshotted separately from the owner's goal.
Incoming messages cannot authorize commands, file changes, or sending a reply.

Live tasks queue commands and text-file operations through the existing
`local-action` broker. Enable local control and add the task folder under
**This Mac** before using these operations. **Review operation…** opens the
native command or file review, including proposed file changes. No operation
runs when merely queued. Stopping, disconnecting, disabling Codex, or restarting
Gulls cancels outstanding review requests; they are not automatically replayed.
The selected working folder applies only to the current task.

Live tasks use a private, text-only copy of Codex's model catalog. Native shell,
browser, plugin, hook, and image-reading capabilities are disabled; local text
file operations go through the review broker. The configured model must exist
in that catalog before a turn can start. Codex's original configuration and
credentials are retained. Open Codex once to load its model catalog if it is
unavailable. Images are not supported by this live adapter.

Completed output remains a draft. **Use draft** copies it to a composer bound
to that Gull, connection, and delivery; replacing an unsent reply requires
confirmation. The user then chooses **Send**. The Overview shows working,
approval, and draft states. Standalone results and follow-ups appear in Codex
settings. Closing the main window preserves a running task while the Mac app
remains running; quitting interrupts it.

**Open in Codex** remains an alternative handoff using Codex's own UI and
permission controls. That handoff contains a scoped CLI prefix without a
connector token and returns an immutable local draft via `gulls codex result`.
**Continue in Codex** opens the recorded thread, never a guessed recent thread.

Requests and immutable results live under the profile's private
`codex-tasks/<task-id>` directory. Returned drafts must match the original
request's exact SHA-256, Gull identity, and connection revision. A reconnected
or removed profile cannot consume an old draft. Live session IDs and state are
stored in a private `codex-tasks/sessions.sqlite3` database. After a restart,
unfinished work is marked interrupted and requires an owner-started continuation.
Task artifacts stay on this Mac; the goal and supplied context are sent to the
configured Codex model provider when the owner starts the task. This prototype
uses the experimental [Codex app-server API](https://learn.chatgpt.com/docs/app-server)
and is verified against CLI 0.146.

## Appearance

Settings → Appearance offers System, Light, and Dark. The choice applies
immediately to the workspace and Settings and is saved on this Mac.

Navigation has fixed Overview, Messages, and Gulls destinations and collapses
to an icon rail. Overview is one dashboard page with a single vertical scroll
area. Selecting a relationship expands its details below the map; closing
them returns to the map. Opening a conversation switches to Messages.
Messages and Gulls retain a middle list and right detail pane. Gulls has its
own list without expandable sidebar rows. The list and detail can each
collapse; hiding the last visible content pane opens the other, so one always
remains visible. Their top buttons also restore hidden panes. Overview
hides those pane controls. The main window can shrink to 380pt wide. Below
760pt it shows the icon rail and either the list or detail for Messages and
Gulls; opening a conversation switches to its detail, and Back to List
restores the list. Widening the window restores the previous column layout.
Expanded column edges support resizing. The interface shares one translucent
window background material with a near-black violet tint in dark appearance and a
light lavender tint in light appearance. Settings
uses the same material. Child panes leave that backdrop visible, while text
and controls stay opaque. A single native `NSVisualEffectView` blends behind
the window, so the desktop remains visible through the whole canvas. Reduce
Transparency uses the flat canvas.
On macOS 26, `safeAreaBar` registers the header and footer controls with the
native `.soft` scroll edge effect. On macOS 27, the current SDK 26.5 build
renders that effect with a hard cutoff. The shared `gullsSafeAreaBar` wrapper
hosts the scroll content and bar controls separately on that system, with a
transparent Core Image blur layer between them. It softly blurs content beneath
the controls without adding a second material color. `CIMaskedVariableBlur`
uses a smooth grayscale mask across a restrained transition band, from zero at the
content-facing edge to a subtle 0.2pt maximum radius near the top controls and 0.35pt near the composer.
The default backdrop extends 52pt past the reserved bar, leaving the initial content rows readable.
Its filter output is clipped to that band so the rest of each pane stays sharp.
Scrolling content fades to 16% opacity beneath top controls and 8% beneath the composer, so lower blur
does not leave readable background text overlapping the foreground labels.
The top opacity transition spans 72pt and uses a sampled smootherstep curve, easing into and out
of the fade without an abrupt change at the fully clear edge.
The finite mask follows AppKit's backdrop coordinates; it updates when the
bar moves, resizes, or changes backing scale, rather than during scrolling.
Native edge effects are disabled to avoid a second boundary. The blur stays
mounted and needs no window-focus updates. Bar heights follow their content.
Overview, Messages, and Gulls use a smaller top treatment: a 16pt blur extension, 0.1pt maximum
radius, and a 36pt opacity transition ending at the title bar's lower edge.
Their foreground controls stay above the backdrop and remain fully readable. They use the same
custom host on macOS 26 to keep the native effect from adding a stronger blur.
Liquid Glass remains on the composer and compact message header controls.
Overview, Messages, and Gulls keep their title in a fixed top row. Supporting
details and full search/filter controls scroll with the content. On macOS 15
and later, compact actions appear as those controls leave the viewport; macOS
14 keeps the compact actions available throughout. Messages keeps one search
control in an overlay: it follows its reserved position in the list and
shrinks into a circular magnifier 8pt below the title's lower edge. Further
scrolling carries the search, filter, and information buttons upward until
they align with the title. A gentle spring animates the search width, while ordinary
scroll tracking stays immediate. Reduce Motion disables the spring.
Clicking it expands the same control into a focused field below the title;
Escape or its close button collapses it without clearing the query and
returns the row to its current scroll position. Scrolling back to the top
restores its full width in place. The title remains visible throughout.
Gulls uses the same two-stage search control, with its Save a Gull button
following the search row as it scrolls and expands.
Both searches remain available through Command-F.
Active searches and filters retain a tinted icon, and message history notices
remain accessible from an information button while scrolled. The title row
does not change height, so scrolling never resizes its reserved safe area.
The message header keeps the sender
and routing information at opposite edges. The reply composer and its replacement draft review
share regular native Liquid Glass on macOS 26 and later, with an ultra-thin material on
older systems. The scroll edge backdrop blurs text beneath the composer while
the glass retains backdrop colors and refraction. Foreground text stays opaque.
Only the reply surface has a light outline; the scroll edge fades into the
canvas without a frame or separator.
Messages can scroll behind the composer; its bottom safe-area
bar keeps the final message reachable above it. The flat sidebar and borderless
window header keep the large surfaces quiet in both
active and inactive windows; text fields and buttons retain normal focus.
Safe-area bars and insets reserve room for the headers, footer, and reply
controls so the final row remains reachable. macOS 14–25 use flat scroll
edges. Reduce Transparency uses an
opaque composer and canvas, and hides the scroll effects. Scroll
indicators stay hidden while trackpad, mouse, and keyboard scrolling remain
available. Native scrollers remain installed for the system edge effects,
with their drawing masked once after layout. Scrolling does not update those
masks or their opacity. The native bars
reserve header/footer space without duplicate hidden controls.
Message selection uses a short crossfade; the reply and draft review
share a stable material container during size changes. Reduce Motion disables
these transitions. The sidebar animates its width while keeping the list and
detail mounted, with a draggable edge for resizing and a top toggle. Only the
draft review measures its height relative to the window.
Technical message details remain available in a disclosure.

The compact composer uses icon actions for drafting, clearing, and sending;
the empty placeholder names the recipient. The draft action uses the shared
seagull wing mark with a blue-to-purple gradient.
Settings opens in an 800 × 580 native window, keeping the inbox
available alongside it. Navigation groups personal settings, Gulls, and
administrator controls. Server is always visible; management controls appear only for administrators.
Labels and fields share rows, with transport settings visible inline.
The native macOS close button and Escape dismiss
the Settings window. It uses the same window material, with section headings
inside the scrolling page and no separate pinned title strip. The main window
uses a hidden titlebar with native traffic lights and background dragging.
Its controls are individual native Liquid Glass buttons above one continuous
canvas, with no full-width toolbar material. Top bars reserve 48pt for those
controls while their scrolling content extends to the actual window top.
Overview, Messages, and Gulls share this layout. Settings retains its native window chrome.
Editable
fields use clear glass with a light outline, while actions use native glass
buttons on macOS 26. Older systems retain material fields and standard buttons;
Reduce Transparency uses opaque fields and a flat canvas.
Allowance bars show remaining account and server credits; Gull bars show
each Gull's share of recorded token usage. Recent activity, allowance changes,
and local results are visible, with **Show all** controls for longer histories.
Server management shows service health, provider, routing, and activity sections inline.
This Mac keeps the connection list visible above the selected Gull's commands,
folder permissions, and connection settings. There are no nested Settings pages
or back controls. Individual local actions still open a review sheet before
approval; large result outputs use disclosures.
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
- The runtime also owns a private SQLite message history shared with the CLI.
  Messages search and older-message pages query that history; live inbox
  snapshots remain separate for notifications. Existing snapshots are imported,
  and cursor-based backfill resumes after restart. Dashboard aggregates count
  synchronized history without loading all message bodies. Server pagination
  must be deployed to backfill beyond the newest inbox page.
- Conversations opened from Messages use a separate local-first cache in
  `Application Support/Gulls/conversation-cache.json`, scoped to the signed-in
  account and local connection revision. Cached messages and pagination cursors
  appear immediately and refresh in the background. A new outgoing message is
  durably written to the outbox before the CLI request starts; its stable UUID
  is sent as the idempotency key. Network failures stay as **Not confirmed**
  until the owner retries, while an acknowledged message remains visible if a
  just-finished thread refresh has not caught up yet. Only never-attempted
  queued messages younger than six days resume automatically; an in-flight
  send is restored as unconfirmed after relaunch.
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
| `post --to <handle> [--thread-id <id>] -- <content>` | `{message_id, thread_id, ...}` |
| `thread <id> --limit N` | `{thread_id, messages: [...]}` |
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
  A website- and account-scoped snapshot restores Gulls, usage, and server status
  before network checks finish. Token rotation keeps the same snapshot. Expired
  sessions can still display saved messages, while cloud requests wait for
  sign-in. Temporary connection errors preserve the workspace; rejected sessions
  and explicit sign-out clear the corresponding account snapshot.
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

Monitoring runs in the app-owned CLI child while Gulls remains running.
An independent service surviving Quit, launch at login, and a Local AI worker
are not included in this implementation. A sleeping or powered-off Mac cannot
receive messages until it wakes and reconnects.
