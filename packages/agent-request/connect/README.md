# Agent Request Connect

This folder owns connectors between Agent Request product surfaces on
Seagulls and participating Gull runtimes.

## Expected Connectors

- MCP task tools.
- Local CLI request and task commands.
- Webhook or local worker-event contract.
- Seagulls request inbox and task-board client.

## Contract

Agent Request connectors may:

- Create a bounded request and send it through the requester's Gull using A2A.
- Accept, refuse, inspect, update, or complete A2A tasks.
- Subscribe to task progress or consume configured push notifications.
- Persist an authorized local projection for Seagulls task views.
- Fetch bounded context and referenced artifacts.
- Return results and safe tool-use summaries.

Agent Request connectors must not:

- Implement a second request, message, result, streaming, or identity protocol.
- Make local Seagulls state override authoritative remote task evidence.
- Tunnel into another agent's private MCP server, shell, or browser by default.
- Copy private prompts, credentials, memory, or raw tool handles into requests.
- Bypass either participating Gull's inbound or outbound policy.
