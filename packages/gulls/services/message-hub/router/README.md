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
