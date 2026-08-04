# Seagull

Seagull is being redesigned around an addressable policy edge for AI agents.
An independently published Gull is owner-operated; a hosted Gull is
provider-operated and owner-configured within that provider's boundaries.

The initial product outcome is deliberately narrower than the full platform:
two independently controlled agents complete one bounded task while the owner
sees and approves the exact effect and retains a durable receipt. See
[Product Direction](PRODUCT.md) for the user, competitive landscape, evidence
gates, and Now / Next / Not Yet priorities.

The authoritative target architecture is
[Agent Voice And DNS Discovery](packages/gulls/docs/agent-voice-and-discovery.md).
Where any other document in this repository conflicts with it, that document
loses. **The redesign is not implemented** — the running system is the
pre-redesign hub, and [Migration Plan](packages/gulls/docs/migration-plan.md) is
the route between them.

DNS and WebFinger discover a known agent, A2A carries interactions, and
**`gulls`** safely connects those interactions to the agent's local runtime.
**Seagulls** is the optional interoperable platform formed around many Gull
voices. It hosts, connects, presents, and augments those voices without
replacing their open discovery or A2A interfaces.
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

## Target Layer Model

This section describes the target, not the code. `gulls` owns the agent's
communication edge: discovery adapters,
direct A2A send and receive, local durable Inbox and Watch projections, runtime
connectors, policy, approval, bounded context, and audit. It does not own DNS,
a global namespace, a mandatory hub, or a social Feed.

Seagulls is the optional platform built from many Gull voices. It may connect
custom-domain Gull voices, host a public Gull under its own domain, present
multiple agents, conversations, and tasks, provide human supervision, and supply
an extension surface for additional products. Its provider-local namespace and
gateway are authoritative only for agents that choose the hosting service;
they are not a network-wide registry, message authority, or trust authority.

"Seagulls" names three separable roles. **Host** provides provider-scoped
identity, delivery, and optional runtime execution; a hosted Gull depends on it.
**Console** is a multi-voice client holding projections only. **Apps** is the
account and extension surface. The platform is optional in the Console and Apps
senses, and not optional for an agent that chose Host.

Pet owns personal and owned-agent assets: prompts, skills, memory, tools,
credentials, owner preferences, configuration, and approval posture. These
appear through the My Agents surface, presented through Seagulls.

Agent Request owns higher-level request/task workflows, presented through
Seagulls, and reuses A2A tasks. Neither product expands the public discovery
protocol or becomes a second communication transport, and neither requires the
platform: Pet's assets and posture are Gull-side state, and Agent Request's
semantics ride A2A task metadata between two Gull voices.

Owner posture from Pet and approval requirements from Agent Request are policy
*inputs*. The Gull is the single enforcement point and fails closed.

The AI Provider is optional internal Seagulls platform infrastructure for
execution and cost control. It is not a separate customer-facing product or
direct business surface.

## Repository Layout

```text
packages/
  gulls/             One-agent voice runtime, protocol adapters, policy, connectors
    apps/mac/        macOS app
    connect/         Local agent CLI, Codex, Claude, ChatGPT, hosted MCP, BYO MCP
    docs/            Architecture, concept, migration plan, legacy design docs
    packages/        common, protocol, policy, sdk
    services/        Current legacy placement: message hub, safety gateway, AI provider
  seagulls/          Multi-voice platform; current code includes legacy SNS assumptions
    apps/            Web and landing apps
    connect/         Product clients and integration surfaces (docs only today)
    docs/            Platform spec, plus the archived pre-redesign spec
    packages/ui/     Shared UI
    services/        Social API
  pet/               Personal and owned-agent product
    connect/         Pet-specific integration surfaces (docs only today)
    docs/            Personal-agent asset docs
    packages/assets/ Asset bundle code
  agent-request/     Work request/tasking product
    connect/         Request-specific tool and webhook surfaces (docs only today)
    docs/            Request, task, context, approval, result docs
    packages/client/ Client code
  connector/         LLM-provider shim (TypeScript). Unrelated to gulls/connect/
infra/
  local/             Local development dependencies
  terraform/         AWS infrastructure as code
scripts/             Build and smoke-test helpers
```

Two naming traps: `packages/connector/` is an LLM-provider shim and has nothing
to do with the agent-runtime adapters in `packages/gulls/connect/`; and the
`connect/` directories under `seagulls`, `pet`, and `agent-request` currently
contain documentation only, while the code for those products lives in their
`packages/` directories.

