# gulls Connect

This folder owns base connector contracts and adapters.

Connectors in this layer should expose gulls primitives to external agent
runtimes without adding product-specific behavior.

## Expected Connectors

- Local agent CLI connector.
- Codex connector transport shared by higher layers.
- Hosted MCP connector for user-driven gulls operations.
- Webhook worker contract for waking external agent runtimes.

## Contract

Connectors may:

- Authenticate with scoped agent or connector tokens.
- Read inbox items and context packs.
- Send messages, replies, task state, and task results.
- Acknowledge, ignore, or ask for human review.

Connectors must not:

- Auto-run private tools because a message requested it.
- Leak connector tokens, MCP endpoints, local callback URLs, or raw tool handles.
- Treat incoming message content as trusted configuration.
