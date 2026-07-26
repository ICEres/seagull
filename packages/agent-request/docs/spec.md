# Agent Request / Tasking Product Spec

Status: Authoritative (layer).

Last updated: 2026-07-27.

Agent Request remains a distinct product built on Seagulls. This spec is
authoritative for its own layer only, and defers to
[Agent Voice And DNS Discovery](../../gulls/docs/agent-voice-and-discovery.md)
wherever the two conflict. The current implementation has not been migrated onto
the contract described here; see Stage 5 of the
[Migration Plan](../../gulls/docs/migration-plan.md).

## Purpose

Agent Request is the structured work product on Seagulls. It lets one Gull ask
another Gull for a bounded result with explicit context, permitted use,
approval, progress, artifacts, result, refusal, and audit.

```text
Agent Request on Seagulls
task UX, policy, supervision
             |
requester Gull <------ A2A ------> worker Gull
```

Agent Request owns the work experience and product policy. The participating
Gulls carry the interaction through A2A, and Seagulls supplies multi-Gull task
views, accounts, notifications, and human supervision. Agent Request does not
define a second public task transport.

## Owns

- Request and task UX semantics.
- Bounded objective, expected output, permitted-use, context, and artifact
  presentation.
- Request, accept, refuse, run, approval-pause, result-review, complete, failed,
  and canceled workflow projections — each one either bound to a named A2A
  `TaskState` or declared local-only in
  [Workflow State Mapping](#workflow-state-mapping).
- Human approval gates for private context, tools, high-cost work, and delegated
  execution.
- Progress, result, artifact, and safe tool-use summary presentation.
- Surfacing expected and actual cost inside approval decisions; see
  [Cost, Quota, And Billing](#cost-quota-and-billing).
- Quote, capacity, credit, escrow, and dispute concepts, which are unmapped
  local product state with no A2A representation and no scheduled work; see
  [Unmapped Local Product State](#unmapped-local-product-state).

## Workflow State Mapping

Every Agent Request workflow state must either map to a named A2A `TaskState`,
or be listed here as a **local product state with no remote meaning**. There is
no third category, and there is no "where possible" escape. A state that is
neither mapped nor listed here is a defect, not a feature.

Consequences of that rule:

- A local product state is never sent as, encoded into, or inferred from a
  remote `TaskState` value. When it must reach the counterparty at all it
  travels as A2A message or task `metadata`, which the counterparty is free to
  ignore without breaking the interaction.
- Seagulls must never render a local product state as remote evidence. A remote
  task is only what `GetTask` last reported.
- A Seagulls-only extension remains an application feature. It never replaces
  the external agent's A2A task state.

The complete A2A 1.0 `TaskState` enum is `TASK_STATE_SUBMITTED`,
`TASK_STATE_WORKING`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`,
`TASK_STATE_CANCELED`, `TASK_STATE_REJECTED`, `TASK_STATE_INPUT_REQUIRED`, and
`TASK_STATE_AUTH_REQUIRED`. There are no mailbox states, and no quote, escrow,
or credit states.

| Agent Request state | A2A `TaskState` | Notes |
| --- | --- | --- |
| `draft`, `pending-owner-approval` (requester side, before send) | **LOCAL PRODUCT STATE** | No remote task exists yet. The requester's own owner gate runs before `SendMessage`. |
| `requested` | `TASK_STATE_SUBMITTED` | Created by the worker on receipt of the requester's `SendMessage`. |
| `accepted` | *(no distinct state)* | Acceptance is the `SUBMITTED` → `WORKING` transition, not a state. A worker that accepts without starting leaves the task at `SUBMITTED`; acceptance is then a **local** annotation on the requester's projection. |
| `refused` | `TASK_STATE_REJECTED` | Clean fit. Refusal is terminal and carries the worker's stated reason. |
| `running` | `TASK_STATE_WORKING` | |
| `needs-approval` — requester must supply a decision or missing input | `TASK_STATE_INPUT_REQUIRED` | The natural A2A home for an approval-style pause. The requester is the party that can unblock it. |
| `needs-approval` — requester must supply credentials or authorization | `TASK_STATE_AUTH_REQUIRED` | Use this, not `INPUT_REQUIRED`, whenever the missing thing is an authorization rather than a decision. |
| `needs-approval` — the **worker's own owner** must approve | `TASK_STATE_WORKING` + **LOCAL** | **This is where the mapping does not fit.** Both `INPUT_REQUIRED` and `AUTH_REQUIRED` mean the client can unblock the task; the requester cannot unblock a gate held by the worker's owner. Reporting either one would tell the requester to act when no action of theirs helps. The task stays `WORKING` and the pause is local to the worker's Gull, optionally described in `metadata`. |
| `result-ready` — worker requires requester sign-off before finishing | `TASK_STATE_INPUT_REQUIRED` | Artifacts are already attached; the required input is the sign-off. |
| `result-ready` — requester-side review of an already finished task | **LOCAL PRODUCT STATE** | The remote task is `TASK_STATE_COMPLETED`. `result-ready` is then a stage of the requester's own projection and means nothing to the worker. |
| `result-accepted` | **LOCAL PRODUCT STATE** | Requester bookkeeping. A2A has no result-acceptance state. |
| `complete` | `TASK_STATE_COMPLETED` | |
| `failed` | `TASK_STATE_FAILED` | |
| `canceled` | `TASK_STATE_CANCELED` | Reached through `CancelTask`. |
| `quoted`, `escrowed`, `released`, `disputed` | **LOCAL PRODUCT STATE, unmapped and unscheduled** | See [Unmapped Local Product State](#unmapped-local-product-state). |

The legacy `TaskState` enum in
`packages/gulls/packages/protocol/src/seagull_protocol/work.py` carries fifteen
values. Six map directly (`requested`, `running`, `completed`, `canceled`,
`refused`, `failed`), `needs_approval` maps conditionally, `accepted` maps to a
transition rather than a state, and the remaining seven — `quoted`, `approved`,
`escrowed`, `result_ready`, `result_accepted`, `released`, `disputed` — are
local or frozen. That enum is the reconciliation target for Stage 5 of the
Migration Plan, not a wire contract.

### Task History Is Not The Audit Log

A2A does not guarantee that every message is persisted in task history.
Agent Request must therefore never treat a remote task's history as the record
of what was requested, approved, or refused. Each participating Gull's local
durable projection and audit trail is that record, and disconnection does not
erase it.

## Unmapped Local Product State

Quote, capacity, credit, escrow, and dispute come from the legacy credit-ledger
design — `TaskQuote`, `TaskEscrow`, `TaskCreditLedgerEntry`,
`TaskCapacityPolicy`, and `TaskWorkerReputationEvent` in
`packages/gulls/packages/protocol`, with the AWS tables sketched in
[AWS Dev Payload And Task Plan](aws-dev-payload-task-plan.md).

Their status is explicit, and it is not "roadmap":

- **No A2A representation.** A2A has no quote, price, budget, escrow, credit,
  reputation, or dispute state, and none of these concepts is expressible as a
  `TaskState`. They are local product state with no remote meaning.
- **No scheduled work.** [Migration Plan](../../gulls/docs/migration-plan.md)
  Stage 0 freezes new task-credit tables: "Quote, escrow, credit ledger, and
  dispute state have no home in the accepted architecture until Agent Request's
  A2A mapping is settled." That freeze is in force. The mapping above settles
  the *task lifecycle*; it does not unfreeze the credit plane.
- **Concepts retained.** The product problems these model — telling a requester
  what work will cost, capping what a worker will take on, recording that a
  result was disputed — are real and are not being discarded. They are recorded
  here so a future change starts from the constraint rather than rediscovering
  it.

Any future work here needs its own decision that names where the state lives,
how it is authorized, and what a counterparty that has never heard of it sees.
Until then, nothing in this list is implemented, planned, or promised.

## Uses From Seagulls

- Hosted and connected Gull participants selected by their owners.
- Human accounts, workspaces, task boards, notifications, and supervision.
- Aggregated task and conversation projections with authorization and source
  evidence preserved.
- Approval, moderation, and readable audit surfaces.
- Provider cost, quota, and billing accounting for hosted execution, owned by
  the Seagulls Host role.
- Platform extension boundaries shared with Pet and future products.

## Uses From Gull, Gulls, And A2A

- WebFinger and AID or DNS-AID resolution of known participants.
- A2A `SendMessage` and `SendStreamingMessage` to open and drive work.
- A2A `GetTask`, `ListTasks`, `SubscribeToTask`, and `CancelTask` for task
  state, enumeration, live updates, and cancellation.
- A2A task push-notification configuration —
  `CreateTaskPushNotificationConfig` and its Get, List, and Delete counterparts
  — for updates while disconnected.
- A2A `GetExtendedAgentCard` where a worker publishes an authenticated
  extended card.
- A2A artifacts and status updates for results and progress.
- Each Gull's inbound and outbound policy, local durable task projection, and
  audit boundary.
- Safe runtime connectors for waking a worker without exposing its private MCP
  server, shell, browser, credentials, or raw tool handles.

## Without Seagulls

Two independent Gulls must be able to do bounded work over A2A tasks with no
platform between them. This is a requirement on Agent Request, not an
aspiration: the request and result semantics are carried by A2A task metadata
between the participating Gulls, so a capability that cannot survive the removal
of the platform is a Seagulls feature and belongs in the Seagulls spec.

```text
requester Gull ---- WebFinger + AID/DNS-AID + A2A ----> worker Gull
      |                                                      |
 local projection                                     local projection
 local audit                                          local audit
 owner approval                                       owner approval
```

**What does not degrade — the semantics themselves:**

- Sending a bounded request with objective, expected output, permitted use, and
  context references, and having a task created for it.
- Every mapped state in [Workflow State Mapping](#workflow-state-mapping):
  accept, refuse via `REJECTED`, run, pause for input via `INPUT_REQUIRED` or
  `AUTH_REQUIRED`, complete, fail, cancel.
- Approval gates. Enforcement lives in each Gull's local policy, which is where
  the authoritative doc puts it; the platform was never the enforcement point.
- Artifacts and referenced context, results, refusal reasons, and safe tool-use
  summaries.
- Each side's local durable projection, receipts, and audit trail.
- Task updates while disconnected, through `SubscribeToTask` or a
  push-notification config the requester registers itself.

**What degrades:**

- **No task board.** Each Gull sees its own tasks. There is no aggregated,
  cross-participant view, and `ListTasks` against one remote endpoint is not a
  substitute for one.
- **No cross-Gull notifications.** A2A delivers task updates to the endpoint the
  requester configured. Fanning those out to a human across several voices, or
  to a second device, is platform work. Without it, a human watches one Gull at
  a time.
- **No shared supervision UI.** Approve, refuse, and constrain happen at each
  Gull's own surface — CLI, connector, or local client — not in one console over
  many voices.
- **No multi-voice history, workspaces, or contact list.** No account-level
  aggregation of who asked whom for what.
- **No worker discovery beyond what the requester already knows.** A catalog
  that suggests a candidate worker is a Seagulls feature; without it the
  requester must already hold the worker's handle. Resolution itself still
  works.
- **Cost visibility narrows** to what the worker asserts in metadata, since
  host-reported figures come from a Host the pair may not share.

## Cost, Quota, And Billing

Provider cost, quota, and billing were disclaimed by every layer at once:
`packages/gulls/services/ai-provider` puts payment in "product layers", while
the Pet spec, the legacy Seagulls spec, and earlier versions of this spec each
listed "provider execution or billing" under Does Not Own. Nobody owned it.

**It belongs to the Seagulls Host role.** Host is the role that executes the
model for a hosted Gull — the one case where, in the authoritative doc's words,
the platform is authoring that voice — and the Migration Plan already routes
`services/ai-provider` to Seagulls for exactly that reason. Host therefore owns
provider accounts and credentials, usage metering, cost accounting, quota
allocation and enforcement, and any customer billing built on them, for the
Gulls that selected it. A Gull running an owner-supplied runtime incurs no Host
cost and needs no Host quota. The [Pet Spec](../../pet/docs/spec.md) makes the
same assignment; this spec and that one are the assignment of record until the
[Seagulls Platform Spec](../../seagulls/docs/spec.md) carries it.

Agent Request keeps one cost responsibility, and it is a presentation
responsibility: **surfacing cost in approval decisions.**

- Show the expected cost of a request at the approval gate, before the owner
  approves it, and the actual cost when the worker or Host reports one.
- Carry a budget limit stated by the requester, and show when reported cost
  approaches or exceeds it.
- Label each figure by source. A worker's statement about its own cost is
  self-asserted and unverified; a Host figure is metered by the Host for the
  Gulls it hosts. Rendering the two identically is the failure mode to avoid.

Agent Request does not hold balances, meter usage, price work, or settle
payment. A2A has no cost, price, or budget field, so every figure above travels
as A2A metadata or as Host-side data — never as remote task state.

## Integration With Pet

Pet and Agent Request are separate products built on Seagulls:

- Pet supplies owned-agent approval posture and private capability boundaries.
- Agent Request owns the work lifecycle and result presentation.
- A Pet-backed Gull may approve, constrain, refuse, or perform a request
  without transferring the Pet asset bundle.

Neither product is the foundational dependency of the other. Both are policy
inputs that the Gull compiles into local enforcement; neither is an independent
gate, and on conflict the Gull's local policy wins and fails closed.

## Does Not Own

- Gull identity, endpoint discovery, A2A transport, or remote task truth.
- A network-wide task database, mandatory relay, or Seagulls-only work
  protocol.
- Pet prompts, skills, memory, tools, credentials, or owner preferences.
- Another Gull's private runtime, local inbox, policy, or audit records.
- Provider execution, usage metering, quota enforcement, or settlement. These
  belong to the Seagulls Host role; Agent Request surfaces cost, it does not
  account for it.
- General Seagulls profiles, social/community features, or platform accounts.

## Public Contracts

- A requester identifies the worker, objective, context references, permitted
  use, expected output, and optional approval or budget requirements.
- The request is sent explicitly through the requester's Gull after resolution
  and outbound policy checks.
- A worker may accept, refuse, ask for approval, report progress, or return a
  result through its A2A interface.
- Every workflow state a client can observe is either a named A2A `TaskState`
  or a declared local product state. Nothing in between is published.
- Seagulls presents an authorized local projection; it does not silently claim
  that a remote task is complete without remote evidence.
- Large inputs and outputs use referenced artifacts rather than giant inline
  messages.
- Tool use is summarized and audited without exposing private tool handles.
- Disconnection does not erase locally persisted request, receipt, approval,
  task, or result evidence.

## Connect Surface

Agent Request connectors expose work flows to Gull runtimes and Seagulls
clients:

- MCP tools for creating, inspecting, accepting, updating, and completing work.
- CLI commands for request inspection and response.
- Webhook or local events for waking external workers.
- Seagulls request-inbox and task-board clients.

Connectors translate these operations to A2A and the participating Gull's local
policy/persistence interfaces. They do not create a second transport.

## Success Criteria

- A user can initiate and supervise bounded work between hosted or external
  Gulls through Seagulls.
- The same request reaches an external standards-compatible Gull through A2A.
- Two Gulls with no shared Seagulls service complete a bounded request end to
  end, including an approval pause and a returned result.
- A worker can return a result or refusal with clear source and state evidence.
- Every workflow state maps to a named A2A `TaskState` or appears in this spec
  as a local product state.
- A Pet-backed worker preserves its private asset boundary and owner policy.
- Agent Request remains a Seagulls product over Gull/A2A interactions, not a
  mandatory network-wide work service.
