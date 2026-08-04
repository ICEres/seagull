# Pet Product Spec

Status: Authoritative (layer).

Last updated: 2026-08-04.

Authoritative for the Pet layer only. Where this document conflicts with
[Agent Voice And DNS Discovery](../../gulls/docs/agent-voice-and-discovery.md),
that document wins. The redesign described here is accepted but not yet
implemented.

## Purpose

Pet is the My Agents product for personal and owned agents. It lets a person
equip an owned Gull with private prompts, skills, memory, tools, credentials,
settings, preferences, and approval posture without exposing that private
bundle to the network.

Pet is presented through the Seagulls platform, but it does not require it.
Pet's asset bundle, bindings, and owner-approval posture are Gull-side state
that works through `gulls` with no platform:

```text
private owner assets + owner posture
        |
        | compiled into local Gull policy
        v
selected Gull voice via gulls          <-- required
        |
        | accounts, multi-voice UI, hosting, presentation
        v
Seagulls platform                      <-- optional
```

The required relationship is Pet to one Gull. The Seagulls relationship is
optional and additive; see [Without Seagulls](#without-seagulls). A Pet
capability that cannot be stated as Gull-side state is a Seagulls feature, not
a Pet feature.

The stack shows dependency direction, not data flow. Pet may use private storage
and a local or hosted runtime, but Seagulls public features never receive the
private bundle merely because Pet is installed.

Seagulls, when present, supplies the multi-Gull product, account, hosting, and
supervision surfaces. Gulls supplies the selected agent's addressable voice and
local runtime boundary. Whether its address survives a provider change depends
on its publication profile; Pet does not define another identity or
communication protocol.

## Owns

- User-owned prompt and skill assets.
- Private memory, tools, credentials, settings, and owner preferences.
- Binding an asset bundle to an owned Gull.
- My Agents configuration and private asset UX.
- The owner's stated approval defaults, relationship presets, and delegation
  posture — as policy input, never as an enforcement point.
- Ask-owner, approve, refuse, constrain, and explain flows.
- Allowed-use terms for context that may be inspected, remembered, or shared.
- Safe projections that another Seagulls feature or Agent Request may present.
- The owner-to-owned-agent relationship and its management experience.

## Owner Posture And Enforcement

Pet owns the owner's stated posture. The Gull owns enforcement. These are
different things, and the split is not negotiable:

- **Pet owns the input.** The owner's relationship presets, approval defaults,
  allowed-use terms, cost thresholds, and delegation posture, plus the UX for
  editing them and explaining what they mean.
- **The Gull owns the enforcement.** A Gull compiles Pet's posture together
  with every other policy input into one local policy and evaluates it at the
  single chokepoint between its A2A endpoint and its runtime connector.

Pet is never an independent gate. It does not sit in the delivery path, and a
Pet outage must not become a way to bypass approval. When Pet posture, Agent
Request approval requirements, and the Gull's own local policy disagree, the
Gull's local policy wins and fails closed. There is exactly one enforcement
point per voice — see
[Enforcement stays with the Gull](../../gulls/docs/agent-voice-and-discovery.md#products-presented-through-seagulls).

### Relationship Presets

The concrete vocabulary of owner posture is the relationship preset set:
`needs_approval`, `trusted_reviewer`, `summary_helper`, `research_helper`,
`paid_worker`, and `blocked`. Their normative behavior is defined once, in
[Relationship Presets](../../gulls/packages/protocol/README.md#relationship-presets).
This spec deliberately does not restate that table.

Pet is where an owner reads and edits presets: they are the owner-editable
surface over a policy compilation that is otherwise opaque to a person. A
preset states a default posture toward a counterpart agent; it is not itself a
decision. The Gull still evaluates it, and a preset that appears to grant
something the Gull's local policy denies does not grant it.

## Without Seagulls

Pet is usable with no Seagulls account and no Seagulls service. What each side
contributes is precise:

| Capability | Pet plus `gulls`, standalone | What Seagulls adds |
| --- | --- | --- |
| Asset bundle | Prompts, skills, memory, tools, credentials, and preferences held in owner-local Pet storage. | Account-scoped storage and cross-device access. |
| Binding | The bundle is bound to one owned Gull through local configuration. | Onboarding UX for hosting or connecting the Gull to bind to. |
| Owner posture | Relationship presets, approval defaults, and allowed-use terms authored locally as policy input. | A place to edit and review posture across several voices. |
| Enforcement | The Gull compiles that posture into local policy and enforces it. | Nothing. Enforcement never moves off the Gull. |
| Approval delivery | Ask-owner reaches the person through `gulls` — connector, CLI, or a local notification bridge. | Approval queues, notifications, and multi-voice supervision. |
| Audit | The Gull's local audit trail. | Readable cross-voice audit and quarantine projections. |
| Identity | A Gull published under the owner's own domain, or a purely local Gull. | A hosted handle under the provider domain, via Seagulls Host. |
| Accounts | None required; one owner, one machine. | Human accounts, sessions, and multi-voice ownership views. |

Nothing in the standalone column requires a Seagulls account, service, or
network call. Removing Seagulls from a standalone deployment removes
presentation and hosting, never enforcement: the compiled local policy stays
with the Gull.

The one real dependency is scoped and belongs to the identity, not to Pet. An
owner who chooses a **Seagulls Host** voice has a hosted Gull that depends on
that host's availability and service policy. Pet running against that Gull
inherits the dependency; Pet does not create it.

## Uses From Seagulls When Present

Each item below is additive. In a standalone deployment it is unavailable, not
broken:

- Human accounts, sessions, and the owner's selected set of Gull voices.
- Onboarding for a Seagulls-hosted Gull or connection to a custom-domain Gull.
- Multi-Gull navigation, conversation and task views, notifications, and human
  supervision surfaces.
- Approval, quarantine, moderation, and readable audit projections where the
  platform is authorized to present them.
- Product-module boundaries shared with Agent Request and future features.

## Uses From Gull And Gulls

- The owned agent's identity, A2A endpoint, local policy, and runtime connector.
- Local durable inbox, task projection, and audit boundary.
- Safe delivery of accepted A2A interactions to the private runtime.
- Bounded context and artifact access without publishing raw private runtime
  handles.

Pet depends on a Gull, not on Seagulls. A Pet runtime connector communicates
with the selected Gull through the `gulls` CLI or runtime APIs; that connection
is the product's foundation rather than a bypass, and it does not make Pet a
sibling network layer. Where a platform is present, Pet is additionally
presented through it.

## Integration With Agent Request

Pet and Agent Request are separate products, each presented through Seagulls
and each usable without it. Neither is the foundational dependency of the
other:

- Pet supplies owner posture and private capability boundaries when an owned
  Gull participates in work.
- Agent Request owns the request, approval, progress, artifact, and result
  lifecycle.
- Pet's posture may approve, constrain, or refuse a request without Pet
  becoming the task store or work protocol.

Both products supply policy input to the same place. Pet's owner posture and
Agent Request's work-specific approval requirements are compiled by the
participating Gull into its one local policy; neither product gates the other,
and a disagreement between them is resolved by the Gull, closed.

## Does Not Own

- The Seagulls platform, its hosted namespace, or its general product shell.
- WebFinger, AID, DNS-AID, A2A, routing, or delivery protocols.
- Another Gull's identity, private state, runtime, or inbox.
- Agent Request task lifecycle, marketplace, quote, escrow, or credit semantics.
- Enforcement of the owner posture Pet authors. The Gull enforces.
- A public social graph, Feed, directory, or moderation service.
- Provider execution, model routing, cost accounting, quota enforcement, or
  billing. These belong to the **Seagulls Host** role, which executes or brokers
  the model for the Gull voices that selected it and enforces its own cost
  controls.

Provider cost is a disclaimer of ownership, not of relationship. Pet must
surface the estimated cost of high-cost work to the owner whose approval it is
about to request, and Pet owns the threshold at which that approval becomes
required. An approval prompt that hides what the work will cost is not an
approval. What Pet does not do is meter, price, reconcile, or settle anything:
the figures it shows are the Host's, read and displayed, never authored.

## Public Contracts

- A Pet-backed agent is still a normal Gull and can communicate with external
  Gull voices through its advertised A2A interface.
- The owner may use a Seagulls-hosted voice, attach an independently published
  Gull, or run a purely local one.
- Other agents may request value from a Pet-backed Gull without receiving its
  private asset bundle.
- Answers and actions remain attributable to the owning person and Gull.
- Private-context sharing, sensitive tools, high-cost work, and other
  policy-defined actions require the configured owner approval, enforced by the
  Gull.
- Public discovery and Agent Cards never expose private prompts, memory,
  credentials, local files, browser sessions, shells, or raw tool handles.

## Connect Surface

Pet connectors bridge an owned private runtime to the owned Gull — configured
locally, or selected through Seagulls where the platform is in use:

- Codex as a personal agent.
- A local personal-agent runtime.
- A hosted Pet runtime.
- Approval and notification bridges.

Connectors use the Gull's standard A2A voice and local Gulls policy boundary.
They may use Seagulls for product UX and Agent Request for structured work;
none of those layers creates an alternate Pet transport, and none is required
for a connector to function.

## Success Criteria

- A person with no Seagulls account can equip an owned Gull through Pet: the
  asset bundle binds to a locally run or custom-domain Gull, and the owner's
  posture compiles into that Gull's local policy.
- A person using Seagulls can host a new Gull or connect a custom-domain one
  from the platform and equip it through Pet, with the same bundle, binding,
  and posture semantics as the standalone case.
- The owner can inspect, approve, refuse, or constrain sensitive behavior —
  locally through the Gull, and through Seagulls supervision surfaces when the
  platform is present.
- Approval requests for high-cost work show the owner the estimated provider
  cost before the owner decides.
- Another Gull can request help without copying the private capability bundle.
- Removing Pet does not delete or redefine the underlying Gull identity or
  voice.
- Removing the Seagulls platform removes presentation, hosting, and multi-voice
  supervision, and removes no enforcement: the posture Pet authored is already
  compiled into the Gull's local policy. A Gull hosted by Seagulls Host still
  depends on that host for its voice.
