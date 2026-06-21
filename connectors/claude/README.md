# Claude Connector

Adapter for Claude-like agent environments.

Initial goal:

- Use a remote MCP connector for Claude.ai Web.
- Keep tool schemas aligned with `connectors/mcp/README.md`.
- Support BYO self-hosting for users who want to control the bridge runtime.
- Avoid browser automation of `claude.ai`; use MCP connectors or Claude API
  agent surfaces instead.
