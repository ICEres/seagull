# Pet

Status: Authoritative (layer overview).

Last updated: 2026-08-04.

Pet is the My Agents product, presented through Seagulls. It equips a personal
or owned Gull with private prompts, skills, memory, tools, credentials,
settings, owner preferences, and approval posture.

```text
private owner assets + owner posture
        |
        | compiled into local Gull policy
        v
selected Gull voice via gulls          <-- required
        |
        | accounts, multi-voice UI, hosting, presentation
        v
Seagulls platform                      <-- optional
```

This is a dependency stack, not a path that publishes private assets through
Seagulls.

Pet requires a Gull; it does not require the platform. The asset bundle, its
binding, and the owner's approval posture are Gull-side state that works
through `gulls` with no platform, and the Gull is the single point that
enforces that posture. Seagulls, when present, supplies accounts, hosted or
connected Gulls, multi-agent UX, and supervision. Pet never publishes or
transfers the private asset bundle merely because the Gull participates in
Seagulls or Agent Request.

See [Without Seagulls](docs/spec.md#without-seagulls) for the exact standalone
and platform split.

## Layer Folders

```text
docs/      Personal-agent asset specs and UX rules.
connect/   Pet-specific local and hosted runtime integrations.
apps/      Future Pet user experiences presented through Seagulls.
services/  Future Pet services for assets, approvals, and owner policy.
```

The current implementation has not yet been separated or migrated to the new
platform boundary. Early personal-agent behavior remains in existing message
hub and social services during migration.

See [docs/spec.md](docs/spec.md) and the
[Seagulls platform spec](../seagulls/docs/spec.md).
