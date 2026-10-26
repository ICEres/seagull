# Codex Integration Implementation Plan

Status: Authoritative (delivery).

Last updated: 2026-10-26.

## Delegated reply delivery — October 26 update

The owner-approved extension changes the reply boundary for **new, explicitly
handed-over source deliveries**. It does not enable unattended handling of every
incoming message. The phase records below describe the earlier draft workflow;
this section supersedes their draft-only statements for authorized tasks.

- Each connected Gull has **Send replies automatically**, enabled by default,
  in its Mac settings. This preference is local to this Mac and profile. Turning
  it off freezes unsent automatic work for review. Turning it back on applies to
  new delegations; it never publishes old review items.
- New request artifacts carry `reply_authorization_id`, paired with a private
  SQLite outbox record. Legacy requests and owner-only tasks have no publishing
  authorization. Ordinary Codex output and `result.json` remain private.
- Embedded execution exposes `gulls_reply(content)` with no recipient or Gull
  override. External agents use scoped `gulls codex reply` to write `reply.json`.
  Both submit exact public text to the same outbox. Neither copies the result
  into the owner's composer or regenerates it with another model.
- The lifecycle is Working → Sending → Sent, or Needs review → Approve & send.
  Sent requires a matching server message ID. The message appears as the Gull;
  Codex work and operation approvals remain private and secondary.
- Take over durably revokes unsent publication before stopping execution and
  retains submitted content for editing. All Mac manual-decision surfaces use
  the same revocation guard. A dispatched reply with an unknown outcome must be
  reconciled before another response; a missing receipt permits an explicit
  retry with the original key, not a blind automatic resend.
- Hub publication atomically creates the outgoing message and completes the
  source delivery. Stable source-bound keys support replay and receipt lookup.
  Mac uses only the new authenticated reply-publications endpoint; an older
  server fails closed, without falling back to legacy reply transport.
- Commands and file operations still require individual Mac review. App-owned
  execution lifetime is unchanged; independent post-quit execution remains a
  later phase. No production send, push, or deployment is part of this change.

Deployment requires the updated message-hub routes before distributing the new
Mac/CLI publication flow. Plugin source instructions are updated in the repo;
an installed cached plugin is not silently changed by this implementation.

Validation for this extension uses isolated profiles and simulated services:
the full native suite passed 317 tests (one live-model opt-in skipped), followed
by focused outbox and integration regressions as recovery cases were added.
The CLI full Go suite passed. Message-hub discovery passed 322 tests with
`boto3`/`moto`, and all five cross-service local-runtime tests passed. Additional
terminal-hook and transaction regressions passed in the focused backend suite.
No real Gull reply or paid model turn was used for these checks.

Implementation state: Phases 0–2 are implemented and passed automated and live
Codex verification. The local plugin and Mac App have been installed; first-launch
UI verification is waiting for macOS Keychain authorization. Phases 3–5 remain
planned. No push, cloud deployment, or service registration was performed.
Baseline: `a099e67` on `main`.

Make Codex useful inside an ongoing Gull conversation: the owner selects a
message, Codex continues the relevant private context, and progress, approvals,
and a reply draft return to that conversation. One Mac supports several owned
Gull voices. A working folder remains optional and belongs to the individual
task.

This plan defines delivery order and acceptance gates for the local Codex
connector. [Agent Voice And DNS Discovery](agent-voice-and-discovery.md) remains
the architectural authority; the broader [Migration Plan](migration-plan.md)
continues to govern transport and identity. These changes use the existing
transport; the delegated delivery extension adds scoped Hub publication and
receipt routes. It does not claim that A2A has shipped.

## Implementation record — phases 0–2

The current source implements the first usable release described below. Manual
owner starts remain the activation boundary; inbound notifications do not
create model work. Same-scoped conversations continue a Codex thread only when
the Gull profile, server, connection revision, folder, private instructions,
policy, and route still match. Each turn keeps its own immutable request and
result artifacts.

- Phase 0 includes explicit multi-Gull routing, readiness checks with a minimum
  supported Codex CLI version of `0.146.0`, sign-in/model/protocol states, and
  plugin version `0.1.1+codex.20261024`. It was refreshed with
  `codex plugin add seagull@seagull-project`; the installed manifest and skill
  match the source. Cached files were not edited manually.
- Phase 1 includes scoped conversation records, bounded remote context with
  stable message IDs, incremental context inclusion, route isolation, and
  additive migration of legacy task artifacts.
- Phase 2 includes a durable owner-started queue with a maximum of two active
  turns globally and one active turn per Gull, explicit queued state, approval
  pauses, conservative uncertain dispatch recovery, and conversation UI
  actions for progress, review, status checks, and draft use.
- A lost Codex acknowledgement becomes `uncertain`. The owner must use
  **Check status** before another attempt; the app never silently replays a
  possibly accepted turn.
- Draft disposition is source-bound and records `available`, `used`, `sent`,
  `discarded`, or `superseded`. A draft is marked `sent` only after the exact
  source delivery succeeds.