Several services remain physically under `packages/gulls` during migration.
Reusable hosted-hub behavior and the AI Provider are dispositioned to the
Seagulls platform; one-voice edge policy and runtime connectivity stay with
`gulls`. The per-module verdicts are in
[Migration Plan](packages/gulls/docs/migration-plan.md).

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

`make setup` prepares developer dependencies; it does not start an end-to-end
product. To exercise the current hub-backed inbox without AWS, run the fake hub
in one terminal:

```text
make hubstub-run
```

Then build the real CLI and read the two seeded deliveries in another:

```text
make local-agent-build
env SEAGULL_API_URL=http://127.0.0.1:8200 \
  SEAGULL_AGENT_HANDLE=@worker:gulls.ai \
  packages/gulls/connect/local-agent/bin/gulls inbox
```

This is a runnable demonstration of the current human-mediated decision queue,
not the target A2A edge. The macOS app can use the same stub; see
[Gulls for macOS](packages/gulls/apps/mac/README.md#manual-end-to-end-testing).

## Current Status

The repository contains the original platform implementation. The accepted
redesign is documented but **not built**: no standards-compliant WebFinger
endpoint/profile, AID resolver, or A2A edge exists yet, and discovery is still
served from the proprietary `/.well-known/gulls` endpoint. Runtime names remain
stable until explicit compatibility work changes them; the frozen list is in
[Migration Plan](packages/gulls/docs/migration-plan.md).

Implemented and tested in development: the local message loop, safety gateway
MVP, social API MVP, frontend MVP, payload/task foundations, MCP connector, AI
provider gateway, and AWS dev Terraform. There is no tagged public release,
packaged CLI installer, notarized macOS distribution, or production environment.
Most code now sits under the four-product layout;
`packages/connector/` has not been relocated.

The CLI ships as one Go binary under two names, `gulls` and `seagull`. Build it
with `make local-agent-build`; the output directory is gitignored, so it is not
on `PATH` by default. Its implemented commands are a hub client and do not match
the target CLI contract — see
[Local Agent CLI](packages/gulls/connect/local-agent/README.md).

## Documentation

Design documents declare their status and precedence. **Instructions inside a
Legacy document are not executable.** [Doc Status](docs/doc-status.md) defines
the vocabulary, banner rules, and lifecycle.

Start here:

- [Product Direction](PRODUCT.md) — current assessment, primary user, market
  boundary, human supervision contract, metrics, and investment gates
- [Agent Voice And DNS Discovery](packages/gulls/docs/agent-voice-and-discovery.md)
  — authoritative target architecture
- [Concept](packages/gulls/docs/concept.md) — the product shape
- [Migration Plan](packages/gulls/docs/migration-plan.md) — how the code gets
  there, what is frozen, what is compatible
- [Terminology](packages/gulls/docs/terminology.md) — the glossary, including
  the legacy vocabulary that deployed code still uses
- [Doc Status](docs/doc-status.md) — status vocabulary, precedence, and
  lifecycle

Layer specs:

- [Seagulls Platform](packages/seagulls/docs/spec.md)
- [Pet](packages/pet/docs/spec.md)
- [Agent Request](packages/agent-request/docs/spec.md)

Running the system today:

- [Local Development](packages/gulls/docs/local-development.md)
- [Stack](packages/gulls/docs/stack.md)
- [AWS And Terraform](infra/terraform/docs/aws-terraform.md)
- [Domain Routing](infra/terraform/docs/domain-routing.md)
- [Local Agent CLI](packages/gulls/connect/local-agent/README.md) — the only
  CLI that actually exists
- [Connector Contract](packages/gulls/connect/connector-contract.md)
- [Connector Response Rules](packages/gulls/connect/response-rules.md)

Legacy design documents — kept as migration reference: the gulls spec, base
layer, architecture, roadmap, agent collaboration, federation and P2P
boundaries, public agent URLs, the pre-redesign Seagulls spec, and the Agent
Request task backlog. Their instructions are not executable.

## Name

A Gull is one agent's voice. Seagulls is the optional platform that hosts,
connects, presents, and augments many such voices. Pet equips an owned voice;
Agent Request structures work between voices.

Four similar tokens do different jobs, so they are not interchangeable:
**Seagull** is this repository and the legacy CLI alias. **`gulls`** is the
runtime and CLI. **Gull** is one voice, and the plural is written *Gull voices*
rather than bare "Gulls", which would collide with the layer name.
**Seagulls** is the platform. Full rules are in
[Terminology](packages/gulls/docs/terminology.md).
