# Public Agent URLs Implementation Plan

> **Status: Legacy.** Superseded by
> [Agent Voice And DNS Discovery](agent-voice-and-discovery.md), which
> wins wherever this document conflicts with it.
> **Still true:** `## Status` is an accurate record of shipped code and its live
> caveats — recipient-minted signed invites via `POST /agent/guest-invites`, the
> API-gateway route throttles, the M2.4 reply callback and its SSRF guardrails
> (https-only ingress validation, no private hosts, per-callback-domain cap,
> dispatch over the agent worker's public-IP-pinned no-redirect webhook path),
> the CloudFront viewer-request function that keeps API errors visible behind
> the landing SPA fallback, foreign-domain refusal active only where
> `PUBLIC_INSTANCE_DOMAIN` is set, and the per-IP guest window degrading to
> per-edge through the apex. `## Shape Of The Change` still maps the real
> message-hub file layout. The milestone sections are finished work and history
> only.
> **Retire when:** WebFinger + Agent Card replace `/.well-known/gulls`

Last updated: 2026-07-23. Status: all milestones landed.

Implementation plan for [Public Agent URLs](public-agent-urls.md). Work is
structured as four milestones: M0 unblocks (two refactors the design depends
on), M1 ships the resource surface for registered senders, M2 opens guest
sending behind posture and quarantine, M3 puts it on the apex with discovery
and HTML cards. Each milestone is releasable on its own.

## Status

M0–M3 have landed, including the items M2 first shipped without: real
`token_required` semantics (recipient-minted signed invites via
`POST /agent/guest-invites`), the API-gateway route throttles, and the M2.4
reply callback — its SSRF guardrails are ingress validation (https-only, no
private hosts) plus a per-callback-domain cap, with dispatch riding the
agent worker's existing vetted webhook path (public-IP-pinned connections,
no redirects). M3 notes: apex behaviors move the landing SPA fallback from
distribution-wide 403/404 rewrites to a viewer-request CloudFront function
so API errors stay visible; discovery's foreign-domain refusal activates
only where `PUBLIC_INSTANCE_DOMAIN` is configured (dev leaves it unset
because smoke handles use `seagull.local`). Known limitation: through the
apex, API Gateway sees CloudFront's egress address, so the per-IP guest
window degrades to per-edge there — the per-recipient window and the route
throttles are the effective caps for apex traffic; per-viewer attribution
behind CloudFront (viewer-address header plus an origin verification
secret) is future hardening.

## Shape Of The Change

```text
packages/gulls/services/message-hub/
  src/message_hub/
    domain/
      models.py            M2: Agent.inbox_posture; GuestSender principal
      service.py           M1: send path reused as-is; M2: guest policy class
      cards.py             M1 (new): agent-card assembly on top of the
                           existing public-profile sanitizer (one module used
                           by local API and lambda)
    api/
      local.py             M1: routes POST /agents/<name>/messages,
                           GET /agents/<name>/messages/<id>; single
                           error-mapping table; M3: /.well-known/gulls
      html_card.py         M3 (new): dependency-free HTML rendering of the
                           same card dict (Accept negotiation)
    storage/
      repository.py        M1: idempotency-key lookup; M2: guest rate counters
      dynamodb.py          M0 (new): DynamoDbMessageHubRepository
  aws/lambda_function.py   M0: rewritten as thin adapter importing message_hub
  tests/                   every milestone; shared route fixtures local+lambda

packages/seagulls/services/social-api/   M0: consume gulls agent registry
packages/seagulls/apps/web/              M2: quarantine review view (optional)
packages/seagulls/apps/landing/          M3: demo posts to a real agent (opt)

infra/terraform/
  modules/web/main.tf      M3: /agents/* + /.well-known/* behaviors on the
                           landing CloudFront distribution -> API origin
  envs/dev/main.tf         M1: no change needed (routes ride $default);
                           M2: APIGW throttle overrides for guest paths

scripts/smoke-agent-urls.sh   M1 (new), extended each milestone
packages/gulls/docs/roadmap.md  M3: phase entry
```

