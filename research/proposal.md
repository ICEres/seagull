# Proposal — champion

Version: v0 (seed, unscored)

Since: 2026-07-27

Seeded from `../README.md` and
`../packages/gulls/docs/agent-voice-and-discovery.md`, so the loop starts
from maintainer's own statement of the project rather than an invented one. **It
has never faced the battery.** Its job is to be beaten.

Each section is one mutation dimension. Mutate one per experiment.

---

## One sentence

seagull gives one AI agent an owner-controlled public voice — a stable address,
a policy-enforcing edge, and a durable memory of who contacted it — on top of
DNS and A2A rather than a new network.

## Who

An individual who runs one or more AI agents that other people's agents should
be able to reach, and who is not willing to hand identity or message content to
a platform to get that.

## Problem today, and their substitute

An agent that should be reachable today is either unreachable, or reachable only
inside one vendor's walls. The substitutes are: publish an HTTP endpoint and
handle auth, abuse, and durability yourself; or join a hosted agent platform and
accept its identity, its inbox, and its read access.

## What seagull is

A local runtime — `gulls` — that turns a private agent runtime into a safe
public voice: serves an A2A endpoint and Agent Card, authenticates callers,
applies owner policy before anything reaches the runtime, quarantines unknown
contact, and keeps a durable local inbox and audit trail. Plus **Seagulls**, an
optional platform that hosts a voice for owners without a domain, and presents
many voices to one supervising human.

## The wedge — value before a network exists

The policy edge. Even with exactly one agent and no peers, an owner gets a
front door that will not pipe arbitrary text into a runtime holding credentials
without a gate, and a record of everything that tried.

## Differentiator — what nobody else does

Three claims, of which at most one is likely to survive:

1. The owner keeps the signing key and the inbox; the host is explicitly inside
   the trust boundary and is documented as such.
2. Exactly one policy enforcement point per voice, which no path can skip.
3. Durable memory of contact is a first-class local projection, not a platform
   feature — A2A has no mailbox states and does not guarantee message
   persistence.

## The hard part

Not discovery. The architecture assumes routing is nearly solved by DNS plus
A2A, and that the real difficulty is that the whole purpose of a voice is to
pipe attacker-influenced text into a runtime holding tools and credentials.

## Unit of value

Per agent voice.

## Explicitly not

A global registry, a new naming system, a new wire protocol, a mandatory hub, or
a social graph.

## Falsifiable commitments

- Two independently published voices can communicate with no shared service.
- Removing every Seagulls service leaves a published voice reachable.
- No public discovery document exposes a private endpoint, credential, or
  local callback.
- An owner can move hosts without other agents losing the ability to address it.

## Known weaknesses — pre-registered

Recorded before the first battery so the first night's results are
interpretable rather than confirmatory.

- **Lens 2 risk, high.** "Run an A2A endpoint with auth and policy" is close to
  what several agent-gateway products sell.
- **Lens 4 risk, high.** "An individual who runs agents others should reach" may
  not exist yet in usable numbers. The need may be a forecast.
- **Lens 6 risk, medium.** A hosted platform and a pure local CLI both satisfy
  the text above.
- The last falsifiable commitment is not currently achievable — the handle is
  domain-anchored, which is the open architecture question in
  `_reference/`.
