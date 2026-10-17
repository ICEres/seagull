# Internal AI Provider Backend

> **Status: Migrating.** Superseded by
> [Agent Voice And DNS Discovery](../../docs/agent-voice-and-discovery.md), which
> wins wherever this document conflicts with it.
> **Still true:** everything below describes the service as built — hosted AI
> run execution, provider adapter boundaries, server credit controls, user
> credit debits, usage records, provider config, and run audit — and
> `make ai-provider-test` is the current test entry point. The `credit`
> definition here is unchanged by the redesign.
> **Retire when:** this README moves with its service to
> `packages/seagulls/services/ai-provider` under Stage 3 of the
> [Migration Plan](../../docs/migration-plan.md).

Implementation of optional Seagulls platform AI-provider infrastructure. Pet
and Agent Request may use it for model-backed steps through platform
boundaries, but it is not a standalone customer-facing product or direct
business surface.

This app owns hosted AI run execution, provider adapter boundaries, server
credit controls, user credit debits, usage records, provider config, and run
audit. Here, `credit` means a non-purchasable internal accounting and quota
unit—not customer balance, product entitlement, or Agent Request task credit.
Payment and billing belong to product layers and plans, outside this service.

Provider execution and token streaming are optional. Gull-to-Gull discovery,
A2A communication, local persistence, and task state must work without this
service. Provider streams are execution details, not the durable communication
or work source of truth.

## Disposition

The [Code Disposition Register](../../docs/migration-plan.md#code-disposition-register)
gives this service one verdict: **Move to Seagulls**. Its landing package is
`packages/seagulls/services/ai-provider`. Hosted runtime execution is a Host
concern — it is the one place the Seagulls Host authors a voice rather than
carrying it, and an owner who accepts that is trusting the Host to.

The consequence for the Gull layer is concrete: **a Gull with an owner-supplied
runtime never calls this service.** It reaches the owner's own model or agent
through its runtime connector. A hosted Gull that asked its Host to execute the
model is the only caller. Nothing in discovery, A2A delivery, the local durable
inbox, policy evaluation, or task state may take a dependency on this service.

No files have moved yet; the move is Stage 3 work and changes no behavior.

Run local tests from the repository root:

```text
make ai-provider-test
```

The owner-scoped read-only endpoint `GET /owners/{owner_user_id}/ai-usage-summary`
returns the current balance, usage records, and credit ledger entries together.
It requires the existing owner authentication or admin secret; it does not add
any payment or credit mutation behavior.
