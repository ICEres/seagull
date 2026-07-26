# Policy

> **Status: Migrating.** Superseded by
> [Agent Voice And DNS Discovery](../../docs/agent-voice-and-discovery.md), which
> wins wherever this document conflicts with it.
> **Still true:** `src/seagull_policy/models.py` and its tests are shipped and
> unchanged, the `seagull_policy` module name is **frozen** by the
> [Compatibility Contract](../../docs/migration-plan.md#compatibility-contract),
> and the provider-neutral rule below still holds.
> **Retire when:** the **Split** of the safety gateway lands and this README is
> rewritten to describe the Gull edge enforcement point directly. The package
> itself is *Keep in Gulls* in the
> [Code Disposition Register](../../docs/migration-plan.md#code-disposition-register)
> and is not going anywhere — only this framing of it is.

Shared safety policy types and evaluation contracts live here. Its register
verdict is **Keep in Gulls**: this is the enforcement point for one agent's
inbound and outbound policy, and after the safety gateway splits, the per-Gull
half of that gateway lands here rather than in a central service.

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
