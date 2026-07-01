# Policy

Shared safety policy types and evaluation contracts live here.

Current implementation:

```text
src/seagull_policy/
  models.py    Dependency-free first sketches for policies, labels, decisions,
               consent, rate limits, and audit events.
tests/
  test_policy_models.py
```

Recommended initial approach:

- Pydantic models for policy and decision types.
- JSON Schema/OpenAPI export for TypeScript consumers.
- Provider-neutral interfaces for future automated classifiers.

Initial candidates:

- Policy.
- Policy scope.
- Trust label.
- Risk label.
- Safety decision.
- Review state.
- Consent record.
- Rate-limit rule.
- Audit event.

Keep this package independent from any single model or moderation provider. The
first version should define the shape of safety decisions before adding
automated classifiers.
