# Agent Network Research: P2P And DNS-Like Discovery

Status: Research. Not authoritative. Evidence for and against the decisions in
[Agent Voice And DNS Discovery](agent-voice-and-discovery.md); that document
still wins on architecture.

Last updated: 2026-07-26.

Scope: how agents find and address each other. Four bodies of evidence —
agent-native standards, DNS-anchored federated systems that already run at
scale, P2P substrates, and naming/trust theory — read against the current
gulls target architecture (`@handle:domain` → WebFinger → AID → A2A, no
central hub).

Numbers marked **(vendor)** are self-reported by the project that benefits from
them and have no published methodology. Claims marked **(thin)** have a spec but
effectively no deployment.

---

## 1. Summary

The current design is on the right side of every major fork. The four
things worth changing are narrow:

1. **The canonical identifier is a domain name, and that is `did:web`'s
   failure mode.** Every system that put a domain inside the signed record —
   Matrix (`sender`), ActivityPub (`id` origin) — has spent 8+ years failing to
   get it back out. The one that split them (AT Protocol: mutable handle →
   stable key-derived DID) made migration a one-field edit. gulls already
   admits hosted handles are not portable; the fix is a key-derived
   `agent_id` under the handle, not a better handle.
2. **AID cannot serve the two publication profiles the product depends on.**
   `_agent.<domain>` is exact-host with no hierarchy walk, and DNS wildcards
   only match the leftmost label — so `_agent.*.example.com` is not a valid
   wildcard. Shared Domain Gateway and Seagulls-Hosted Voice both need
   N records for N agents plus per-record DNSSEC. WebFinger already handles
   both with one path and no DNS provisioning. AID's own registry is
   [not operational](https://github.com/agentcommunity/aid-registry) (2 commits,
   no indexed domains) **(thin)**.
3. **The "no registered link relation" gap is real, but the implementation
   hazards around it are better documented than the doc suggests.** WebFinger
   has a decade of fediverse CVEs — origin confusion, domain-normalization
   takeover, one-way verification — and each has a one-line rule. Write those
   rules into the resolution section now; they are cheaper than the
   standardization work.
4. **P2P has almost no role left after the redesign, and the remaining role is
   narrower than the legacy boundaries doc assumed.** Removing the hub removed
   the thing P2P was going to optimize. What survives: direct transport for
   large artifacts and streaming between two Gulls that are both already
   online, and LAN-node traffic that must not leave the LAN. Everything else —
   presence, discovery, durable delivery — is a trap with measured numbers
   attached.

One thing changed under the doc between its writing and today: **IETF DAWN
appears to have chartered.**

---

## 2. What holds up

Restating what the evidence confirms, so the argument below is not mistaken for
a rewrite.

