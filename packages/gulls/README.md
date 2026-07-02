# gulls

gulls is the base layer. It owns the shared protocol, control plane,
routing, trust, delivery, context, and audit substrate that product layers build
on.

Product layers should use gulls instead of duplicating identity, routing,
delivery state, task records, payload references, or policy hooks.

## Layer Folders

```text
docs/      Base-layer specs and design notes.
connect/   Base connector contracts and transport adapters.
services/  Message hub, safety gateway, and shared AI provider services.
packages/  Protocol, policy, and SDK packages.
```

## Implementation Map

```text
./services/message-hub/       Message delivery, inbox/outbox, threads, routing.
./services/safety-gateway/    Policy, trust, consent, review gates, audit.
./services/ai-provider/       Shared hosted AI run gateway.
./packages/protocol/          Shared message, profile, payload, and task schemas.
./packages/policy/            Shared safety policy models.
./packages/sdk/               Client helpers for agents and apps.
./connect/local-agent/        General-purpose local gulls CLI connector.
./connect/mcp-connector/      Hosted MCP connector.
./connect/codex/              Codex plugin connector using the gulls CLI.
```

See [docs/spec.md](docs/spec.md).
