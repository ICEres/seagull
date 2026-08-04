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

SwiftUI macOS app for supervising a local agent — the GUI equal of the
[`gulls` CLI](../../connect/local-agent/README.md). The CLI is for coders; this
app covers the same core inbox flow for everyone else:

- Inbox as a decision queue: the default filter and the Dock badge both
  show deliveries awaiting a decision; search and status filters in the
  toolbar (customizable via right-click → Customize Toolbar…)
- Background polling plus optional WebSocket push (instant refresh via
  `gulls stream`), always on — one toolbar status item shows stream/poll
  health, last check, and a Pause Notifications toggle
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
- Settings with Keychain-stored connector token and one-way import from
  `~/.config/seagull/env`

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

The WebSocket stream is an Inbox wake-up channel, not a Live A2A session.
Push carries no durable conversation state; the app always re-fetches Inbox as
the source of truth.

## How it works

The app **bundles the gulls CLI binary** (universal arm64 + x86_64, built by
`scripts/build-gulls-binary.sh` in a run-script phase) and shells out to
`gulls --json <command>` for every operation. The CLI stays the single source
of truth; the app adds no second transport implementation.

Key mechanics:

- Global flags precede the command: `gulls --json inbox --limit 100`
  (Go's `flag` package stops at the first non-flag argument).
- Config is passed to the subprocess as environment variables;
  `SEAGULL_AGENT_ENV_FILE` is pointed at a nonexistent path so the app's
  settings are the only config the subprocess sees.
- Exit codes: `0` success, `1` runtime/hub error (stderr text is shown),
  `2` usage/config error (surfaced as "check Settings").
- One-shot CLI invocations are strictly serialized (FIFO) inside the app.
  Swift actors are reentrant, so `GullsCLI` chains each command on the
  previous one — the CLI reads and writes shared files under the context
  dir, and two subprocesses must not overlap. The long-lived `stream`
  subprocess is exempt (read-only). Draft previews for a burst of new
  deliveries are generated by one sequential pipeline for the same reason.
- Polling calls `inbox --json` and diffs by `delivery_id` against an
  app-private notified-set (`~/Library/Application Support/Gulls/`).
  It deliberately does **not** run `watch --once`, which would mutate the
  CLI's `seen-deliveries.json` and suppress a concurrently running
  `gulls watch`. Running both at once at worst duplicates a notification.
  When the notified-set file doesn't exist yet (first launch), the current
  queue is marked as seen without notifying.
- With a Stream URL configured (Settings), the app also runs a long-lived
  `gulls --json stream` subprocess and treats each NDJSON event as a wake-up:
  it re-fetches the inbox immediately (push = wake-up, poll = truth). The
  fallback poll stretches to ≥90s while the stream is connected (green bolt
  in the toolbar) and returns to the normal interval when it drops. The
  subprocess handles WebSocket reconnects itself; if it exits unexpectedly,
  the app restarts it with backoff (5s → 60s) — except on a config-fatal
  exit (code 2: bad URL/token/scope) or a launch failure, where it stops
  and shows the reason in the status item instead of respawning forever.

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

Prerequisites: Xcode 15+ (macOS 14 SDK), Go, [XcodeGen](https://github.com/yonaskolb/XcodeGen)
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

Settings (⌘,) holds the Message Hub API URL, agent handle, connector token,
poll interval, and context directory.

- The token is stored in the **Keychain** (service `ai.gulls.mac`), never in a
  file. It's written when you press Return in the field or close Settings —
  not on every keystroke.
- "Import from `~/.config/seagull/env`" copies values one-way from the CLI's
  config file. The app never writes that file.

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

`post`, `route add`, and thread/context browsing exist in the CLI only.
App Nap may pause polling while the window is hidden; use the CLI's
`gulls watch` for always-on monitoring.
