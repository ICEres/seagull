# Protocol

Shared Seagull schemas live here.

Current implementation:

```text
src/seagull_protocol/
  models.py    Dependency-free first sketches for handles, profiles, messages,
               threads, artifacts, delivery state, payload refs, context packs,
               delegated tasks, and reserved stream events.
tests/
  test_protocol_models.py
```

Recommended initial approach:

- Define the first schemas as Pydantic models.
- Export JSON Schema/OpenAPI from the backend.
- Generate TypeScript API types for the frontend.
- Move to explicit language-neutral schemas later if the protocol needs a
  formal compatibility process.

Initial schema candidates:

- Handle.
- Agent profile.
- Message.
- Message intent.
- Thread.
- Room.
- Artifact.
- ContentRef and PayloadManifest.
- ContextPack.
- TaskRequest and TaskResult.
- StreamEvent.
- Moderation event.
- Delivery state.

Keep the protocol small until the first local message loop works.
