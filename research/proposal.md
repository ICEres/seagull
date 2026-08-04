# Proposal — champion

Variant: jul28-01.md · Score: 6/6 · Fatal: none · Since: 2026-07-28

Variant: jul27-19.md · Score: 6/6 · Fatal: none · Since: 2026-07-28


Variant: jul27-18.md · Score: 6/6 · Fatal: none · Since: 2026-07-28


Variant: jul27-17.md · Score: 6/6 · Fatal: none · Since: 2026-07-28


Variant: jul27-16.md · Score: 6/6 · Fatal: none · Since: 2026-07-28


Variant: jul27-15.md · Score: 6/6 · Fatal: none · Since: 2026-07-28


Variant: jul27-12.md · Score: 6/6 · Fatal: none · Since: 2026-07-27


Variant: jul27-11.md · Score: 6/6 · Fatal: none · Since: 2026-07-27


Variant: jul27-10.md · Score: 6/6 · Fatal: none · Since: 2026-07-27


Variant: jul27-09.md · Score: 6/6 · Fatal: none · Since: 2026-07-27


Variant: jul27-08.md · Score: 6/6 · Fatal: none · Since: 2026-07-27


Variant: jul27-07.md · Score: 6/6 · Fatal: none · Since: 2026-07-27


Variant: jul27-06.md · Score: 6/6 · Fatal: none · Since: 2026-07-27


Variant: jul27-04.md · Score: 6/6 · Fatal: none · Since: 2026-07-27


Variant: jul27-03.md · Score: 6/6 · Fatal: none · Since: 2026-07-27


## One sentence

seagull is an agent network with exactly one social object — the **introduction**:
a signed record that *A told C to contact B for purpose P* — retained by all
three parties, closed automatically from the A2A task state that follows it, and
governed by one executable rule: **an introducer whose introductions to a
recipient stay open does not get to make more of them to that recipient.**

## Who

A person who has typed another agent's address into their own agent's
instructions. Concretely, the line in an `AGENTS.md`, a system prompt, or a tool
config that reads *"for scheduling, contact @booking:acme.example."* One human,
between one and thirty agents, no ops team, no fleet. Call them what they are:
**the referral author.**

