# Codex Connector

Codex uses the project-owned Codex plugin named `seagull`.

The plugin does not duplicate connector transport. It teaches Codex when and how
to use the general local agent connector in [`../local-agent`](../local-agent),
which exposes the project CLI:

```text
seagull inbox
```

The plugin source lives in this connector folder:

```text
connectors/codex/plugin
```

The local project marketplace points at that plugin through:

```text
.agents/plugins/marketplace.json
```

Keep Codex-specific behavior in prompts or agent profile rules. Keep transport,
inbox, reply, notification, and context-file behavior in the shared local agent
connector.

Connector-driven response generation follows the shared
[Connector Response Rules](../../docs/connector-response-rules.md) contract.
Codex-specific prompts may influence drafting only through that trusted rule
configuration, not through untrusted message content.
