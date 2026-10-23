# Message Reliability and Codex Recovery Repair Plan

Date: 2026-10-23

Status: Implemented and verified; cloud deployment completed on 2026-10-23 with dual publication enabled. Native distribution remains pending.

Baseline: `03881e0`. Implementation release: `57a4448`, including the earlier Mac, iOS, and local runtime changes.

Repair the six issues identified in the recent review: split conversations on rapid sends, non-atomic server idempotency, missing iOS history, rewound Mac pagination, discarded Mac history, and orphaned Codex operations. Preserve immediate local feedback and background synchronization. Implement the server consistency contract first, then complete the client and recovery changes against that contract.

This plan defines implementation and release gates. Product changes, installation, push, and deployment are separate execution steps.

## Implementation result

All six repairs are implemented and committed in the release. Earlier native app and runtime work was preserved.

- Mac sends use a durable per-conversation queue. A retry keeps the exact originally dispatched request, including an absent thread ID. Uncertain acknowledgments block successors until reviewed; definite HTTP rejections remain distinguishable through CLI/runtime exit code 3.
- Message and task creation atomically commit their complete resource set and idempotency record. Replay reconstructs deliveries through the committed IDs with consistent reads; incomplete legacy records return a retryable recovery conflict. Thread revisions preserve counts, participants, and the maximum timestamp/ID head. Transaction action, item, and aggregate size limits are checked before writes and map to HTTP 413.
- iOS persists separate older-history and catch-up continuations together with fetched rows. Mac polling keeps its independent history cursor, loaded messages remain in memory beyond 500, and bounded warm caches rebuild omitted coverage after restart.
- Codex request version 2 binds operations to their durable task, request digest, connection revision, and selected folder. Publication follows association persistence. Restart/reconnect cancels abandoned operations, while a resumable migration quarantines ambiguous old requests.
- Committed delivery rows have a DynamoDB Streams publisher, stable queue IDs, lease-protected webhook dispatch, retained S3 failure envelopes, and checkpointed replay/reconciliation tooling. The default infrastructure configuration retains direct publication during stream handoff. An operator must verify mapping health before explicitly disabling it.

### Verification record

