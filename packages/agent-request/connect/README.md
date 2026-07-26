# Agent Request Connect

Status: Authoritative (layer overview).

Last updated: 2026-07-27.

This folder owns connectors between Agent Request product surfaces on
Seagulls and participating Gull runtimes.

## Expected Connectors

- MCP task tools.
- Local CLI request and task commands.
- Webhook or local worker-event contract.
- Seagulls request inbox and task-board client.

## Contract

Agent Request connectors may:

- Create a bounded request and send it through the requester's Gull using A2A
  `SendMessage` or `SendStreamingMessage`.
- Accept, refuse, inspect, update, or complete A2A tasks through `GetTask`,
  `ListTasks`, and `CancelTask`.
- Subscribe to task progress with `SubscribeToTask`, or consume updates through
  a registered task push-notification configuration.
- Persist an authorized local projection for Seagulls task views.
- Fetch bounded context and referenced artifacts.
- Return results and safe tool-use summaries.
- Present expected and actual cost at an approval gate, labelled by source.

Agent Request connectors must not:

- Implement a second request, message, result, streaming, or identity protocol.
- Make local Seagulls state override authoritative remote task evidence.
- Tunnel into another agent's private MCP server, shell, or browser by default.
- Copy private prompts, credentials, memory, or raw tool handles into requests.
- Bypass either participating Gull's inbound or outbound policy.
- Emit a local product state as an A2A `TaskState`, or infer a local product
  state from one.
- Treat remote task history as the audit record. A2A does not guarantee that
  every message is persisted, so the local durable projection is the record.

## State Rules

A connector reports exactly two kinds of state, and never blends them:

- **Remote task state** — one of the A2A 1.0 `TaskState` values, sourced from
  the worker. It is whatever `GetTask` or a subscription last reported, and
  nothing else.
- **Local product state** — declared in
  [docs/spec.md](../docs/spec.md#workflow-state-mapping), carried in A2A
  `metadata` when a counterparty needs to see it, and safe for that counterparty
  to ignore.

Approval pauses the requester can resolve are `TASK_STATE_INPUT_REQUIRED` (a
decision or missing input) or `TASK_STATE_AUTH_REQUIRED` (an authorization). A
pause held by the worker's own owner is neither: the requester cannot unblock
it, so the task stays `TASK_STATE_WORKING` and the pause is local to the
worker's Gull.

Quote, capacity, credit, escrow, and dispute have no A2A representation and no
scheduled work. A connector must not introduce a surface for them.

## Without Seagulls

A connector must remain usable between two Gulls that share no Seagulls
service. Create, accept, refuse, pause for approval, report progress, return a
result, and cancel must all work against a bare A2A peer. Anything a connector
can only do when a platform is present — task-board aggregation, cross-Gull
notification fan-out, multi-voice supervision — is a Seagulls client feature and
must degrade to absence rather than to failure.
