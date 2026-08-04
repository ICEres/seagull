# Product Direction

Last reviewed: 2026-08-04.

> This is a product-priority brief, not a second architecture authority.
> [Agent Voice And DNS Discovery](packages/gulls/docs/agent-voice-and-discovery.md)
> remains the target technical contract, and
> [Migration Plan](packages/gulls/docs/migration-plan.md) remains the delivery
> contract. This page decides which user outcome should be proved first and
> what evidence earns the next investment.

## Producer Assessment

Seagull has a strong engineering alpha and an unimplemented differentiated
product. Those are both useful facts, but they must not be blended into one
claim of maturity.

| Area | Evidence as of this review | Assessment |
| --- | --- | --- |
| Running system | Central Message Hub, Safety Gateway, Social API, AI Provider, web and landing apps, macOS client, CLI/router, connectors, and dev Terraform exist. | Substantial development MVP. |
| Target product | No standards-compliant WebFinger endpoint/profile, AID resolver, A2A Agent Card endpoint, A2A edge, or local A2A inbox is implemented. | Pre-implementation. |
| Verification | 556 Python and 93 JavaScript tests passed locally; both Go modules passed. Twenty-nine AWS storage tests skipped locally because `moto` was unavailable, while CI installs it. | Engineering discipline is a strength. |
| Distribution | No tagged release, packaged CLI installer, notarized macOS release, or production environment exists. | Internal alpha, not a shipped public product. |
| Product evidence | The repository records no primary persona, interviews, activation funnel, retention cohort, payer, or design partners. | Product hypothesis, not product validation. |
| Operations | The [inspected dev deployment](https://github.com/ICEres/seagull/actions/runs/30202072105) built, tested, and applied, but post-apply verification stopped because the AWS account was still in the SES sandbox. | Dev exists; the latest inspected deployment is not end-to-end verified. |
| Execution | The migration is detailed prose, while the [GitHub issue tracker](https://github.com/ICEres/seagull/issues) has no executable product backlog. | High documentation velocity, weak milestone visibility. |

The current product surface is too wide for the evidence available. Gull,
Seagulls Host, Console, Apps, Pet, Agent Request, Feed, provider execution, web,
macOS, and several connector shapes should not all be treated as simultaneous
validation targets.

## Product Bet

> **Seagull is the operator inbox and policy edge for work that crosses agent,
> vendor, or administrative boundaries. Agents delegate over an open protocol;
> people see only decisions that need them, approve the exact effect, and keep
> durable evidence.**

The valuable segment is not every agent. Ephemeral subagents inside one trusted
runtime usually need orchestration, not a public voice. A Gull becomes useful
when work crosses a trust boundary, must survive either runtime being offline,
or needs an independently enforceable policy and audit trail.

### Primary user

The first user is a technical individual operating roughly two to ten agents
across coding assistants, local runtimes, and hosted services. They can run a
CLI or local app, but they do not want to expose shells, browser sessions,
credentials, or raw MCP tools to another agent.

Small-team operators are a plausible second segment. Nontechnical consumers,
enterprise administration, and an open marketplace are later segments, not
requirements for the first proof.

### First bounded workflow

Use a cross-agent review or test handoff as the initial design-partner workflow:

1. An owner connects one coding runtime to a local Gull.
2. It receives a bounded review or test request from a second independently
   controlled Gull through A2A.
3. Unknown contact is quarantined before it reaches the private runtime.
4. The owner sees the requester, delegation chain, exact artifact scope, cost
   ceiling, deadline, requested effect, and reason for interruption.
5. The owner rejects, narrows, or approves the exact immutable action.
6. The result and an execution receipt return after either side may have
   restarted.

Start with read-only artifacts and a hard resource budget. Arbitrary shell,
browser, credential, and write access are not needed to prove the value.

### Explicit non-goals for the first proof

- A general social network or Feed.
- A new universal agent protocol, directory, or trust authority.
- A replacement for multi-agent orchestration inside one runtime.
- Hosting public identities before the local edge has repeat users.
- Autonomous consequential side effects without standing policy or an exact
  human approval receipt.
- Public discovery of an agent the requester cannot already name.

## Human Supervision Contract

The product is safe only when the action a person reviewed is the action the
system executes. Every consequential approval must display:

- initiating person, origin agent, delegation chain, and proposed executor;
- operation, destination, parameters, data and artifact scope;
- estimated cost, hard maximum, deadline, and reversibility;
- the policy rule that interrupted the work and what rejection will do; and
- action id, version, payload hash, expiry, and execution preconditions.

The invariant is:

```text
reviewed(action_id, version, payload_hash, expiry, preconditions)
    == executed(action_id, version, payload_hash, expiry, preconditions)
```

Any mutation, regeneration, stale precondition, or expired approval invalidates
the receipt and asks again. A one-time approval and a reusable standing policy
are separate choices.

Notifications may announce that a decision is waiting, but they must not expose
sensitive content on a lock screen or perform a consequential effect from a
truncated preview. The trusted review surface is the only approval surface.

The default operator inbox should be ordered by impact, deadline, and blocked
work—not by sender-claimed urgency:

1. Security review.
2. Needs decision.
3. Blocked on you.
4. In progress.
5. Outcomes and FYI, normally digested.

The UI must keep routing evidence separate from behavioral trust. “Domain
authority verified,” “endpoint authenticated,” “capability self-asserted,”
“known interaction history,” and “allowed by local relationship policy” are
different statements and should never collapse into a single trusted badge.

## Landscape And Product Boundary

Seagull should compose the emerging ecosystem instead of rebuilding it.

| Project or standard | What it already provides | Decision for Seagull |
| --- | --- | --- |
| [A2A](https://a2a-protocol.org/latest/specification/) | Agent Cards, messages, stateful asynchronous tasks, artifacts, authentication declarations, streaming, and push updates. It accepts well-known URLs, catalogs, or direct Agent Card configuration. | Adopt as the remote peer protocol and publish a precise conformance profile. Prove direct configuration first. |
| [MCP](https://modelcontextprotocol.io/specification/2025-11-25/architecture) | A host/client/server boundary for giving an AI application contextual tools and resources. | Keep behind the Gull edge as a private runtime adapter; never expose raw MCP authority to a remote peer. |
| [AGNTCY](https://docs.agntcy.org/) | Directory, schema, identity, secure messaging, observability, and integration testing across organizations. | Integrate where useful; do not build a parallel universal directory or network stack. |
| [NANDA](https://arxiv.org/abs/2507.14263), [ANP](https://agentnetworkprotocol.com/en/specs/), and [Agentverse](https://docs.agentverse.ai/) | Research or products for agent discovery, identity, networking, hosting, and marketplaces. | Treat as discovery inputs, interoperability targets, and onboarding benchmarks—not dependencies for the first workflow. |
| [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/multi_agent/), [AutoGen](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/teams.html), [CrewAI](https://docs.crewai.com/en/concepts/crews), and [LangGraph](https://docs.langchain.com/oss/python/langchain/multi-agent) | Orchestration among agents inside an application or framework. | Build connectors. Do not compete on orchestration graphs. |
| [AgentMail](https://www.agentmail.to/) and similar inbox APIs | A narrow address, inbox, webhook, and sending product for agents. | A close substitute and useful implementation-pattern benchmark, not proof of Seagull demand. Differentiate with A2A tasks, local policy, exact consent, and owner-held evidence. |

The IETF DAWN work reinforces a useful distinction: WebFinger resolves a
subject the caller already knows; it is not descriptive or capability search.
Use direct Agent Card configuration and the standard A2A well-known path for
the first slice. Add WebFinger, AID, and DNS-AID as optional known-identity
adapters after the protected transport works. A catalog may suggest candidates
later, but the client must re-resolve the selected identity before contact.

The defensible product is not basic A2A serving. That will commoditize. The
durable value is the combination of owner-side policy, offline delivery,
identity continuity where the publication profile permits it, human
supervision, bounded private context, and readable evidence across runtimes.

## Now, Next, Not Yet

### Now — restore truth and prove one protected loop

1. Fix the known consent-integrity defects and label affected interfaces
   honestly until fixed.
2. Keep the verified current-system hubstub quickstart runnable; describe
   `make setup` as dependency setup rather than product startup.
3. Build the direct A2A edge behind `GULLS_A2A_EDGE`: Agent Card, send/receive,
   local durable inbox, caller authentication, unknown-contact quarantine,
   bounded context, exact-action approval, idempotency, restart/resume, and
   receipts.
4. Pass the official [A2A Inspector](https://github.com/a2aproject/a2a-inspector)
   or [Technology Compatibility Kit](https://github.com/a2aproject/a2a-tck), or
   interoperate with an independent implementation. Two repository processes
   alone prove self-compatibility, not interoperability.
5. Turn the vertical slice into tracked issues with an owner, fixture, metric,
   rollout flag, rollback, and demo evidence for every acceptance criterion.

### Next — reduce setup and supervision cost

- Add well-known, WebFinger, and AID resolution adapters without changing the
  edge contract.
- Let one person supervise several connected Gulls through a projection-only
  Console.
- Add deduplication, snooze, assignment, quiet hours, queue-age visibility, and
  digest controls.
- Test a second cross-vendor workflow only after the first repeats.

### Not yet: provider hosting and broad platform expansion

Seagulls Host is not a cheap or no-regret follow-on. It creates provider duties
for abuse, privacy, availability, recovery, key custody, export, moderation,
support, incident response, and possible billing. Start it only after all of
these gates pass:

- at least five design partners complete the first workflow, and at least
  three repeat it in three of four consecutive weeks;
- no known approval/display binding defect or policy bypass remains;
- the hosted-identity ADR defines stable identifier semantics, key ownership,
  recovery, rotation, provider exit, tombstoning, and history continuity;
- abuse, privacy, export, recovery, incident, and service-shutdown runbooks are
  reviewed; and
- an independent A2A interoperability check passes.

A hosted `@name:gulls.ai` identity is provider-bound. Exporting its configuration
and attaching another domain is re-registration, not identity portability,
unless a separate durable identifier and recovery design is adopted.

## Measures

The north-star measure is:

> **Weekly bounded cross-boundary tasks completed with an accepted result,
> where every consequential effect is covered by standing policy or an
> exact-action receipt.**

Track the smallest set that diagnoses that outcome:

| Need | Measure |
| --- | --- |
| Activation | Time from install to first independent A2A task completed. |
| Value | Accepted-result task completion rate and repeat workflows per active owner. |
| Reliability | Delivery/resume success, retries, abandoned tasks, and duplicate irreversible effects (target: zero). |
| Consent integrity | Display-to-execution binding (target: 100%) and policy bypasses (target: zero). |
| Attention | Interruptions per task, false escalations, overrides, and decision queue age at p50/p95. |
| Trust | Whether a person can correctly explain who is asking, what is verified, what will execute, and what data will leave. |
| Retention | Owners repeating a real workflow in week four, not accounts or Agent Cards created. |
| Exit | Pause, revoke, export, and recovery drills completed without losing evidence. |

Do not use registered agents, messages sent, Feed activity, or raw approval rate
as a north star. Each can rise while user value or safety falls.

## Immediate Product Risks

1. **Consent is not yet exact everywhere.** Two of the three defects here are
   closed. The in-app approval path is bound: `draft-reply --approve` takes
   `--expect-draft <draft_sha256>` and the macOS approval passes the digest of
   the draft it displayed, so a draft that changed after review is refused
   rather than sent. The macOS notification no longer performs a consequential
   effect from a truncated preview — its draft action opens the app, and the
   draft text is not carried in the notification. Message and draft text are now
   omitted from banners unless the owner opts in, though the title still names
   the sender. The remaining defect is the
   [generic web action](packages/seagulls/apps/web/src/components/sky-page.tsx#L782),
   which still lacks a sufficiently explicit effect summary.
2. **The identity promise is conditional.** A custom-domain voice can retain
   its address across runtime or platform changes. A hosted-domain voice cannot.
3. **There is no cold-start mechanism.** Known-handle resolution does not help a
   user find a capable stranger, and a marketplace is not justified yet.
4. **Onboarding is still developer-only.** `make setup` starts dependencies;
   the verified hubstub quickstart still requires Go, a source build, and manual
   configuration. It is a seeded fake-hub demo, not an independent cross-agent
   end-to-end workflow, and it demonstrates the legacy hub rather than the A2A
   target.
5. **The payer is unproved.** The technical individual is the user hypothesis;
   willingness to pay for hosting, supervision, or policy has not been tested.
6. **The project has no executable product backlog.** Long prose and commit
   history are not a substitute for milestone issues and linked evidence.

## Validation Work Before More Surface Area

- Conduct 12 problem interviews around the last real cross-runtime delegation,
  not reactions to the Seagull concept.
- Prototype the approval receipt and inbox prioritization with at least five
  users, including misleading identity, changed payload, stale approval, and
  sensitive lock-screen cases.
- Recruit five design partners for the bounded review/test workflow and measure
  setup time, interruptions, completion, and repeat use.
- Record why a task was not delegated: no need, setup cost, trust, policy,
  capability mismatch, or supervision burden.
- Stop or change the wedge if owners consistently prefer a single-runtime
  orchestrator, if supervision costs more than manual handoff, or if no three
  partners repeat the workflow after four weeks.

The next product review should update this page with interview evidence,
tracked milestone links, the selected A2A conformance profile, and an explicit
go/change/stop decision for Seagulls Host.
