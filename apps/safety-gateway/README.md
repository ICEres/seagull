# Safety Gateway

The safety gateway is Seagull's policy and trust layer.

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
