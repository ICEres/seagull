# Safety Gateway

> **Status: Legacy.** Superseded by
> [Agent Voice And DNS Discovery](../../docs/agent-voice-and-discovery.md), which
> wins wherever this document conflicts with it.
> **Still true:** the service described below is deployed and still the
> chokepoint every agent-originated message passes. The module layout, the
> deterministic evaluator, the six decision outcomes, the DynamoDB safety audit
> repository, the `MessageHubService` adapter, and the `make safety-gateway-test`
> / `make safety-gateway-build` targets are all current.
> **Retire when:** the **Split** verdict in the
> [Code Disposition Register](../../docs/migration-plan.md#code-disposition-register)
> lands — per-Gull policy enforced at the Gull edge, provider policy in the
> Seagulls Host — and no caller reaches a central gateway.

The safety gateway is the deployed central policy and trust layer. Under the
accepted redesign it does not stay central, and it does not stay one service.

## Where Policy Lives After The Split

The redesign moves the enforcement point rather than removing enforcement.
**Each Gull is the enforcement point for its own voice**, and there is exactly
one per voice:

| Concern | After the split | Owner |
| --- | --- | --- |
| One owner's inbound and outbound policy, approval posture, quarantine of unknown contact | Compiled and enforced locally at the Gull edge, before an interaction reaches the private runtime | `gulls`, using [`packages/policy`](../../packages/policy/README.md) |
| Provider policy over the Gulls a host serves, plus human review, moderation, and audit UX | The Seagulls Host | `packages/seagulls` |

Two consequences are easy to get wrong:

- **Distributing policy to the edge removes the central gateway; it must not
  remove the chokepoint.** No path from a Gull's A2A endpoint to a runtime
  connector may skip policy evaluation.
- **Pet posture and Agent Request approval requirements are policy inputs, not
  independent gates.** A Gull compiles them into local enforcement; when inputs
  conflict, local policy wins and fails closed.

A Gull that selected no Seagulls Host still enforces the first row. A Gull that
selected a Host is subject to both, and the Host's policy applies only to the
Gulls that chose it.

## What The Service Does Today

Current MVP implementation:

```text
src/safety_gateway/
  api/local.py          dependency-free local policy API adapter
  domain/models.py      request, flag, result, and audit record models
  domain/service.py     deterministic policy evaluator
  storage/dynamodb.py   deployed DynamoDB safety audit repository
  storage/memory.py     in-memory safety audit repository
  adapters/message_hub.py
                        optional MessageHubService safety adapter
aws/
  lambda_function.py    API Gateway HTTP Lambda adapter
tests/
  test_safety_gateway.py
```

Run tests from the repository root:

```text
make safety-gateway-test
```

Build the deployable Lambda package from the repository root:

```text
make safety-gateway-build
```

Recommended initial stack:

- Python 3.13.
- FastAPI for HTTP policy APIs.
- Pydantic for request, policy, and decision schemas.
- Plain Lambda handlers for queue and review workflows.

It decides whether a message or action should be:

- Allowed.
- Allowed with warning.
- Rate-limited.
- Quarantined.
- Sent to human review.
- Blocked.

It owns:

- Agent identity and provenance checks.
- Trust labels.
- Policy evaluation.
- Consent checks.
- Visibility and privacy checks.
- Rate limits and loop prevention.
- Prompt-injection and spam flags.
- Artifact safety checks.
- Human-review queues.
- Safety audit records.

All agent-originated messages should pass through this layer before delivery.
High-impact connector actions should pass through this layer before execution.

That rule is what survives the split. What changes is *where* the layer runs:
today it is one central service in front of the shared hub; afterwards the same
evaluation runs at each Gull edge for the owner's own policy, with the Seagulls
Host applying provider policy on top for the Gulls it hosts.
