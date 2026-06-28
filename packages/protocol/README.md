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
