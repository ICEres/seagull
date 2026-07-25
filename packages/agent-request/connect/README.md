# Agent Request Connect

This folder owns request-specific connector surfaces.

## Expected Connectors

- MCP task tools.
- Local CLI task commands.
- Webhook worker event contract.
- Future request inbox or task-board client.

## Contract

Agent Request connectors may:

- Create task requests delivered through gulls Inbox.
- Accept, refuse, update, or complete requests.
- Publish optional Live progress while preserving durable Inbox and task state.
- Fetch bounded context packs.
- Upload artifacts by ref.
- Return results and tool-use summaries through gulls Inbox and durable task
  records.

Agent Request connectors must not:

- Implement a second request, message, result, or Live transport.
- Tunnel into another agent's private MCP server by default.
- Copy private prompts, credentials, memory, or raw tool handles into requests.
- Store large task inputs or outputs inline when payload refs are required.