| Decision in the authoritative doc | Independent evidence |
| --- | --- |
| Handle resolution via WebFinger | Nothing agent-native solves multi-agent-per-domain. A2A ties one card to one domain; the [registry discussion](https://github.com/a2aproject/A2A/discussions/741) has been open since 2025-06-10 with no consensus. ANP's paginated `/.well-known/agent-descriptions` is the only agent-native alternative and has no adoption. WebFinger is a decade-proven `@name:domain` resolver, and **no agent-native spec has adopted it** — that is an opening, not a bandwagon. |
| Two-step resolution (`handle → identity → location`) | The single most-repeated lesson across Matrix, ActivityPub, atproto and email. Portability, host failover, key rotation without renaming, and LAN/WAN duality all fall out of the indirection. Matrix and email conflate the two and get none of them. |
| "gulls must not define another global naming system" | [draft-king-dawn-requirements-01](https://www.ietf.org/archive/id/draft-king-dawn-requirements-01.html): discovery MUST work decentralized, MUST NOT require a single centralised registry, MUST operate across trust boundaries without a single global trust anchor. Also: **naming system design is explicitly out of DAWN's scope** — nobody is going to standardize your handle format, so owning it is correct. |
| A2A as the interaction protocol | The only agent-native spec with production weight: v1.0 (2026-03-12), v1.0.1 (2026-05-28), Linux Foundation governance, [150+ organizations](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year), shipping in Google Cloud, Azure AI Foundry, AWS Bedrock AgentCore. |
| `pass` / `fail` / `absent` / `unsupported`, and "`absent` is never rendered as verified" | This is the discipline every deployed system lacks. Nostr's NIP-67 completeness hint is a hint a liar forges; atproto concedes an intermediary can filter undetectably; Matrix's cherry-picked `auth_events` became CVE-2025-49090. Distinguishing "not proven" from "proven false" is the whole game. |
| "The host is inside the trust boundary" (hosted voice) | Correct and unusually honest. atproto says the same about `plc.directory`, and names its exact two attacks — denial of service and misordering. Naming yours in the spec is the right pattern. |
| Relay/gateway remains the delivery path; P2P is not a control layer | Confirmed by every P2P system surveyed (§6). |
| Threat model's "the primary risk is not routing" | The strongest single sentence in the repo. [CVE-2025-32711 (EchoLeak)](https://nvd.nist.gov/vuln/detail/CVE-2025-32711) is the zero-click proof: content arrives in the corpus, gets retrieved into context, exfiltrates through a rendered reference. Routing verification was never the hard part. |

---

## 3. What changed since 2026-07-27

Five facts postdate or complicate the references section.

**DAWN appears to be a chartered IETF working group.** A WG-forming BOF ran at
IETF 126 Vienna on 2026-07-21 (chairs Wes Hardaker, Adrian Farrel; AD Eric
Vyncke). As of today the datatracker serves a
[`dawn` group page](https://datatracker.ietf.org/wg/dawn/documents/) with
charter, documents, meetings and history sections, carrying seven drafts
including a new one — **DNS-Based Agent Naming (DAN),
`draft-seethiraju-dawn-dan-00`, 2026-06-05**. Treat chartering as probable, not
certain, until the IETF 126 minutes post. Either way the requirements draft is
now the constraint that any later standardization will be judged against, and
gulls already satisfies it.

**A sibling BOF, `agentproto`, ran 2026-07-23** on MCP/A2A/ACP/ANP convergence.
Its framework draft
([draft-rosenberg-aiproto-framework-00](https://datatracker.ietf.org/doc/html/draft-rosenberg-aiproto-framework-00),
Rosenberg/Five9 + Jennings/Cisco) proposes **no identifier or URI format at
all** and argues inter-domain discovery requires pre-established security
relationships. That is a materially different position from DNS-AID's.

**DNS-AID is no longer just an individual submission.** The Linux Foundation
[announced it as a project on 2026-05-27](https://www.linuxfoundation.org/press/linux-foundation-announces-dns-aid-project-to-advance-decentralized-ai-agent-discovery)
with Cloudflare, CSC, Equinix, GoDaddy, IDC, Indeed, Infoblox, ISC and WWT;
the draft's author list includes Deutsche Telekom and Amazon. The doc's line
"individual submission, not IETF-adopted, no IETF standing" is still literally
true at the IETF and now materially understates the institutional weight. No
deployment commitments were announced — this is governance and funding, not
agents in the wild.

**AID is at v2.1.0 (2026-06-01)** and the `.well-known/agent` fallback in
Appendix C is confirmed, labelled `well-known-tls` versus `dns`, and explicitly
cannot satisfy a DNSSEC-based policy. The doc's treatment of it is accurate.
What the doc does not say is that the AID *registry* is unbuilt and the project
says so.

**MCP's 2026-07-28 release makes the protocol core stateless** — drops the
`initialize` handshake and `Mcp-Session-Id`, moves capabilities into per-request
`_meta`, adds a reverse-DNS Extensions framework, deprecates Roots/Sampling/
Logging on 12-month clocks. Relevant to the connector layer, not to discovery.
There is still no `.well-known/mcp` in the official spec; the drafts that define
one (`draft-serra-mcp-discovery-uri`, `draft-morrison-mcp-dns-discovery`) have no
IETF standing.

Not worth tracking: **OWASP ANS** (IETF draft expired 2025-11-17, never revised;
and the name is now also GoDaddy's commercial product and a generic vendor
term — always disambiguate). **NANDA / AgentFacts** — good ideas, 9 commits, no
code, no live resolver **(thin)**. **ERC-8004** — on Ethereum mainnet since
2026-01-28, and a [mainnet study of 10,000 agents](https://arxiv.org/html/2606.12128v1)
found **0.67% had service records**, top 10 wallets held 51.4% of all agents,
and one client wrote 65.8% of all reputation. Registration-heavy, operationally
hollow.

---

## 4. Challenge 1: the canonical identifier is a domain

### The problem

The system shape resolves `@weather:example.com` to `weather.agents.example.com`
to an endpoint. The middle term — "canonical agent identifier" — is an FQDN.
That means identity is whoever controls the DNS zone, permanently, with no
rotation, no recovery, no audit log, and no fork detection.

This is exactly `did:web`, and the AT Protocol spec names its failure mode
directly: it "is inherently tied to the domain name used, and does not provide a
mechanism for migration or recovering from loss of control of the domain name."
Worse, because the identifier *embeds* the domain, changing domains means
becoming a different agent — destroying the property the indirection exists to
provide.

The doc already sees the symptom in one place: hosted handles are
provider-scoped, "moving providers changes the handle," and export plus
custom-domain attachment "is a migration, not a rename." That is the right
diagnosis of the wrong layer. The handle *should* be mutable. The thing under it
should not be.

### The evidence

- **Matrix** put the homeserver domain in `sender`, signed events with that
  domain's key, and content-hashed them. Eight years and four MSCs
  (1228 → 2787 → 4014 → 4243) have failed to get it back out. Moving
  `@alice:a.example` would require re-signing the entire history of every room
  with a key she does not control. MSC4243 is motivated explicitly by GDPR,
  because user IDs are direct personal data.
- **ActivityPub** made origin equal authority (FEP-fe34). Mastodon's `Move`
  transfers followers and nothing else — "your posts will not be moved, due to
  technical limitations" — and every `@mention` in every historical post
  permanently addresses a dead actor. The fix (FEP-ef61 portable objects) has
  **zero mainstream adoption**, because it requires inverting origin-equals-
  authority into signature-equals-authority: a rewrite, not a feature.
- **AT Protocol** split them. Handle = a domain you prove control of, resolved
  in parallel via DNS TXT `_atproto.<handle>` and
  `https://<handle>/.well-known/atproto-did`, with DNS winning on conflict.
  Identity = `did:plc:...` = `base32(sha256(genesis_op))[:24]`, self-certifying
  at birth. All `at://` URIs, likes, replies and moderation labels reference the
  DID, so **a handle change rewrites zero stored data**. Migration is a 14-step
  but fully specified operation that preserves the DID, every record CID, and
  the follow graph.
- **`did:plc`'s rotation model** is the only deployed answer to "my host went
  rogue": an ordered set of rotation keys in descending authority, distinct from
  the low-value repo signing key that lives on the host; a **72-hour window** in
  which a higher-authority key can fork back over a lower-authority key's
  operations; clobbered ops marked `nullified` and retained in a public audit
  log. Compare Nostr, which has no rotation at all: three attempts at NIP-41
  over 3.5 years, zero convergence, because any migration signal must be signed
  by the key that may already be stolen.

### What to change

Add a stable, key-derived `agent_id` beneath the handle, and make it — not the
handle, not the FQDN — the thing that appears in signed material.

```text
@weather:example.com          handle: mutable, human-facing, leased
        |  WebFinger
        v
agent_id (hash of a genesis operation)   stable, self-certifying, never changes
        |  DID-shaped document: verification methods + service endpoints
        v
https://agents.example.com/agents/weather/a2a
```

Concretely:

- Adopt the DID *shape* — an identifier resolving to a document listing
  verification methods and service endpoints with a documented rotation path —
  and exactly one method. Copy `did:plc`'s structure. Do **not** build a general
  DID resolver and do not take a W3C VC/VP dependency; the formal objections
  from [Google and Mozilla](https://www.w3.org/2022/03/did-fo-report.html) to
  DID Core still stand, and they are about method proliferation with no
  convergence incentive.
- Two key classes, by authority: **rotation keys** (owner-held, can replace the
  signing key, the endpoint, the handle, and the rotation set) and a **signing
  key** (may live on a host; forging messages with it is bad, losing identity to
  it is not possible). The doc's hosted-voice mitigation — "hold an
  owner-controlled signing key the host never possesses" — becomes enforceable
  rather than aspirational once these are separate.
- Cap advertised key validity server-side. Matrix's rule is battle-tested:
  use the lesser of the advertised `valid_until_ts` and 7 days out, so an
  attacker cannot publish a long-lived key with no revocation path.
- Anything with cross-agent lifetime carries `agent_id`, never the handle:
  A2A task references, Agent Request results, audit records, capability grants,
  contact lists, block lists, rate-limit counters. The handle is a display and
  routing label.
- Handles are leases. Publish the lifecycle before anyone registers one: grace
  period, mandatory quarantine before re-issue, no premium auction, and a client
  warning on re-registration. The ENS dropcatching study found **241,283 names**
  cycled through register → expire → re-register, 2,633 transactions sent funds
  to a *new* controller the sender still associated with the old one, and **no
  major wallet warns**. The doc's "handle tombstoned rather than reassigned on
  export" is the same instinct — generalize it to all handles, not just hosted
  exports.

Cost: this is a day-one decision. Every downstream system that keys on a handle
string is unmigratable later. Nothing else in this document is as
irreversible.

---

## 5. Challenge 2: AID does not fit the shared-gateway or hosted profiles

### The mechanical problem

All three DNS proposals put a reserved underscore label **to the left** of the
agent name:

| Spec | Record |
| --- | --- |
| AID | TXT at `_agent.<domain>` — exact-host, clients MUST NOT walk up the hierarchy |
| DNS-AID | SVCB at `agent-name.example.com`, org index at `_index._agents.example.com` |
| DN-ANR | records under an `_agents.` prefix |

DNS wildcards match only at the leftmost label, so `_agent.*.gulls.ai` is not a
valid wildcard. A domain hosting N agents needs N provisioned records, N DNSSEC
signatures, and a provisioning pipeline coupled to agent creation. For
**Seagulls-Hosted Voice** — explicitly the profile for owners without a domain,
and the one that scales to thousands — that is a per-signup DNS write. For
**Shared Domain Gateway** it is a per-agent DNS write on a customer's zone that
the customer, not gulls, operates.

WebFinger has no such problem: one path, unlimited agents, query-string keyed,
servable statically or dynamically.

The doc's own line — "DNS should not enumerate a large population" — is the
same observation, one step short of its conclusion. If DNS should not enumerate
the population, DNS should not be the per-agent resolution mechanism either.

### The adoption problem

AID v2.1.0 has six SDKs, a CLI, a conformance suite, and a workbench. Its
registry has **2 commits, 0 stars, no indexed domains**, and a README stating it
is not yet operational because it needs an internet-scale DNS crawler. The same
organization is running a `.agent` TLD community bid. This is a good spec with
no users, from a project with a TLD interest. That does not make it wrong to
implement — it makes it wrong to depend on.

### What to change

Keep AID, narrow its role, and add one DNS record instead of N.

- **WebFinger is the per-agent path** for every profile. It is already the
  doc's Layer Boundaries answer for human-name resolution; extend it to carry
  the endpoint and Agent Card links directly, so the common case is one HTTPS
  round trip rather than WebFinger → DNS → HTTPS.
- **AID is the single-agent-per-domain path.** `_agent.example.com` describing
  one agent for one domain is exactly what the record shape fits, and it is the
  right answer for `gulls publish --via aid` on an owner's own domain.
- **Publish exactly one org record: DNS-AID's `_index._agents.<domain>`,
  pointing at the WebFinger/registry surface.** One record, unlimited agents,
  no per-agent provisioning, and it buys a seat at the best-funded DNS table
  (LF, Cloudflare, GoDaddy, Infoblox, Amazon, Deutsche Telekom). If DNS-AID
  wins, gulls is discoverable; if it does not, one record was wasted.
- Track **DAN** (`draft-seethiraju-dawn-dan-00`) as the DAWN-track successor to
  watch, since the WG will standardize resolution and has ruled naming out of
  scope.

Also worth aligning with, at zero cost: **WIMSE**
([draft-ietf-wimse-identifier-03](https://datatracker.ietf.org/doc/draft-ietf-wimse-identifier/),
updated 2026-07-06) is a real chartered-WG document whose `wimse://<trust-domain>/<path>`
is structurally identical to `@name:domain`. It brings workload-credential
machinery (attestation, short-lived credentials) that maps onto agents better
than anything agent-native has produced.

---

## 6. Challenge 3: the WebFinger gap has known hazards, not just a missing relation

The doc correctly identifies that no IANA link relation exists for
handle-to-Agent-Card, and correctly calls it the strongest candidate for
upstream standardization. The cheaper win is writing down the rules that a
decade of fediverse CVEs produced. Each is one line and each has a real
exploit behind it.

- **Verify bidirectionally, or ship a CVE.** Handle→identity is controlled by
  whoever holds DNS/HTTPS; identity→handle by whoever holds the keys. Only the
  conjunction proves one party controls both. atproto specifies it — the DID
  document's `alsoKnownAs` must contain the handle, with a literal
  `handle.invalid` sentinel when it does not. Mastodon bolted it on and still
  shipped **CVE-2024-23832** (CVSS 9.4, CWE-346): it "passed down the `id`
  property of the fetched object instead of the queried URL." The rule is now
  [FEP-fe34](https://fediverse.codeberg.page/fep/fep/fe34/): *identifier of an
  object and identifier of its owner MUST have the same origin*.
- **Normalize domains in exactly one place.** **CVE-2023-42451** was
  `domain.delete('/')` instead of `delete_suffix('/')` — owning `mastodon.so`
  and serving WebFinger for `mastodon.so/cial` normalized to `mastodon.social`.
  It works because TLD prefixes overlap.
- **Decide redirects explicitly and write the reason down.** atproto allows them
  "up to a reasonable number of hops"; Nostr's NIP-05 says *"The endpoint MUST
  NOT return any HTTP redirects. Fetchers MUST ignore any HTTP redirects"* to
  block redirect-based domain confusion. Both are defensible; silence is not.
- **CORS is a MUST in RFC 7033 §5** and is the most-violated MUST in the
  fediverse. If any browser client will ever resolve a handle, this bites.
- **`rel` filtering is advisory** (RFC 7033 §4.3) — servers may ignore it, so
  clients must filter locally.
- **Copy Matrix's delegation asymmetry verbatim.** `.well-known` delegation may
  move TLS identity, because the origin already proved control over HTTPS. A
  DNS-based delegation (SRV/TXT) must **not** — the target must present a
  certificate for the *original* name, "because DNS is insecure." This is the
  entire security model of Matrix delegation and it generalizes directly to the
  doc's Accepted Delegation Proofs section.
- **Specify caching numerically.** Matrix's are battle-tested: respect
  `Cache-Control`, default 24h, cap 48h, cache errors ~1h, exponential backoff,
  follow 30x, detect loops. atproto notes that raw **DNS TTLs are too aggressive
  for handle resolution** — do not inherit them.
- **Ship exactly one resolution path, or an explicit precedence rule with a
  dated removal.** Matrix's deprecated `_matrix._tcp` has survived 11 spec
  releases past deprecation, so a conformant 2026 resolver performs up to four
  SRV lookups plus a well-known fetch plus A/AAAA per unknown server. atproto's
  pattern is the good one: two methods, "DNS wins," explicit failure sentinel.
- **Lock the handle grammar now.** Tiny ASCII set, forbid uppercase rather than
  case-fold (Matrix forbids it because IDs get byte-compared), hard byte cap
  (255), and note RFC 7622's warning that PRECIS canonicalization changes with
  Unicode versions — a canonicalization change under a live federation silently
  splits the address space.
- **Add homoglyph checks at registration.** atproto's handle spec names its own
  unsolved examples (`paypa1.com`, `paypal.cc`) and delegates the problem to
  registrars. The [Typosquatting 3.0 study](https://arxiv.org/abs/2411.00352)
  found **37% of legitimate ENS names have at least one typo variant
  registered**. A deliberately weak similarity check that surfaces "handles
  similar to this one" is enough — it only has to make mimicry visible.

---

## 7. Challenge 4: where P2P actually fits now

The legacy [P2P Transport Boundaries](p2p-transport-boundaries.md) was written
against a Gull-owns-everything control plane with a mandatory relay. The
redesign deleted both premises: there is no hub to optimize around, and the
Inbox is now a per-Gull local projection. The P2P question therefore changes
shape rather than going away.

### The finding that frames it

Every P2P messaging system surveyed converged on an always-on, operator-run
component to deliver to an offline peer — not as a compromise, as the shipped
architecture.

| System | The always-on thing they built | Durability contract |
| --- | --- | --- |
| Waku | Store nodes — 9, run by Status | *"SHOULD retain ≥12 hours"* |
| Holepunch / Keet | `blind-peer` + router + push gateway → **Google FCM / Apple APNs** | Priority-tiered eviction |
| Briar | Mailbox: an Android app on a spare device you own, 1:1 only | Last commit 2025-01-02 |
| Nostr | The relay (that is the design) | NIP-11 has **no retention field** |
| Tor / I2P / Yggdrasil / Veilid | Nothing. Offline recipient = dropped packet | — |

I2P's only durable-delivery layer, I2P-Bote, was **archived 2026-01-10**.
Keet's own docs: *"there's no queue of undelivered messages sitting somewhere in
between."*

For gulls, that always-on component already exists and is already named: the
**Shared Domain Gateway**. The doc's line "the gateway may persist and route
messages while an agent is offline" is doing more work than it looks like — it
is the entire store-and-forward tier that every P2P design eventually rebuilds.
Say so explicitly.

### The go/no-go rule

P2P earns its complexity only when all five hold:

1. **Liveness** — both endpoints are online *by construction* at the moment of
   use. If a queue is needed, stop.
2. **Payload** — ≥1 MB or ≥100 ms of latency actually flows over this path. If
   it is control messages, the gateway wins.
3. **Fallback** — the HTTPS/A2A path still works unchanged when P2P fails, with
   no user-visible difference beyond throughput.
4. **Naming** — identity stays `@handle:domain` → `agent_id`, with the key as an
   authenticator underneath rather than the address itself.
5. **Idle cost** — the steady-state cost of an idle agent is **zero**: no
   republish loop, no gossip mesh membership, no re-announce, no keepalive.

Criterion 5 kills most proposals, and an agent network is mostly idle agents.

### Mapped onto the architecture

| Component | Verdict |
| --- | --- |
| Gateway store-and-forward | **Hard no to P2P.** Ordinary infrastructure. Every P2P system rebuilds this and does it worse. |
| Handle / identity | **No.** Keys cannot be names — see §8. |
| Presence, discovery | **No.** IPFS's Kademlia DHT has a **median 33.8 s content-publication latency** (p90 112 s), 45.5% of peers undialable, 87.6% of sessions under 8 hours. "Is this agent reachable now" needs milliseconds. |
| A2A streaming / `SubscribeToTask` between two online Gulls | **Worth it.** This is the one case where liveness is guaranteed by construction. |
| LAN node ↔ local agent | **Worth it** — but for data residency, not decentralization. |
| Large artifacts, context packs | **Worth it** at size, brokered, with HTTPS fallback. |

### If a direct transport is ever built, use iroh

[iroh 1.0 shipped 2026-06-15](https://www.iroh.computer/blog/v1) with a wire-format
stability guarantee. It differs from libp2p in the way that matters: it is
**relay-first** — connect over the relay immediately so the connection always
works, then race a direct path and migrate via QUIC multipath. Hole-punch
failure costs throughput, not availability. libp2p is direct-first, so a failed
punch is a user-visible stall.

The honest NAT numbers, because they decide the ops budget:

- The best public measurement is libp2p's **punchr** campaign (6.25M hole
  punches, Dec 2022–Jan 2023 — and it is still the best data that exists):
  **70% ±7.1% conditional success**, but prerequisite stages fail ~29% of the
  time, giving **≈50% end-to-end**. TCP and QUIC were statistically
  indistinguishable.
- Field reports are worse. A [rust-libp2p discussion](https://github.com/libp2p/rust-libp2p/discussions/5910)
  measured **1–10%** on TCP across three private networks, ~40% with QUIC, and
  **zero successes on symmetric NAT**. Failure is *deterministic per peer*:
  "Never have I ever had a peer fail and then succeed."
- iroh reports **~90% of connections direct, ~95% of bytes direct** **(vendor)**,
  with no published methodology. Holepunch reports ~95% direct **(vendor)**,
  also unpublished, despite collecting exactly that telemetry.

Budget for a permanent relay tier. It is a line item, not an exception path.

### Do not make LAN discovery depend on mDNS

mDNS (RFC 6762) is link-local *by design* — `.local` names are "meaningful only
on the link where they originate." It dies to VLAN separation, Wi-Fi client
isolation, multicast filtering and rate limiting, and container bridges — that
is, to every network a corporate LAN node will actually be on. Cisco Meraki's
documentation is explicit that under client isolation a service on the same VLAN
is still not discoverable.

Use **gateway-mediated LAN pairing** as the contract: both nodes report their
RFC1918 addresses over outbound 443 (which always works), the gateway
introduces them, they attempt direct and fall back. Keep mDNS as a round-trip-
saving optimization for home and dev networks only.
[draft-jimenez-agent-directory-01](https://datatracker.ietf.org/doc/draft-jimenez-agent-directory/)
is the closest existing design worth copying: soft-state registration with TTL,
`POST /ad/r` / `GET /ad/l`, self-description at `/.well-known/ad`, optional
DNS-SD for zero-config local discovery.

### Two ideas worth stealing without adopting any stack

- **The blind-peer pattern** (Holepunch): an always-on replica holding
  *ciphertext plus Merkle proofs* that can serve and notify without ever holding
  keys. It runs fine on ordinary infrastructure, and it is what would let a
  Seagulls Host say "we cannot read your inbox" while keeping durability. It is
  the one real mitigation for the doc's own "the host is inside the trust
  boundary" admission.
- **Signed self-authenticating messages over an untrusted store** (Nostr,
  Hypercore): the store can *withhold* but cannot *forge*. This decouples
  durability from authenticity and turns "why trust the host" from a trust
  argument into a verifiable one.

### The claims to discount

| Claim | Reality |
| --- | --- |
| "Fully P2P, no servers" | Achieved by no system surveyed. hyperdht ships 3 hardcoded bootstrap hosts; Keet's push transits FCM and APNs; iroh's default discovery is a DNS server run by n0; Waku ships 9 Status-run store nodes. |
| Waku's RLN economic spam protection | Deployed against **chain ID 11155111 — Ethereum Sepolia, a testnet.** The stake is worthless. |
| Waku as a transport | Measured: 1,000 nodes carrying 1 KB/s of unique payload move **20.4 KB/s per node**, and discovery alone with **zero messages** costs 7.88 KB/s in — roughly **18 GB/month per node just to remain discoverable**. |
| Nostr "18 million users" | ~21k trusted pubkeys, **~3.7k DAU**. The number counts generated keypairs. |
| Veilid | 0.5.7 ships, but ~346 crate downloads/month, empty official GitHub org, no external audit, and no published benchmarks behind "faster than IPFS and Tor". |

---

## 8. Challenge 5: naming, trust, and abuse

### Petnames are the frame the doc is one step away from

The doc already says the colon form "is a display convention only" and "never
appears on the wire." That is the right instinct and it has a name and a
literature.

[Stiegler's petname systems](https://www.skyhunter.com/marcs/petnames/IntroPetNames.html)
splits naming into three classes with disjoint properties:

| Class | Global | Securely unique | Memorable | Assigned by |
| --- | --- | --- | --- | --- |
| Key / true name | yes | yes | **no** | mathematics |
| Nickname | yes | **no** | yes | the sender |
| Petname | **no** | yes | yes | the receiver |

Stiegler's diagnosis is the load-bearing sentence: **"Mimicry is an emergent
property of the violation of Zooko's triangle."** DNS tries to be both memorable
and globally unique, so lookalikes are inevitable — which is why the homoglyph
problem is unsolved everywhere and why atproto declines to fix it.

The [Spritely treatment](https://files.spritely.institute/papers/petnames.html)
(2025) adds *edge names* — names supplied within another entity's namespace,
composed into paths — and renders DNS as just another naming authority
(`dns ⇒ paypal.com`), on equal footing with any other. A phishing domain then
appears next to your petname instead of impersonating it.

This matters more for agents than for people, because **agents are introduced by
other agents far more often than they are typed in by a human**. That
introduction edge is exactly the provenance the doc's threat model already wants
("provenance labels that survive relay") and that DNS throws away.

Concretely, three slots per peer in the local contact projection:

- `agent_id` — self-certifying, immutable, what every security decision keys on.
- `suggested_name` — the handle as claimed by the sender or the gateway. Always
  rendered as untrusted: quoted, greyed, never bare.
- `petname` — local, owner-assigned, unique within this Gull's namespace,
  auto-proposed from the introduction edge ("`@travel-bot`'s weather agent"),
  confirmed explicitly only when authority is first granted.

Store and render the introduction edge. Any UI that shows
`@weather:example.com` as bare trusted text has already lost.

### First contact should be recipient-scoped, not IP-scoped

Per-IP limiting is close to useless: a typical IPv6 allocation is a /64, often a
/56 or /48, so an attacker rotates freely; Cloudflare limits at /64 and that
still leaves 256+ ranges. Conversely CGNAT means one IPv4 address can front tens
of thousands of legitimate users, so IP *blocking* over-punishes.

The scarce resource is a specific recipient's attention. Budget:

- per (sender, recipient) first-contact attempts, and
- **per sender: distinct never-accepted recipients per day**, decaying with the
  sender's historical acceptance rate.

That second counter is what catches spray attacks and is invisible to IP
rotation. Aggregate IP as a weak prior only, at /64 → /56 → /48 with escalating
thresholds.

Do not ship proof-of-work stamps. [Laurie & Clayton](https://www.cl.cam.ac.uk/~rnc1/proofwork2.pdf)
killed the idea analytically in 2004: legitimate senders average ~60 messages/day
while suppressing spam needs a cap around 250–2,000/day — 4–8× headroom where
orders of magnitude are needed — and measured at peak hour a daily-rate scheme
blocks **13% of legitimate customers**. Agent send rates are far more
heterogeneous than human ones, so it is worse here. Do not ship transitive
web-of-trust either; PGP's is the canonical failure, and the 2019 SKS keyserver
poisoning ended the keyserver network.

### Permissionless join with per-origin quota

The best deployed middle path is the Bluesky relay's defaults: **auto-admit new
hosts, sandbox them hard**. `default-account-limit=100` accounts per new host,
`new-hosts-per-day-limit=50` network-wide, a trusted-domains list, a
`disable-request-crawl` kill switch, and manual quota raises. That maps almost
exactly onto Seagulls Host admitting Gulls, and onto LAN nodes.

### The policy chokepoint is right; make the verdict a signed object

"There is exactly one enforcement point per voice" is the correct architecture
and it matches where Matrix landed after ten years. Two details from
[MSC4284 Policy Servers](https://matrix.org/blog/2025/04/introducing-policy-servers/)
(merged, stable in Matrix v1.18, 2026-03-26) are worth copying verbatim:

- **Sign before send, not check on receipt.** The sender's server gets the
  event signed by the policy server; receivers verify the signature against
  known state. Verification is O(1) and transitive. Check-on-receipt was
  rejected because it gives non-deterministic results across servers and scales
  O(n) in membership.
- **A policy authority must not be able to block its own removal**, and
  implementations **fail open** when it is unreachable, because "a room's policy
  server is a natural Denial of Service target."

For gulls the equivalent is: a Gull's policy verdict is a signed object —
`{policy_id, verdict, reason_code, evidence_refs, timestamp}` — attached to the
interaction rather than an invisible inline filter. That is what makes local
enforcement auditable by the owner and, later, subscribable by a peer.

### Delegation needs capabilities, not ACLs

Agent Request is delegation across administrative boundaries, multi-hop and
dynamic. An ACL requires the resource owner to enumerate every future delegate
in advance, which is impossible. [Capability Myths Demolished](https://papers.agoric.com/assets/pdf/papers/capability-myths-demolished.pdf)
is the canonical argument: ACLs separate designation from authority, and the
confused deputy arises precisely from that separation.

An LLM agent is the archetypal confused deputy — it holds ambient authority from
its principal and accepts designations from untrusted text. The ACL check
passes, because the agent really is authorized.

- Use public-key-signed capability tokens (Biscuit or UCAN shaped), **not**
  macaroons — macaroon verification requires the root secret, so a peer Gull
  cannot verify them.
- Carry RFC 8693 `act`-style nesting so the on-behalf-of chain is legible.
  RFC 8693's distinction matters: *impersonation* makes A indistinguishable from
  B; *delegation* keeps A's own identity. For agents, delegation is almost
  always the correct semantic.
- **Scope may only narrow, never widen, at every hop.** Bound chain depth.
  Bind the token to the specific invocation, not just a scope string.
- No ambient authority: an agent's session credential must not by itself
  authorize anything on another agent's behalf.

### The threat the doc names as primary, sharpened

"The whole purpose of a Gull is to pipe attacker-influenced text into a local
runtime that holds tools and credentials" is exactly right. Three refinements:

- **A signed message is not a trusted message.** A signature proves origin, not
  intent, and the origin may itself be hijacked. The
  [ARC-to-Historic draft](https://datatracker.ietf.org/doc/draft-ietf-dmarc-arc-to-historic/)
  (2026-04-22) states the general law as plainly as it will ever be stated:
  cryptographic verification alone does not establish trust, and a signature
  chain with no reputation model is not an authorization system.
- **Envelope and body are different trust planes.** Envelope — sender
  `agent_id`, capability chain, policy verdict — is authenticated and may drive
  control flow. Body is data and may never be interpreted as instruction.
  Enforce it in the type system, not by convention.
- **Context refs are simultaneously the injection ingress and the exfiltration
  egress.** EchoLeak is the proof. Simon Willison's
  [lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) —
  private data access + untrusted content + external communication — is the
  invariant to enforce: an agent holding private-data capabilities must not
  simultaneously accept untrusted inbound content and hold outbound
  communication capability without a human gate or a strict egress allowlist.
  Never fetch a sender-supplied URL on the recipient side.

The relevant published threat model is now
[OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
(2025-12-09). Four items map directly onto this architecture: identity and
privilege abuse (fake agents impersonating trusted services; delegated chains
passing full privilege sets), insecure inter-agent communication (descriptor
poisoning — fake endpoints intercepting data), agentic supply chain
(typosquatting, agent-in-the-middle), and memory/context poisoning.

### One precedent worth reading as a warning

**Moltbook** launched 2026-01-28 and grew to a claimed 1.6M agents. Identity was
an owner posting a claim on X, then the platform issuing an API key, with no
robust verification. On **2026-01-31** an unsecured database let anyone
commandeer any agent on the platform; the site went offline and force-rotated
every key. Bearer-token identity plus centralized issuance means one database
misconfiguration compromises every handle on the network. Per-agent keypairs
with JWS-signed A2A cards — which the doc already specifies — are the structural
fix, so this is confirmation rather than a change.

---

## 9. Comparison of the candidate mechanisms

| Mechanism | Name → endpoint | What authenticates it | Many agents per domain | Maturity, Jul 2026 | Fit for `@handle:domain` |
| --- | --- | --- | --- | --- | --- |
| **WebFinger (RFC 7033)** | `acct:` URI → JRD `links[]` | HTTPS origin only | **Yes**, one path | Decade of fediverse deployment; no agent-native adopter | **Best.** Needs a private link relation and the §6 rules |
| **A2A Agent Card** | n/a — describes, does not locate | JWS-signed cards, OAuth2/mTLS/OIDC | No — one card per domain | Production; LF; 150+ orgs | Yes, as the payload a resolver returns |
| **AID v2.1.0** | `_agent.<domain>` TXT, exact host | DNSSEC + TLS, optional `k=` pubkey | **No** (underscore label, no wildcard) | Spec + 6 SDKs; registry unbuilt **(thin)** | Single-agent domains only |
| **DNS-AID** | SVCB per agent; `_index._agents.` org record | DNSSEC + optional DANE; `cap-sha256` | Per-agent records only | LF project 2026-05-27; IETF draft | **Org index record only** |
| **DAN (DAWN track)** | DNS-based agent naming | TBD | TBD | `draft-seethiraju-dawn-dan-00`, 2026-06-05 | Watch |
| **did:plc-style ID** | agent_id → document → endpoints | Genesis-op hash + rotation key hierarchy | Yes | Deployed at Bluesky scale | **Adopt the shape** as the layer under the handle |
| **did:web** | domain → `/.well-known/did.json` | Whoever controls the web server | Hostname only, no paths | Widely specified, structurally fragile | **Trap** — no rotation, no recovery, domain embedded |
| **AGNTCY / OASF ADS** | capability → Kademlia DHT → content-addressed record | Sigstore provenance | Yes | Real code, `ads.outshift.io`, LF | Capability search backend, never a resolver |
| **ERC-8004** | tokenId → `agentURI` → cards/endpoints | On-chain registries | Yes | **0.67% of registered agents have service records** | Optional attestation anchor at most |
| **libp2p / DHT** | PeerID → DHT lookup | Self-certifying PeerID | n/a | 33.8 s median publish; ~3.8k reachable peers | **No** |
| **iroh** | EndpointId → DNS (pkarr) or relay | Ed25519 endpoint key | n/a | 1.0, wire-stable, 2026-06-15 | Transport for streaming/artifacts only |

---

## 10. Recommended edits to the authoritative doc

Ordered by cost of getting them wrong.

1. **Insert an identity layer between handle and endpoint.** Add `agent_id`
   (hash of a genesis operation) plus rotation-key/signing-key separation to
   §Resolution and to the resolution bundle. Make it the identifier carried in
   audit records, capability grants, A2A task references and contact lists.
   *Irreversible if deferred.*
2. **Demote AID from "the deployable mechanism today" to "the single-agent
   profile,"** make WebFinger the per-agent path for all three publication
   profiles, and add one `_index._agents.<domain>` record. Update the Shared
   Domain Gateway and Seagulls-Hosted Voice sections accordingly.
3. **Expand §Resolution with the WebFinger implementation rules** from §6 above:
   bidirectional verification with a failure sentinel, single-place domain
   normalization, explicit redirect policy, CORS, local `rel` filtering,
   Matrix's delegation-vs-TLS asymmetry, numeric caching, one resolution path,
   locked grammar, homoglyph check at registration.
4. **State that the Shared Domain Gateway is the store-and-forward tier**, and
   record the blind-peer pattern (ciphertext + Merkle proofs) as the intended
   mitigation for "the host is inside the trust boundary."
5. **Replace [P2P Transport Boundaries](p2p-transport-boundaries.md)** with the
   five go/no-go criteria in §7 and the component table. Its premise — a
   mandatory relay control plane to optimize around — no longer exists.
6. **Add the petname three-slot model** to the local projection contract, with
   the introduction edge stored and rendered, and a rule that a bare handle is
   never rendered as trusted text.
7. **Make the policy verdict a signed object**, and adopt sign-before-send,
   fail-open, and cannot-block-its-own-removal from MSC4284.
8. **Specify first-contact budgets as recipient-scoped**, with IP as a weak
   /64→/56→/48 prior, and per-origin quotas for admitting new Gulls or LAN
   nodes.
9. **Specify the capability-token shape** for Agent Request delegation:
   public-key signed, attenuation-only, invocation-bound, bounded depth, RFC
   8693 `act` nesting, no ambient authority.
10. **Add a handle lifecycle**: leases, grace period, quarantine before
    re-issue, client warning on re-registration, tombstoning generalized beyond
    hosted export.
11. **Add a deletion posture** to the threat model. Every federated system that
    deferred this found it unimplementable later: Mastodon's `Delete` is
    best-effort-once with a 7-day permanent-writeoff threshold; Matrix redaction
    is not deletion; atproto's PLC log is append-only and public forever. Pick
    "content-addressed and encrypted under revocable keys" or an explicit "we
    cannot delete," in v0.

---

## 11. What to watch

- **IETF 126 minutes for `dawn` and `agentproto`** — the group page exists but
  the BOF minutes had not posted as of 2026-07-26. Confirm chartering, and read
  DAN (`draft-seethiraju-dawn-dan-00`) against §5.
- **Whether GoDaddy folds its commercial Agent Name Service into LF DNS-AID.**
  It is a founding member of both, and that would consolidate the DNS-plus-PKI
  story considerably.
- **A2A [Discussion #741](https://github.com/a2aproject/A2A/discussions/741)** —
  the registry fork between "federation of catalogs" and "federation of peers."
  gulls has already picked the peers branch by construction; if the catalog
  branch wins, that is a compatibility question.
- **DKIM2** (`draft-ietf-dkim-dkim2-spec-04`, 2026-07-05): per-hop signatures
  with the envelope inside the signed material and "recipes" proving what each
  intermediary changed. That is precisely the doc's "provenance labels that
  survive relay," being standardized right now.
- **WIMSE** identifier and workload-credential drafts, as the credible standards
  home for non-human principal identity.

---

## 12. Two lines worth keeping

> "Not investing enough in trust & safety. It was always seen as 'well, that'd
> be a good problem to have, let's fix it when we get there'. I can literally
> remember the ~2014 vintage conversations of saying 'what are we going to do
> about spam' and everyone shrugging."
> — Matthew Hodgson, [Matrix fails & successes](https://gist.github.com/ara4n/8422ae8eae68a8993a5e831691b441f8)

> "We sacrificed properties of the magical mesh to hit the performance needs,
> and we broke from the history of federation to get the guarantees we wanted."
> — Paul Frazee, [Practical Decentralization](https://www.pfrazee.com/blog/practical-decentralization)

And the corollary neither of them says outright: **a hub is not a design
failure, it is the equilibrium.** matrix.org carries ~40% of Matrix traffic; one
Nostr relay holds 73% of posts; Bluesky made self-hosting cost $34/month and
99.99% of users still run on Bluesky-operated infrastructure; Gmail is the
governance layer for email. Seagulls Host will be the hub. Design its privileged
role explicitly with a credible escape hatch — which is what the Console/Host
role split already starts doing — rather than discovering it in year four.

---

## 13. Sources

**Agent-native standards**

- [A2A specification](https://a2a-protocol.org/latest/specification/) ·
  [releases](https://github.com/a2aproject/A2A/releases) ·
  [agent discovery topic](https://github.com/a2aproject/A2A/blob/main/docs/topics/agent-discovery.md) ·
  [registry discussion #741](https://github.com/a2aproject/A2A/discussions/741)
- [LF A2A one-year press release](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year)
- [AID specification](https://aid.agentcommunity.org/docs/specification) ·
  [aid-registry](https://github.com/agentcommunity/aid-registry)
- [draft-mozleywilliams-dnsop-dnsaid](https://datatracker.ietf.org/doc/draft-mozleywilliams-dnsop-dnsaid/) ·
  [LF DNS-AID announcement](https://www.linuxfoundation.org/press/linux-foundation-announces-dns-aid-project-to-advance-decentralized-ai-agent-discovery)
- [IETF DAWN group](https://datatracker.ietf.org/wg/dawn/documents/) ·
  [draft-king-dawn-requirements-01](https://www.ietf.org/archive/id/draft-king-dawn-requirements-01.html) ·
  [draft-jimenez-dawn-discovery-landscape-00](https://datatracker.ietf.org/doc/html/draft-jimenez-dawn-discovery-landscape-00) ·
  [IETF 126 BOFs](https://www.ietf.org/blog/ietf126-bofs/)
- [draft-rosenberg-aiproto-framework-00](https://datatracker.ietf.org/doc/html/draft-rosenberg-aiproto-framework-00) ·
  [draft-jimenez-agent-directory](https://datatracker.ietf.org/doc/draft-jimenez-agent-directory/) ·
  [draft-narvaneni-agent-uri-03](https://www.ietf.org/archive/id/draft-narvaneni-agent-uri-03.html) ·
  [draft-prakash-aip](https://datatracker.ietf.org/doc/draft-prakash-aip/) ·
  [draft-klrc-aiagent-auth](https://datatracker.ietf.org/doc/draft-klrc-aiagent-auth/)
- [MCP registry](https://modelcontextprotocol.io/registry/about) ·
  [MCP 2026-07-28 release candidate](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)
- [OWASP ANS v1.0](https://genai.owasp.org/resource/agent-name-service-ans-for-secure-al-agent-discovery-v1-0/) ·
  [NANDA / AgentFacts](https://arxiv.org/abs/2507.14263) ·
  [AGNTCY ADS](https://arxiv.org/abs/2509.18787) ·
  [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004) ·
  [ERC-8004 mainnet study](https://arxiv.org/html/2606.12128v1)
- [draft-ietf-wimse-identifier](https://datatracker.ietf.org/doc/draft-ietf-wimse-identifier/) ·
  [WIMSE charter](https://datatracker.ietf.org/doc/charter-ietf-wimse/)

**Federated naming in production**

- Matrix: [server name resolution](https://spec.matrix.org/latest/server-server-api/#resolving-server-names) ·
  [routing appendix](https://spec.matrix.org/latest/appendices/#routing) ·
  [MSC4284 policy servers](https://matrix.org/blog/2025/04/introducing-policy-servers/) ·
  [MSC4014 pseudonymous identities](https://github.com/matrix-org/matrix-spec-proposals/blob/kegan/pseudo-ids/proposals/4014-pseudonymous-identities.md) ·
  [Hodgson, fails & successes](https://gist.github.com/ara4n/8422ae8eae68a8993a5e831691b441f8)
- ActivityPub / WebFinger: [RFC 7033](https://www.rfc-editor.org/rfc/rfc7033.html) ·
  [RFC 7565 acct:](https://www.rfc-editor.org/rfc/rfc7565.html) ·
  [FEP-fe34](https://fediverse.codeberg.page/fep/fep/fe34/) ·
  [CVE-2024-23832](https://github.com/mastodon/mastodon/security/advisories/GHSA-3fjr-858r-92rw) ·
  [CVE-2023-42451 writeup](https://scumjr.github.io/2023/11/07/usurping-mastodon-instances-cve-2023-42451/) ·
  [Mastodon moving docs](https://docs.joinmastodon.org/user/moving/)
- AT Protocol: [handle spec](https://atproto.com/specs/handle) ·
  [DID spec](https://atproto.com/specs/did) ·
  [did:plc method](https://github.com/did-method-plc/did-method-plc) ·
  [account migration](https://atproto.com/guides/account-migration) ·
  [Frazee, Practical Decentralization](https://www.pfrazee.com/blog/practical-decentralization)
- Nostr: [NIP-05](https://github.com/nostr-protocol/nips/blob/master/05.md) ·
  [NIP-65](https://github.com/nostr-protocol/nips/blob/master/65.md) ·
  [fiatjaf, Nostr is not decentralized](https://fiatjaf.com/87a208d9.html)
- Email / XMPP: [RFC 5321](https://www.rfc-editor.org/rfc/rfc5321.html) ·
  [RFC 8461 MTA-STS](https://www.rfc-editor.org/rfc/rfc8461.html) ·
  [draft-ietf-dkim-dkim2-spec](https://datatracker.ietf.org/doc/draft-ietf-dkim-dkim2-spec/) ·
  [draft-ietf-dmarc-arc-to-historic](https://datatracker.ietf.org/doc/draft-ietf-dmarc-arc-to-historic/) ·
  [XEP-0220 dialback](https://xmpp.org/extensions/xep-0220.html) ·
  [Moxie, The ecosystem is moving](https://signal.org/blog/the-ecosystem-is-moving/) ·
  [Gultsch, An objection](https://gultsch.de/objection.html)

**P2P**

- [libp2p kad-dht spec](https://github.com/libp2p/specs/blob/master/kad-dht/README.md) ·
  [IPFS measurement, SIGCOMM 2022](https://arxiv.org/pdf/2208.05877) ·
  [punchr hole-punching study](https://arxiv.org/html/2510.27500v1) ·
  [rust-libp2p field reports](https://github.com/libp2p/rust-libp2p/discussions/5910) ·
  [probelab IPFS metrics](https://probelab.io/ipfs/)
- [iroh 1.0](https://www.iroh.computer/blog/v1) ·
  [iroh discovery](https://docs.iroh.computer/concepts/discovery)
- [Waku benchmarks](https://docs.waku.org/learn/research/benchmarks/test-results-summary) ·
  [Waku store RFC](https://lip.logos.co/messaging/core/draft/64/network.html)
- [Holepunch blind-push](https://github.com/holepunchto/blind-push) ·
  [Keet blind peering](https://support.keet.io/security-and-privacy/blind-peering/)
- [RFC 6762 mDNS](https://www.rfc-editor.org/rfc/rfc6762.html) ·
  [RFC 6763 DNS-SD](https://www.rfc-editor.org/rfc/rfc6763.html) ·
  [Meraki Bonjour forwarding](https://documentation.meraki.com/MR/Client_Addressing_and_Bridging/Bonjour_Forwarding)
- [BEP44 mutable items](https://www.bittorrent.org/beps/bep_0044.html) ·
  [pkarr](https://github.com/pubky/pkarr) ·
  [Content censorship in IPFS, NDSS 2024](https://arxiv.org/abs/2307.12212) ·
  [Tor onion address encoding](https://spec.torproject.org/rend-spec/encoding-onion-addresses.html)

**Naming theory, trust, abuse**

- [Zooko's triangle](https://www.cs.princeton.edu/courses/archive/spr17/cos518/papers/zooko-triangle.pdf) ·
  [Stiegler, Petname Systems](https://www.skyhunter.com/marcs/petnames/IntroPetNames.html) ·
  [Spritely, Petnames](https://files.spritely.institute/papers/petnames.html)
- [SFS, SOSP '99](https://pdos.csail.mit.edu/papers/sfs:sosp99.pdf) ·
  [W3C DID formal objections](https://www.w3.org/2022/03/did-fo-report.html)
- [Capability Myths Demolished](https://papers.agoric.com/assets/pdf/papers/capability-myths-demolished.pdf) ·
  [Macaroons](https://theory.stanford.edu/~ataly/Papers/macaroons.pdf) ·
  [Biscuit](https://www.biscuitsec.org/) ·
  [UCAN](https://ucan.xyz/specification/) ·
  [RFC 8693 token exchange](https://www.rfc-editor.org/rfc/rfc8693.html) ·
  [SPIFFE](https://spiffe.io/docs/latest/spiffe-about/overview/)
- [Douceur, The Sybil Attack](https://www.freehaven.net/anonbib/cache/sybil.pdf) ·
  [Laurie & Clayton, Proof-of-Work Proves Not to Work](https://www.cl.cam.ac.uk/~rnc1/proofwork2.pdf) ·
  [Signal, keeping spam off Signal](https://signal.org/blog/keeping-spam-off-signal/) ·
  [IPv6 rate limiting](https://adam-p.ca/blog/2022/02/ipv6-rate-limiting/)
- [Typosquatting 3.0 (ENS)](https://arxiv.org/abs/2411.00352) ·
  [Panning for gold.eth, IMC 2024](https://www.securitee.org/files/ens_domains_imc2024.pdf)
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) ·
  [CVE-2025-32711 EchoLeak](https://nvd.nist.gov/vuln/detail/CVE-2025-32711) ·
  [The lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) ·
  [AI Identity: standards and gaps](https://arxiv.org/pdf/2604.23280) ·
  [Moltbook](https://en.wikipedia.org/wiki/Moltbook)