- External continuation copies a scoped handoff and opens the exact recorded
  Codex thread. The owner must paste the handoff into Codex; documented deep
  links do not prefill an existing composer. Embedded and external routes never
  share execution ownership.

The Mac suite ran 296 cases with one opt-in case skipped and zero failures;
the local CLI passed `go test ./...`. The opt-in live test passed separately
using two low-effort model turns, an isolated temporary profile, and local
drafts only. No Gull message was sent.
The implementation record does not claim phases 3–5, automatic drafts,
post-quit background execution, broader capabilities, A2A, or cloud deployment.

## 1. Decisions and scope

- Keep the Gull as the public identity. Codex is a private execution capability.
- Reuse the Swift app-server adapter, Go message runtime, local SQLite stores,
  task handoffs, and exact-operation approval broker.
- Deliver owner-started conversation continuity first. Automatic drafting and
  independent background operation are later, separately enabled milestones.
- Legacy tasks return drafts through the existing composer. New delegated
  message tasks submit a separate public reply under the owner's per-Gull
  delivery preference. Owner-only tasks remain private.
- Project file reads, writes, and commands continue to require explicit Mac
  review. A selected folder, incoming message, or private prompt is not approval.
- Preserve the current Mac layout, Gull avatars, purple accent, settings
  structure, and three-column behavior. Add contextual state, not another task
  management screen.
- Do not add payment, a hosted Codex worker, iPhone execution, a second public
  Codex identity, or a permanent Gull-to-project assignment.

## 2. What exists and what needs changing

| Existing component | Keep | Change |
| --- | --- | --- |
| Codex plugin and skill | Shared CLI commands and scoped Mac handoff instructions | Publish a fresh plugin version and make multi-Gull selection explicit |
| `CodexAppServer` | Local stdio JSON-RPC, streaming, cancellation | Readiness checks and version-specific request validation |
| `CodexExecutionCoordinator` | Thread/turn execution and brokered local actions | Resolve conversation context and run one immutable request per turn |
| `CodexTaskStore` / `CodexSessionDatabase` | Private artifacts, request digest validation, persisted execution state | Durable conversation association, queue, and recovery records |
| Go `gulls runtime` | Multi-profile polling, IPC, inbox SQLite, history | Sanitized profile discovery and durable dispatch inputs |
| `LocalControlStore` | Exact request review, folder scope, file-change checks, recovery | Separate execution from UI observation when moving into the service |
| Mac lifecycle | Work continues after closing the window | A separate service is needed to continue after quitting the App |

The pre-continuity baseline association was `taskID → codexThreadID`. Incoming
deliveries did not automatically create Codex turns, and the external Gull
thread was only source metadata. Phases 1–2 now add the scoped conversation and
turn records described below; inbound deliveries still do not create model work
without an owner start.

At the planning baseline, the installed plugin lacked the Mac task handoff and
`gulls codex result` guidance. The supported local refresh now installs the new
skill, including both the `Multiple Gull Profiles` and `Mac Task Handoffs`
sections. Already-open Codex chats may require an App restart to load the new
plugin; the active development chat was not restarted.

The installed CLI inspected for this plan is `codex-cli 0.146.0`. Its generated
schema supports the main adapter methods, but `ThreadResumeParams` does not
declare `environments`. Resume requests now omit that field; start and turn
requests retain their supported empty environment lists.

## 3. Delivery sequence

| Phase | Deliverable | Depends on | Exit gate |
| --- | --- | --- | --- |
| 0 | Plugin freshness, explicit Gull selection, Codex readiness | None | Automated checks and supported plugin refresh passed |
| 1 | Conversation association and immutable turn records | Phase 0 contract | Implemented; native automated suite passed |
| 2 | Durable queue, recovery, conversation UI | Phase 1 | Implemented; native automated suite passed |
| 3 | Optional automatic drafts | Phase 2 | Only eligible new messages create bounded draft work; nothing sends automatically |
| 4 | Independent Mac background service | Phase 2; phase 3 optional | Quit/reopen, service ownership, Keychain, approval, and upgrade checks pass |
| 5 | Broader Codex capabilities, only when needed | Phases 0–2 | Each added capability has a tested permission and recovery contract |

**First usable release: phases 0–2.** It improves continuity and reliability
inside the existing App lifetime. It does not need a cloud deployment or a
background-service installation. Phase 3 can ship while execution is still
App-owned, provided the UI states that lifetime accurately.

## 4. Phase 0 — Make the existing integration dependable

### Plugin and multiple owned Gull voices

1. Update the plugin release version using the supported plugin update flow.
   Verify the installed skill matches the released source. Do not edit cached
   plugin files in place.
2. Reuse `gulls --json runtime status` for discovery. Add only the sanitized
   profile metadata needed to display the Gull name/handle, connection status,
   profile ID, and revision. Never expose environment maps or credentials.
3. Keep the exact profile and revision in every selected command. A Mac task
   handoff already identifies its Gull; use it directly. For an ordinary inbox
   request with multiple profiles and no selection, ask the owner to choose.
   An explicit all-inboxes read may aggregate results with their profile labels.
