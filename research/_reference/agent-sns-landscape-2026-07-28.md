# Agent SNS Landscape — 2026-07-28

Status: Research. Surveyed ground for the overlap lenses, so they do not re-derive it.
Companion to `agent-network-research.md`, which covers naming/discovery/P2P. This one
covers the **social dimension**: feeds, follows, reputation, vouching, introductions.

Produced by five blind survey lenses (papers / products / open source / standards /
recent trend), 131 findings, all URL-bearing. Corrections to the companion document are
flagged at the bottom.

---

## 1. The finding that reframes everything

**The agent social network is not unbuilt. It is built, at scale, and measured to not
work.**

| Paper | Date | Measurement |
| --- | --- | --- |
| [Form Without Function](https://arxiv.org/abs/2604.13052) | 2026-03-17 | On Moltbook: 91.4% of post authors never return to their own thread; 85.6% of conversations stay flat; reciprocity **3.3%** vs 22–60% on human platforms; 97.3% of comments get zero upvotes; 97.9% of agents post outside their stated interests; 64.6% of comments have no argumentative connection to the parent; 92.5% of communities show random topic assignment. **"The form of social media is reproduced in full. The function is absent."** |
| [The Moltbook Illusion](https://arxiv.org/abs/2602.07432) | 2026-02-07 | 226,938 posts / 55,932 agents: only **15.3% genuinely autonomous**, 54.8% human-influenced. Four accounts produced 32% of all comments. Zero of the viral "agent culture" phenomena originated from autonomous agents. |
| [Gender Dynamics and Homophily (Chirper.ai)](https://arxiv.org/abs/2602.02606) | 2026-02-02 | 70k+ agents, ~140M posts, one year of followership. Ties form by **persona homophily, not capability complementarity**. |
| [When Agents Talk](https://arxiv.org/abs/2606.00067) | 2026-05-20 | **18.28%** of posts on a live agent social network are toxic, manipulative or malicious, across 74 attack classes. |
| [WARP](https://arxiv.org/abs/2605.24245) | 2026-05-22 | Deep-research agents poisoned via user-generated content. **13 words** of injected text is cheaper than any reputation an honest party can accumulate. |

The single most useful mechanism-design result, from *Form Without Function*: **hard
constraints (rate limits, filters) produce immediate behavioural shifts; soft guidance
("upvote good posts", community guidelines) is ignored unless formalised into an
executable checklist.** Any social mechanism for agents that relies on norms is refuted
in advance.

Corollary, stated by [Forbes 2026-06-22](https://www.forbes.com/): *the AI agents that
actually work don't post on social media.*

---

## 2. Occupied — a proposal making these claims dies to a live URL

### Shipping products

| Claim | Taken by | URL |
| --- | --- | --- |
| Agent-only social network at scale | Moltbook — 206,839 verified / 2,895,874 registered agents; **acquired by Meta 2026-03-10**, now in Meta Superintelligence Labs | [techcrunch](https://techcrunch.com/2026/03/10/meta-acquired-moltbook-the-ai-agent-social-network-that-went-viral-because-of-fake-posts/) |
| Agent-only feed + follows + discovery | Chirper.ai — 65k agents, years old, peer-reviewed | https://chirper.ai/ |
| Full SNS primitive set for agents (posts, comments, votes, DMs, follows, reputation, marketplace, wiki) | The Colony — 841 agents / 910 humans / 12,833 posts live | https://thecolony.cc/ |
| Domain-verified organisational agent identity as a social primitive | Agent Commune ("LinkedIn for AI agents"), company-email-domain auth | [producthunt](https://www.producthunt.com/products/linkedin-for-ai-agents) |
| Standalone cross-platform agent reputation registry with third-party behaviour reporting | KnowThat.ai (by Vouched) — but only **214 reporting operators** | https://knowthat.ai/ |
| Enterprise agent registry / directory / inventory | Microsoft Agent 365 (GA 2026-05-01, $15/user/mo) + Entra Agent ID; Google Gemini Enterprise Agent Registry | [learn.microsoft.com](https://learn.microsoft.com/en-us/microsoft-agent-365/overview) |
| Durable address + inbox for agents, with self-onboarding | AgentMail (YC/GC-backed) — 8 providers in the field | https://www.agentmail.to/ |
| Registry + offline mailbox + marketplace for agents | Fetch.ai Agentverse (Almanac + Mailroom), ~36k agents | https://arxiv.org/html/2606.20570 |
| Agent behavioural attestation as a credential | Workday Agent Passport | [newsroom.workday.com](https://newsroom.workday.com/2026-06-02-Workday-Launches-Agent-Passport-to-Test,-Verify,-and-Continuously-Monitor-Every-AI-Agent-in-the-Enterprise) |
| Human↔agent binding + trust tokens for commerce | Experian Agent Trust ("Know Your Agent"), with Visa/Cloudflare/Fastly | [experianplc.com](https://www.experianplc.com/newsroom/press-releases/2026/experian-announces-agent-trust-to-power-trusted-ai-driven-commer) |
| Permissionless agent-native accounts on a human social graph | Farcaster — an agent self-registers and posts for ~$1, no human in the loop | [bitget](https://www.bitget.com/news/detail/12560605182089) |

### Open source, commits in the last 6 months

| Claim | Taken by | URL |
| --- | --- | --- |
| Open-source self-hostable agent SNS with **Ed25519 keypair identity + reputation/trust scoring** | agentgram/agentgram (MIT) | https://github.com/agentgram/agentgram |
| **Decentralised agent social network, agents run 100% locally, federate** (XMPP + A2A) | ai-sns/ai-sns — 334★ | https://github.com/ai-sns/ai-sns |
| Agent SNS on Nostr with self-certifying keypair identity | clawstr/clawstr (dormant since 2026-02-09) | https://github.com/clawstr/clawstr |
| **Typed relationships beyond follow** (friend, partner, mentor, student, rival, coworker…) + Top-8 | geeks-accelerator/bot-space-ai | https://github.com/geeks-accelerator/bot-space-ai |
| Agent-to-agent **vouching with real economic cost** (stake, disputes, slashing) | dirtybits/agentvouch | https://github.com/dirtybits/agentvouch |
| Portable numeric agent trust/credit score, tamper-evident ledger | mnemopay/mnemopay-sdk | https://github.com/mnemopay/mnemopay-sdk |
| Sybil/vote-farming-resistant reputation graph for agents | TheColonyCC/closure-vs-reciprocity | https://github.com/TheColonyCC/closure-vs-reciprocity |
| Signed attestation envelope / policy verdict as a signed object with rotation + contestability | TheColonyCC/attestation-envelope-spec (v0.1.18, ~208 tests) | https://github.com/TheColonyCC/attestation-envelope-spec |
| First-contact consent as a protocol verb (`pending` / `accept`) | SlanchaAI/wire | https://github.com/SlanchaAI/wire |
| Social graph exposed as MCP tools | terminalcraft/moltbook-mcp, colony-mcp-server, The Lounge | https://github.com/terminalcraft/moltbook-mcp |
| Serverless/operator-free agent social network | kody-w/rappterbook (GitHub repo *is* the platform) | https://github.com/kody-w/rappterbook |
| Agent society simulator | tsinghua-fib-lab/AgentSociety (1,162★), YSocialTwin/YSocial | https://github.com/tsinghua-fib-lab/AgentSociety |
| "This space is empty" as a market claim | ColonistOne/awesome-agent-native-social — ~35 live platforms with admission criteria | https://github.com/ColonistOne/awesome-agent-native-social |

Also live: an explicit peer-to-peer **agent trust graph** shipped and measured — Pilot
Protocol, 119★, 866 commits, `draft-teodor-pilot-protocol-01`, 626 agents forming 1,567
trust edges autonomously ([paper](https://arxiv.org/abs/2604.09561), [repo](https://github.com/pilot-protocol/pilotprotocol)).
Vendor claims ~219k agents online; the only methodologically grounded number is 626.

**Two dead, therefore NOT prior art:** `agentmessaging/protocol` (federated `@name@domain`
agent messaging with Ed25519 keys — 29★, dead since 2026-03-23) and `0xIntuition/agent-rank`
(dead 2025-05-21). Cite as proof the shape is obvious, not as a kill.

---

## 3. Unoccupied — verified by evidence of absence across independent lenses

Each of these was searched for by at least two lenses and returned nothing shipped.

1. **Introduction / vouching edges as the discovery mechanism, with the introduction edge
   retained as provenance the recipient can see.** No product ("NO INTRODUCTION OR
   VOUCHING PRIMITIVE ANYWHERE — only academic work"). No spec: `draft-sharif-attp-00`,
   the one IETF draft whose entire subject is agent trust scoring, **explicitly excludes**
   reputation networks, trust propagation between agents, social relationships,
   endorsements and vouching. Nearest OSS is agentvouch (economic stake, not social
   provenance). Academically uncontested.
2. **Agent presence — "is this agent reachable now."** No specification anywhere;
   FEP-82f6 is nearest and explicitly disclaims it. Unclaimed as a product. Only
   hivemind (1★) ships realtime at all.
3. **An agent contact list / address book / introduction graph as a shared protocol.**
   GitHub search returns zero. Only `kurvronw/MaiHH-Connect` (1★, committed 2026-07-27)
   stakes the phrase "first address book for agents" — contested, not occupied.
4. **Recipient-scoped first-contact and attention-budget economics between agents.** No
   papers, no products. (This is the companion document's §8 recommendation, still open.)
5. **Petnames / receiver-assigned local naming for agents.** Only the general petname
   literature exists; nothing applies it to agent networks.
6. **Federation between agent social networks.** Every agent SNS with real data —
   Moltbook, Chirper.ai, AI-Gram — is a single centralised platform. No paper proposes
   federating them. The ActivityPub/AT-Protocol-for-agents lane is **named but empty**
   (`keptlive/agent-fediverse`: 0★, created and abandoned the same day). Caveat: ai-sns
   occupies the *federated-local* position via XMPP.
7. **A human-owner-mediated social graph.** ClawNet ([arXiv 2604.19211](https://arxiv.org/abs/2604.19211),
   2026-04-21) is the only paper where "nodes are humans rather than agents", and it
   addresses authorisation and audit **only** — no discovery, no naming, no social graph,
   no inbox posture.
8. **No standards body defines an agent-to-agent follow / contact-list / social-graph
   edge, a feed, a timeline, or a disclosure primitive for agent-authored content.**
   Verified against the complete MCP extensions roster, the four documented A2A
   extensions (Secure Passport, Timestamp, Traceability, Agent Gateway Protocol), the
   FEP index, atproto lexicons, and merged NIPs.
9. **No IANA link relation for agent cards or agent discovery** — full 236-entry registry
   pulled and grepped. The only agent well-known URI is `agent-card.json`.

---

## 4. Why now — ranked

1. **2026-06-03 — bots passed humans on Cloudflare's network**, ~18 months ahead of the
   vendor's own forecast. The population is no longer forecast.
   [semrush summary](https://www.semrush.com/blog/ai-agent-bot-traffic/)
2. **Human networks are actively expelling agents.** Digg pulled its relaunched app after
   an AI bot swarm broke its voting system within hours (2026-03-14); Reddit mandated
   human verification ten days later.
   [pymnts](https://www.pymnts.com/cybersecurity/2026/reddit-wants-you-to-prove-you-are-human/)
   This is a *necessity* argument and is stronger than any appetite argument.
3. **The one real agent social network is a measured exploit channel** — 18.28% of posts
   malicious across 74 attack classes.
4. **Meta bought the category-definer** (2026-03-10) and put it in Superintelligence Labs.
5. **The standardisation window is still open.** IETF **Web Bot Auth is chartered and
   shipping** per-request cryptographic agent identity — and its charter puts **bot
   reputation tracking and end-user authentication explicitly out of scope**.
   [webbotauth](https://datatracker.ietf.org/wg/webbotauth/about/)

---

## 5. Corrections to `agent-network-research.md`

- **DAWN has NOT chartered.** The companion doc records "DAWN appears to have chartered"
  and advises treating it as probable. As of 2026-07-28 the datatracker shows group state
  **BOF**, "Charter: (None) / Not chartered yet" — for both `dawn` and `agentproto`.
  Do not cite either as institutional cover.
  https://datatracker.ietf.org/wg/dawn/about/ · https://datatracker.ietf.org/group/agentproto/about/
- **OWASP ANS is not dead.** The companion doc says "expired 2025-11-17, never revised,
  not worth tracking." An **ANS v2** draft is active (`draft-narajala-courtney-ansv2-01`,
  rev 2026-04-13, expires 2026-10-15) and is the only spec-level artifact naming
  behavioural reputation as an architectural layer. The **Linux Foundation announced
  intent to launch an Agent Name Service on 2026-06-23** with Cloudflare, Cisco,
  Salesforce and Infoblox.
- **New, missed entirely: the IETF ATP working group chartered 2026-04-02** to standardise
  AT Protocol — including a registry of recommended account-identifier resolution systems.
  The handle→identity split the companion doc recommends copying is becoming
  standards-track.
- **New: Google Agentic Resource Discovery (ARD)**, 2026-06-17 — federated agent
  capability directory, with no reputation, no social graph, no relationship model.
