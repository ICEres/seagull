# Agent Request

Agent Request is the Request/Tasking interface for agent-to-agent work. It turns
gulls Inbox, Live, task, context, artifact, and audit primitives into explicit
request, acceptance, approval, progress, and result workflows.

Requests, approvals, state changes, and results use durable gulls Inbox
delivery. Live adds optional real-time collaboration and progress, then falls
back to Inbox when a participant disconnects. Agent Request owns structured
Work semantics, not a second transport.

## Layer Folders

```text
docs/      Request, task, context, approval, and result specs.
connect/   Request-specific MCP tools, CLI commands, and webhook contracts.
apps/      Future request inbox and task UI.
services/  Future request workflow services.
```

Current implementation is not split yet. Early task and request primitives live
inside the message hub, MCP connector, SDK, and local agent CLI.

See [docs/spec.md](docs/spec.md).
