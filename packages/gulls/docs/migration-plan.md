# Migration Plan

Status: Authoritative (delivery plan).

Last updated: 2026-07-27.

[Agent Voice And DNS Discovery](agent-voice-and-discovery.md) defines the target
architecture. This document defines how the repository gets there from what is
deployed today, in what order, and what must stop.

It exists because the redesign landed as prose. The accepted architecture
describes a system with no implementation, while the running code is still
building toward the design the redesign supersedes. Until this plan is executed,
those two facts coexist, and every reader needs to know which one applies.

## Scope

In scope: discovery, transport, the Gull edge, the disposition of the message
hub and social API, and the compatibility contract for deployed identifiers.

Out of scope: renaming code identifiers, packages, DynamoDB tables, or domains.
Those are frozen (see [Compatibility Contract](#compatibility-contract)) and
need their own change with its own migration.

## Definition Of Done

Migration is complete when every one of these is demonstrated by a test or a
metric, not by a document:

1. Two independent Gulls discover and communicate with no common Seagulls
   service.
2. An agent with no owner-controlled domain publishes a resolvable public voice
   through optional Seagulls hosting.
3. One person connects or hosts several Gulls and supervises them from one
   Seagulls platform.
4. Pet equips an owned Gull without exposing its private asset bundle.
5. Agent Request coordinates bounded A2A work and presents durable task state.
6. Removing a Seagulls client leaves an independently published Gull
   discoverable and able to communicate.
7. No network-wide Seagulls database is required for identity or delivery.

Criteria 1 and 6 are the ones that fail today, and they fail for the same
reason: there is no transport except the hub.

## Stage 0 — Freeze

Before anything is built, work that deepens the superseded coupling stops.

**Frozen — do not execute:**

- **Feed cutover step 4**, "Drop the seagulls feed tables"
  ([Social API](../../seagulls/services/social-api/README.md)). This step is
  irreversible and its stated justification — making gulls the source of truth
  for Feed — is the opposite of the accepted architecture, which moves Feed out
  of the Gull base entirely. The step is marked DO-NOT-EXECUTE at its site.
- **New task-credit tables** proposed in
  [AWS Dev Payload And Task Plan](../../agent-request/docs/aws-dev-payload-task-plan.md).
  Quote, escrow, credit ledger, and dispute state have no home in the accepted
  architecture until Agent Request's A2A mapping is settled.
- **New `/.well-known/gulls` surface area.** The existing endpoint keeps
  serving; nothing new is added to it.

**Held as-is:** `feed_mirror_metrics_enabled` and `gulls_feed_reads_enabled`
stay at their current dev values. The mirrored data is not discarded — Stage 4
decides whether it becomes the Seagulls host store or is retired.

**Not frozen:** everything unrelated to the Feed/hub boundary, including auth
verification, the deploy-role IAM repairs, and durable delivery resume.

Blast radius: none. Stage 0 is a decision, not a deploy.

## Stage 1 — Prove The Vertical Slice

The single blocking item. Every other stage assumes a working Gull-to-Gull path
that does not exist yet.

Build, additively and beside the hub, on one throwaway domain: WebFinger resolve
→ AID or DNS-AID endpoint discovery → A2A Agent Card fetch → A2A `SendMessage`
send and serve → local durable inbox projection.

- **Precondition:** Stage 0.
- **Flag:** `GULLS_A2A_EDGE` (new, default off).
- **Acceptance:** an automated test resolves a handle it was not configured
  with, sends a message, and reads it from the receiving side's local inbox.
  That test is Definition-of-Done criterion 1.
- **Rollback:** turn the flag off. Nothing existing depends on the new path.
- **Blast radius:** none while the flag is off.

Nothing about Feed, the hub, or the social API changes in this stage. Deleting
capability before the replacement runs is how a migration becomes an outage.

## Stage 2 — Hosted Voice

Publish `@name:gulls.ai` through the existing accounts, DNS, and hosting work:
WebFinger document, Agent Card, A2A endpoint, durable hosted inbox.

- **Precondition:** Stage 1 acceptance passes.
- **Acceptance:** Definition-of-Done criterion 2. A hosted voice resolves and
  receives from the Stage 1 slice with no shared code path.
- **Rollback:** stop publishing the zone records; hosted Gulls become
  unreachable but no other Gull is affected.
- **Blast radius:** additive. This is the only no-regret stage — it reuses
  shipped account and DNS work and gives Stage 1 a second endpoint to talk to.

Stage 2 is deliberately early. It is cheap, it validates the host role against
a real peer, and it is the stage that proves the platform is optional by making
it visibly separable.

## Stage 3 — Classify And Re-home

Apply the placement test in [Concept](concept.md) to every existing module and
record the verdict in the
[Code Disposition Register](#code-disposition-register). Move code to the
package its verdict names. No behavior changes in this stage.

- **Precondition:** Stage 2. The register cannot be filled honestly until a
  working A2A edge shows what the Gull edge actually needs.
- **Acceptance:** every row in the register has a verdict and a landing package.
- **Rollback:** moves are pure relocation; revert the commit.
- **Blast radius:** import paths. Frozen identifiers are unaffected.

## Stage 4 — Re-scope Feed And The Hub

Feed becomes a provider-scoped Seagulls feature. It is not "moved out" and not
deleted: it is relabeled, re-homed, and cut off from any claim to network-wide
truth. The hub becomes an optional Seagulls host destination, one of several a
Gull owner may select — not the transport a Gull requires.

- **Precondition:** Stage 3, and Definition-of-Done criterion 6 demonstrated.
- **Acceptance:** criteria 6 and 7. A Gull configured for direct A2A never
  contacts the hub.
- **Rollback:** the hub keeps serving throughout; this stage removes a
  dependency, not a service.
- **Blast radius:** high. This is where the Stage 0 freeze on Feed step 4 is
  finally resolved, in one direction or the other, with the answer recorded in
  the register.

## Stage 5 — Product Transports

Move Pet and Agent Request onto A2A tasks. They are leaf consumers and go last.

- **Precondition:** Stage 4.
- **Acceptance:** Definition-of-Done criteria 4 and 5.
- **Rollback:** products keep their existing transport until each cuts over
  independently.
- **Blast radius:** per product.

## Stage 6 — Retire Dual Discovery

Turn off `/.well-known/gulls` after a deprecation window, and delete the
documents whose `Retire when` condition Stage 4 and Stage 5 satisfied.

- **Precondition:** Stage 5, plus a published deprecation date honored.
- **Acceptance:** no traffic on the legacy discovery path for the full window.
- **Rollback:** re-enable the endpoint; it is a read path with no state.

Both discovery mechanisms run in parallel from Stage 1 to Stage 6. There is no
point at which a deployed agent has neither.

## Compatibility Contract

Runtime identifiers do not change during this migration. This is the explicit
list, so that "identifiers stay stable" stops being a slogan.

| Identifier | Status | Changes in |
| --- | --- | --- |
| Python modules `seagull_*` | Frozen | A separate rename migration, not scheduled |
| npm scopes `@seagull/*`, `@seagulls/ui` | Frozen | Same |
| DynamoDB table names | Frozen | Never during this plan; Stage 4 may stop writing, not rename |
| Terraform module and resource names | Frozen | Same |
| Domains `gulls.ai`, `sea.gulls.ai` | Frozen | Stage 2 adds records; renames nothing |
| API route `/.well-known/gulls` | Deprecated | Stage 6, after a published window |
| Env prefixes `SEAGULL_`, `GULLS_`, `SEAGULLS_` | Frozen; new vars use `GULLS_` | A separate rename migration |
| CLI `gulls` | Canonical | — |
| CLI `seagull` | Supported alias, no end-of-life date | Announced separately, never silently |

The `seagull` alias has no removal date on purpose. Removing it is a
user-visible break that must be its own decision, not a side effect of this
plan.

## Code Disposition Register

Every module gets one verdict. Empty verdicts are the work of Stage 3.

| Module | Verdict | Rationale |
| --- | --- | --- |
| `connect/local-agent` (CLI, Go) | Keep in Gulls | It is the owner's edge interface; gains `resolve`/`publish`/`serve`/`send` |
| `packages/policy` | Keep in Gulls | Enforcement point for one agent's inbound and outbound policy |
| `packages/protocol` | Keep in Gulls | Body conventions and refs survive inside A2A parts |
| `services/message-hub` — delivery, resume | Keep in Gulls, re-homed | `DeliveryStore`/`ResumeFrom` is the durable local inbox the target requires |
| `services/message-hub` — routing, fan-out | Move to Seagulls host | Optional destination selected by an owner |
| `services/safety-gateway` | Split | Per-Gull policy to Gulls; provider policy to Seagulls host |
| `services/ai-provider` | Move to Seagulls | Hosted runtime execution is a host concern; a Gull with an owner-supplied runtime never calls it |
| `seagulls/services/social-api` — Feed, follows, rooms | Keep in Seagulls, re-scoped | Provider-local product data, not network truth |
| `seagulls/services/social-api` — accounts, login | Keep in Seagulls | Host and Apps role |
| Feed mirror tables in gulls | **Undecided — Stage 4** | Either becomes the Seagulls host store or is retired; do not drop before this is answered |
| `packages/common` | Keep in Gulls | Shared by five build targets; no README yet, which is a gap to close |
| `packages/sdk` | Split | Payload helpers survive inside A2A parts; `post`/`reply` helpers are hub-shaped and follow Feed to Seagulls |
| `apps/mac` | Keep in Gulls | An owner-facing client for one voice; its hub URL setting becomes a local-inbox connection |
| `packages/connector` (TS) | Undecided — Stage 3 | Not currently placed in the four-product layout |
| `pet/packages/assets` | Keep in Pet | Private owner assets |
| `agent-request/packages/client` | Keep in Agent Request | Product client |

## Rollback And Dual-Run

Stages 1 through 3 are additive and reversible by flag or revert. Stage 4 is the
first stage that removes a dependency, and Stage 6 is the first that removes a
capability; both require the preceding acceptance evidence, and both keep the
old path running until the window closes.

No stage is accepted on the basis of a document being written. Every acceptance
line above names a test or a metric.
