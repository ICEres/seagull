# Social API

The Social API owns the human-facing SNS model and its projections over shared
gulls Feed, Inbox, and Live capabilities. It does not own a second
communication transport.

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

Feed is moving from seagulls to gulls in stages. Each step has a precondition
that the previous one establishes, so they cannot be safely reordered.

Current state: seagulls dual-writes every feed write into gulls and still
serves all reads from its own tables. `GULLS_FEED_READS` is off.

**1. Confirm the mirror is actually working.**

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

**4. Drop the seagulls feed tables.**

Only after a soak with `FeedMirrorFailed` flat and no fallback hits. This is
the irreversible step and the one that makes gulls genuinely the source of
truth the concept docs describe.

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
