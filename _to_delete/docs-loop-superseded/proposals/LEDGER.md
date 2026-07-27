# Proposal Ledger

Status: Authoritative (process record).

Last updated: 2026-07-26.

The queue state and the loop's permanent memory. Read this before opening
anything — see [README](README.md). Rejected entries never leave this file;
they are the dedup key that stops the loop re-proposing the same idea.

## Open (limit 3)

| ID | Title | Opened | Targets | Waiting on |
| --- | --- | --- | --- | --- |
| [P-0001](0001-agent-identity-layer.md) | Stable agent identifier beneath the handle | 2026-07-26 | `agent-voice-and-discovery.md` §Resolution; `migration-plan.md` Stage 1 | maintainer |

Two slots free.

## Accepted

| ID | Title | Decided | Applied |
| --- | --- | --- | --- |
| — | — | — | — |

## Rejected

Permanent. A rejected claim may only be re-opened with new evidence, and the new
proposal must state what changed.

| ID | Title | Decided | Reason |
| --- | --- | --- | --- |
| — | — | — | — |

## Candidates

Known open questions with no proposal file yet. Parked deliberately: a candidate
costs nothing, an Open proposal costs a decision. The weekly run promotes from
here only when a slot is free and the question is forced.

### Forced by a migration stage

| Candidate | Source | Forced by |
| --- | --- | --- |
| Feed mirror tables in gulls — host store or retire | Code Disposition Register, `Undecided` | Stage 4 |
| `packages/connector` (TS) placement in the four-product layout | Code Disposition Register, `Undecided` | Stage 3 |
| Which WebFinger link relation the handle→Agent-Card hop uses | `agent-voice-and-discovery.md` §Human Handle, documented gap | Stage 1 |
| Whether Stage 1's throwaway domain publishes AID, DNS-AID, or both | `migration-plan.md` Stage 1 | Stage 1 |

### From the 2026-07-26 research brief

| Candidate | Note |
| --- | --- |
| Serve an A2A-shaped `/.well-known/agent-card.json` alongside `/.well-known/gulls` | Must be decided before the CloudFront behavior list is frozen |
| The M3 agent card is unsigned while DAWN requirements call for cryptographic trust indicators | Interacts with P-0001 |
| CONTEXT.md's safety boundary rule does not cover seagulls Feed projection *reads*, which are an untrusted instruction channel | Threat-model gap, not a routing gap |

### From the 2026-07-26 agent-network research

Ordered as delivered in that document's §10. P-0001 is item 1; the rest are
parked.

| Candidate | Note |
| --- | --- |
| Demote AID to the single-agent-domain profile; WebFinger as the per-agent path everywhere | Blocked on P-0001 — the identifier decision changes what the resolver returns |
| Publish one `_index._agents.<domain>` record instead of per-agent DNS | Cheap, low blast radius |
| Add WebFinger implementation rules — bidirectional verification, single-place domain normalization, redirect policy, CORS, delegation-vs-TLS asymmetry, numeric caching, locked grammar, homoglyph check | Large but mechanical; may split |
| State that the Shared Domain Gateway is the store-and-forward tier | Documentation of an existing fact |
| Replace `p2p-transport-boundaries.md` with go/no-go criteria | Its premise (a mandatory relay control plane) no longer exists |
| Petname three-slot model in the local projection contract | Extends the "handle is a display convention" position already taken |
| Policy verdict as a signed object; sign-before-send, fail-open | |
| First-contact budgets recipient-scoped, IP as a weak prior | |
| Capability-token shape for Agent Request delegation | Blocked on Stage 5 |
| Handle lifecycle — leases, quarantine, re-registration warning | |
| Deletion posture in the threat model | |

## Changelog

| Date | Change |
| --- | --- |
| 2026-07-26 | Ledger created; loop stood up; P-0001 opened; candidates seeded from the migration plan, the daily brief, and the agent-network research |
