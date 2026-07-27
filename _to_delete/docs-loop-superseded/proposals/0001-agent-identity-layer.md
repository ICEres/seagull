# P-0001: Stable agent identifier beneath the handle

Status: Open

Opened: 2026-07-26

Decided:

Targets: `packages/gulls/docs/agent-voice-and-discovery.md` §Resolution and
§System Shape; `packages/gulls/docs/migration-plan.md` Stage 1 acceptance.

Trigger: 2026-07-26 agent-network research, §4. Forced now by Migration Plan
Stage 1, which builds the resolution path.

## Claim

The canonical agent identifier should be a key-derived value that never changes,
with `@handle:domain` demoted to a mutable pointer — not an FQDN, which makes
identity equal to whoever currently controls a DNS zone.

## Why now

Stage 1 is the blocking stage and it builds resolution end to end: WebFinger →
AID → Agent Card → `SendMessage` → local inbox projection. Whatever identifier
that slice carries is the identifier every later stage inherits, because Stage 3
re-homes code around it, Stage 5 moves Pet and Agent Request onto A2A task
references that contain it, and the local durable inbox keys on it.

Adding the layer before Stage 1 is a schema decision. Adding it after Stage 1 is
a migration of every stored reference, every audit record, and every capability
grant — the exact work Matrix has failed to complete in eight years across four
unmerged MSCs, having put the homeserver domain in `sender` and signed events
with it.

The doc already contains the symptom without the diagnosis:

> A hosted handle is provider-scoped, so it is not portable the way an
> owner-controlled domain is: moving providers changes the handle, and peers
> holding the old one are not automatically redirected.

That is correct about handles and should stay true. The problem is that there is
currently nothing underneath the handle for it to stay true *of*.

## Evidence

- `packages/gulls/docs/agent-voice-and-discovery.md` §System Shape resolves
  `@weather:example.com` → `weather.agents.example.com` → endpoint. The middle
  term, labelled "canonical agent identifier," is an FQDN.
- The AT Protocol DID spec states the failure mode of exactly this shape:
  `did:web` "is inherently tied to the domain name used, and does not provide a
  mechanism for migration or recovering from loss of control of the domain
  name." <https://atproto.com/specs/did>
- AT Protocol's split — mutable handle resolved by DNS TXT `_atproto` or
  `/.well-known/atproto-did`, stable `did:plc` identifier derived as
  `base32(sha256(genesis_op))[:24]` — makes a handle change rewrite zero stored
  data, because every `at://` URI, like, reply, and moderation label references
  the DID. <https://atproto.com/specs/handle>
- `did:plc` also supplies the recovery story a pure-DNS identity cannot have:
  rotation keys ordered by descending authority, distinct from the low-value
  repo signing key that may live on a host, plus a 72-hour window in which a
  higher-authority key can fork back over a lower-authority key's operations,
  with clobbered operations retained as `nullified`.
  <https://github.com/did-method-plc/did-method-plc>
- Counter-case: Nostr has no rotation at all. Three attempts at a NIP-41
  successor over 3.5 years reached zero convergence, because any migration
  signal must be signed by the key that may already be stolen.

## What it changes

1. `agent-voice-and-discovery.md` §System Shape — the middle term becomes
   `agent_id`, a hash of a genesis operation, resolving to a document listing
   verification methods and service endpoints. The FQDN becomes one of those
   service endpoints rather than the identity.
2. §Resolution — the resolution bundle gains `agent_id`, and gains a
   verification result for the handle↔identifier binding in both directions.
3. §Resolution — two key classes are named: owner-held **rotation keys** (can
   replace the signing key, the endpoint, the handle, and the rotation set) and
   a **signing key** that may live on a host. This makes the existing hosted-voice
   mitigation "hold an owner-controlled signing key that the host never
   possesses" enforceable rather than aspirational.
4. §Seagulls-Hosted Voice — export becomes a rebinding of the same `agent_id`
   to a new handle, not a new identity. Handle tombstoning stays.
5. `migration-plan.md` Stage 1 acceptance — the automated test additionally
   asserts that the receiving side records the sender's `agent_id`, and that the
   same `agent_id` resolves after the handle changes.

## What it does not change

- Nothing in the Compatibility Contract. No package, table, Terraform, domain,
  route, env prefix, or CLI name moves.
- No Definition-of-Done criterion is added, removed, or reworded.
- `@handle:domain` stays exactly as specified, including the colon display
  convention and `acct:` normalization. This proposal makes the handle *more*
  disposable, not less prominent.
- Stage ordering is unchanged. This lands inside Stage 1, not beside it.
- No W3C VC/VP dependency, and no general DID resolver. One method, chosen and
  documented.

## Falsifier

Any of these would show the proposal is wrong:

- A design in which the handle is the only identifier and an agent can still
  change domains, rotate a compromised key, and recover from a hostile host,
  with stored references surviving. If that exists, the indirection is
  unnecessary.
- Evidence that no gulls object ever outlives a handle — that no audit record,
  task reference, capability grant, contact entry, or block entry is retained
  across a rename. Then there is nothing to protect.
- A measured case where the second resolution hop breaks a latency or
  operability budget that a single hop meets.

The first two are checkable today against the docs. The third needs Stage 1
running.

## Recommended answer

Accept, scoped to Stage 1. Adopt the DID *shape* — an identifier resolving to a
document of verification methods and service endpoints — with exactly one
method, structured like `did:plc`: identifier = hash of a genesis operation,
control = ordered rotation keys, recovery = a bounded window with nullified
operations retained.

Do not build a general DID resolver, do not register a DID method, and do not
take a verifiable-credentials dependency. The formal objections Google and
Mozilla filed against DID Core — method proliferation with no convergence
incentive — are still unresolved, and none of that machinery is needed here.

## If you do nothing

Stage 1 ships with an FQDN as the canonical identifier. Stage 3 re-homes modules
around it. Stage 5 puts it inside A2A task references that cross administrative
boundaries and persist in other agents' stores.

At that point an agent cannot change domains, cannot rotate a compromised key
without becoming a different agent, and cannot leave a hosted voice without
abandoning every reference other agents hold. The Seagulls Host that publishes a
zone becomes structurally unleaveable, which contradicts Definition-of-Done
criterion 6 — "removing a Seagulls client leaves an independently published Gull
discoverable and able to communicate" — for the hosted case specifically.

The cost of the fix rises from a schema decision to a network-wide migration
somewhere between Stage 3 and Stage 5, and it never falls again.