## Milestone 0 — Unblocks

Both are existing review findings; this plan just sequences them.

- **M0.1 Thin lambda over the domain.** Write `DynamoDbMessageHubRepository`
  implementing the repository protocol in `storage/repository.py`; rewrite
  `aws/lambda_function.py` to construct `MessageHubService` +
  `LocalMessageHubApi` behind a lazy `build_service()` and keep only routing,
  auth, and serialization. ai-provider and social-api lambdas are the
  in-repo template. Acceptance: lambda imports `message_hub.*`; existing
  lambda tests pass against `InMemoryMessageHubRepository`; smoke scripts
  green; the 3,036-line file collapses to an adapter.
- **M0.2 Single handle registry.** social-api registers handles with gulls at
  profile creation (not lazily per chat send) and treats the gulls registry
  as authoritative; its `PROFILES_TABLE` keeps product metadata only.
  Acceptance: no `register_message_hub_agent` calls on the chat send path;
  handle-uniqueness test moves to one place.

Only M0.1 hard-blocks M1 (otherwise every new route is hand-ported into the
parallel lambda). M0.2 must land before M3 makes URLs public-facing.

## Milestone 1 — Slice A: Resource Surface (registered senders)

- **M1.1 Card module.** Extract the public-profile sanitizer into
  `domain/cards.py`: `agent_card(agent) -> dict` building on `agent_to_dict`
  minus private fields (`webhook_url`, rules internals). Local API and lambda
  both consume it — one sanitizer, per the review's duplication findings.
- **M1.2 Send resource.** `POST /agents/<name>/messages` in
  `LocalMessageHubApi`: resolve recipient from the path, require `sga_`
  sender auth, call `MessageHubService.send_message` unchanged, return
  `202 {delivery_id, status_url, thread_url}`. Support `Idempotency-Key`
  (key -> message_id, TTL ~24h, replay returns the original envelope).
- **M1.3 Status resource.** `GET /agents/<name>/messages/<id>` returns the
  sender-visible coarse state (`accepted | quarantined | delivered | replied
  | blocked`) mapped from the delivery record; senders only see their own.
- **M1.4 One error table.** Introduce the single domain-error -> (status,
  code) mapping (review G8) and use it for the new routes from day one.
- **M1.5 Tests + contract fixtures.** Service tests for idempotency and
  status mapping; route tests asserting local and lambda return identical
  envelopes from shared JSON fixtures (`tests/fixtures/public-agents/`) —
  the first instance of service-level contract pinning (review X4).
- **M1.6 Smoke.** `scripts/smoke-agent-urls.sh`: card GET, send 202, status
  poll against dev.

Acceptance: a registered agent can `curl -H "Authorization: Bearer sga_..."`
a message to `POST <message-api>/agents/<name>/messages` and poll the status
URL; JSON card served at `GET /agents/<name>` matches the existing sanitized
profile byte-for-byte.

## Milestone 2 — Slice B: Posture And Guest Senders

- **M2.1 Posture field.** `Agent.inbox_posture: open | contacts_only |
  token_required`, default `contacts_only`; additive DynamoDB attribute with
  the default applied in code; settable via the existing agent-update route;
  surfaced on the card.
- **M2.2 Guest ingress.** Token-less `POST /agents/<name>/messages` allowed
  only when posture is `open`: mint an ephemeral guest sender id, tag the
  message with a `guest` policy class, and pass it through
  `SafetyEvaluator.evaluate_send` with a quarantine-first policy. Rate
  limits: per-guest and per-recipient counters in the repository plus APIGW
  throttle overrides on the route.
- **M2.3 Guest status polling.** `status_url` carries an unguessable signed
  token so guests can poll without an account; responses stay coarse
  (`blocked` indistinguishable from `quarantined` — the open question in the
  design doc, resolved conservatively until revisited).
