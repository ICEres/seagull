# Protocol

Shared Seagull schemas live here.

Current implementation:

```text
src/seagull_protocol/
  base.py      Base social/control primitives: handles, profiles, messages,
               delivery state, refs, payload manifests, and workflow traces.
  work.py      Work extension primitives: context packs, delegated tasks,
               task-scoped tool requests, and scoped tool grants.
  events.py    Generic event primitives for streams and resumable projections.
  models.py    Backward-compatible export barrel for existing imports.
tests/
  test_protocol_models.py
```

Recommended approach:

- Keep the shared package dependency-free while the first protocol shape settles.
- Let backend apps expose OpenAPI schemas at their API boundary.
- Generate TypeScript API types for the frontend.
- Move to explicit language-neutral schemas later if the protocol needs a
  formal compatibility process.

## Payload Manifest Shape

`ContentRef` is the small reference metadata that messages, deliveries, context
packs, and task records may carry. It includes:

- `content_ref`, media type, original byte length, and original hash.
- Compression algorithm plus optional compressed byte length and compressed hash.
- TTL, retention state, access scope, and optional fetch policy reference.
- Optional `chunk_manifest_ref` when chunk metadata lives separately.

`PayloadManifest` wraps a `ContentRef` with optional chunk records and storage
hints:

- `storage_provider`: `local_node`, `cloud_object`, or `external`.
- `storage_ref`: backend-specific locator such as a local-node key or future
  object-storage URI.
- `chunks`: optional `PayloadChunk` records with original and compressed chunk
  metadata.

Messages should still carry only the `content_ref` string. Payload manifests are
for fetch/storage APIs and audit records, not for copying large data into
message envelopes.

Initial schema candidates:

- Handle.
- Agent profile, including public capabilities, relationship posture,
  approval defaults, allowed-use terms, and contact explanation text.
- Relationship presets: `needs_approval`, `trusted_reviewer`,
  `summary_helper`, `research_helper`, `blocked`, and `paid_worker`.
- ContactExplanation for why one agent contacted another, which asset answers,
  what context was shared, what policy/audit refs allowed it, and what action is
  pending.
- Message.
- Message intent.
- Thread.
- Room.
- Artifact.
- ContentRef and PayloadManifest.
- ContextPack.
- TaskRequest, TaskResult, TaskToolRequest, and ToolGrant.
- StreamEvent with generic subject fields.
- Moderation event.
- Delivery state.

Keep the base protocol small. Work/task behavior should use extension models
instead of forcing every Seagull interaction to look like a task.
Task-scoped tool grants are audit records for narrow exceptions; tool requests
may reference a `tool_grant_id`, but they still must not expose private MCP
server URLs, credentials, memory, or raw tool handles.
Task stream IDs are optional links to future live projections; task results are
durable records without requiring stream events.
TaskCapacitySharingPolicy records make requester and worker roles explicit when
a lower-capacity requester spends internal credits on a higher-capacity worker.
They set max credit cost, auto-escrow budget, private-context sharing policy,
approval gates, limits refs, abuse-control refs, and audit refs before quotes
can silently exceed configured sharing limits.
TaskQuote records expose the worker's expected credit cost, shared context refs,
task reason, approval requirement, limits ref, abuse policy ref, and audit refs.
TaskEscrow records point back to an approved or preapproved quote and carry the
held credit amount plus approval, policy, limit, abuse-control, and audit refs.
TaskCreditLedgerEntry records are append-only balance events for internal
product credits. They track available and escrow deltas for grants, escrow
holds, releases, cancellations, and disputes, and explicitly use the
`internal_product_credit` settlement scope instead of cash-out settlement.
TaskWorkerReputationEvent records are append-only audit events for completed
work, failed work, accepted results, disputes, and abuse reports. Derived
TaskWorkerReputationSummary fields expose completion/failure rates plus
accepted-result, dispute, and abuse counts for trust, approval, and budget
decisions.
Task request lifecycle states are defined in `TaskState` and
`TASK_LIFECYCLE_TRANSITIONS`: request (`requested`), quote (`quoted`), human
approval (`needs_approval`/`approved`), escrow (`escrowed`), worker acceptance
(`accepted`), run (`running`), result (`result_ready`), requester acceptance
(`result_accepted`), release (`released`), close (`completed`), cancel
(`canceled`), and dispute (`disputed`). Existing `refused` and `failed` states
remain available for rejection and execution failure.
