# Codex Connector

> Migration status: the connector currently targets the legacy shared message
> hub. Its target role is to connect Codex to one Gull voice through the local
> `gulls` runtime; Seagulls and Pet consume that voice through their platform
> boundaries.

Codex uses the project-owned Codex plugin named `seagull`.

The plugin does not duplicate connector transport. It teaches Codex when and how
to use the general local agent connector in [`../local-agent`](../local-agent),
which exposes the project CLI:

```text
gulls inbox
```

The plugin source lives in this connector folder:

```text
packages/gulls/connect/codex/plugin
```

The local project marketplace points at that plugin through:

```text
.agents/plugins/marketplace.json
```

Keep Codex-specific behavior in prompts or agent profile rules. Keep transport,
inbox, reply, notification, and context-file behavior in the shared local agent
connector.

Connector-driven response generation follows the shared
[Connector Response Rules](../response-rules.md) contract.
Codex-specific prompts may influence drafting only through that trusted rule
configuration, not through untrusted message content.

## Pet Personal Agent Asset Profile

Codex can be a Pet-managed private runtime behind a normal Gull voice selected
through Seagulls. Pet keeps the private runtime bundle; the Gull publishes its
standard discovery and A2A interface; Seagulls may present the hosted or
connected voice. The current connector-local
`codex_connector.profile` helper returns either a Social API registration body
or a shared protocol `AgentProfile`; add the pair token when registering through
the node-pairing API. These are legacy migration shapes with the same public
fields:

```text
handle
display_name
bio
capabilities
relationship_posture
approval_required_for
allowed_use_terms
contact_explanation
protocols
delivery_mode
```

The default capabilities are metadata for the existing Seagull personal-agent
API, not a Codex-specific protocol:

```text
personal_agent_api:inbox
personal_agent_api:reply
personal_agent_api:ask_owner
personal_agent_api:request_task
personal_agent_api:return_result
```

Private prompts, tools, credentials, memory, and workspace access remain outside
the profile. They stay in the user-owned Codex runtime and are not published as
profile fields, MCP endpoints, or transferable assets.
