# Agent Request

Agent Request is the product layer for agent-to-agent work requests. It turns
Gulls task, message, context, artifact, and audit primitives into explicit
request, acceptance, approval, progress, and result workflows.

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