4. Never silently switch from an unavailable runtime profile to the ambient
   `~/.config/seagull/env` account. Standalone CLI use remains supported through
   an explicitly selected configuration.

### Readiness and protocol compatibility

1. Add a small `CodexReadiness` service: executable discovery, version, protocol
   initialization, account/login readiness, model availability, and required
   capability checks. Run no paid model turn as a health check.
2. Expose distinct states: `Ready`, `Codex not installed`, `Sign in required`,
   `Unsupported version`, and `Connection failed`. Keep the useful recovery
   action next to the state in the existing Codex settings section.
3. Build start, resume, and turn parameters separately against tested schema
   fixtures. Unknown approval/tool requests remain rejected. An unsupported
   experimental interface must not silently gain extra capabilities.
4. Document the tested CLI version and update procedure. Use paginated history
   methods only when that version supports them; a missing recovery method
   results in owner review rather than a guessed replay.

**Files:**

- `connect/codex/plugin/.codex-plugin/plugin.json`
- `connect/codex/plugin/skills/seagull/SKILL.md` and `connect/codex/README.md`
- `connect/local-agent/internal/agentcli/runtime.go`, its tests, and CLI docs
- `apps/mac/Gulls/Services/CodexAppServer.swift`, new `CodexReadiness.swift`
- `apps/mac/Gulls/Services/CodexExecutionCoordinator.swift`
- `apps/mac/Gulls/Views/CodexCapabilitySettingsView.swift`
- `apps/mac/GullsTests/CodexAppServerTests.swift` and new readiness tests

Paths in phase file lists are relative to `packages/gulls/`.

**Acceptance:** two profiles can be discovered and explicitly selected without
credential output or fallback to the wrong Gull; the source plugin release
contains the handoff instructions; missing login and unsupported protocol
fixtures show actionable states before task dispatch. Refresh future plugin
releases through the supported installer; the current installed release was
verified against source.

## 5. Phase 1 — Associate Codex with the conversation

### Private records

Extend the existing Codex SQLite database with versioned, additive tables.
Keep the Go history database as the only owner of inbox history; Swift must
not open it directly. Do not copy the entire Codex transcript into another DB.

| Record | Required fields and purpose |
| --- | --- |
| Conversation association | Local association ID; trusted server/connection identity; owner profile ID; connection revision; local conversation ID; external thread ID when present; verified participant IDs; active context revision |
| Execution context | Association ID and context revision; persisted embedded or external-App route; route-specific Codex thread ID; private workspace path; selected folder scope; permission-policy digest; authenticated owner-instruction digest |
| Turn | Local turn ID; association/context IDs; source message and delivery IDs; durable owner request ID when manually started; immutable task ID and request digest; input/context digest; queue sequence; Codex turn ID; execution and draft state |
| Attempt | Turn ID, attempt number, dispatch intent, observed Codex IDs, timestamps, failure/recovery reason; previous attempts remain inspectable |

These are local connector records, not new public identity or A2A objects.

### Identity and context rules

1. Define one canonical scoped key: a deterministic serialization of
   `(ownerProfileID, normalized API base URL, connectionRevision,
   localConversationID)`. Normalize scheme/host/default port consistently while
   preserving a meaningful base path. Store its digest and validate the raw
   fields, external thread, sender, and recipient IDs on lookup. A handle alone
   is never sufficient; two servers with identical thread IDs remain separate.
2. For an incoming thread without a Mac conversation record, create the local
   association from a verified scoped thread. Reuse only a unique match. A
   standalone task or ambiguous source remains task-scoped.
3. Reuse a Codex thread only inside the same association and execution context.
   Folder, execution route, approval policy, or authenticated private instruction
   changes create a fresh context and Codex thread. Previously read file content
   must not leak into a task whose scope no longer includes that folder.
4. Folder selection stays on the individual task. Do not silently inherit a
   previous folder, infer one from a message, or save one as the Gull's project.
5. Keep the current connection revision check. It presently includes operational
   settings such as polling interval, so some harmless changes also invalidate
   continuity. Accept that conservative behavior in this release; redesigning
   identity revisions is a separate migration.
6. Keep embedded and external Codex App execution distinct. Never manage the
   same Codex thread concurrently from both. Opening a Codex deep link prefills
   or opens a task; it does not prove that an owner started or completed a turn.
   Persist the route before dispatch and enforce it on enqueue, resume, and
   result import. An external task cannot be claimed by the embedded worker.
   Reject a returned thread ID already owned by another profile or route.
7. Give each embedded execution context one stable private workspace under
   `codex-contexts/<contextID>/workspace`. Use it for Codex `cwd` and runtime
   workspace roots across turns; immutable task directories remain separate.
   Gulls supplies their validated snapshots as input. The selected project
   folder remains broker scope, never Codex's native working directory.
   External continuation opens the exact external thread and supplies the new
   scoped handoff for the owner to start; it does not reuse the embedded workspace.

### Turn creation and context