This role is not a forecast and not a taste. It exists because there is no
alternative. A2A is the production interaction protocol and it has no registry:
[discussion #741](https://github.com/a2aproject/A2A/discussions/741) has been open
since 2025-06-10 with no consensus, and the spec ties one Agent Card to one
domain. Capability directories exist and are real — Microsoft
[Agent 365](https://learn.microsoft.com/en-us/microsoft-agent-365/overview) (GA
2026-05-01), Google's Agentic Resource Discovery (2026-06-17), Fetch.ai's
[Agentverse Almanac](https://arxiv.org/html/2606.20570) — but each is an
enterprise tenant boundary or a self-claim catalogue. For everyone outside a
tenant, an agent learns another agent's address exactly one way: **somebody told
it.** The referral author is that somebody.

Two dated facts make the population non-optional rather than merely large. Bots
passed humans on Cloudflare's network on **2026-06-03**, about eighteen months
ahead of the vendor's own forecast
([summary](https://www.semrush.com/blog/ai-agent-bot-traffic/)) — the
counterparties exist. And the human networks are expelling them: Digg pulled its
relaunched app on **2026-03-14** after an agent swarm broke voting within hours,
and Reddit mandated human verification ten days later
([pymnts](https://www.pymnts.com/cybersecurity/2026/reddit-wants-you-to-prove-you-are-human/)).
Agents will not be introduced to each other on a human platform. Somebody has to
hold that edge, and today nobody does.

The distinguishing property of this role is not scale. It is that **their list is
write-only.** The referral author writes "use @y for X", commits it, and never
learns whether that line was used, whether it worked, or who told them to write
it in the first place.

## Problem today, and their substitute

The substitute is the hardcoded referral list, and it is genuinely adequate.

It is free, version-controlled, needs no network, no account and no protocol,
readable by a human in ten seconds, and at five entries it does not rot fast
enough to hurt. Any proposal that pretends this is broken is lying. It is not
broken. It is **write-only**, which is a different and smaller complaint, and
three specific things fall out of it.

- **No provenance.** Six months later nobody can answer who said `@y` was the
  right agent for X, or on what evidence. The recommendation and the recommender
  were one sentence in a chat window, and only the address survived.
- **No reach.** The agent can only use referrals its own owner personally wrote.
  A referral your correspondent's agent already made, to an agent it already
  succeeded against, for the purpose you now have, is invisible to you. That is
  the whole of the discovery problem for anyone outside an enterprise tenant.
- **No closure.** The list does not change when the referral goes badly. No state
  anywhere in the system distinguishes a line your agent uses daily from a line
  no agent has ever acted on.

The two substitutes that do carry a social dimension are both occupied and both
already measured.

The **feed** shipped, at scale, and does not work. Moltbook reached 206,839
verified agents and was
[acquired by Meta on 2026-03-10](https://techcrunch.com/2026/03/10/meta-acquired-moltbook-the-ai-agent-social-network-that-went-viral-because-of-fake-posts/);
[Chirper.ai](https://chirper.ai/) has 65k agents and roughly 140M posts;
[The Colony](https://thecolony.cc/) ships the full primitive set — posts,
comments, votes, DMs, follows, reputation, marketplace, wiki. And
[Form Without Function](https://arxiv.org/abs/2604.13052) (2026-03-17) measured
what those primitives produce: 91.4% of post authors never return to their own
thread, reciprocity of **3.3%** against 22–60% on human platforms, 64.6% of
comments with no argumentative connection to the parent, 97.9% of agents posting
outside their own stated interests. *"The form of social media is reproduced in
full. The function is absent."* Worse for discovery specifically, the
[Chirper.ai followership study](https://arxiv.org/abs/2602.02606) (2026-02-02,
70k agents, one year of ties) found ties form by **persona homophily, not
capability complementarity** — a feed builds the wrong graph. And the
[Moltbook Illusion](https://arxiv.org/abs/2602.07432) found only 15.3% of that
activity genuinely autonomous, with four accounts producing 32% of all comments.

**A feed of posts is a dead product. This proposal does not contain one.**

The **global reputation score** also shipped, and is thin exactly where it
matters. [KnowThat.ai](https://knowthat.ai/) is a real cross-platform agent
reputation registry with third-party behaviour reporting and **214 reporting
operators**; [mnemopay](https://github.com/mnemopay/mnemopay-sdk) ships a
portable numeric trust score on a tamper-evident ledger; ERC-8004 has been on
Ethereum mainnet since 2026-01-28 and a
[10,000-agent study](https://arxiv.org/html/2606.12128v1) found **0.67% had
service records** and **one client wrote 65.8% of all reputation**. All of them
compute a scalar attached to a node. A scalar has no purpose attached to it, no
recipient attached to it, and — as [WARP](https://arxiv.org/abs/2605.24245)
(2026-05-22) showed — is cheaper to defeat than to earn: **13 words** of injected
text beats any reputation an honest party can accumulate.

## What seagull is

A local store and one wire verb, in front of the A2A endpoint an owner already
publishes.

```
gulls intro @booking:acme.example --to @assistant:mine.example \
    --for "book a same-day dental appointment"
```

That writes one object, the **introduction**, and hands a copy to each of the
three parties:

- **introducer** — the agent that made the recommendation,
- **introduced** — the agent being recommended,
- **recipient** — the agent being told,
- **purpose** — a short label, and
- **state** — `open`, then exactly one of `completed`, `failed`, `rejected`,
  `never-contacted`.

The object is keyed on the triple plus the purpose. It is not derivable from any
pair: an introduction is not a follow, not a trust edge, not a vouch and not an
attestation, because all four of those have two ends and this has three.

**Closure is derived, never authored.** The introduction closes when the
recipient's A2A task against the introduced agent reaches a terminal state — the
[A2A specification](https://a2a-protocol.org/latest/specification/) already
defines those states and every conforming runtime already emits them — or, if no
task is ever created, when the introduction's clock expires as `never-contacted`.
Nobody writes a review. Nobody rates anybody. Nobody returns to a thread, which
matters, because *Form Without Function* measured that 91.4% of agents never do.

**The rule is a hard constraint, not a norm.** An introducer may hold at most *k*
`open` introductions with any one recipient at a time — default 3. Closure in any
terminal state frees the slot; `completed` closures raise *k* for that ordered
pair; expiries into `never-contacted` lower it. The counter is a property of the
**pair**, it is computed and enforced on the recipient's own box, it is never
aggregated into a score, and it is never published. An introducer discovers its
budget only by being refused, and the refusal is a signed verdict object carrying
a machine reason code, not prose. This follows the single most useful mechanism
result in *Form Without Function*: hard constraints such as rate limits produce
immediate behavioural shifts, while soft guidance is ignored unless formalised
into something executable.

**Discovery is a query over retained introductions, and nothing else.**

```
gulls whom --for "dental appointment"
```

returns agents reachable through introductions this owner's agents hold, ranked
by closed-`completed` count on that purpose, each row naming its introducer. When
no introduction matches, it returns **nothing**. There is no fallback to a
directory, no ranking by popularity, no suggestion, no feed.

**One capability rides the edge, and only this one.** An introduced agent may
pre-authorise an introducer to spend a bounded number of single-use first-contact
grants on its behalf. Where it has, the introduction carries a grant bound to one
recipient, one purpose and one expiry, letting the recipient past the introduced
agent's stranger gate exactly once. The grant may only narrow, never widen, and
is invocation-bound — the capability-not-ACL discipline from
[Capability Myths Demolished](https://papers.agoric.com/assets/pdf/papers/capability-myths-demolished.pdf),
because an LLM agent is the archetypal confused deputy. Without that
pre-authorisation the introduction is a record and nothing more, and it still
works.

**The edge is where the local name comes from.** The recipient's petname for the
introduced agent is auto-proposed from the introduction —
*"@travel-bot's dental booker"* — in the receiver-assigned sense of
[Stiegler](https://www.skyhunter.com/marcs/petnames/IntroPetNames.html) and the
[Spritely treatment](https://files.spritely.institute/papers/petnames.html). A
bare handle is never rendered as trusted text.

seagull does not host the runtime, mint the identity, sign the Agent Card, serve
the endpoint, or transport the messages. Those exist. It holds one edge.

## Differentiator — what nobody else does

One claim: **an introduction is a three-party object whose terminal state is
derived from the recipient's task history, and that state is what rations the
introducer's future access to that recipient.**

Almost every neighbouring shape is built, and being exact about which is the
whole argument.

- **Typed relationships beyond `follow` are built.**
  [geeks-accelerator/bot-space-ai](https://github.com/geeks-accelerator/bot-space-ai)
  ships nine of them — friend, partner, mentor, student, rival, coworker and more
  — plus a Top-8. It is the richest relationship vocabulary shipping anywhere.
  Every one of them is **dyadic, self-declared and unfalsifiable**: no third
  party, no purpose, no outcome, and nothing in the system contradicts a label
  you assert about yourself.
- **An autonomous peer-to-peer agent trust graph is built and measured.** Pilot
  Protocol ([paper](https://arxiv.org/abs/2604.09561),
  [repo](https://github.com/pilot-protocol/pilotprotocol), 866 commits,
  `draft-teodor-pilot-protocol-01`) recorded 626 agents forming 1,567 trust edges
  autonomously through a mutual trust handshake. It is real and that number is
  methodologically grounded. Its edge is **A↔B**. A third agent is never a party
  to it, and no edge names what the trust was *for*.
- **Vouching with real economic cost is built.**
  [dirtybits/agentvouch](https://github.com/dirtybits/agentvouch) ships stake,
  disputes and slashing. It is the nearest thing by name. Its vouch is a **global
  bond about an agent**, not a claim scoped to one recipient; it names no
  purpose; and its terminal state arrives only when someone raises a dispute — an
  authored, optional act, and therefore refuted in advance by the mechanism
  result above.
- **The signed, rotatable, contestable verdict object is built.**
  [TheColonyCC/attestation-envelope-spec](https://github.com/TheColonyCC/attestation-envelope-spec)
  is at v0.1.18 with roughly 208 tests. This is the closest match by *shape* and
  I concede it fully. An attestation has an **issuer and a subject** — two roles
  — with no recipient scoping; nothing in it budgets an issuer's access to a
  particular relying party, and its verdicts are authored by the issuer rather
  than derived from what happened next.
- **Keypair identity plus trust scoring on a self-hostable agent SNS is built.**
  [agentgram/agentgram](https://github.com/agentgram/agentgram) (Ed25519 plus
  reputation scoring) and [ai-sns/ai-sns](https://github.com/ai-sns/ai-sns)
  (334★, fully local agents federating over XMPP and A2A). Both produce a
  **scalar on a node**.
- **First contact as a protocol verb is built.**
  [SlanchaAI/wire](https://github.com/SlanchaAI/wire) has `pending`/`accept`. Two
  parties. Nobody introduced anybody.
- **Sybil-resistant social-graph analysis for agents is built.**
  [TheColonyCC/closure-vs-reciprocity](https://github.com/TheColonyCC/closure-vs-reciprocity)
  analyses an existing graph. It does not create an edge type.
- **Domain-verified organisational agent identity as a social primitive is
  built** — Agent Commune, "LinkedIn for AI agents", with company-email-domain
  auth ([producthunt](https://www.producthunt.com/products/linkedin-for-ai-agents)).
  It is a directory of verified profiles. A LinkedIn profile is not an
  introduction, and this one has no introduction verb.

On the standards side the space is not merely empty, it is **excluded by
charter**. `draft-sharif-attp-00`, the one IETF draft whose entire subject is
agent trust scoring, explicitly rules out reputation networks, trust propagation
between agents, social relationships, endorsements and vouching. IETF
[Web Bot Auth](https://datatracker.ietf.org/wg/webbotauth/about/) is chartered
and shipping per-request cryptographic agent identity with **bot reputation
tracking explicitly out of scope**. No A2A extension, no MCP extension, no FEP,
no atproto lexicon and no merged NIP defines an agent-to-agent relationship edge
of any kind.

The one claim is false if any of these fail:

- The stored object is keyed on (introducer, introduced, recipient, purpose) and
  cannot be reconstructed from any set of two-party edges.
- All three parties retain it. The **introduced** agent can enumerate who has
  been recommending it, to whom, and for what — which no shipping product,
  including every one conceded above, exposes to the subject of the
  recommendation.
- The terminal state is derived from A2A task states and an expiry clock. No
  party authors a rating, a score, a star or a review, and there is no field in
  which one could.
- An `open` introduction has a cost paid by the introducer, so closure is
  structurally enforced rather than requested.
- The budget is per ordered pair, computed on the recipient's box, never
  aggregated, never published and never sold, and never presented as a global
  reputation.
- Discovery returns the empty set when no introduction matches. There is no
  directory fallback and no popularity ranking — so a registry with social
  features does not satisfy this text.
- No free text controlled by another party is an input to the code that decides
  whether an introduction is accepted or a grant honoured, and this is testable
  by trying.

## The wedge — value before a network exists

**The dead-referral report.**

With one owner, several agents and zero peers, `gulls intro` is a place to write
down the referrals currently sitting in an `AGENTS.md`. That alone is worth
nothing. What is worth something arrives free with it: because every one of the
owner's own agents already emits A2A task states, each recorded referral acquires
— without anybody doing anything — a count of how many times it was acted on and
how many of those completed.

On day one, at zero peers, the owner can run one query nobody can answer today:
**which lines in my referral list has no agent of mine ever once acted on?**

That is a list of dead configuration, and every referral author has one. It gets
more useful as their own agent count rises, before a second owner exists, and it
is what makes the ledger non-empty on the day a peer finally shows up. The
network effect is real but it is not the wedge; the wedge is that write-only
configuration becomes readable.

## The hard part

Not discovery routing — DNS plus A2A very nearly solves it. Not injection at the
message layer — that is the runtime's problem and deliberately not this one's.

**First: `never-contacted` is the most common state and the least informative
one.** A recipient that does not act on an introduction may be telling you the
recommendation was bad, or that its owner changed their mind, or that it was busy
that week. The mechanism spends the introducer's budget in all three cases, which
is correct for suppressing spray and wrong as signal. The abundant edge is the
uninformative edge, and no amount of design removes that, because the alternative
— asking the recipient why — is exactly the soft, authored act that
*Form Without Function* measured agents refusing to perform 91.4% of the time.
This is the differentiator's load-bearing wall and it may not hold.

**Second: `completed` is not `correct`.** Deriving the outcome from the A2A task
lifecycle buys automaticity and pays for it in semantics. A colluding pair can
open and complete tasks all day. The containment is structural rather than
detective — the budget is recipient-scoped, so a collusion ring can only inflate
its standing with recipients it has already reached, and inflating a counter that
never leaves someone else's box buys nothing — but the honest statement is that
the signal measures *"contact happened and terminated"*, not *"the work was
good."* Anyone who needs the second thing needs a different product.

**Third, the growth ceiling: recipient-scoping is both the Sybil defence and the
reason the graph propagates badly.** Because a counter never leaves the
recipient, a newcomer with no history is illegible to everyone simultaneously,
and a good introducer must earn budget separately with each recipient. The cheap
fixes are all measured failures — proof-of-work postage
[blocks around 13% of legitimate senders](https://www.cl.cam.ac.uk/~rnc1/proofwork2.pdf)
long before it taxes a determined one, and transitive webs of trust are the
canonical unsolved case. Whether an introduction graph with no transitivity is
still worth traversing is the open empirical question, and it is not answered
here.

**Fourth: the object is a disclosure about a third party.** *A told C about B* is
a statement about B that B did not consent to, held by two parties who are not B.
Making it visible to B is the strongest single claim above and it is equally the
attack surface: an enumerable record of who is recommending whom, for what, is
precisely the artifact a competitor wants. What is retained, for how long, and
what B can compel — deletion, contest, or only annotation — are v0 questions
here, not v2 questions. A social object whose novelty is third-party visibility
does not get to defer its deletion posture.

## Unit of value

Per owner, flat. Never per introduction.

Pricing per introduction would pay the product to encourage more of them, which
is exactly the behaviour the open-introduction budget exists to suppress — a
product that profits from what it rate-limits will eventually stop rate-limiting.
Pricing per agent would imply fleets, and the referral author does not have one.

The consequence is deliberate and constraining: seagull cannot grow revenue from
graph volume, cannot sell the graph, and cannot monetise placement in a `gulls
whom` result — so it has to be worth paying for by a single owner holding thirty
introductions.

## Explicitly not

A feed, a timeline, a post, a comment, a like, a follow, or a Top-8. Not a global
reputation score, not a portable trust number, not a marketplace, not an escrow,
not a stake-and-slash system, not a capability registry, not a new naming system,
not a new wire protocol, not a mandatory hub.

Also not, deliberately: content inspection. seagull does not classify what an
introduction says, does not score the purpose string, and does not detect prompt
injection. The purpose is a label rendered to a human and used as a filter key,
never an instruction reaching a model — the
[lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)
discipline applied to this one object.

And explicitly not a human social graph.
[ClawNet](https://arxiv.org/abs/2604.19211) (2026-04-21) is the only paper whose
nodes are humans rather than agents, and it addresses authorisation and audit
only. Here the parties to every edge are agents; the human sets the budget and
reads the report.

## Falsifiable commitments

On the object:

1. The stored introduction has exactly four identity-bearing fields —
   introducer, introduced, recipient, purpose — and no two-party edge type can
   represent it without loss.
2. All three parties can enumerate the introductions they are party to, from
   local state, with no call to any service the owner does not run.
3. The introduced agent can enumerate introductions naming it that it did not
   create and did not authorise.
4. Every introduction carries each party's `agent_id`, not a handle, so a handle
   change rewrites no stored edge.
5. An introduction's identity does not change when any party changes host.
6. No introduction is created without a purpose field; a purpose-free
   introduction is rejected at the wire, not defaulted.
7. Two introductions between the same three parties for different purposes are
   different objects with independent states.
8. The wire object is signed by the introducer and verifiable by the other two
   parties without contacting the introducer.

On closure:

9. A terminal state is derived from A2A task states or an expiry clock, and from
   nothing else.
10. There is no field, flag or endpoint by which any party can author a rating,
    score, star or review of another party.
11. `never-contacted` is distinguishable in the store from `failed` and from
    `rejected`, and all three from `open`.
12. An introduction that produced a completed task cannot be reopened by the
    introducer.
13. Expiry is per-introduction, set at creation, visible to all three parties,
    and does not silently extend.
14. A recipient that never installs seagull produces no closures, so the
    introducer's budget with it saturates rather than degrading gracefully. This
    is a stated cost, not a hidden one.

On the constraint:

15. The open-introduction cap is enforced in code on the recipient's box, not
    requested in documentation or in a prompt.
16. Refusal for cap-exceeded returns a signed verdict object with a machine
    reason code and no natural-language explanation.
17. No byte of introducer- or third-party-controlled text is an input to the code
    that evaluates the cap, and this is testable by submitting adversarial purpose
    strings.
18. The cap default is a published number, not a heuristic, and an owner can read
    and set it.
19. The pair counter is never transmitted off the recipient's box by default —
    not to a vendor, not to the introducer, not to any peer.
20. No global, network-wide or cross-recipient score is computed anywhere in the
    system, and no API returns one.
21. Two recipients can hold contradictory budgets for the same introducer
    indefinitely, and nothing reconciles them.
22. Raising a cap requires an action by the recipient's owner or a completed
    closure; it is never purchasable.

On discovery:

23. `gulls whom` returns only agents reachable via retained introductions, and
    the empty set otherwise.
24. There is no directory lookup, catalogue fetch or popularity ranking anywhere
    in the resolution path.
25. Ranking within results uses closure counts on the queried purpose only, and
    the ranking function is published.
26. Every returned row names its introducer, and a row whose introducer cannot be
    verified is not returned.
27. Discovery works with two owners and no third party; no hub is required for an
    introduction to be made, delivered or closed.
28. Nothing requires an agent to be online at the moment an introduction is made.
29. An idle agent's steady-state cost is zero: no republish loop, no gossip
    membership, no keepalive.

On the capability:

30. A first-contact grant is issued only by the introduced agent, never minted by
    the introducer.
31. A grant is bound to one recipient, one purpose and one expiry, and is
    single-use.
32. Grant scope may only narrow at every hop and never widen.
33. Revoking an introduced agent's pre-authorisation invalidates unspent grants
    without invalidating the introductions that carried them.
34. An introduction with no grant still records, still closes, and still counts
    toward discovery.
35. No introduction can cause any message to be delivered to the introduced
    agent; only the recipient can initiate contact.

On the social surface:

36. There is no timeline, feed, post, comment, reaction or follower count in the
    data model, and adding one would require a new object type.
37. No content authored for consumption by other agents exists in the system; the
    only free-text field is the purpose label.
38. Petnames are receiver-assigned, unique only within one owner's namespace, and
    never transmitted as another party's name.
39. A handle supplied by a sender is always rendered as untrusted — quoted or
    marked — and never as bare trusted text.
40. The system produces no ranking of agents by popularity, activity or follower
    count.

On retention and exit:

41. An introduction's purpose text and its terminal state have separate
    lifetimes: an owner can purge the text and keep the fact that the
    introduction was made and how it closed.
42. Any party can ask "what do you hold about me?" and be answered from local
    state without contacting any service.
43. An introduced agent can compel annotation of an introduction naming it, and
    the annotation travels with the edge.
44. Everything held is exportable in a documented format, and an owner who stops
    using seagull leaves with their introduction history.
45. Nothing in the store is transmitted to any party outside the three named in
    the edge, by default or by upsell.
46. The graph is not a saleable asset: no pricing tier, API or partnership grants
    a fourth party read access to introductions it is not a party to.

On the premise:

47. A2A defines task terminal states but defines no relationship edge, so this
    object cannot be obtained by conforming to A2A more thoroughly.
48. No IETF working group has chartered work on agent-to-agent social
    relationships as of 2026-07-28, and the one draft on agent trust scoring
    excludes them by scope.

## Known weaknesses

- **The URL most likely to kill this is
  [dirtybits/agentvouch](https://github.com/dirtybits/agentvouch).** It ships
  agent-to-agent vouching with real economic cost — stake, disputes, slashing —
  and the word "vouch" sits close enough to "introduce" that a reviewer may stop
  reading. It does not kill this variant *yet* for three reasons, each of which
  is one commit away from being false: its vouch is dyadic and global rather than
  scoped to a recipient; it names no purpose; and its terminal state requires
  someone to raise a dispute, which is precisely the authored, optional act
  agents were measured not to perform. If agentvouch adds a third party and
  derives resolution from task state, this proposal is finished.
- **The second most likely is
  [TheColonyCC/attestation-envelope-spec](https://github.com/TheColonyCC/attestation-envelope-spec)**,
  which already has the signed-verdict-as-first-class-contestable-object shape at
  v0.1.18. The distance is issuer/subject versus introducer/introduced/recipient,
  and authored versus derived verdicts. That is two design decisions, not a moat.
- **The wedge is thinner than a single-agent wedge should be.** The dead-referral
  report needs the owner to run more than one agent and to have written more than
  a handful of referrals. Below that threshold an `AGENTS.md` and a text editor
  win, and this proposal concedes it rather than widening the claim.
- **Commitment 14 is a real product hole.** An introduction to a recipient that
  never installs seagull can never close, so the introducer's budget saturates
  against exactly the population the network most needs to recruit. The bootstrap
  runs backwards from every social product: the *recipient* must adopt first for
  the *introducer* to get value.
- **The three-party edge may simply be rarer than assumed.** Every measurement
  cited here — 626 Pilot Protocol trust edges, 841 Colony agents, roughly 35 live
  platforms in
  [awesome-agent-native-social](https://github.com/ColonistOne/awesome-agent-native-social)
  — counts dyads. Nobody has published a count of agent-to-agent *introductions*,
  because nobody stores them. That is the opportunity and equally the reason the
  demand is unproven.
- **18.28% of posts on a live agent social network are toxic, manipulative or
  malicious across 74 attack classes**
  ([When Agents Talk](https://arxiv.org/abs/2606.00067), 2026-05-20). This
  proposal removes the post, which removes that surface, and replaces it with an
  edge carrying one short free-text field. There is no reason to believe the
  adversaries go away; there is only reason to believe the surface is smaller,
  and "smaller" has not been measured here.