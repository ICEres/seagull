# Message Router

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

Live is optional real-time delivery that falls back to the durable Inbox and
resumes from durable state (`packages/gulls/docs/concept.md`). The library now
implements that directly:

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

Still outstanding: policy evaluation on session join, and wiring `Resume` into
the deployed `$connect` handler so a reconnecting client is replayed
automatically rather than asking for the backlog itself.

The deployed Lambda adapter currently owns:

- `$connect`: store `connection_id -> agent_id` in DynamoDB.
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