- Every new message, owner follow-up, or deliberate regeneration creates a new
  task request and result artifact. Do not overwrite an earlier task's result
  when continuing a conversation.
- Preserve task/result format version 1 and its exact-byte digest checks in
  this phase. Store new associations in the private DB, bound to the task and
  request digest. Local-action provenance version 2 is a separate contract;
  retain its checks without confusing these version numbers.
- Persist the source association before making the task dispatchable. Use a
  staging directory plus a durable prepared/ready transition so a crash between
  file creation and SQLite commit cannot publish an unassociated request.
- At result import, resolve the committed association through the exact task ID
  and request digest, then validate source, route, profile, context revision,
  and any returned Codex thread ID. An early or mismatched result is quarantined
  rather than attached by proximity. A valid result without a verifiable session
  ID may supply a draft but cannot establish reusable Codex context.
- Snapshot the selected message and bounded conversation context through the
  current CLI/runtime. Keep remote content separate from owner instructions.
  Continue with newly included messages and confirmed owner replies, tracked
  by stable IDs; an unsent Codex draft must never appear as a sent Gull reply.
- If required context or private instruction retrieval fails, leave the turn
  blocked with an explanation. Do not fill a history gap by borrowing a different
  conversation or treating an incomplete cache as complete.

### Migration

Use a transactional schema version and a private backup before first migration.
Keep legacy rows and task artifacts intact. Associate old tasks for display only
when their source/profile/revision can be verified uniquely. Leave ambiguous
ones unlinked. Do not automatically merge old task threads or choose the most
recent Codex thread. Continuing a legacy task remains available; opting into
conversation continuity creates a new context unless explicitly and safely
adopted by the owner. An interrupted migration must be safe to rerun.

**Files:** `Models/CodexTask.swift`, new private conversation/turn models,
`Services/CodexSessionDatabase.swift`, `Services/CodexTaskStore.swift`,
`Services/CodexExecutionCoordinator.swift`,
`Services/GullConversationStore.swift`, and their Mac tests.
All paths in this paragraph are under `apps/mac/Gulls/`, except tests under
`apps/mac/GullsTests/`.

**Acceptance:** three messages in one conversation and unchanged scope use one
Codex thread but three immutable task/result pairs. Another Gull, another
server, another conversation, or a changed folder/policy cannot reuse it. Old
tasks still open, and repeated migration does not alter their request digests.

## 6. Phase 2 — Queue work and show it in the conversation

### Queue and execution ownership

Add `CodexWorkQueue` over the same private database. Only explicit owner starts
enqueue work in this phase. Repeated notifications alone do nothing.

- One active turn per Codex conversation context; FIFO order for its successors.
- Initially retain one active turn per Gull. Different owned Gull voices can
  progress independently under a maximum of two active turns globally. Do not
  add arbitrary same-Gull parallelism in the first release.
- Deduplicate source messages within the scoped conversation, using message ID
  with delivery ID as a fallback. Without either, require a manual task.
   Duplicate starts return the existing work. Persist an `ownerRequestID` before
   enqueueing a manual follow-up, and reuse it for retries of that UI action.
   Explicit regeneration creates a new owner request and revision.
- Persist `queued → starting → working / needsApproval → draftReady`, with
  `failed`, `cancelled`, `interrupted`, and `uncertain` outcomes. Track draft
  disposition separately: `available`, `used`, `sent`, `discarded`, or `superseded`.
- Completion may release the next eligible turn. An unresolved approval,
  failure, or uncertain dispatch pauses successors in that conversation.

### Recovery

1. Persist dispatch intent before `thread/start` or `turn/start`; save returned
   IDs immediately. Record acknowledgment separately from intent.
2. Work never dispatched can resume after validation. A crash or timeout after
   dispatch can mean Codex accepted the request: reconcile known thread/turn
   state before deciding what happened.
3. Do not match a turn by text similarity or assume the latest turn is ours.
   Persist a dispatch nonce and exact input digest with intent. Reconcile only
   using a known Codex turn ID or supported history that preserves that exact
   submitted input/nonce in the expected thread; generated text is not proof.
   Otherwise persist `uncertain` and require owner recovery. Do not
   automatically replay possible side effects.
4. Preserve partial output as partial, never as a completed draft. A worker
   restart invalidates pending operation approvals and uses the existing
   abandoned-action cancellation path. Resume requires fresh valid scope and
   review, not restoration of an old approval grant.
5. Keep previous attempts. UI reconnection to a still-running worker is not a
   worker restart and must not cancel healthy work or pending reviews.

This provides deduplication and conservative recovery, not an exactly-once
guarantee for external model execution.

### Mac interaction

- In Messages, show `Work with Codex` for a new context and `Continue with Codex`
  when a valid association exists. Keep the selected Gull and source message
  visible in the setup sheet, with an optional folder for this task.
- Show compact progress, `Review operation`, and `Draft ready` inside the
  existing conversation. Preserve text selection and reading position as
  streamed updates arrive; batch UI updates instead of relaying every token.
- Reuse the current exact-operation review UI. Put actionable errors next to
  the task; avoid a new bottom popup or deep settings subpage.
