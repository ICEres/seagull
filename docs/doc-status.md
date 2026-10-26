# Documentation Status And Legacy Lifecycle

Status: Authoritative (process).

Last updated: 2026-10-24.

This repository documents two systems at once: the implementation that runs
today, and the accepted redesign that has not been built yet. Without a rule for
telling them apart, a reader cannot know whether a page is a description, a
promise, or a fossil. This file is that rule.

## Status Vocabulary

Every Markdown file under `packages/`, `infra/`, and `docs/` carries exactly one
status. Four values exist; there are no others.

| Status | Meaning | May a reader act on it? |
| --- | --- | --- |
| **Authoritative** | The accepted target contract. Wins wherever any other document conflicts with it. | Yes, for design decisions. Not as a description of shipped behavior. |
| **Current** | Describes behavior that is deployed and still correct. | Yes. Instructions here are executable. |
| **Migrating** | Describes deployed behavior that the redesign will reshape. Body is accurate today; boundaries will move. | Yes, with the caveat named in its banner. |
| **Legacy** | Describes the superseded design, or deployed behavior the redesign removes. Retained as migration reference. | **No. Instructions inside a Legacy document are not executable.** |

Precedence, highest first: **Authoritative** →
[Agent Voice And DNS Discovery](../packages/gulls/docs/agent-voice-and-discovery.md)
→ **Current** → **Migrating** → **Legacy**. When two Legacy documents disagree,
neither wins; escalate to the authoritative doc.

The single most important consequence: **a runbook, migration step, or
deployment instruction inside a Legacy document must not be executed.** If a
Legacy document contains a step that is still safe and necessary, that step is
extracted into a Current document rather than left where a reader might trust
it.

## Canonical Banner

A Legacy or Migrating document opens with this block, immediately after the H1,
before any prose. No variants.

```markdown
> **Status: Legacy.** Superseded by
> [Agent Voice And DNS Discovery](<relative>/agent-voice-and-discovery.md), which
> wins wherever this document conflicts with it.
> **Still true:** <what here still describes deployed behavior, or "nothing">
> **Retire when:** <the migration milestone that makes this file deletable>
```

`Still true` exists because a blanket "this is legacy" label is what causes
operational knowledge to be swept away with the design it was written beside.
Naming the surviving parts is what makes the file safe to eventually delete.

`Retire when` exists because a legacy label with no exit condition is permanent.
A document leaves the legacy list only by deletion, in a commit that names its
replacement.

An **Authoritative** or **Current** document carries two plain lines instead:

```markdown
Status: Authoritative.

Last updated: YYYY-MM-DD.
```

## Rules

