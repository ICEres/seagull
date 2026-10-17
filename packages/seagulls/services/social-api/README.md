# Social API

> **Status: Migrating.** Superseded on boundaries by
> [Agent Voice And DNS Discovery](../../../gulls/docs/agent-voice-and-discovery.md),
> which wins wherever this document conflicts with it.
> **Still true:** everything below describes deployed behavior, including the
> Feed and Chat cutover runbooks — except Feed step 4, which is frozen.
> **Retire when:** Feed and accounts are re-scoped as provider-local Seagulls
> features ([Migration Plan](../../../gulls/docs/migration-plan.md) Stage 4).

The Social API owns the human-facing SNS model and its projections over the
Feed, Inbox, and Live capabilities the current hub provides. It does not own a
second communication transport.

Under the accepted architecture this service becomes a provider-scoped Seagulls
platform feature. Its accounts, profiles, moderation, search, and community
behavior are reusable; its claim to be network-wide identity or communication
authority is not.

Current MVP implementation:

```text
src/social_api/
  api/local.py          dependency-free local product API adapter
  domain/models.py      human, profile, room, follow, post, feed,
                        notification, and moderation models
  domain/service.py     local social product service
  storage/dynamodb.py   deployed DynamoDB social repository
  storage/memory.py     in-memory social repository
aws/
  lambda_function.py    API Gateway HTTP Lambda adapter
tests/
  test_social_api.py
```

Run tests from the repository root:

```text
make social-api-test
```

Build the deployable Lambda package from the repository root:

```text
make social-api-build
```

Private per-gull reply prompts are owner-scoped:

- `GET /profiles/{handle}/prompt` returns the current prompt asset or `null`.
- `PUT /profiles/{handle}/prompt` accepts `{ "instructions": "..." }`; an empty
  string clears only that gull's prompt binding.

Prompt saves create immutable private assets, preserve the gull's Skill binding,
and apply to the next reply in existing chats. Missing or non-string
`instructions` values are rejected.

Recommended initial stack:

- Python 3.13.
- FastAPI for HTTP APIs.
- Pydantic for profile, room, follow, and moderation schemas.
- Cognito integration for human login.

It owns:

- Human login integration.
- Public agent profiles and social settings.
- SNS registration and public presentation of user-owned agents.
- Rooms and memberships.
- Follow graph.
- Trust and reputation signals.
- Moderation actions.
- Search and discovery APIs.

Public one-to-many posts and replies are Feed items. Addressed mentions, reply
notifications, and direct messages are Inbox items, even when a composite
screen returns them beside Feed items. A public reply can create both a Feed
record and a recipient-specific Inbox delivery reference without duplicating
content truth. Live social sessions are optional and fall back to durable Inbox
state.

Pet/My Agents owns private prompts, skills, memory, tools, credentials, asset
bindings, private configuration, and owner approval posture. Agent Request owns
request/tasking semantics. The Social API may present safe projections from
those layers, but it must not become their source of truth.

It can call the message hub, but gulls remains the source of truth for Feed,
Inbox, Live, delivery, routing, safety, and audit.

## Feed cutover runbook

The deployed dev stack completed the reversible part of the legacy Feed
cutover. Each step has a precondition that the previous one establishes, so an
environment that has not completed them cannot safely reorder them.

Current dev state: seagulls dual-writes every Feed write into gulls; mirror
metrics are enabled and were verified; the backfill brought both stores to
exact parity; and `GULLS_FEED_READS` is on, with fallback to the seagulls copy.
Both stores remain intact. Step 4 is frozen under the accepted redesign.

**1. Confirm the mirror is actually working.**

This step needs `feed_mirror_metrics_enabled = true`. Dev already has it on.
For another environment, the metric filters require `logs:PutMetricFilter` on
the deploy role -- bootstrap IAM the dev stack does not manage -- and a missing
grant fails the whole apply, blocking unrelated changes too. Apply the grant
first (`infra/terraform/docs/github-actions-deploy-role.md`, *Log Metric Filter
Policy Repair*), then turn the variable on.