- `Use draft` revalidates the task, source message, destination, and revision
  before copying into the existing composer. A newer incoming message leaves
  the old draft visible but marked as belonging to an earlier message. It must
  not silently become the reply to the newer message.
- Sending uses the existing durable outbox. Mark a draft `sent` only after its
  specific send is confirmed; uncertain network sends stay unresolved.
- Reuse Overview for counts of active work, pending reviews, and available
  drafts. Per-Gull settings show readiness and recent work without adding a new
  top-level Codex navigation destination.

**Files:** new `Services/CodexWorkQueue.swift`; existing coordinator, task store,
database, conversation store and lifecycle services; `Views/MainWindow.swift`,
`GullConversationView.swift`, `CodexTaskSetupView.swift`,
`CodexTaskResultView.swift`, `CodexCapabilitySettingsView.swift`,
`DashboardView.swift`; relevant Mac tests.

**Acceptance:** repeated message starts and manual-follow-up retries create one
queued turn per owner action; crashes at each dispatch boundary never blindly
rerun it; old drafts cannot enter another message's
composer; two Gull voices remain isolated; closing a window preserves work,
while quitting the App clearly interrupts it in this release.

## 7. Phase 3 — Offer bounded automatic drafts

Add an optional per-Gull `Automatically prepare drafts` setting, off by default.
This is separate from enabling Codex and from the cloud reply mode.

1. Only accepted inbound messages from owner-selected conversations/contacts
   are eligible. Unknown, blocked, quarantined, outgoing, and self-originated
   events do not dispatch. Do not introduce a new trust-classification system.
   Store selected stable IDs and the configuration revision per Gull beside
   its Codex preference. Eligibility also requires the intended active Local
   reply mode and pairing; do not run alongside a cloud auto-reply path.
2. Record an activation boundary so enabling the setting does not replay the
   existing inbox. Decide eligibility from persisted messages, not transient
   notification delivery; reconcile after reconnect using the same dedup keys.
   Establish a synchronized source baseline before activation, persist excluded
   existing source IDs plus its cursor/watermark, and suppress older backfill.
   A wall-clock activation timestamp alone is insufficient. Revision or
   selection changes cancel ineligible queued automatic work and require a
   fresh baseline for newly selected conversations.
3. Automated tasks have no project folder or local operation authorization.
   Requests needing either pause for owner setup and exact-operation review.
4. Authenticate private reply guidance and check connection revision before
   dispatch. Stop new work when the Gull is disconnected, paused, revoked, or
   Codex is disabled. Define queued-work cancellation explicitly in the UI.
5. Bound pending work, concurrent turns, output size, and retry count. Begin
   with one automatic attempt per source message; a failure requires review.
   Expose a daily run cap and pause action. Reaching a cap preserves pending
   source work without starting further turns.
6. Keep Codex accounting separate from hosted OpenAI API usage. Do not invent
   a dollar balance for subscription-backed Codex usage. A run cap bounds
   frequency; it is not a provider billing cap.
7. No automatic `reply`, `post`, `ack`, or `ignore`. Inbound text and other agent
   replies never authorize a send, preventing autonomous reply loops here.

**Files:** queue, `GullsConfig.swift`, `GullsWorkspace.swift`, runtime event
consumer, Codex settings, and queue/eligibility tests. Add runtime IPC fields
only if a durable source needed for reconciliation is unavailable today.

**Acceptance:** enabling the feature leaves old inbox history untouched;
duplicate, self, blocked, and out-of-scope events start zero extra turns; caps
pause work; every completed turn remains a private draft.

## 8. Phase 4 — Run independently of the Mac UI

### Process structure

Keep execution in Swift rather than reimplementing the app-server protocol in
Go. Extract non-UI services into a shared target and add a bundled per-user
`GullsAgentService`. Prefer the supported `SMAppService` LaunchAgent lifecycle;
verify packaging, signing, Keychain access, and background-item registration
in a small buildable spike before migrating ownership.

```text
Gulls.app — conversation UI, owner approvals, explicit sends
    │ authenticated NSXPCConnection
    ▼
GullsAgentService — queue, Codex execution, configuration, lifecycle
    ├── Codex app-server — private threads, streaming, model execution
    └── gulls runtime — multi-Gull sync, inbox/history SQLite, scoped commands
```

The agent runs in the logged-in user's session, not as a privileged system
daemon. Closing or quitting the UI can leave it running when enabled. Sleep,
logout, shutdown, or a locked credential store are distinct states; do not
promise execution while the machine is asleep or the user is logged out.

### Ownership and IPC

1. Extract the transport, task persistence, queue, coordinator, and local action
   validation/execution into the shared target. SwiftUI observable stores become
   clients of snapshots/events. Keep the service free of window dependencies.
2. The service exclusively owns Codex SQLite writes and the Codex process. It
   supervises the existing Go runtime, which remains the inbox/history owner.
   The GUI must not start another executor or open either database for writes.
   Move the existing `runtime serve --stdio --socket ...` launch and NDJSON
   profile configuration into the helper. Once service ownership is committed,
   the GUI only consumes helper snapshots/events and sends scoped requests.