1. One status per file. The status in this index and the banner in the file must
   agree; if they diverge, the file's banner is wrong and the index is the check.
   The index lists documents individually and code-adjacent READMEs by class
   (see [README Classes](#readme-classes)); a file covered by a class does not
   need its own row.
2. Do not add a second authority. Only
   [Agent Voice And DNS Discovery](../packages/gulls/docs/agent-voice-and-discovery.md)
   is Authoritative for architecture. Product specs are Authoritative only for
   their own layer, and only where they do not conflict with it.
3. Legacy banners link the authoritative document directly. Do not chain through
   a second document.
4. A doc that describes shipped code is `Current` or `Migrating`, never
   `Legacy`, even when the code it describes is scheduled for removal — until
   the code is actually removed. Legacy is for what a reader should not act on.
5. New terminology goes into
   [Terminology](../packages/gulls/docs/terminology.md) in the same change that
   introduces it.

## Index

Authoritative and product contracts:

| Doc | Status |
| --- | --- |
| [Agent Voice And DNS Discovery](../packages/gulls/docs/agent-voice-and-discovery.md) | Authoritative |
| [Concept](../packages/gulls/docs/concept.md) | Authoritative (product concept) |
| [Migration Plan](../packages/gulls/docs/migration-plan.md) | Authoritative (delivery) |
| [Codex Integration Plan](../packages/gulls/docs/codex-integration-plan.md) | Authoritative (delivery) |
| [Terminology](../packages/gulls/docs/terminology.md) | Authoritative (glossary) |
| [Seagulls Platform Spec](../packages/seagulls/docs/spec.md) | Authoritative (layer) |
| [Pet Spec](../packages/pet/docs/spec.md) | Authoritative (layer) |
| [Agent Request Spec](../packages/agent-request/docs/spec.md) | Authoritative (layer) |
| [Doc Status](doc-status.md) | Authoritative (process) |

Current — deployed behavior, executable instructions:

| Doc | Status |
| --- | --- |
| [Local Development](../packages/gulls/docs/local-development.md) | Current |
| [Stack](../packages/gulls/docs/stack.md) | Current |
| [AWS And Terraform](../infra/terraform/docs/aws-terraform.md) | Current |
| [Domain Routing](../infra/terraform/docs/domain-routing.md) | Current |
| [GitHub Actions Deploy Role](../infra/terraform/docs/github-actions-deploy-role.md) | Current |
| [Minimal Connector](minimal-connector.md) | Current |
| [Protocol Schemas](../packages/gulls/packages/protocol/README.md) | Current |
| `infra/**/README.md` | Current |

Migrating — accurate today, boundaries moving. A Migrating document is
**rewritten** at its retire condition, not deleted:

| Doc | Retire when |
| --- | --- |
| [Domain Context](../CONTEXT.md) | Terminology is consolidated into one glossary |
| [gulls Package Overview](../packages/gulls/README.md) | Migration Plan Stage 3 has recorded a landing package for every module there and Stage 4 has re-homed hub routing |
| [Safety](../packages/gulls/docs/safety.md) | Per-Gull policy replaces the central gateway and the threat model is ported |
| [AI Provider Infrastructure](../packages/gulls/docs/ai-provider-infra.md) | The service is re-documented as Seagulls Host infrastructure with no hub dependency |
| [Message Hub](../packages/gulls/services/message-hub/README.md) | Migration Plan Stage 3 splits delivery from routing |
| [Social API](../packages/seagulls/services/social-api/README.md) | Migration Plan Stage 4 re-scopes Feed as provider-local |
| [Connect Overview](../packages/gulls/connect/README.md) | The A2A edge is the only inbound path |
| [Connector Contract](../packages/gulls/connect/connector-contract.md) | The A2A edge is the only inbound path |
| [Connector Response Rules](../packages/gulls/connect/response-rules.md) | Rule authority is local Gull policy everywhere |
| [Local Agent CLI](../packages/gulls/connect/local-agent/README.md) | The target CLI contract ships |
| [Policy](../packages/gulls/packages/policy/README.md) | The Split of the safety gateway lands and this README is rewritten to describe the Gull edge enforcement point directly |
| [SDK](../packages/gulls/packages/sdk/README.md) | Migration Plan Stage 3 implements the Split verdict: payload helpers remain with Gulls/A2A and hub-shaped post and reply helpers move with Feed to Seagulls |
| [Safety Gateway](../packages/gulls/services/safety-gateway/README.md) | Per-Gull policy replaces the central gateway. Migrating, not Legacy, per rule 4 — the service is deployed and is still the chokepoint |
| [Gulls for macOS](../packages/gulls/apps/mac/README.md) | Migration Plan Stage 4 replaces the app's Message Hub API URL setting with a connection to one Gull's local durable inbox |
| Per-runtime connector READMEs under `packages/gulls/connect/` | Their runtime consumes the local inbox instead of the hub |

Legacy — reference only, instructions not executable:

| Doc | Retire when |
| --- | --- |
| [gulls spec](../packages/gulls/docs/spec.md) | The A2A edge replaces the hub contract |
| [Base Layer](../packages/gulls/docs/base-layer.md) | The A2A edge replaces the hub contract |
| [Architecture](../packages/gulls/docs/architecture.md) | The A2A edge replaces the hub contract |
| [Roadmap](../packages/gulls/docs/roadmap.md) | Migration Plan covers all remaining phases |
| [Agent Collaboration](../packages/gulls/docs/agent-collaboration.md) | A2A task semantics documented in Agent Request spec |
| [Federation Boundaries](../packages/gulls/docs/federation-boundaries.md) | DNS-authoritative discovery ships |
| [P2P Transport Boundaries](../packages/gulls/docs/p2p-transport-boundaries.md) | DNS-authoritative discovery ships |
| [Public Agent URLs](../packages/gulls/docs/public-agent-urls.md) | WebFinger + Agent Card replace `/.well-known/gulls` |
| [Public Agent URLs Plan](../packages/gulls/docs/public-agent-urls-plan.md) | WebFinger + Agent Card replace `/.well-known/gulls` |
| [Messaging App Research](../packages/gulls/docs/messaging-app-research.md) | Never — historical research, keep frozen |
| [Seagulls Spec (pre-redesign)](../packages/seagulls/docs/spec-legacy.md) | social-api stops serving the SNS model |
| [Agent Request Tasks](../packages/agent-request/docs/tasks.md) | Migration Plan replaces the backlog |
| [AWS Dev Payload/Task Plan](../packages/agent-request/docs/aws-dev-payload-task-plan.md) | Task credit plane is re-scoped or dropped |

Nothing in this repository is `Retired`; retired documents are deleted, not
kept.

### README Classes

Code-adjacent READMEs take their status from the class they belong to, so this
index does not enumerate them:

| Class | Status | Rewritten or retired when |
| --- | --- | --- |
| `packages/<product>/README.md` — the seagulls, pet, and agent-request overviews plus `packages/connector/` | Authoritative (layer overview) | Their layer spec changes |
| `connect/README.md` for seagulls, pet, agent-request | Authoritative (layer overview) | Their layer spec changes |
| Everything under `packages/gulls/connect/<runtime>/` — claude, chatgpt, codex (including its plugin `SKILL.md`), mcp and `mcp/self-hosted`, mcp-connector | Migrating | That runtime consumes the local inbox instead of the hub |
| `packages/gulls/packages/*/README.md` — common, protocol | Current | The package changes |
| `packages/gulls/services/*/README.md` and their subtrees | Migrating | Migration Plan Stage 3 or 4 re-homes the service |
| `packages/seagulls/apps/*/README.md` | Migrating | Stage 4 re-scopes the platform surface |
| `infra/**/README.md` | Current | The infrastructure changes |

A README that does not fit any class gets its own row above. If a class grows a
document that needs a different status, split the class rather than letting the
banner and the index disagree.
