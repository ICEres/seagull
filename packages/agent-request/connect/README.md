# Agent Request Connect

This folder owns request-specific connector surfaces.

## Expected Connectors

- MCP task tools.
- Local CLI task commands.
- Webhook worker event contract.
- Future request inbox or task-board client.

## Contract

Agent Request connectors may:

- Create task requests.
- Accept, refuse, update, or complete requests.
- Fetch bounded context packs.
- Upload artifacts by ref.
- Return results and tool-use summaries.

Agent Request connectors must not:

- Tunnel into another agent's private MCP server by default.
- Copy private prompts, credentials, memory, or raw tool handles into requests.
- Store large task inputs or outputs inline when payload refs are required.
