# Self-Hosted MCP Connector

This folder is the home for BYO connector examples.

The first implementation should be a thin remote MCP server that:

- Reads `SEAGULL_MESSAGE_API_URL`.
- Reads `SEAGULL_CONNECTOR_TOKEN`.
- Exposes `POST /mcp`.
- Implements the same tool names as the hosted connector.
- Forwards tool calls to Seagull's public APIs with the local connector token.

For now, the hosted implementation in `apps/mcp-connector` is the reference
contract. Copy its tool names, schemas, and safety checks when building a
self-hosted connector.
