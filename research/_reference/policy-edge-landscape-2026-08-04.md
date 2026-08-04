# Policy Edge And Consent Landscape — 2026-08-04

Status: Research. Surveyed ground for the consent/authorization lenses, so they do not re-derive it.

Companion to `agent-network-research.md` (naming, discovery, P2P) and
`agent-sns-landscape-2026-07-28.md` (the social dimension). This one covers the
dimension those two do not: **the operator inbox, the policy edge, and consent
integrity** — that is, the bet `PRODUCT.md` actually makes.

Produced by six research lenses (approval integrity / delegated authority / A2A
maturity / untrusted-input containment / agent commerce / supervision cost).
Every load-bearing claim below was re-verified by the author against its primary
source; claims that could not be verified are marked and the reason is given.

---

## 1. The finding that reframes the bet

**Human approval does not work the way the product assumes, and the strongest
evidence is first-party production telemetry from a security-conscious vendor
selling to exactly our target user.**

Anthropic, [How we contain Claude](https://www.anthropic.com/engineering/how-we-contain-claude)
(2026-05-25), verified by direct fetch:

> "Our telemetry showed users approved roughly 93% of permission prompts."

> "The more approvals a user sees, the less attention they pay to each, becoming
> over time much less diligent in their supervision."

Their response was not a better prompt. It was to **replace attention with
deterministic policy** and spend the human's attention only on the residue:
auto-mode cut prompts by **84%** while catching **~83% of overeager behaviours
before execution**.

Three independent results converge on the same conclusion:

| Finding | Measurement | Source |
| --- | --- | --- |
| An approval-gated agent becomes risk-equivalent to a fully autonomous one once users approve routinely | L4 ≈ L5 argument | [Knight First Amendment Institute / arXiv:2506.12469](https://knightcolumbia.org/content/levels-of-autonomy-for-ai-agents-1), 2025-07-28 |
| Developers miss agent-inserted sabotage; an explicit warning does not rescue them | **94%** failed to detect; **56%** accepted the malicious code *even when shown a safety-monitor warning*. >100 devs, ~5h realistic task | [arXiv:2606.05647](https://arxiv.org/abs/2606.05647), 2026-06-04 |
| More escalation can make a system *less* safe — an inverted U, not a monotone | Reviewer agreement on "risky" is only Fleiss' κ=0.52; fatigued reviewers can be **flooded to mask a real attack** | [arXiv:2606.08919](https://arxiv.org/abs/2606.08919), 2026-06-08 |

The consequence for `PRODUCT.md` is not that the operator inbox is wrong. It is
that **the human's judgement cannot be the safety mechanism.** The invariant has
to hold structurally — hash binding, precondition re-check, expiry — with the
human as a bonus check over a guarantee that already holds without them. A
product whose safety story is "a person looked at it" is refuted in advance by
the 93% and the 94%.

**Corollary for the Measures table:** `PRODUCT.md` already tracks "false
escalations" and "interruptions per task". Add the one number Anthropic acted
on: **the approval rate itself.** If operators approve more than ~80%, the gate
is decorative and should be read as a defect, not as adoption.

### The nuance that rescues the inbox — oversight shifts, it does not collapse

The pessimistic reading above is incomplete, and the correction comes from the
same vendor's telemetry. Anthropic,
[Measuring AI agent autonomy in practice](https://www.anthropic.com/research/measuring-agent-autonomy)
(2026-02-18), verified by direct fetch:

> "roughly 20% of sessions use full auto-approve, which increases to over 40% as
> users gain experience" (under 50 sessions → 750 sessions)

> "New users (those with around 10 sessions) interrupt Claude in 5% of turns,
> while more experienced users interrupt in around 9% of turns."

> "80% of tool calls come from agents that appear to have at least one kind of
> safeguard … 73% appear to have a human in the loop in some way."

> "only 0.8% of actions appear to be irreversible (such as sending an email to a
> customer)."

Auto-approval *and* interruption both rise with experience. Operators are not
degrading into rubber stamps; they are **reallocating** — bulk-approving the
routine while intervening more surgically on what matters. Anthropic's own
framing: new users approve beforehand, experienced users let the agent work and
step in when needed.

This is the strongest available validation of the categorised-queue design over
a flat approval list, and it sets the design target precisely:

- Make the bulk-digest and standing-policy paths genuinely frictionless, because
  that is where experienced operators go.
- Spend the engineering budget disproportionately on **"needs decision" and
  "blocked on you"** being easy to find and act on *precisely* — not on
  optimising the whole queue uniformly.
- Note the **0.8% irreversible** figure. The exact-action receipt is expensive
  ceremony; it is justified on roughly one action in a hundred. Applying it
  uniformly is how the 87% over-prompting failure in §2 happens. Tier it.

---

## 2. Our invariant has already been formalised, built, and measured

`PRODUCT.md` states the contract as:

```text
reviewed(action_id, version, payload_hash, expiry, preconditions)
    == executed(action_id, version, payload_hash, expiry, preconditions)
```

**This is now a named research object with a reference implementation.** "What
You Approve Is What Executes: Consent Integrity for Black-Box LLM Agents"
([arXiv:2606.02668](https://arxiv.org/html/2606.02668), 2026-06-01) defines
*Consent Integrity* with a **Bind-to-execution** condition — no action A′ may
execute under an approval issued for A. Their mediator is ~500 LOC at 0.056 ms
mean overhead, catches **100%** of TOCTOU swaps and flags 90% of malicious
commands.

Two things to take from it, one encouraging and one a warning:

- The naive shape the industry ships — *"the agent describes the action, the
  human clicks approve"* — approved **100% of a 22-case malicious corpus** until
  action-binding was added. Our invariant is the correct response, and this is
  independent confirmation of it.
- Their mediator **over-prompts badly on benign traffic: 87% of normal commands
  were marked "uninspectable" and only 4.1% passed silently.** A renderer that
  escalates whatever it cannot fully verify will be disabled by its own users.
  This is the failure mode our design is closest to walking into.

**The fix for the over-prompting has field data.** ConLeash
([arXiv:2605.11360](https://arxiv.org/html/2605.11360v1), 2026-05-12) replaces
tool-level allow/deny with **boundary-scoped consent** — input scope × output
sink × data sensitivity × effect type. Results: participants granted scoped
"Always Allow" **3.5× more often** than blanket tool grants; across 50 real MCP
sessions (1,435 invocations) it safely auto-permitted **41.9%** of calls at
**99.4% escalation recall**; 15 of 16 participants preferred it.

This is the shape our "standing policy" should take. Scope the reusable "yes" to
an action family plus a precondition envelope — never to a tool — so that a
habituated approval stays safe.

---

## 3. Prior art for the grant and receipt objects — read before designing

### `draft-nelson-agent-delegation-receipts-10` — the closest existing design

Verified directly on the datatracker (rev **10**, updated **2026-06-13**,
expires 2026-12-15, **individual submission, no working-group standing**):
[Delegation Receipt Protocol for AI Agent Authorization](https://datatracker.ietf.org/doc/draft-nelson-agent-delegation-receipts/).

Its abstract, quoted:

> "Before any agent action executes, the authorizing user signs an Authorization
> Object containing scope boundaries, time window, operator instruction hash, and
> model state commitment. This signed receipt is published to an append-only log
> before the agent runtime receives control. The protocol reduces reliance on the
> operator as a trusted intermediary by making the user's private key the sole
> signing authority over the delegation record."

Map that onto our invariant: scope boundaries ≈ preconditions, time window ≈
expiry, **operator instruction hash ≈ payload_hash**, model state commitment ≈
version. It is the same object.

**The one design idea it has that we do not:** the *user's private key* is the
sole signing authority, and the receipt is published **before the runtime gets
control**, explicitly so that the operator is not a trusted intermediary. In our
current design the Gull — operator-side software — computes and holds the
receipt, which makes the operator exactly the trusted intermediary this draft is
built to remove. Worth deciding deliberately rather than by default.

Also tracking, same shape, weaker standing:
`draft-marques-asqav-compliance-receipts-07` (2026-07-20, individual, no WG) —
signed envelope with `action_ref`, `payload_digest`, `policy_digest`,
`result_digest`, `previousReceiptHash` chaining.

### AP2 mandates — the live precedent

Google's Agent Payments Protocol chains signed Verifiable Credentials: Intent
Mandate → Cart Mandate → Payment Mandate, each with an "open" (constraints) and
"closed" (bound to specific amount) stage, and explicit support for delegated,
human-not-present tasks with pre-set spending caps. **Donated to the FIDO
Alliance 2026-04-28** with 60+ contributing organisations
([FIDO Alliance](https://fidoalliance.org/google-donates-agent-payments-protocol-to-fido-alliance/)).

Two lessons: the mandate *chain* is the right shape for a cost-capped human
authorisation, and Google independently chose to **ride A2A task metadata rather
than build a second transport** — the same architectural bet we made.

---

## 4. The standard that matches our architecture, which we are not tracking

**OpenID Foundation AuthZEN** publishes a standard protocol between Policy
Decision Points and Policy Enforcement Points. That is, architecturally, what a
local policy edge *is*.

Verified by direct fetch of the
[OpenID announcement](https://openid.net/openid-foundation-advances-authorization-for-the-agent-era-with-new-authzen-working-group-drafts/)
(**2026-06-15**), two working-group drafts approved:

- **AARP — Access Request and Approval Profile.** For the case where
  authorisation cannot proceed until a prerequisite is met: *"Approval, consent,
  delegated authority, an attestation, a risk assessment, or additional
  justification may be required before a decision can be reached."* It
  standardises asynchronous, out-of-band approval, positioned as analogous to
  CIBA for authentication. **This is our approval flow, as a standard.**
- **COAZ — a profile for MCP tool authorisation**, mapping information models
  into AuthZEN's Subject-Action-Resource-Context structure. Directly relevant,
  since we keep MCP behind the edge.

Neither `PRODUCT.md` nor the authoritative architecture doc mentions AuthZEN.
Given we are pre-implementation on the edge, this is the cheapest available
correction: adopt the request/decision vocabulary now rather than inventing one
and translating later.

### The rest of the delegation stack worth adopting rather than inventing

| Need | Adopt | Standing |
| --- | --- | --- |
| Subject-vs-actor in a token | RFC 8693 Token Exchange, `act` claim | Shipped RFC since 2020 |
| Fine-grained scope narrowing | RFC 9396 Rich Authorization Requests | Shipped RFC |
| Request signing between Gull voices | RFC 9421 HTTP Message Signatures + Ed25519 | Shipped RFC |
| Cross-boundary mandate with no shared IdP | W3C Verifiable Credentials + OID4VC | Shipped W3C; what AP2, Okta and Dock all converged on |
| Task-scoped, cost-capped, expiring grant | **No standard exists** | Genuine gap — see §3 |

**Correction to our current framing.** IETF **Web Bot Auth** is cited in our
research as institutional cover. Its charter
([datatracker](https://datatracker.ietf.org/wg/webbotauth/about/)) **explicitly
excludes** authenticating access to content not intended for human consumption
(i.e. HTTP APIs), end-user authentication, and bot reputation. It answers "is
this crawler allowed to fetch this website", **not** "on whose authority is this
agent asking mine to act". Reuse RFC 9421 + Ed25519 as plumbing; do not cite the
working group as covering our problem. As of this survey it has published zero
RFCs and none of its ten feeder drafts have been WG-adopted.

---

## 5. A2A gives us less than assumed — which validates the durable inbox

Verified by direct fetch of the [A2A specification](https://a2a-protocol.org/latest/specification/):

> "Clients using streaming to retrieve task updates **MAY not receive all status
> update messages** if the client is disconnected and then reconnects."

> "A duplicate cancellation request MAY return `TaskNotFoundError` if the task
> has already been **canceled and purged**."

> "Send Message operations **MAY be idempotent.**"

**No guaranteed replay. No mandated retention. Optional idempotency.** A2A gives
a task-state vocabulary, a `SubscribeToTask` verb, push-notification config, and
server-generated correlation IDs. The durability, replay, retry and dedup logic
— the hard part — is deliberately left to implementers.

The strategic read: **our durable inbox is not redundant work, it is the
load-bearing piece the protocol declines to specify.** Design it as the system
of record and treat A2A task states purely as wire vocabulary. Never assume a
remote peer's server remembers anything across a restart.

Other corrections for our docs:

- Current version is **v1.0.1** (2026-05-28); v1.0.0 landed 2026-03-12. v1.0
  changed state enums to `SCREAMING_SNAKE_CASE`, renamed push RPCs, and added
  **signed Agent Cards** (JWS RFC 7515, canonicalised with JCS RFC 8785). Pin
  v1.0.1; v0.3-era tutorials are still circulating and are wrong.
- **There is no consent, delegation, or receipt extension.** The four official
  extensions are Secure Passport, Timestamp, Traceability and Agent Gateway
  Protocol; none covers approval or receipts. *Beware an acronym collision that
  cost this survey an hour: **UCP is the Universal Commerce Protocol**
  (Google/Shopify/Etsy/Target/Walmart, commerce checkout), **not** a "User
  Consent Protocol". A2A has no consent extension.*
- **Evidence gate correction.** `PRODUCT.md` and `migration-plan.md` offer "A2A
  Inspector **or** TCK". Prefer **a2a-tck** specifically: it is the pytest
  conformance suite with RFC 2119 MUST/SHOULD/MAY coverage across three
  transports, actively maintained (pushed 2026-06-29). **a2a-inspector is an
  interactive debugger, not a pass/fail gate,** and shows maintenance fatigue
  (last default-branch commit found 2025-11-19, 45 open issues). Note also that
  a2a-tck has **no tagged releases** — pin a commit SHA in CI — and there is **no
  certified-implementations registry**, so any conformance claim we make is
  self-attested. Our docs should say so rather than implying a badge exists.

---

## 6. Containment over detection — and the one gap in our stance

Our stance ("treat remote content as untrusted, contain rather than classify,
approve consequential effects") is **correct and matches the 2026 consensus**,
including the NSA's MCP guidance and OWASP's own researchers. Detection-based
defences — PromptGuard, PiGuard, DataFilter, PromptArmor, Spotlighting,
Instruction Hierarchy — were all circumvented by adaptive attack
([arXiv:2606.15057](https://arxiv.org/pdf/2606.15057), 2026-06-23). PromptArmor
reported <1% false-positive and <1% false-negative rates on a benchmark and was
broken five months later; a benchmark-clean classifier is not an adaptive-robust
one.

**But there is a real gap.** `research/proposal.md` states injection is "the
runtime's problem and deliberately not this one's." The Gull is the policy edge
in front of the runtime and is **the only component that knows the provenance of
the bytes.** Every defence with measured effectiveness — CaMeL, FIDES, Progent,
RTBAS — works by *propagating provenance labels to the enforcement point*. If
bounded context arrives at the private runtime as unlabelled text, we have
discarded the one fact that makes deterministic enforcement possible and handed
enforcement to a component structurally unable to perform it.

**The reference model to copy is FIDES** — two label axes (integrity
trusted/untrusted, confidentiality public/private/user-identity),
most-restrictive-wins propagation, and **sink annotations enforced before the
tool runs** (`accepts_untrusted: false`, `max_allowed_confidentiality`). It is
published ([arXiv:2505.23643](https://arxiv.org/abs/2505.23643)) *and shipped* in
Microsoft's `agent-framework-core` as `agent_framework.security`
([docs](https://learn.microsoft.com/en-us/agent-framework/agents/security),
updated 2026-07-10). It is the closest existing implementation of what we are
building, with a documented threat model we can cite.

**And the cost is real and must be planned for.** On the dynamic **AgentDyn**
benchmark (longer trajectories, 33 tools), CaMeL achieved **0% attack success and
0% utility — it blocked everything.** Progent cut mean AgentDojo utility from
45.2% to 25.8%. A boundary that blocks too much gets switched off, and a disabled
control is worth less than a weak one. **Ship a dry-run mode first** — propagate
labels, enforce nothing, log what *would* have been blocked — and enable
enforcement per sink once the false-positive rate is known. FIDES ships exactly
this (`enable_policy_enforcement=False`).

Two further corrections to our posture:

- **Quarantine-by-sender presumes sender authenticity A2A does not give us.** If
  a peer can be spoofed, the quarantine tier is a free upgrade for the attacker.
  Signed Agent Cards + mTLS are prerequisites, not enhancements.
- **Provenance must be per-message, not per-peer.** A promoted peer relaying a
  third party's content still yields untrusted bytes (OWASP ASI08, cascading
  failures).

Guidance worth citing in our safety doc, which currently cites none of it:
**OWASP Top 10 for Agentic Applications 2026** (released 2025-12-09) — ASI07
Insecure Inter-Agent Communication and ASI09 Human-Agent Trust Exploitation are
precisely our risk categories, and ASI07's nine mitigations read as a checklist
for our boundary. **NSA AISC Cybersecurity Information Sheet on MCP**
(2026-05-20) is the most citable government artifact for this design; note it
classes semantic poisoning as immature and does **not** endorse detection either.

Finally, a wording fix: state the stance as **"no classifier is load-bearing;
classifier output may be logged and may inform risk tiering, but never gates
correctness."** Written as a flat "no content inspection" it reads to a reviewer
as a gap, because OWASP's letter does recommend sanitising external text.

---

## 7. Agent commerce: keep our own primitives, and do not let the narrative move us

The volume that supposedly proves agent commerce is real does not survive
inspection. Independent analysis by Artemis, reported by
[CoinDesk](https://www.coindesk.com/markets/2026/03/11/coinbase-backed-ai-payments-protocol-wants-to-fix-micropayment-but-demand-is-just-not-there-yet)
(2026-03-11), found roughly **half of observed x402 transactions are artificial**
— self-dealing and wash trading — with **real organic volume around $28,000/day**
against a headline of ~165M cumulative transactions.

More important for us: **almost all genuine volume is consumer-agent-buys-from-
merchant checkout, not agent-hires-agent for bounded work with a returned
result.** No shipping protocol — AP2, x402, ACP — defines escrow, quote
negotiation, or dispute resolution as a first-class primitive; where those exist
they are bolted-on extensions (x402r) or small unproven startups (Nevermined,
Trustap, Taskmarket).

**Verdict: keep the home-grown quote/escrow/credit primitives.** They are not a
gap we are behind on; they are ahead of what any standard offers. Design the
interface so an AP2 mandate could later be accepted as an *input* to the
authorisation step, and treat marketplace-scale economics as still unjustified —
exactly as `PRODUCT.md` already does.

On pricing, the closest live comparable to a policy-edge product is
**HumanLayer** (human-in-the-loop approvals for agents): free up to 3 seats,
**$100/user/month unlimited tasks**. Seat-based or usage-tiered fits; percentage-
of-transaction requires GMV we do not have.

---

## 8. Supervision capacity — our scope is already well calibrated

One of the few places the research says *keep doing what you are doing*.

- **Span of control.** The only well-measured human-factors data on supervising
  multiple autonomous systems — Cummings & Guerlain,
  [Human Factors 2007](https://journals.sagepub.com/doi/10.1518/001872007779598109)
  — puts one operator at **~4–5 vehicles at moderate autonomy, up to ~12 under
  heavy supervisory automation** before performance degrades. Cursor 3 ships a
  console capped at **8 parallel background agents**. `PRODUCT.md`'s "two to ten
  agents" sits squarely inside the only real envelope that exists. **Resist
  roadmap or marketing pressure toward "supervise 50 agents"** — there is no
  measured basis for it, and the 2026 thought-leadership pieces claiming 100–200
  are unsourced opinion in both directions.
- **The false-escalation cliff.** Across ICU alarms (false **72–99%** of the
  time, **>42% unanswered**,
  [AHRQ](https://www.ncbi.nlm.nih.gov/books/NBK555522/)) and security operations
  (**53%** false positives, worsening year over year; 62–67% of alerts ignored
  once volume is high), operators begin blanket-ignoring a queue somewhere past
  "half of it is noise." This makes our **false-escalation rate the gating
  metric**, not a secondary KPI. A purpose-built multi-agent alarm-suppression
  pipeline reached a 16.3% false-escalation rate on synthetic benchmarks
  ([arXiv:2604.16081](https://arxiv.org/pdf/2604.16081), 2026-04) — a reasonable
  external marker for what "good" looks like. **Hold it under ~20%.**
- **Put a price on interruption.** Mark, Gudith & Klocke
  ([CHI 2008](https://dl.acm.org/doi/10.1145/1357054.1357072)) measured **~23
  minutes** to recover pre-interruption focus. That converts our "interruptions
  per task" metric into operator-minutes and makes the cost of a false escalation
  arguable in a way a raw count is not.
- **Prefer batched pull over continuous watch.** Vigilance decrement costs
  10–15% detection accuracy within the first 30 minutes even in motivated
  observers ([Frontiers, 2025](https://www.frontiersin.org/journals/cognition/articles/10.3389/fcogn.2025.1632885/pdf)).
  A live feed the operator is expected to monitor is the wrong shape; the
  digest-and-queue design is right.

**Competitive note the SNS survey does not cover:** the literal "agent inbox" is
occupied. [LangChain Agent Inbox](https://github.com/langchain-ai/agent-inbox) is
an open-source Gmail-style queue for reviewing, approving, editing and rejecting
pending agent actions across agents; **HumanLayer** ships approval queues with
Slack/SMS/email escalation. Neither, as far as this survey found, **publishes any
usage data** — no queue age, no interruptions per task, no false-escalation rate.
Our Measures table is already designed to produce exactly those numbers. Being
the first to publish them is a cheaper and more defensible differentiator than
any additional protocol surface.

## 9. Durable execution: adopt, do not build

§5 establishes that A2A declines to specify durability. That argues for owning
the *system of record* — it does **not** argue for hand-rolling crash-consistent
replay.

The pattern — *persist completed step/tool-call/approval boundaries to a journal;
on restart replay and skip anything already executed; never re-run a tool call,
external mutation, approval, or outbound message* — is now implemented
independently by **Temporal, Restate, DBOS and Cloudflare Workflows**, plus AWS
(Step Functions + Bedrock AgentCore added managed multi-agent workflows that
**pause for days awaiting human approval and resume with an audit trail**,
[Mar 2026](https://aws.amazon.com/about-aws/whats-new/2026/03/aws-step-functions-sdk-integrations),
[Jun 2026](https://aws.amazon.com/about-aws/whats-new/2026/06/aws-step-functions-agentcore/)).
Cloudflare Workflows **hibernate at zero cost while paused on a human approval**
— precisely our resume-after-disconnect requirement, already a shipping managed
primitive. Pydantic AI now treats durable backends as pluggable across four
vendors, which is the signal that this has commoditised.

**Recommendation for our actual scale (one operator, 2–10 agents): start with
DBOS or Restate, not Temporal.** DBOS persists workflow state directly in
Postgres and runs in-process as a library with no new infrastructure; Restate is
a lightweight journal-and-replay sidecar. Temporal's cluster/worker model only
pays off well past single-operator deployments.

Spend the saved budget on what no engine provides: risk tiering, learned
auto-approval thresholds, and the human-readable decision record.

**For the receipt trail specifically:** adopt **in-toto/SLSA-style signed
attestation envelopes** now — mature, production-proven outside AI, and already
being repurposed for agent actions — and track **IETF SCITT**
([architecture draft](https://datatracker.ietf.org/doc/draft-ietf-scitt-architecture/),
[REST API draft](https://datatracker.ietf.org/doc/draft-ietf-scitt-scrapi/), -10
May 2026) as the emerging vendor-neutral transparency-log standard. Prefer both
over the several sub-six-month-old single-author "agent receipt" proposals. Note
that none of these are human-readable at the raw layer: the plain decision record
(who, what, why, evidence, outcome) is a rendering layer we build regardless,
the way a browser verifies Certificate Transparency without showing anyone a
Merkle proof.

## 10. What to change, ranked

1. **Stop treating human approval as the safety mechanism.** Make the invariant
   hold structurally (hash binding, precondition re-check under compare-and-swap
   against live state, expiry), and treat the human as a bonus check. Add
   *approval rate* to the Measures table and read >80% as a defect. (§1)
2. **Close the labelling gap.** Emit integrity and confidentiality labels
   alongside bounded context and enforce sink policy in our code, before the tool
   runs. Copy FIDES. Ship dry-run mode before enforcement. (§6)
3. **Adopt scoped consent instead of tool-level allow/deny.** Scope the reusable
   "yes" to an action family plus precondition envelope. ConLeash's 41.9%
   auto-permit at 99.4% recall is the target shape. (§2)
4. **Read `draft-nelson-agent-delegation-receipts-10` before finalising the
   receipt schema**, and decide deliberately whether the owner's key — not the
   Gull — signs the authorisation object. (§3)
5. **Track AuthZEN AARP/COAZ and adopt its vocabulary** rather than inventing a
   PDP/PEP request shape. (§4)
6. **Correct the A2A claims in our docs**: pin v1.0.1, prefer a2a-tck (pinned
   SHA) over the inspector, say the conformance claim is self-attested, note
   there is no consent/receipt extension, and stop citing Web Bot Auth as cover.
   (§4, §5)
7. **Cite the external guidance our safety doc lacks** — OWASP Agentic Top 10
   2026 (ASI07/ASI09) and the NSA MCP CSI. (§6)
8. **Adopt a durable-execution engine (DBOS or Restate) instead of hand-rolling
   replay**, and adopt in-toto/SLSA envelopes for receipts. Own the system of
   record and the decision rendering; do not own crash-consistency. (§9)
9. **Make false-escalation rate a gating metric with a target under ~20%**, and
   price interruptions at ~23 operator-minutes each. (§8)
10. **Publish our queue metrics.** LangChain Agent Inbox and HumanLayer occupy
    the literal concept but publish no operational data. First credible numbers
    win the argument. (§8)

## 11. Two claims we should stop making without qualification

- **"Governance Gaps in Agent Interoperability Protocols" (arXiv:2606.31498,
  2026-06-30) does not say what it is being cited for.** It is a real paper and
  it does support "agent community governance constitutes a missing architectural
  layer above current interoperability standards." But its abstract is about
  *community governance* — voting, dissent, deliberation — not delegated
  authority. The frequently-quoted line about protocols being unable to express
  "who is really asking on whose behalf" is attributed to its body, which this
  survey could not verify. Read the PDF before citing it as validation of the
  policy edge.
- **A widely-repeated "17% vs 76% incident rate with/without least privilege"
  statistic** is attributed in secondary blogs to Microsoft; the Microsoft post
  contains no such figure. Do not cite it.

---

## 12. Sources

Primary sources verified by direct fetch during this survey are marked ✔.

- ✔ [Anthropic — How we contain Claude](https://www.anthropic.com/engineering/how-we-contain-claude) (2026-05-25) — 93% approval rate, declining diligence, auto-mode 84%/83%
- ✔ [A2A specification](https://a2a-protocol.org/latest/specification/) — replay/retention/idempotency language
- ✔ [draft-nelson-agent-delegation-receipts](https://datatracker.ietf.org/doc/draft-nelson-agent-delegation-receipts/) rev 10 (2026-06-13)
- ✔ [OpenID Foundation — AuthZEN AARP and COAZ](https://openid.net/openid-foundation-advances-authorization-for-the-agent-era-with-new-authzen-working-group-drafts/) (2026-06-15)
- ✔ [arXiv:2606.31498 — Governance Gaps](https://arxiv.org/abs/2606.31498) (2026-06-30) — abstract verified; body not
- [arXiv:2606.02668 — What You Approve Is What Executes](https://arxiv.org/html/2606.02668) (2026-06-01)
- [arXiv:2605.11360 — ConLeash, boundary-scoped consent](https://arxiv.org/html/2605.11360v1) (2026-05-12)
- [arXiv:2606.05647 — Coding with Enemy](https://arxiv.org/abs/2606.05647) (2026-06-04) — 94% / 56%
- [arXiv:2606.08919 — Oversight Has a Capacity](https://arxiv.org/abs/2606.08919) (2026-06-08)
- [arXiv:2506.12469 — Levels of Autonomy for AI Agents](https://knightcolumbia.org/content/levels-of-autonomy-for-ai-agents-1) (2025-07-28)
- [arXiv:2606.15057 — AutoDojo, adaptive defeat of in-band defences](https://arxiv.org/pdf/2606.15057) (2026-06-23)
- [arXiv:2505.23643 — FIDES](https://arxiv.org/abs/2505.23643) · [shipped docs](https://learn.microsoft.com/en-us/agent-framework/agents/security)
- [arXiv:2503.18813 — CaMeL](https://arxiv.org/abs/2503.18813) · [AgentDyn utility results](https://www.emergentmind.com/topics/agentdyn)
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) (2025-12-09)
- [NSA AISC — MCP Security Design Considerations](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4496698/) (2026-05-20)
- [FIDO Alliance — Google donates AP2](https://fidoalliance.org/google-donates-agent-payments-protocol-to-fido-alliance/) (2026-04-28)
- [CoinDesk / Artemis — x402 wash trading](https://www.coindesk.com/markets/2026/03/11/coinbase-backed-ai-payments-protocol-wants-to-fix-micropayment-but-demand-is-just-not-there-yet) (2026-03-11)
- [IETF Web Bot Auth charter](https://datatracker.ietf.org/wg/webbotauth/about/) — scope exclusions
- ✔ [Anthropic — Measuring AI agent autonomy in practice](https://www.anthropic.com/research/measuring-agent-autonomy) (2026-02-18) — auto-approve 20%→40%, interrupts 5%→9%, 0.8% irreversible
- [Cummings & Guerlain — Operator capacity for supervisory control](https://journals.sagepub.com/doi/10.1518/001872007779598109) (2007) — span of control 4–12
- [AHRQ — Alarm Fatigue](https://www.ncbi.nlm.nih.gov/books/NBK555522/) · [Mark et al., Cost of Interrupted Work, CHI 2008](https://dl.acm.org/doi/10.1145/1357054.1357072)
- [LangChain Agent Inbox](https://github.com/langchain-ai/agent-inbox) — closest shipping precedent to the literal concept
- [IETF SCITT architecture](https://datatracker.ietf.org/doc/draft-ietf-scitt-architecture/) · [SCITT REST API](https://datatracker.ietf.org/doc/draft-ietf-scitt-scrapi/) (-10, 2026-05)
- [CVE-2025-59536 / GHSA-4fgq-fpq9-mr3g](https://github.com/advisories/GHSA-4fgq-fpq9-mr3g) — code executed before trust dialog accepted
