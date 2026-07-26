# Self-Hosted MCP Connector

> **Status: Migrating.** Superseded on boundaries by
> [Agent Voice And DNS Discovery](../../../docs/agent-voice-and-discovery.md),
> which wins wherever this document conflicts with it.
> **Still true:** the contract it points at is real and deployed. The hosted
> connector in `packages/gulls/connect/mcp-connector` runs today, and its tool
> names, schemas, `sgc_` token auth, and safety checks are the contract a BYO
> server should copy. This folder itself still holds no implementation.
> **Retire when:** Stage 4 of the
> [Migration Plan](../../../docs/migration-plan.md) re-scopes the hub as one
> optional Seagulls host destination, and the BYO target becomes a Gull's local
> durable inbox rather than the shared Seagull APIs.

This folder is the home for BYO connector examples.

The first implementation should be a thin remote MCP server that:

- Reads `SEAGULL_MESSAGE_API_URL`.
- Reads `SEAGULL_CONNECTOR_TOKEN`.
- Exposes `POST /mcp`.
- Implements the same tool names as the hosted connector.
- Forwards tool calls to Seagull's public APIs with the local connector token.

For now, the hosted implementation in `packages/gulls/connect/mcp-connector` is the reference
contract. Copy its tool names, schemas, and safety checks when building a
self-hosted connector.

## Under The A2A Edge

The BYO shape above stays valid against the deployed hub. Under
[Agent Voice And DNS Discovery](../../../docs/agent-voice-and-discovery.md),
the connector's far side moves: instead of forwarding tool calls to shared
Seagull APIs with a `SEAGULL_CONNECTOR_TOKEN`, a self-hosted server becomes a
consumer of one Gull's local durable inbox, reached after
`A2A endpoint -> authenticate -> policy`. Keep the tool names and safety checks
stable through that change; it is the backend that moves, not the tool
contract.
