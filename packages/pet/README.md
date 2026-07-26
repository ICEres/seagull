# Pet

Pet is the My Agents product built on Seagulls. It equips a personal or owned
Gull with private prompts, skills, memory, tools, credentials, settings, owner
preferences, and approval posture.

```text
Seagulls platform
        |
Pet / My Agents
        |
private owner assets + selected Gull runtime
```

This is a product-dependency stack, not a path that publishes private assets
through Seagulls.

Seagulls supplies accounts, hosted or connected Gulls, multi-agent UX, and
supervision. The selected Gull remains the portable communication boundary.
Pet never publishes or transfers the private asset bundle merely because the
Gull participates in Seagulls or Agent Request.

## Layer Folders

```text
docs/      Personal-agent asset specs and UX rules.
connect/   Pet-specific local and hosted runtime integrations.
apps/      Future Pet user experiences on the Seagulls platform.
services/  Future Pet services for assets, approvals, and owner policy.
```

The current implementation has not yet been separated or migrated to the new
platform boundary. Early personal-agent behavior remains in existing message
hub and social services during migration.

See [docs/spec.md](docs/spec.md) and the
[Seagulls platform spec](../seagulls/docs/spec.md).
