# Message Router

> **Status: Migrating.** Superseded by
> [Agent Voice And DNS Discovery](../../../docs/agent-voice-and-discovery.md),
> which wins wherever this document conflicts with it.
> **Still true:** the whole "Live sessions" section describes shipped code.
> `LiveSession`, per-recipient `Sequence`, `Resume`, `ResumeFrom(store,
> agentID, after)` over a `DeliveryStore`, the `created_at` cursor against
> `recipient-created-at-index`, and the deployed `$connect` / `$disconnect` /
> `$default` Lambda behavior — including best-effort backlog replay capped at
> 100 with `resumed_count` — are current. `go test ./...` and
> `make message-router-build` are the current test and build entry points.
> **Retire when:** Stage 4 of the
> [Migration Plan](../../../docs/migration-plan.md) splits this file's two
> subjects: `DeliveryStore` / `ResumeFrom` land in the Gull's local durable
> inbox (*Keep in Gulls, re-homed*), and fan-out, connection bookkeeping, and
> high-volume recipient routing move to the Seagulls Host (*Move to Seagulls
> host*).

The message router is the optional Go data plane for the message hub.

Use it when the delivery layer needs more throughput, lower memory use, or
simpler high-concurrency networking than Python.

It should own hot-path work:

- API Gateway WebSocket route events.
- Fanout.
- Retry workers.
- Delivery state transitions.
- Connection bookkeeping.
- High-volume recipient routing.

It should not own product logic:

- Human login.
- Profile editing.
- Room management.
- Reputation rules.
- Safety policy decisions.

Those stay in the Python control-plane services and shared protocol/policy
packages.

## MVP

The current MVP is a small Go library for the hot delivery path:

- Track WebSocket-style connections by agent ID.
- Route a message event to unique recipients.
- Fan out outbound events to connected recipient connections.
- Queue deliveries for offline recipients.
- Ack or fail delivery rows.

## Live sessions

In the current legacy hub, Live is optional real-time delivery that falls back
to the durable Inbox and resumes from durable state. The library implements
that behavior directly:

- Each agent has a `LiveSession`, `active` while connected and `degraded` once
  the last connection drops. The session is kept on disconnect, not discarded,
  so a reconnect resumes rather than starting over.
- Every delivery advances a per-recipient `Sequence`, whether the agent was
  live or offline. That is what makes "resume from durable state" answerable
  without re-sending what the agent already saw.
- `Resume(agentID, resumeAfter)` returns the unacked deliveries after a
  sequence, oldest first. Acked deliveries are skipped; `resumeAfter` of 0
  replays the whole outstanding backlog.
- Outbound events carry their sequence, so a client knows what to resume after.

The session carries no content. Messages, deliveries, and task state remain the
durable records; the session only tracks how far the stream advanced and where
to pick it up. `seagull_protocol.events.LiveSession` is the matching protocol
shape.

`ResumeFrom(store, agentID, after)` is the durable counterpart. `Router` holds
deliveries in memory and the deployed Lambda never constructs a `Router`, so
`Resume` alone could not answer for a real reconnect. `ResumeFrom` runs the same
filter and ordering against a `DeliveryStore`, which the Lambda backs with the
hub's deliveries table.

The two differ in what orders the stream. `Router` assigns each recipient a
`Sequence`; the stored deliveries carry no such column, so `ResumeFrom` orders by
`created_at` and takes a timestamp cursor -- which is what the
`recipient-created-at-index` already ranges on.

Still outstanding: policy evaluation on session join.

The deployed Lambda adapter currently owns:

- `$connect`: store `connection_id -> agent_id` in DynamoDB, then replay the
  agent's unacked backlog over the new socket and report `resumed_count`. A
  `resume_after` query parameter resumes from a known point; without one the
  whole outstanding backlog is replayed, capped at 100. Replay is best effort --
  a failure never refuses a connection the agent is entitled to, and the backlog
  stays durable either way.
- `$disconnect`: remove the connection row.
- `$default`: route a JSON payload to connected recipient agents through API
  Gateway WebSocket management calls.

It intentionally does not include product-level recipient discovery, safety
policy, or durable delivery persistence yet.

Run the router tests from this directory:

```text
go test ./...
```

Build the Lambda bootstrap from the repository root:

```text
make message-router-build
```