3. Add versioned handshake, snapshot, event cursor/resync, enqueue, cancel,
   pause, and approval operations. Approval messages bind the exact operation
   digest, task, connection revision, folder, and reviewed file state.
4. Use `NSXPCConnection` with peer code-signing/identity validation for
   GUI-to-service mutations. Prove the identity check with supported APIs in
   the deployment-target spike. Reuse the private Go socket for existing CLI
   commands; do not expose a generic CLI endpoint that grants Mac approval.
5. Keep external `gulls codex result` as its immutable file handoff. The service
   validates and imports the result; the CLI does not become a second database
   writer. External Codex App work remains owner-started.

### Credentials, approvals, and migration

- Migrate the App's profile registry and non-secret configuration into an
  atomic, versioned service-readable store. Preserve stable profile IDs. The
  App becomes a configuration client after handover, not a second authority.
- Keep tokens in Keychain. Verify the signed helper can read the intended
  items/access group before enabling it; ad-hoc development signing may require
  user interaction. Never copy tokens into plist files, arguments, logs, or
  ordinary config. Pass tokens to the Go child through the existing private
  pipe. Codex continues to own its login credentials.
- If credentials need unlock or reauthentication, report that state and wait.
  Do not create repeated prompts or restart loops. Sign-out/revocation must
  clear active configuration, pause dispatch, and invalidate stale requests.
- Without the GUI, new project operations wait for review. An already approved
  and started exact operation can finish within its recorded scope. The receipt
  binds its operation ID and reviewed digest; it authorizes no retry, widened
  scope, or successor. Reopening the App shows pending reviews; no broad
  permission is inferred from background mode.
- Quiesce App-owned execution, preserve artifacts, stop its children, then
  transfer ownership under an exclusive process lock. Verify service handshake
  and state before marking migration complete. Persist the handover states
  `app → transferring → service`; the process lock is the live ownership
  authority, not the marker alone. Inject crashes at each boundary and prove
  neither recovery nor fallback can produce two owners.
- On IPC loss, reconnect first. Do not launch an App-owned fallback merely
  because the service did not answer. Fallback requires proving the service is
  stopped and acquiring exclusive ownership; otherwise remain disconnected.
- Unregistering the background service stops work and preserves history and
  drafts. Upgrades quiesce active work, use compatible IPC, and recover uncertain
  turns conservatively. Repeated crashes pause dispatch instead of consuming
  unlimited model calls.

**Files:** `apps/mac/project.yml`, new shared service target and helper target,
packaging/signing configuration, `AppLifecycleCoordinator.swift`,
`GullsWorkspace.swift`, `GullsRuntime.swift`, `LocalConnectionsStore.swift`,
`LocalControlStore.swift`, Codex services, and service integration tests.

**Acceptance:** use a signed, installed App/helper build to prove registration,
login startup, background-item consent/disable, relocation, upgrade, and removal.
Verify access to existing per-profile Keychain items and the intended access
group; no request for profile A may receive profile B's token. Locked Keychain
and revocation must pause safely. A draft can finish after quitting the GUI;
reopening attaches to that run; local operations wait without the GUI; an
unrelated local process cannot enqueue, resume, or approve work through helper
IPC. Only one runtime and executor own state, including after a transfer crash.

## 9. Phase 5 — Expand capability only behind a defined boundary

The embedded policy currently disables native shell, filesystem tooling,
browser, images, plugins, hooks, and delegation, exposing the Mac local-action
broker instead. Do not describe this as full Codex parity.

Retain this profile for the initial release. Add a capability only for a proven
workflow, one at a time, after defining its data access, owner review, runtime
support, cancellation, and restart semantics. Native shell/file approval APIs
cannot be enabled if they allow operations that bypass the owner's every-action
review requirement. Plugin, MCP, and hook tools need their own scope review.

The full Codex App can remain an optional handoff route. Its skill instructions
are guidance, not an enforced sandbox; do not claim that handoff provides the
same technical containment as the embedded restricted adapter.

The existing Swift adapter can deliver these phases without an SDK rewrite.
Do not use the removed `codex mcp-server` command. A future Gulls MCP tool server would
be a separate interface to the same scoped runtime, not a second execution or
messaging implementation. Hooks are not an incoming-message delivery service.

## 10. Verification and release gates

### Verification record — 2026-10-24

- Mac: `xcodebuild test` for scheme `Gulls`, destination `platform=macOS`,
  using `/Applications/Xcode.app/Contents/Developer`: **296 cases, one opt-in
  live test skipped, zero failures**. Derived data and test artifacts are outside
  the repository.
- Final Mac Release `xcodebuild build` and deep code signature verification:
  **passed**. Settings readiness runs independently of bundled Gulls CLI
  availability and uses the same compatible private catalog as execution.
- Local CLI: `go test ./...` from `connect/local-agent`: **passed**, including
  the loopback end-to-end suite and runtime status redaction checks.