| Check | Result |
| --- | --- |
| Mac `Gulls` full native test suite | 238 tests passed, including queue, history, runtime status mapping, and Codex recovery cases. |
| iOS `GullsIOS` full native test suite | 36 tests passed on iPhone 17 Pro Simulator, iOS 26.5. |
| Message hub full Python suite | 314 tests passed with boto3 and moto enabled; no skipped repository suites. |
| Go local-agent full suite | `go test ./...` passed, including runtime and end-to-end fixtures. |
| Builds | Native test builds, both Go CLI entry points, and message hub Lambda package build passed. The stream publisher has its own Terraform archive entry point. |
| Infrastructure | Terraform format checks and local validation passed. Existing DynamoDB argument deprecation warnings remain. |
| Diff hygiene | `git diff --check` passed. |
| Cloud release | [CI Deploy 39898363385](https://github.com/ICEres/seagull/actions/runs/39898363385) passed all jobs, auth configuration checks, and isolated smoke tests. Terraform applied 18 additions and 6 updates with 0 destroyed resources. |
| Live recovery infrastructure | Deliveries table and publisher are active; stream mapping is enabled with `LastProcessingResult=OK`. Failure archive encryption, versioning, public access block, publisher IAM, and log retention are verified. Publisher alarms are `OK`; queue backlog is zero. |
| Public endpoints | Website HTTPS, public `config.js`, and the message API health endpoint are reachable. |

Backend regressions include 100 identical concurrent requests, same/different task keys, changed-input conflicts, delayed delivery indexes, missing replay resources, legacy revisions, expired live keys, the 97/98 keyed-recipient action boundary, item/aggregate byte limits, stream failure ordering, lease races, and recovery checkpoints. Mac/iOS regression fixtures use temporary storage and mocked transport; Codex command/file tests operate on temporary fixtures.

### Remaining release checks and limits

- CI deployed the cloud changes and ran isolated smoke fixtures. No real-user messages, real OTP requests, or device installation were performed for this release. The backend transaction suite uses the real boto3 transaction API against moto, not a live AWS service or DynamoDB Local process.
- The native scrolling/reading-position acceptance session, deliberate failure-destination exercise, and stream-only handoff checks remain pending before client distribution or disabling direct publication. Automated store tests establish message and cursor correctness, not visual scroll behavior.
- Direct publication remains enabled alongside the healthy stream mapping. The encrypted, versioned failure archive is private and currently empty; no live failure was injected to test archival recovery.
- The Mac warm cache holds the newest 500 confirmed messages plus pending outbox entries. An active session retains all explicitly loaded pages. After restart, older omitted pages require network backfill; this change does not guarantee a complete offline thread archive in runtime SQLite.
- External webhooks remain at least once. A receiver should deduplicate by the stable event/delivery ID. SQS FIFO deduplication and worker leases cannot guarantee exactly once across an external receiver accepting a request immediately before a worker crash.
- S3 failure payloads remain retained until reconciled. Recovery defaults to dry-run, validates checkpoint source/target/window, and reports unresolved or incomplete work as unsuccessful. CloudWatch alarms are visible in the console; notification destinations are not configured by this change.

## Scope and evidence

| Finding | Priority | Observed failure | Required result |
| --- | --- | --- | --- |
| F1 Mac first sends | P1 | Two sends used a null thread ID and created different server threads. | A conversation has one network send in flight; subsequent sends use the established thread. |
| F2 Server idempotency | P1 | Concurrent requests with one sender and key created two messages and two recipient deliveries. | One accepted operation creates one resource set, including after a timeout or crash. |
| F3 iOS history gaps | P2 | Refreshing a populated cache can discard the cursor needed to reach messages received while offline. | Catch-up reaches previously synchronized history without losing historical pagination. |
| F4 Mac cursor rewind | P2 | Loading page two advanced the cursor to 200; refreshing the head reset it to 100. | Refresh leaves the older-history cursor unchanged. |
| F5 Mac history truncation | P2 | Loading a 700-message thread retained only messages 201–700 and reported no more history. | Every explicitly loaded message remains accessible; restart cannot skip an omitted cache range. |
| F6 Codex operation recovery | P2 | A request file can survive a crash without its task association or original connection scope. | Restart and reconnect cancel abandoned Codex operations with durable attribution. |

F1, F4, and F5 were reproduced with the real Mac conversation store and a mocked CLI. F2 was reproduced with concurrent service calls. F3 and F6 were verified through their persistence and recovery paths; add executable reproductions in phase 0.

F2 predates the recent client work. Durable client outboxes make its existing race more likely to matter. F6 is a stale queue and attribution defect: the owner still has to approve the exact operation before execution.

### Implementation constraints

- Preserve the current uncommitted work. Keep repairs in focused commits with their regression tests.
- Use isolated caches, test accounts, mock services, and temporary task folders. Automated tests must not send production messages, request real OTPs, or execute commands on user files.
- Keep the existing English UI and the current Mac and iOS visual design. Add only the state explanations needed for blocked sends or interrupted operations.
- Keep the runtime as the owner of Mac inbox SQLite storage. Do not add another GUI-owned inbox database or open the runtime database directly from SwiftUI.
- Keep six-day client retry eligibility and seven-day server idempotency retention. Expired uncertain messages require explicit review; they must not receive an automatic new key.
- Keep guest sends, review holds, account isolation, and approval-before-execution behavior.

## Delivery sequence

| Phase | Change | Dependency | Exit gate |
| --- | --- | --- | --- |
| 0 | Deterministic regression fixtures | None | Each finding has a reproducible failing test. |
| 1 | Atomic backend creation and recoverable delivery publication | Phase 0 | Concurrent requests and injected failures produce one resource set. |
| 2 | Mac per-conversation send queue | Freeze phase 1 request fingerprint contract | Rapid sends stay in one thread; uncertain sends block successors. |
| 3 | iOS and Mac pagination and cache boundaries | Phase 0 | Offline gaps, polling, restart, and histories over 500 messages pass. |
| 4 | Durable Codex provenance and cancellation | Phase 0 | Every injected crash point leaves no executable orphan. |
| 5 | Integration and staged release | Phases 1–4 | Compatibility, recovery, and UI checks pass. |

Phases 3 and 4 can run in parallel with backend work. Phase 2 can be developed in parallel once request fingerprinting and replay responses are fixed. Release the backend before distributing clients that rely on its guarantees.

## Phase 0 Establish regression fixtures

1. Convert the existing Mac conversation probe into tests in `packages/gulls/apps/mac/GullsTests/GullConversationStoreTests.swift`. Use a controllable mock CLI that records request parameters and can suspend each response.
2. Add a backend barrier fixture: concurrent requests must reach the old idempotency read before either continues. Assert resource counts, IDs, and event publication separately.
3. Add iOS fixtures for both inbox pages of 50 and thread pages of 100. Persist the initial cache, recreate the store, and then expose a larger server history.
4. Add Codex failure injection immediately before and after approval persistence and request publication. Use fake execution and temporary directories.
5. Record the baseline test failures. Existing passing suites do not replace these reproductions.

**Acceptance:** all six failures are represented by tests that fail for the reviewed implementation for the intended reason. No regression fixture depends on timing sleeps, production accounts, or a real Codex session.

## Phase 1 Make backend sends atomic

### Repository transaction

Introduce repository commands for committing a message send and committing a task creation. The domain service prepares validated resources; the repository commits the complete resource set. Keep a typed result indicating `created` or `replayed`.

For messages, one DynamoDB transaction writes:

1. The message.
2. The new thread, or a conditional update to the existing thread.
3. All recipient deliveries, with their final initial review status.
4. The idempotency record when a key was supplied.

For tasks, the same transaction also writes the task and uses the task idempotency namespace. Do not call the old message-writing method and then save the task separately.

Implement equivalent all-or-nothing behavior in the in-memory repository under a lock. A conditional idempotency write performed after message creation is insufficient.

### Key ownership and replay

- Retain the existing table keys and the `task:` namespace. Keep legacy `message_id` and `task_id` attributes readable while adding a request fingerprint and commit metadata.
- Claim an unused or expired key inside the resource transaction. The condition must permit an expired row that DynamoDB TTL has not deleted yet: absent key **or** `expires_at <= now`.
- Fingerprint the normalized caller request, including sender identity, requested recipients, exact content, content reference, refs, intent, visibility, supplied thread ID, runtime mode, and task fields where applicable. Freeze a canonical encoding with fixtures.
- Fingerprint the requested inputs before routing, generated IDs, timestamps, and safety outcomes. A routing or policy change must not turn a retry of an identical request into a different operation.
- A matching live key returns the original committed resource. A different fingerprint returns HTTP 409 with a stable `idempotency_key_reused` code and no writes.
- A legacy key without a fingerprint replays its referenced resource. A key pointing to a missing resource returns a recovery conflict; it must not silently create a replacement.
- Read the winning key and resources consistently after a transaction conflict. Retry transient transaction conflicts with a bounded backoff; distinguish a thread conflict from an idempotency conflict.
- Authentication and access checks still apply to replays. Return replay status from the committed result, replacing the public route's separate pre-read for its 202 versus 200 decision.

### Concurrent thread updates

Add a thread revision, treating a missing legacy revision as zero. The transaction conditions an existing-thread update on the expected revision. On conflict, reread and rebuild participants, count, and last-message metadata before retrying. Preserve the newest head using a deterministic timestamp and ID ordering; an older request finishing later must not move it backward.

A new thread uses a nonexistence condition. Failed transactions leave no message, delivery, task, or key behind.

### Transaction capacity

A keyed message needs `N + 3` transaction actions for `N` effective recipients; a task adds its task row. DynamoDB permits 100 actions, 4 MB per transaction, and 400 KB per item.

Validate the actual serialized transaction before writing. Reject an oversized operation with HTTP 413 and a stable `send_too_large` code. Do not split it into partly committed transactions or fall back to the unsafe path. A keyed message can have at most 97 effective recipients under this layout, and the size limit can be reached sooner.

This introduces an explicit capacity limit where the legacy API had no declared recipient cap. Document it and check route fixtures and known callers before release. Large fanout would require a separate durable fanout design; it is outside this repair. Public, legacy, personal-agent, and task routes must all use the atomic path within its supported capacity.

### Recoverable event publication

Use DynamoDB Streams on the existing deliveries table to connect committed deliveries to the existing FIFO agent queue. This adds a stream publisher rather than a second message outbox table.

1. Enable `NEW_AND_OLD_IMAGES`. The publisher handles insertion of a deliverable row and transition from a held state to `delivered`; it ignores unrelated updates.
2. Reconstruct the current production wire payload from delivery, message, and agent records, including the enrichment currently performed by `DeliveryEventPublisher`. Preserve sender/recipient handles, intent, visibility, timestamps, stable event ID, refs, and current content fields. Use delivery ID for FIFO deduplication and thread ID for grouping; add a payload parity test.
3. Resolve safety and routing holds before the transaction and create held rows as `needs_review`. Move the pending-review handling in `GatedMessageHubService` into preparation, removing its reliance on a post-send hold mutation. Recheck current eligibility before publishing. A transient `delivered` row followed by a later hold is unacceptable.
4. Return partial batch failures on enrichment or SQS failure. Configure retry, alarms, and an S3 failure destination that retains the original failed stream payload. AWS supports this directly for DynamoDB event source mappings; see [Retain discarded records](https://docs.aws.amazon.com/lambda/latest/dg/services-dynamodb-errors.html). Document replay from that archive; DynamoDB Streams retention alone is only 24 hours.
5. Test archive replay and recovery after an outage exceeding stream retention. If the mapping or archive itself was unavailable, perform a bounded reconciliation scan of deliveries created or updated during the outage and republish currently eligible rows with their stable event IDs. The worker skips completed webhook triggers; duplicate socket wake-ups remain harmless. Keep an operator checkpoint and retain failed records until reconciled.
6. Switch production creation events from the direct SQS callback to the stream path. Preserve direct injectable event sinks for local service tests. Audit approval/release paths as well as initial sends so a held delivery is eventually published once eligible.

Before enabling stream publication, make the existing webhook worker claim a delivery conditionally with a lease and attempt token. Only that owner may record success or release its failed attempt. A duplicate arriving while a lease is active must remain retryable, not be acknowledged as completed. Keep socket wake-ups separate from webhook completion state.

The guarantee is one committed message/delivery set and recoverable event publication. External webhook calls remain at least once: a crash after the receiver accepts a call but before success is stored can cause a retry. Preserve the stable event ID so receivers can deduplicate. FIFO's deduplication window does not provide permanent exactly-once execution.

### Files

Paths below are relative to the repository root.

- `packages/gulls/services/message-hub/src/message_hub/storage/repository.py`: atomic commit and replay contracts.
- `packages/gulls/services/message-hub/src/message_hub/storage/memory.py`: lock-backed transaction behavior.
- `packages/gulls/services/message-hub/src/message_hub/storage/dynamodb.py`: transactions, consistent replay reads, expiry conditions, and thread revisions.
- `packages/gulls/services/message-hub/src/message_hub/domain/models.py`: result metadata and thread revision if represented in the domain.
- `packages/gulls/services/message-hub/src/message_hub/domain/service.py`: prepare and commit messages/tasks; remove final unconditional key writes.
- `packages/gulls/services/message-hub/src/message_hub/api/local.py`: shared replay/error mapping.
- `packages/gulls/services/message-hub/aws/lambda_function.py`: production publication handoff and review behavior.
- `packages/gulls/services/message-hub/aws/agent_worker.py`: webhook claim ownership.
- Proposed `packages/gulls/services/message-hub/aws/delivery_stream_publisher.py`: stream-to-queue publication and failed-record replay entry point.
- `infra/terraform/modules/message-hub/main.tf`, `outputs.tf`, and `infra/terraform/envs/dev/main.tf`: stream, publisher, transaction/IAM permissions, failure archive, and alarms.
- `scripts/build-message-hub.sh` and deployment packaging where required by the new entry point.

### Required tests

- 100 concurrent identical keyed message sends produce one message, one thread increment, and one delivery per recipient. Repeat for task creation, including its request message.
- Same key with a changed body or supplied thread ID returns 409. Message and task key namespaces do not collide.
- Expired-but-present keys can be replaced once; live keys and legacy keys replay correctly.
- Inject failure before commit, after commit before HTTP response, before queue publication, and after queue publication before publisher completion.
- Concurrent different keys in one thread preserve count, participants, and newest head.
- Reject excess actions, aggregate size, and oversized items with zero partial writes.
- Held and guest-quarantined rows produce no event until approved. Duplicate stream records and expired worker leases recover safely.
- Exercise the real SDK transaction shape and conditions against disposable DynamoDB Local tables; in-memory mocks alone do not verify DynamoDB transaction behavior.

Extend `test_message_hub_service.py`, `test_dynamodb_repository.py`, `test_public_agent_routes.py`, `test_agent_task_queue.py`, `test_delivery_events.py`, and `test_lambda_safety_gateway.py`. Add focused publisher and worker concurrency coverage alongside the existing worker tests.

**Acceptance:** retries return the original resource, no accepted keyed operation creates duplicate resources, and a committed deliverable operation has a tested publication recovery path.

## Phase 2 Serialize Mac sends without delaying typing

### Queue behavior

1. Enqueue and persist the optimistic message immediately. Clear the composer only after that local save succeeds.
2. Maintain one drain task per account scope, connection revision, and conversation. Different conversations can send independently.
3. All entry points use this drain: new sends, queued-send recovery, and explicit retry. A set keyed only by pending message ID does not serialize a conversation.
4. At first dispatch, reread the current conversation and its confirmed thread binding. Persist an immutable request snapshot before calling the CLI: sender profile/handle, connection revision, recipient, content, idempotency key, and the exact supplied thread ID. Keep this snapshot with the pending message ID.
5. Represent an unprepared request separately from a prepared request whose `threadID` is null. The latter means that the first attempt intentionally started a new thread.
6. On success, persist confirmed message ID, confirmed thread binding, and outbox state in one cache snapshot before releasing the next send. Keep the thread binding in that snapshot so recovery does not depend solely on a separate UserDefaults write.
7. The next queued message prepares its request using that durable binding. A retry of the previous message uses its original snapshot, including its original null thread ID and the same idempotency key.

Persist the FIFO array order and use it after restart, including when timestamps tie. Do not rely on dictionary iteration order. A legacy queue whose order is unavailable uses creation time and pending ID as a deterministic migration fallback.

### Failure and lifecycle behavior

- A timeout, cancellation after dispatch, or unreadable acknowledgment is `unconfirmed`. Block later sends in that conversation until the owner retries/reconciles it. Keep typing and local queueing available.
- A definitive validation rejection is `failed`. The owner can correct or discard it. Distinguish this from an outcome that might already exist on the server.
- If the first send returns no usable thread ID, mark it unconfirmed even if a message ID is returned. Keep successors blocked and reconcile through the same request/key. Do not create another null-thread send.
- A failed local acknowledgment save keeps the pending entry and blocks the drain. Do not send successors using a binding that is only in memory.
- After restart, previously dispatched entries become unconfirmed; never auto-replay them. Only entries known never to have been attempted are eligible for automatic draining.
- Legacy attempted entries without a reconstructable request snapshot stay review-only. Inferring their original thread parameter from the current conversation can conflict with server fingerprinting.
- Account, Gull, or connection changes cancel the drain and invalidate its generation. Validate the captured scope after every suspension and before dispatch. An old completion cannot release or mutate a new scope's queue.

### Files and tests

- `packages/gulls/apps/mac/Gulls/Services/GullConversationStore.swift`: queue owner, prepared request, durable thread binding, recovery, and error classification.
- `packages/gulls/apps/mac/Gulls/Models/GullConversation.swift`: model additions only if needed outside the store.
- `packages/gulls/apps/mac/Gulls/Views/GullConversationView.swift`: immediate enqueue feedback and compact blocked-send explanation using existing controls.
- `packages/gulls/apps/mac/GullsTests/GullConversationStoreTests.swift`: suspended first send, retry, restart, save failure, and scope changes.
- `packages/gulls/apps/mac/GullsTests/GullsCLITests.swift`: exact reuse of the original key and thread arguments.

Test rapid A/B/C sends, independent simultaneous conversations, an unconfirmed A, same-key retry after a successful-but-lost response, a crash after acknowledgment persistence, missing thread IDs, expiry, and sign-out during each await boundary.

**Acceptance:** A/B/C appear locally immediately and reach one server thread in order. No ambiguous first send allows a successor to open a second thread.

## Phase 3 Separate catch up from older history

### Minimal pagination state

Each inbox/thread needs independent state for:

- **Older history:** unknown, a server cursor, or confirmed end. Null alone cannot mean both never loaded and exhausted.
- **Confirmed head anchor:** a stable raw server item ID from the last completed refresh traversal.
- **Active catch-up traversal:** its next cursor, previous confirmed anchor, and candidate new head ID. The presence of a traversal is distinct from an exhausted cursor; completion is an explicit committed transition.
- **Cache boundary validity:** whether saved rows still support the saved cursor, or a rebuild is required.

Use delivery IDs for inbox pagination and message IDs for thread pagination. Use raw response IDs before UI filtering; hidden or contentless rows still belong to the server cursor chain. Treat cursors as opaque. Never compare or manufacture them from IDs or timestamps.

### Refresh and catch up

1. Serialize page requests per resource, retaining existing account/generation checks. A resource has one pagination state writer.
2. On an empty resource, fetch the head and initialize older history from its next cursor.
3. On a known resource, fetch the head and show new rows immediately. Preserve the older-history cursor.
4. If the response contains the previous confirmed head anchor, the new head joins known history. Complete the refresh without changing older-history progress.
5. Otherwise, follow that response's cursor until reaching the previous anchor or the end. Persist the active traversal so interruption cannot lose the missing range.
6. While catch-up is active, later refresh requests resume it; they do not start another head chain. Coalesce them into one follow-up refresh after completion. This avoids dropping another gap when more than one page arrives during catch-up.
7. Merge the page containing the target anchor, then publish the candidate head anchor and close catch-up. Its next cursor must not replace the independent older-history cursor. Do not stop merely because a page overlaps an optimistic message or an unrelated cached range.
8. If an anchor was deleted, continue to the true server end while pagination advances. Track visited cursors within a traversal; a repeated cursor pauses with a recoverable sync error, preserving incomplete state. An empty page with a new continuation is followed; it is not an end marker.

Use a small work budget, initially two catch-up pages per scheduling turn, then persist and yield. Continue in the background while active, or on the next sync/explicit load. Cached content remains usable throughout. A load-more request may advance a pending gap before older history; `hasMore` includes either kind of continuation.

### iOS persistence

Store versioned page state in the existing SQLite cache. Commit fetched rows and their advanced page state in one database transaction; separate successful cursor writes after failed row writes can lose history on restart.

Keep SQLite's local continuation separate from the server cursor. Increasing the visible local window does not advance the server cursor. Missing ranges take precedence over claiming that all history is present.

Legacy page states have no coverage proof. Keep their cached rows visible, but mark coverage unverified and rebuild a cursor chain from the server head in bounded background pages. Persist the rebuild cursor, target boundary where applicable, and explicit completion state after each batch so a restart resumes the work. Do not trust a legacy null cursor as proof of a complete cache, and do not stop a migration rebuild at the first arbitrary cached overlap. Persist completion so this is a one-time repair per resource.

### Mac retention and restart

Remove `.suffix(500)` from the live merge path. Retain every page explicitly loaded in the active conversation, deduplicated by message ID with deterministic ordering.

Keep the JSON cache as a bounded warm window, initially the latest 500 confirmed messages per conversation. Retain pending outbox entries independently of that limit. Persist `historyBoundaryID` for the oldest retained confirmed row and `needsHistoryRebuild`. If persistence omits a loaded range, invalidate the saved older-history cursor rather than saving one that skips those rows.

After restart, show the warm window immediately. To recover older history, traverse from a fresh server head and establish a valid boundary before continuing; keep all fetched rows and deduplicate overlaps. Legacy capped caches use the same conservative rebuild. This can repeat network pages, but cannot skip the omitted range.

The current `GullsCLI.thread()` uses the `thread` command; it must not be assumed to read the runtime's SQLite archive. Reuse local history only where the existing runtime API provides the necessary thread coverage. This repair does not promise complete offline conversation history beyond the saved warm window.

### UI behavior

Preserve the current reading position when inserting older messages or filling a gap. Follow new messages only when the user is already at the bottom or explicitly sends. Verify this with an open long conversation; add view changes only where the store repair exposes a jump. Do not introduce a blocking loading screen.

### Files

- `packages/gulls/apps/ios/Gulls/Services/MobileCloudStore.swift`: inbox/thread pagination state and request scheduling.
- `packages/gulls/apps/ios/Gulls/Services/MobileLocalDatabase.swift`: atomic page-and-state persistence in existing SQLite storage.
- `packages/gulls/apps/ios/Gulls/Views/MessagesView.swift`: existing continuation and scroll behavior where needed.
- `packages/gulls/apps/mac/Gulls/Services/GullConversationStore.swift`: independent pagination state, live retention, cache version, and boundary rebuild.
- `packages/gulls/apps/mac/Gulls/Views/GullConversationView.swift`: history availability and scroll preservation where needed.
- `packages/gulls/apps/ios/GullsTests/MobileLocalFirstTests.swift`, `MobileLocalDatabaseTests.swift`, `MobileCloudStoreTests.swift`, and `packages/gulls/apps/mac/GullsTests/GullConversationStoreTests.swift`: regressions and migration fixtures.

### Required tests

| Scenario | Assertion |
| --- | --- |
| Cache 100 messages, receive 150 offline | All 250 IDs become reachable exactly once; cover inbox and thread page sizes. |
| Load two older pages, then poll head | Older-history cursor remains unchanged; next older request uses its own chain. |
| Another page arrives during catch-up | Finish the current traversal, then refresh again; no intermediate range disappears. |
| Refresh while older request is suspended | One state writer; neither response overwrites the other's continuation. |
| Anchor absent or deleted | Traverse to end without false completion or an infinite loop. |
| Optimistic message overlaps a page | It does not falsely close the catch-up gap. |
| Catch-up page contains the target anchor | Merge that page and close catch-up without replacing the older-history cursor. |
| Server repeats a continuation cursor | Pause with a recoverable sync error; never mark coverage complete. |
| More than 500 messages | Loading 700 and 2,000 messages retains the complete requested history in memory. |
| Restart after a 700-message session | Initial warm window stays bounded; omitted 200 messages remain recoverable before reporting end. |
| Legacy nil cursor and disjoint cached ranges | Migration rebuild repairs coverage; arbitrary overlap does not terminate it early. |
| Rows fail to persist | Cursor does not advance durably; retry recovers the same page. |
| Account change during fetch | Old rows, cursors, and cache writes cannot enter the new account scope. |

**Acceptance:** all historical ranges remain reachable, polling does not rewind backfill, warm startup stays bounded, and background repair preserves usable cached UI.

## Phase 4 Bind local operations to their Codex task

### Request format

Keep generic CLI requests at version 1. Introduce version 2 for Mac-created Codex requests, with required provenance: task ID, profile ID, connection revision, task request digest, selected scope root, and an explicit Codex source marker. Derive the task directory from the validated task ID and the current trusted context directory instead of trusting an arbitrary supplied directory.

Keep local-action results at version 1. Update Swift and Go readers to accept request versions 1 and 2, reject partial or malformed version 2 provenance, and preserve metadata in status output. Older Mac builds reject version 2 instead of silently treating it as a generic operation.

### Persist before publishing

1. Prepare and validate the request and canonical operation digest without making it visible to the approval queue.
2. Persist the task execution's approval ID, operation digest, and provenance in the existing session database. The persistence call must throw on failure; do not swallow an error and continue publishing.
3. Publish the complete request using a private temporary file and an atomic, no-clobber publication step. Preserve existing file permissions and symlink protections.
4. Register the live waiter and expose the request for review. On publication failure, clear or interrupt the approval state.

A crash before publication leaves at most an approval reference with no executable request. A crash after publication leaves enough durable information to attribute and cancel it. The in-memory scope dictionary may be a cache, but cannot be the only source of authority.

### Recovery and execution checks

- Before displaying pending actions on startup, mark interrupted Codex runs and cancel their version 2 requests, including requests not listed by an approval ID. Restart does not recreate a live Codex waiter or replay an operation.
- On connection revision changes, task interruption, or disabling local control, cancel matching requests in their original context directory. Do not stamp restored Codex actions with the new connection revision.
- Immediately before execution, require a matching live task, durable approval association, request digest, profile, revision, and selected folder. Recheck the existing file-content and allowed-folder protections.
- Cancellation is idempotent. Preserve existing successful results; write one cancelled result for unexecuted requests. If result persistence fails, remove the request from the executable queue by an atomic quarantine move and expose the existing error surface.

### Legacy pending requests

Pre-fix Codex requests and generic CLI version 1 requests have the same persisted shape. They cannot be reliably classified after a crash.

On the first activation of each existing local-action context after upgrade, inventory and quarantine pre-existing unresolved version 1 requests without executing or deleting them. Record migration progress durably so an interrupted migration resumes. The owner can inspect and explicitly reissue an intended operation. Completed results remain intact; subsequently created generic version 1 requests use the normal approval flow.

This one-time interruption also affects legitimate generic requests already pending at upgrade. It is the explicit compatibility cost of removing unknowable stale Codex operations; do not silently relabel them as safe generic work.

### Files and tests

- `packages/gulls/apps/mac/Gulls/Models/LocalActionModels.swift`: version 2 provenance and independent result compatibility.
- `packages/gulls/apps/mac/Gulls/Services/LocalControlStore.swift`: prepare/publish, validation, cancellation, and legacy quarantine.
- `packages/gulls/apps/mac/Gulls/Services/CodexExecutionCoordinator.swift`: durable approval ordering and live waiter lifecycle.
- `packages/gulls/apps/mac/Gulls/Services/CodexTaskStore.swift` and `CodexSessionDatabase.swift`: approval digest persistence and recovery lookup.
- `packages/gulls/connect/local-agent/internal/agentcli/local_action.go`: versioned request reads and status serialization.
- `packages/gulls/apps/mac/GullsTests/LocalControlTests.swift`, `CodexExecutionCoordinatorTests.swift`, `CodexTaskStoreTests.swift`, and `packages/gulls/connect/local-agent/internal/agentcli/local_action_test.go`: crash, migration, and compatibility coverage.

Inject a crash before approval save, after approval save, during request publication, and before waiter registration. Test changed revision with the same Gull handle, missing task, changed folder, changed request digest, missing approval, cancellation write failure, already-completed result, and interrupted legacy migration. Every case must produce zero command/file executions during recovery.

**Acceptance:** a restarted or reconnected app has no abandoned Codex operation in its executable approval queue. New generic CLI requests still work with explicit owner approval.

## Phase 5 Verify and release in stages

### Automated gates

Run focused new tests after each phase, then the affected full suites once before release:

```sh
make message-hub-test
make local-agent-test
make mac-app-test
git diff --check
```

For iOS, generate the project with XcodeGen and run the `GullsIOS` scheme on an available simulator selected from `xcrun simctl list devices available`. Use a dedicated DerivedData directory and the current Xcode developer directory. Run the affected iOS tests and a build for the existing deployment target.

Also run publisher/worker tests, disposable DynamoDB transaction integration tests, and Terraform formatting/validation for the infrastructure change. Inspect `terraform plan` for table replacement or deletion before any future apply; these repairs require additive changes.

### Integrated acceptance session

Use a local stub or isolated test environment:

1. Open a cached Mac conversation and rapidly queue three messages. Drop the first server response after commit, explicitly retry, and verify one thread and one copy of each message.
2. Repeat an offline/reconnect cycle with more than one page of new messages on iOS and Mac. Confirm there are no missing IDs.
3. Read the middle of a long conversation while new messages arrive; load older history and verify the visible reading position.
4. Restart after loading over 500 messages. Confirm immediate cached display and eventual recovery of older history.
5. Queue a fake Codex file operation, terminate at each persistence boundary, and relaunch. Confirm no operation executes and the task explains its interruption.
6. Switch account or reconnect a Gull while requests are suspended. Confirm isolation of messages, cursors, pending sends, and local operations.

### Deployment order and rollback

1. Ship compatible worker claims, review-status preparation, publisher resources, failure storage, and stream configuration first, while retaining direct publication during readiness checks.
2. Enable the stream mapping at `LATEST` while the direct callback still operates (`delivery_stream_direct_publication_disabled=false`). Verify the mapping is active and an isolated delivery reaches the queue before setting `delivery_stream_direct_publication_disabled=true`. Reconcile the bounded handoff interval. Temporary duplicate events are tolerated by the worker; never create a period where neither path can recover accepted deliveries. Exercise held-delivery release during the handoff.
3. Verify the atomic message/task write path and replay contract, then explicitly switch to stream-only publication after the handoff checks. The default configuration supports the dual-publication migration stage. Confirm counters and isolated smoke tests before client distribution.
4. Distribute Mac queue/history/recovery changes and iOS pagination changes. Keep caches and databases intact during upgrade.
5. Monitor duplicate resource IDs per key, transaction conflicts, oldest failed stream record, queue/DLQ depth, catch-up progress, blocked outbox entries, and recovery cancellations. Log identifiers and states rather than message bodies, tokens, or command contents.

Rolling back UI changes must retain the backend's atomic contract and delivery recovery infrastructure. Keep new request version checks and migration markers when rolling back Codex UI. Restoring the old backend write path would restore the duplicate-send defect; use a forward repair instead. Do not delete tables, caches, archived requests, or failed-event records as a rollback shortcut.

Main pushes trigger deployment through `.github/workflows/ci-deploy.yml`. The workflow now rejects plans that delete or replace DynamoDB tables, S3 buckets, Cognito user pools, or SQS queues before apply.

## Completion checklist

- [x] F1 Rapid Mac sends use one conversation and one server thread.
- [x] F2 Concurrent keyed message/task sends and tested failure recovery create one resource set.
- [x] F3 iOS offline gaps are repaired across cache restore and repeated refresh.
- [x] F4 Mac head polling preserves older-history progress.
- [x] F5 Loaded Mac history survives in-session paging and remains recoverable after bounded cache restore.
- [x] F6 Codex operations retain provenance and are cancelled safely after restart/reconnect.
- [x] Legacy records, request versions, and cache states have tested migration behavior.
- [x] All affected automated suites and local builds pass.
- [x] Verification observations and remaining external-delivery limitations are recorded.
- [x] Main release deployed through CI; auth and isolated smoke checks pass.
- [x] Live stream mapping, failure archive protection, publisher IAM/logging, alarms, and queue health are verified.
- [ ] Native long-conversation scroll/reading-position acceptance session passes.
- [ ] Stream-only handoff and deliberate failure-destination recovery checks pass before client distribution or disabling direct publication.
