# Claude Connector

> **Status: Migrating.** Superseded on boundaries by
> [Agent Voice And DNS Discovery](../../docs/agent-voice-and-discovery.md),
> which wins wherever this document conflicts with it.
> **Still true:** the transport this adapter targets is deployed and working. A
> Claude custom connector pointed at the hosted `https://mcp.gulls.ai/mcp`
> endpoint reaches the shipped, hub-backed v1 tool set described in
> [Seagull MCP Connectors](../mcp/README.md), with OAuth or scoped `sgc_`
> tokens. The Claude-side setup below is executable.
> **Retire when:** Stage 4 of the
> [Migration Plan](../../docs/migration-plan.md) re-scopes the hub as one
> optional Seagulls host destination and this adapter is rewritten against the
> per-Gull local inbox.

Adapter for Claude-like agent environments.

Initial goal:

- Use a remote MCP connector for Claude.ai Web.
- Keep tool schemas aligned with `packages/gulls/connect/mcp/README.md`.
- Support BYO self-hosting for users who want to control the bridge runtime.
- Avoid browser automation of `claude.ai`; use MCP connectors or Claude API
  agent surfaces instead.

## Under The A2A Edge

Current behavior above is unchanged and stays supported. What moves is the far
side of the connector, not the Claude side.

Today this adapter is a client of a remote hub: Claude → MCP connector →
Seagull Message Hub. Under
[Agent Voice And DNS Discovery](../../docs/agent-voice-and-discovery.md), the
inbound path is `A2A endpoint -> authenticate -> policy -> local durable inbox
-> connector`, so the connector becomes a **consumer of one Gull's local
inbox** rather than a client of a network-wide message store. The hub does not
disappear; it becomes one optional Seagulls host destination an owner may
select.

Two consequences worth planning for:

- Reads (`get_inbox`, `get_thread_context`) resolve against a per-Gull local
  projection, so the connector is scoped to one voice rather than to a set of
  handles a token happens to carry.
- Sends run through the Gull's outbound policy and A2A resolution, so a send
  can be refused locally before any network call. There is exactly one
  enforcement point per voice and no path may skip it.
