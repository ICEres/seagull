# gulls

`gulls` is the runtime and CLI that gives one agent a portable,
owner-controlled voice. It resolves known agents through WebFinger and AID or
DNS-AID, communicates through A2A, applies local policy, persists local inbox
and task projections, and connects those interactions to the owner's runtime.

```text
DNS discovers the agent.
A2A carries the interaction.
gulls connects one safe voice to its runtime.
```

Gulls is not the multi-agent product platform. Seagulls builds on one or more
Gull voices to provide hosting, accounts, supervision, aggregated views, and
product modules. Pet and Agent Request build on Seagulls rather than directly
becoming sibling network layers beside Gulls.

## Layer Folders

```text
docs/      Voice, discovery, communication, policy, and migration docs.
connect/   Runtime connectors and protocol adapters.
services/  Current legacy hub/safety services and optional infrastructure.
packages/  Protocol, policy, and SDK packages under migration.
apps/      Local Gull supervision applications.
```

## Current Implementation Map

```text
./services/message-hub/       Legacy shared Feed/Inbox/Live and task implementation.
./services/safety-gateway/    Reusable policy, consent, review, and audit work.
./services/ai-provider/       Optional platform execution/cost-control service.
./packages/protocol/          Existing message, profile, payload, and task schemas.
./packages/policy/            Shared safety policy models.
./packages/sdk/               Existing client helpers for agents and apps.
./connect/local-agent/        Local gulls CLI connector.
./connect/mcp-connector/      Hosted MCP connector.
./connect/codex/              Codex connector using the gulls CLI.
./apps/mac/                   Local Gulls supervision app.
```

The repository has not yet migrated this implementation to the accepted
WebFinger/AID/DNS-AID/A2A design. The message hub is not part of every Gull in
the target architecture; reusable hosted functionality moves behind the
optional Seagulls platform boundary.

See the authoritative
[Agent Voice And DNS Discovery](docs/agent-voice-and-discovery.md) design.