- Covered continuity through three distinct incoming messages, one confirmed
  owner reply, one Codex thread, and three immutable turn results. Unsent
  drafts are not reinjected as owner replies.
- Covered queue limits, approval pauses, duplicate starts, scoped routing,
  migration/publication recovery, uncertain dispatch without replay, and both
  embedded and imported external result tampering.
- Opt-in `CodexLiveIntegrationTests`: **passed** with the real app-server and
  `chatgpt-new/gpt-6-luna`, low reasoning effort, and a temporary Gull profile.
  Two turns reused one Codex thread; the second retrieved a synthetic marker
  supplied only in the first. Both immutable result files and available draft
  states were verified. No working folder, local control, inbox, or reply API
  was used, and the owner's Codex configuration was unchanged.
- Local plugin `0.1.1+codex.20261024`: **installed and verified against source**.
  The Release App was installed at `~/Applications/Gulls.app`. Both existing
  `gulls` and `seagull` command aliases now point to its bundled CLI, replacing
  stale standalone links that did not support explicit profile selection.
- `git diff --check`: **passed**. Regular tests use fake app-server responses
  and temporary stores; real model work requires the explicit opt-in live test.
- Initial installed App GUI verification: **passed** after macOS Keychain authorization.
  The main window opens and Settings → This Mac → test2 shows `Codex ready`
  with Codex CLI `0.146.0` and eight available models. Runtime discovery confirms
  test2 is connected and monitoring. Its per-Gull Codex switch was left off
  during verification. An existing default `@worker:gulls.ai` profile still
  points to an unavailable localhost service and reports reconnecting; this does
  not prevent test2 from connecting.
- Follow-up message-context repair: embedded and external setup now use the
  same preparation path, accept history-only messages from the scoped merged
  inbox, preserve underlying context and thread failures inline, and revalidate
  the profile, connection revision, and message after each asynchronous fetch.
  Authenticated owner instructions still require a successful CLI context fetch.
  Nine regression tests cover historical sources, specific errors, missing
  setup, and connection/message changes during preparation. The Start button
  now also respects Codex readiness.
- The follow-up Release build and installed signature verification **passed**;
  the previous App is backed up in `/private/tmp/gulls-context-update-backup-5n2q12kb`.
  Its first launch initially waited for macOS Keychain authorization, confirmed
  by a process sample in `SecItemCopyMatching`. The installed App opened normally
  during the October 26 UI check below. No additional model turn or Gull reply
  was started during the repair itself. Source changes remain unpushed.
- Automatic drafting, an independent background service, and broader tools
  belong to phases 3–5 and were not implemented in this slice.

### Installed UI acceptance — 2026-10-26

- Used computer interaction with `~/Applications/Gulls.app`, selected the
  connected test2 Gull from the Overview scope, and opened its existing ping
  conversation. Codex was already enabled and readiness showed ready.
- With the owner's explicit authorization for the conversation and private
  reply instructions, completed `Work with Codex` → `Start in Gulls` → draft
  generation → one follow-up → `Use draft`. Both real model turns completed.
- Read-only task metadata confirms both tasks used the same Gull profile,
  connection revision, source delivery, conversation key, and Codex thread, with
  distinct turns. The first request hash remained unchanged. The follow-up
  draft disposition changed to `used`; neither task was marked `sent`.
- Edited the unsent composer text and selected `Use draft` again. Replacement
  required confirmation; Cancel preserved the edit, and explicit replacement
  restored the generated draft. Left that draft in the composer without sending.
- The check also identified three workspace UX issues: stale default-worker
  messages dominated the initial view, the counterpart displayed a raw agent
  ID, and the sidebar showed a global count beside a scoped message list.
  The local follow-up below resolves these findings.

### Mac workspace UX follow-up — 2026-10-26

- Initial scope prefers the selected paired Gull, then another paired Gull,
  before falling back to standalone profiles. This choice is independent of
  transient network availability and does not delete existing messages.
- Explicit Gull and All Gulls scopes persist across app launches. Overview,
  Messages, and Gulls navigation preserves the scope. The sidebar count and
  accessibility description use the same scope as the visible messages.
- Sender labels use local directory names, public display names, or readable
  handles when available. ID-only historical messages use a short Gull label.
  Raw IDs remain unchanged for routing and grouping, and full handles and IDs
  remain searchable.
- Focused native regression: **59 tests passed, zero failures**. Release build,
  installed application signature verification, and `git diff --check` passed.
- Computer interaction confirmed default test2 scope, matching one-conversation
  sidebar count, readable counterpart labels, and scope preservation across all
  three sections. Explicit All Gulls scope survived a normal quit and relaunch.
  The installed app was left in Messages scoped to test2. This UX verification
  performed no new model runs or message sends. No push or deployment was made.

### Acceptance matrix

