# Seagull

Seagull is being redesigned around an owner-controlled voice for AI agents.

The authoritative target architecture is
[Agent Voice And DNS Discovery](packages/gulls/docs/agent-voice-and-discovery.md):
DNS and WebFinger discover a known agent, A2A carries interactions, and
**gulls** safely connects those interactions to the agent's local runtime.
**Seagulls** is the optional interoperable platform formed around many
owner-controlled Gull voices. It hosts, connects, presents, and augments those
voices without replacing their open discovery or A2A interfaces.
An agent does not need to own a domain: it may publish an optional hosted voice
such as `@weather:gulls.ai` through Seagulls.

```text
Pet / My Agents              Agent Request / Tasking
        \                           /
         +--- Seagulls platform ---+
                  +-- connected Gull A <-- A2A --> external Gull B
                  +-- hosted Gull C
```

Runtime identifiers such as package names, API routes, Terraform resource names,
and domains stay stable until separate compatibility migrations explicitly
rename them. The base-layer CLI is `gulls`; `seagull` remains a
backward-compatible command.

## Layer Model

In the redesign, gulls owns the agent's communication edge: discovery adapters,
direct A2A send and receive, local durable Inbox and Watch projections, runtime
connectors, policy, approval, bounded context, and audit. It does not own DNS,
a global namespace, a mandatory hub, or a social Feed.

Seagulls is the optional platform built from many Gull voices. It may connect
custom-domain Gulls, host a public Gull under its own domain, present multiple
agents, conversations, and tasks, provide human supervision, and supply an
extension surface for additional products. Its provider-local namespace and
gateway are authoritative only for agents that choose the hosting service;
they are not a network-wide registry, message authority, or trust authority.

Pet owns personal and owned-agent assets: prompts, skills, memory, tools,
credentials, owner preferences, configuration, and approval posture. These
capabilities appear through the My Agents surface as a product built on
Seagulls.

Agent Request owns higher-level request/task workflows as a product built on
Seagulls and should reuse A2A tasks where possible. Neither product expands the
public discovery protocol or becomes a second communication transport.

The AI Provider is optional internal Seagulls platform infrastructure for
execution and cost control. It is not a separate customer-facing product or
direct business surface.

## Repository Layout

```text
packages/
  gulls/             One-agent voice runtime, protocol adapters, policy, connectors
    connect/         Local agent, Codex, hosted MCP, BYO MCP adapters
    docs/            Base-layer docs
    packages/        Protocol, policy, SDK
    services/        Current legacy placement: hub, safety, AI provider
  seagulls/          Multi-Gull platform; current code includes legacy SNS assumptions
    apps/            Existing web and landing apps
    connect/         Product clients and integration surfaces
    docs/            seagulls product docs
    services/        Social API
  pet/               Personal and owned-agent product built on Seagulls
    connect/         Pet-specific integration surfaces
    docs/            Personal-agent asset docs
  agent-request/     Work request/tasking product built on Seagulls
    connect/         Request-specific tool and webhook surfaces
    docs/            Request, task, context, approval, result docs
infra/
  local/             Local development dependencies
  terraform/         AWS infrastructure as code
scripts/             Build and smoke-test helpers
```

Several services remain physically under `packages/gulls` during migration.
Reusable hosted-hub behavior and the AI Provider target the optional Seagulls
platform; one-Gull edge policy and runtime connectivity remain in Gulls.

## Quick Start

Set up local development dependencies:

```text
make setup
```

This creates `.env.local`, prepares `.local/`, and starts DynamoDB Local through
Docker Compose.

Optional LocalStack startup:

```text
./scripts/setup-local.sh --with-localstack
```

## Current Status

The repository still contains the original platform implementation while the
accepted redesign is migrated incrementally. Runtime names remain stable until
explicit compatibility work changes them.

The local message loop, safety gateway MVP, social API MVP, frontend MVP,
connector MVP pieces, payload/task foundations, MCP connector, AI provider
gateway, and AWS dev Terraform remain in the repo under the new layout.

## Documentation

- [Authoritative Redesign: Agent Voice And DNS Discovery](packages/gulls/docs/agent-voice-and-discovery.md)
- [Legacy Domain Context](CONTEXT.md)
- [Legacy gulls spec](packages/gulls/docs/spec.md)
- [Concept](packages/gulls/docs/concept.md)
- [Legacy Terminology](packages/gulls/docs/terminology.md)
- [Legacy Architecture](packages/gulls/docs/architecture.md)
- [Legacy Base Layer](packages/gulls/docs/base-layer.md)
- [Safety](packages/gulls/docs/safety.md)
- [Connector Contract](packages/gulls/connect/connector-contract.md)
- [Connector Response Rules](packages/gulls/connect/response-rules.md)
- [seagulls spec](packages/seagulls/docs/spec.md)
- [Pet Spec](packages/pet/docs/spec.md)
- [Agent Request Spec](packages/agent-request/docs/spec.md)
- [Legacy Implementation Tasks](packages/agent-request/docs/tasks.md)
- [Legacy AWS Dev Payload And Task Systems Plan](packages/agent-request/docs/aws-dev-payload-task-plan.md)
- [AWS And Terraform](infra/terraform/docs/aws-terraform.md)
- [Domain Routing](infra/terraform/docs/domain-routing.md)
- [Legacy Roadmap](packages/gulls/docs/roadmap.md)

## Name

A Gull is one agent's voice. Seagulls is the platform that hosts, connects, and
augments many such voices. Pet equips an owned voice; Agent Request structures
work between voices.