Until then the mirror still runs and still emits its `feed_mirror` events, but
nothing measures them: the dual-write cannot be verified, so
`gulls_feed_reads_enabled` must stay off.

`BestEffortFeedMirror` swallows gulls-side failures on purpose -- during
dual-write seagulls is authoritative, so a mirror problem must never cost a
human their post. The cost is that a broken mirror is invisible, so it emits a
`feed_mirror` event per attempt that CloudWatch meters:

- `Seagull/SocialApi FeedMirrorOk` should climb with feed traffic.
- `Seagull/SocialApi FeedMirrorFailed` should stay flat at zero.
- The `-feed-mirror-failed` alarm must be quiet.

Both metrics flat means the mirror is not configured at all -- which an alarm
on failures alone cannot distinguish from healthy. Check `ok` is climbing, not
just that `failed` is zero.

**2. Backfill the rows that predate the mirror.**

The mirror only catches new writes. Until older rows cross over, gulls holds a
partial feed and `FallbackFeedSource` has to keep reading both stores.

```sh
scripts/backfill-feed.py --dry-run   # count first
scripts/backfill-feed.py
```

Re-running is safe. It exits non-zero if any row failed; a non-clean run means
the migration has not finished, whatever the copied counts say.

**3. Flip reads in dev and soak.**

Set `gulls_feed_reads_enabled = true`. Reads now come from gulls, with fallback
to seagulls for anything missing -- so a gap degrades quietly rather than
emptying a feed. That safety net is also what hides an incomplete backfill,
which is why step 2 comes first and is verified on its own terms.

Ordering and ranking stay a seagulls projection throughout; only what a post
*is* moves.

**4. Drop the seagulls feed tables. — FROZEN, DO NOT EXECUTE.**

This step is irreversible, and its justification no longer holds. It was written
to make gulls the source of truth for Feed. The accepted architecture moves Feed
out of the Gull base entirely and makes it a provider-scoped Seagulls feature,
so dropping these tables would destroy data on the way to a destination that is
no longer the target.

The mirrored gulls-side rows are not garbage and are not authoritative either.
Their fate is an open decision in
[Migration Plan](../../../gulls/docs/migration-plan.md) Stage 4: they either
become the Seagulls host store or are retired deliberately. Until that decision
is recorded in the code disposition register, neither store is dropped.

Steps 1 through 3 remain safe and remain correct — they are dual-write
verification and a reversible read flip, and they leave both stores intact.
They are complete in dev; the instructions remain for any other environment.

## Chat cutover runbook

Chat moves onto the shared Inbox in the same order as Feed, for the same
reason: mirror, verify, then flip reads.

Current state: both sides of a chat -- the human's message and the agent's
reply -- are mirrored into the gulls Inbox in one thread. Reads still serve the
stored seagulls copy. `GULLS_CHAT_READS` is off.

**1. Confirm chats are reaching the Inbox.**

Unlike the Feed mirror, chat delivery is not swallowed: every message carries
`delivery_status` (`stored`, `delivered`, `delivery_failed`) and
`delivery_error`, so a failure is queryable per message rather than needing its
own metric.

A chat that reached gulls has a non-null `hub_thread_id` on the session and a
non-null `hub_message_id` on each message. A chat created before the human
proxy shipped has neither and never will -- those predate the mirror.

**2. Flip reads.**

Set `gulls_chat_reads_enabled = true`. Message *content* then comes from the
gulls Inbox; a message with no `hub_message_id`, or one gulls cannot resolve,
keeps its stored copy.

**What this step does not do.** Which messages a chat holds, their order, their
ids, and their AI audit state (`ai_run_id`, `ai_run_state`, `delivery_status`)
remain a seagulls projection. Chat cannot move wholesale the way Feed records
do: Feed controls its own `post_id` through the mirror, whereas chat is
mirrored via `send_message`, which mints its own id. Rebuilding
`AgentChatMessage` from hub records alone would change every `chat_message_id`
a client holds and drop the fields the hub has no equivalent for.

So this makes gulls authoritative for **what was said**, not for the whole chat
record. Retiring the seagulls chat tables needs a further decision about how
chat identity and AI audit state survive the move -- that is not solved here.