| Area | Required checks |
| --- | --- |
| Compatibility | Missing CLI/login; supported and incompatible schemas; unknown tool request; plugin source/install parity |
| Isolation | Same counterpart across two owned Gull voices; two servers with identical thread values; profile/revision change; folder and policy change |
| Continuity | Three incoming messages and one confirmed owner reply; stable private workspace; folder retained/changed/removed; bounded context; independent immutable drafts |
| Routes | External task alongside embedded work; early/mismatched result import; conflicting returned thread ID; explicit external continuation |
| Queue | Duplicate delivery/start and owner-request retry; manual regeneration; cancellation; approval pause; limits; per-Gull fairness |
| Recovery | Crash before/after artifact publication, dispatch intent, returned IDs, local-action association, result import, and send confirmation |
| Uncertain execution | Lost `turn/start` acknowledgment; nonce/digest attribution; missing history capability; partial output; no automatic side-effect replay |
| Drafts | Stale message target; modified result/request; changed destination; explicit send confirmation; uncertain outbox state |
| Migration | Legacy linked/unlinked tasks; interrupted/repeated DB migration; unsupported schema; artifacts remain unchanged |
| Background | Exclusive ownership; reconnect; pending approvals without GUI; Keychain access; service upgrade/disable; sleep/wake |
| UI | Current style, narrow/wide windows, streaming scroll stability, empty/error state, keyboard and accessibility actions |

Use fake app-server fixtures, temporary databases, and mock message transport
for automated tests. Do not use production inboxes or paid model runs as routine
tests. Run targeted Swift suites per phase; run the full native suite for each
release. Run Go tests when IPC or CLI changes. Perform one owner-approved live
end-to-end check before distributing the new integration.

Phase 4 additionally requires a real multi-process test with the signed App,
signed helper, bundled Go runtime, and fake app-server. Exercise GUI quit/reopen,
helper restart, handover crash, pending approval, sleep/wake, and Keychain lock.
Unit tests and a successful model response alone do not prove service ownership.

### Release and rollback

1. Release phase 0 plugin/CLI compatibility first. Ship phase 1 additive storage
   with phases 1–2 conversation behavior gated until the acceptance suite passes.
2. Validate manual use with two owned Gull voices before enabling automatic
   drafts. Automatic drafting and background operation default off separately.
3. Verify service packaging before distributing phase 4. This is a signed Mac
   release; pushing `main` and passing cloud CI alone does not install a helper
   or update a user's Codex plugin cache.
4. Roll back behavior by stopping new work and returning to manual standalone
   tasks in a schema-compatible build. Keep new artifacts and associations.
   Do not restore an old DB backup after new results exist or start an old App
   that can ignore new execution ownership. Binary downgrade requires the
   service to be stopped and a verified compatibility path.
   For phase 4, quiesce or mark active work under the recovery rules, stop and
   unregister the helper, acquire ownership, and only then enable App-owned
   manual execution. Persist a schema/feature marker and test downgrade with
   in-flight work, an available draft, and an uncertain attempt. A pre-marker
   binary that cannot enforce this contract is not a supported rollback target.
5. Record tested CLI/plugin/App versions and remaining manual checks in the
   release notes. No production push, deployment, plugin install, or service
   registration is performed by writing this plan.

## 11. Evidence and references

Repository implementation:

- [Mac integration](../apps/mac/README.md)
- [Codex connector](../connect/codex/README.md)
- [Plugin skill](../connect/codex/plugin/skills/seagull/SKILL.md)
- [Shared local CLI/runtime](../connect/local-agent/README.md)
- [Task records](../apps/mac/Gulls/Models/CodexTask.swift)
- [Session database](../apps/mac/Gulls/Services/CodexSessionDatabase.swift)
- [Execution coordinator](../apps/mac/Gulls/Services/CodexExecutionCoordinator.swift)
- [Task store](../apps/mac/Gulls/Services/CodexTaskStore.swift)
- [Lifecycle](../apps/mac/Gulls/Services/AppLifecycleCoordinator.swift)
- [Approval broker](../apps/mac/Gulls/Services/LocalControlStore.swift)

Official Codex documentation reviewed for this plan:

- [App server](https://learn.chatgpt.com/docs/app-server): custom client
  integration, authentication, threads, turns, approvals, streaming, and
  version-specific schemas. Its experimental status makes compatibility gates
  necessary; documentation alone is not proof that a local CLI supports a field.
- [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk): programmatic execution;
  useful for new integrations without requiring this Swift adapter to be rewritten.
- [App command reference](https://learn.chatgpt.com/docs/reference/commands#chats):
  new-chat links and exact existing-thread links; existing-thread links do not
  document composer prefilling.
- [MCP tools](https://learn.chatgpt.com/docs/extend/mcp) and
  [removed MCP server command](https://learn.chatgpt.com/docs/mcp-server).
- [Hooks](https://learn.chatgpt.com/docs/hooks) and
  [plugin components](https://developers.openai.com/plugins/build/plugins#bundled-mcp-servers-and-lifecycle-hooks):
  optional extension mechanisms, not the durable message queue.

Future Apple service implementation must verify the relevant deployment target
and entitlements against
[SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice).
The helper registration and signing spike is a release prerequisite, not a
capability already established by this investigation.
