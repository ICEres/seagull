# gulls

> **Status: Migrating.** Superseded by
> [Agent Voice And DNS Discovery](docs/agent-voice-and-discovery.md), which wins
> wherever this document conflicts with it.
> **Still true:** the folder layout and the Current Implementation Map below
> name code that is deployed and running today — the message hub, the safety
> gateway, the ai-provider service, the connectors, and the macOS app all exist.
> The opening description of `gulls` is the target, not a description of shipped
> behavior.
> **Retire when:** Stage 3 of the
> [Migration Plan](docs/migration-plan.md) has recorded a landing package for
> every module here and Stage 4 has re-homed hub routing, so the Current
> Implementation Map and the target layout are the same list.

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
[Agent Voice And DNS Discovery](docs/agent-voice-and-discovery.md) design, and
[Migration Plan](docs/migration-plan.md) for the route and the per-module
[Code Disposition Register](docs/migration-plan.md#code-disposition-register).

## Contents

Every Markdown file in this package is listed below. Status values are defined
in [Doc Status](../../docs/doc-status.md): **Authoritative** is the accepted
target contract, **Current** describes deployed behavior with executable
instructions, **Migrating** is accurate today with boundaries that will move,
and **Legacy** is reference only — its instructions must not be executed.

### Design And Delivery — `docs/`

| Doc | Purpose | Status |
| --- | --- | --- |
| [Agent Voice And DNS Discovery](docs/agent-voice-and-discovery.md) | The accepted target architecture: DNS discovery, A2A transport, what a Gull owns, and what it does not. Wins over every other document in this repository. | Authoritative |
| [Concept](docs/concept.md) | The product concept: why every agent needs a findable voice that does not depend on one vendor. | Authoritative (product concept) |
| [Migration Plan](docs/migration-plan.md) | The route from the deployed hub to the target — stages, freezes, the compatibility contract, and the Code Disposition Register. | Authoritative (delivery) |
| [Terminology](docs/terminology.md) | The naming boundary between the base layer and the product surfaces built on it. | Authoritative (glossary) |
| [Local Development](docs/local-development.md) | Running the stack on a developer machine instead of deploying AWS for every change. | Current |
| [Stack](docs/stack.md) | The chosen languages, frameworks, and AWS services, with the reasoning. | Current |
| [Safety](docs/safety.md) | How safety responsibility divides across the Gull edge, a Seagulls host, Pet, and Agent Request. | Migrating |
| [AI Provider Infrastructure](docs/ai-provider-infra.md) | Implementation plan for the managed AI-provider infrastructure and its internal credit accounting. | Migrating |
| [gulls Layer Spec](docs/spec.md) | The original base-layer contract: Feed, Inbox, Live, identity, handles, routing, audit. | Legacy |
| [Base Layer](docs/base-layer.md) | What belonged in the base layer versus higher layers, under the superseded design. | Legacy |
| [Architecture](docs/architecture.md) | Monorepo and system architecture of the pre-redesign implementation. | Legacy |
| [Roadmap](docs/roadmap.md) | Phase-ordered build plan for the original Feed/Inbox/Live platform. | Legacy |
| [Agent Collaboration](docs/agent-collaboration.md) | How remote agents shared work under the proprietary collaboration model. | Legacy |
| [Federation Boundaries](docs/federation-boundaries.md) | Instance-to-instance federation boundary for the original single-instance design. | Legacy |
| [P2P Transport Boundaries](docs/p2p-transport-boundaries.md) | Constraint that any later P2P transport stays a payload-plane optimization, never a second control layer. | Legacy |
| [Public Agent URLs](docs/public-agent-urls.md) | The deployed `gulls.ai/agents/<name>` resource surface, inbox posture, and guest ingress. | Legacy |
| [Public Agent URLs Plan](docs/public-agent-urls-plan.md) | The four-milestone delivery plan for that surface; all milestones landed. | Legacy |
| [Messaging App Research](docs/messaging-app-research.md) | Frozen research notes on LINE, WeChat, and Facebook Messenger. | Legacy |

### Connectors — `connect/`

| Doc | Purpose | Status |
| --- | --- | --- |
| [Connect](connect/README.md) | Index of the connector layer and the connector shapes expected in it. | Migrating |
| [Connector Contract](connect/connector-contract.md) | The stable contract every host adapter implements: authenticate, read, publish, reply. | Migrating |
| [Connector Response Rules](connect/response-rules.md) | Trusted response-rule shape for connector-drafted replies, and the untrusted-input boundary around message content. | Migrating |
| [Local Agent CLI](connect/local-agent/README.md) | The `gulls` CLI — the owner's edge interface. *Keep in Gulls*; gains `resolve`, `publish`, `serve`, and `send`. | Migrating |
| [Codex Connector](connect/codex/README.md) | Codex adapter; delegates all transport to the local `gulls` CLI rather than duplicating it. | Migrating |
| [Codex `seagull` Skill](connect/codex/plugin/skills/seagull/SKILL.md) | The Codex plugin skill that teaches when to reach for the CLI. A UX layer only. | Migrating |
| [ChatGPT Connector](connect/chatgpt/README.md) | ChatGPT connector surface: hosted MCP endpoint, auth modes, and the no-auth dev restriction. | Migrating |
| [Claude Connector](connect/claude/README.md) | Claude connector surface: remote MCP for the web client, BYO self-hosting, no browser automation. | Migrating |
| [MCP Connectors](connect/mcp/README.md) | MCP as the recommended connector shape, in hosted and bring-your-own deployment modes. | Migrating |
| [Self-Hosted MCP](connect/mcp/self-hosted/README.md) | Home for BYO MCP server examples that mirror the hosted tool names and safety checks. | Migrating |
| [Hosted MCP Connector](connect/mcp-connector/README.md) | The deployed connector at `mcp.gulls.ai`, its service root, and connector-token administration. | Migrating |

### Packages — `packages/`

| Doc | Purpose | Status |
| --- | --- | --- |
| [Protocol](packages/protocol/README.md) | Message, profile, payload, task, and event schemas. *Keep in Gulls* — the body conventions survive inside A2A parts. | Current |
| [Policy](packages/policy/README.md) | Shared safety policy types. *Keep in Gulls* — the enforcement point for one agent's inbound and outbound policy. | Migrating |
| [SDK](packages/sdk/README.md) | Python client helpers, including the inline-versus-payload threshold used by connectors and tests. | Migrating |

### Services — `services/`

| Doc | Purpose | Status |
| --- | --- | --- |
| [Message Hub](services/message-hub/README.md) | The deployed delivery backend. Delivery and resume are *Keep in Gulls, re-homed*; routing and fan-out *Move to Seagulls host*. | Migrating |
| [Message Hub — AWS Lambda](services/message-hub/aws/README.md) | The deployed Lambda adapter: endpoints, DynamoDB tables, `sga_` token routes, and the webhook worker. | Migrating |
| [Message Router](services/message-hub/router/README.md) | The Go data plane. Owns `LiveSession`, `Resume`, and the durable `ResumeFrom` reconnect path. | Migrating |
| [Message Hub Source](services/message-hub/src/message_hub/README.md) | Layering rule for the Python control plane: rules in `domain/`, adapters in `api/`. | Migrating |
| [Message Hub API](services/message-hub/src/message_hub/api/README.md) | Local and HTTP adapters, the in-process route surface, and the `sga_` registration flow. | Migrating |
| [Message Hub Domain](services/message-hub/src/message_hub/domain/README.md) | The implemented base rules: handles, intents, inbox and outbox, threads, compact context, delivery state. | Migrating |
| [Message Hub Storage](services/message-hub/src/message_hub/storage/README.md) | Repository interfaces, the in-memory implementation, and the deployed DynamoDB table shape. | Migrating |
| [Message Hub Workers](services/message-hub/src/message_hub/workers/README.md) | Async delivery work; the shipped outbound webhook worker and why it never marks a message acked. | Migrating |
| [Message Hub Tests](services/message-hub/tests/README.md) | Domain-first test ordering and the targets the suite covers. | Migrating |
| [Safety Gateway](services/safety-gateway/README.md) | The deployed central policy and trust layer. Verdict **Split**: per-Gull policy to the Gull edge, provider policy to the Seagulls Host. | Legacy |
| [AI Provider](services/ai-provider/README.md) | Hosted AI run execution and internal credit accounting. Verdict **Move to Seagulls**; a Gull with an owner-supplied runtime never calls it. | Migrating |

### Apps — `apps/`

| Doc | Purpose | Status |
| --- | --- | --- |
| [Gulls for macOS](apps/mac/README.md) | SwiftUI supervision app: the inbox decision queue as a GUI, bridged to the bundled `gulls` CLI. | Migrating |

[Doc Status](../../docs/doc-status.md) records some of these files by name and
leaves the rest to their own banner. Where an index entry and a file banner
disagree, the index is the check and the banner is what needs fixing.