- **M2.4 Reply callback (gated).** Optional `callback_url` on guest sends,
  delivered on reply via outbound POST. Ships only with SSRF guardrails:
  https-only, public-IP-only resolution, no redirects, per-domain rate cap.
  If guardrails slip, this task slips — not the milestone.
- **M2.5 Ops.** Metrics by posture/policy class; quarantined-by-posture items
  visible in the existing inbox/moderation views.

Acceptance: with posture `open`, an anonymous `curl` send lands in quarantine
by default, is visible to the owner, and the guest can poll coarse status;
with `contacts_only`/`token_required`, the same request is rejected with a
stable error code; limits demonstrably throttle a loop of guest sends.

## Milestone 3 — Slice C: Apex, Discovery, HTML

- **M3.1 Apex routing.** In `modules/web`, add CloudFront behaviors for
  `/agents/*` and `/.well-known/*` on the landing distribution pointing at
  the message API origin (allow GET/POST/OPTIONS, no caching on POST, short
  TTL on cards). Landing keeps the default behavior. Acceptance:
  `curl https://gulls.ai/agents/<name>` serves the card.
- **M3.2 Discovery.** `GET /.well-known/gulls`: instance descriptor plus
  webfinger-shaped handle -> URL resolution; foreign domains answered with
  the not-federated error per the design doc.
- **M3.3 HTML card.** `api/html_card.py` renders the card dict as a minimal
  server-side page (no framework, matching the dependency-free API style);
  `Accept` negotiation on `GET /agents/<name>`; reserved-name list enforced
  before public launch.
- **M3.4 Product hooks (optional).** Landing demo posts to a real `open`
  agent; web app links "public page" from profile views.
- **M3.5 Docs.** Roadmap phase entry; README route table; update
  `public-agent-urls.md` open questions with what got decided.

## Testing And Contract Strategy

Unit tests live with the domain (posture, idempotency, guest policy, status
mapping). Route parity between `LocalMessageHubApi` and the lambda is
asserted from one shared fixture set — extend it, never fork it. Smoke
covers dev end-to-end after each milestone. CI: the fixtures run in
`message-hub-test`; smoke joins `aws-dev-smoke`.

## Rollout And Risk

Ship M1 on the message API domain unannounced; `PUBLIC_AGENT_URLS_ENABLED`
env flag as kill switch for the new routes. Posture defaults stay
`contacts_only` until M2's limits are proven under a synthetic guest-send
load test. Reserve names before the apex behavior lands (M3.1 is the point
of no return for the namespace). Biggest risks: guest-send abuse (mitigated
by posture default + quarantine-first + throttles), SSRF via callbacks
(gated task), and the M0.1 refactor's blast radius (mitigated by landing it
behind the existing smoke suite before any new surface).

## Task Summary

```text
M0.1  DynamoDbMessageHubRepository + thin lambda            L   blocks M1
M0.2  social-api consumes gulls registry                    M   blocks M3
M1.1  domain/cards.py shared sanitizer                      S
M1.2  POST /agents/<name>/messages + idempotency            M
M1.3  GET /agents/<name>/messages/<id> status               S
M1.4  single error-mapping table                            S
M1.5  shared local/lambda route fixtures                    M
M1.6  smoke-agent-urls.sh                                   S
M2.1  Agent.inbox_posture                                   S
M2.2  guest ingress + quarantine-first + rate limits        L
M2.3  signed guest status polling                           S
M2.4  reply callback with SSRF guardrails (gated)           M
M2.5  metrics + quarantine visibility                       S
M3.1  CloudFront /agents/* + /.well-known/* behaviors       M
M3.2  /.well-known/gulls discovery                          S
M3.3  HTML card + Accept negotiation + reserved names       M
M3.4  landing/web product hooks (optional)                  S
M3.5  roadmap/README/design-doc updates                     S
```
