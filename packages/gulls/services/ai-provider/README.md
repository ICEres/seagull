# Internal AI Provider Backend

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

Run local tests from the repository root:

```text
make ai-provider-test
```
