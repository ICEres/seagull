# Internal AI Provider Backend

Implementation of Seagull's optional shared AI provider infrastructure. Pet,
seagulls, and Agent Request may use it for model-backed steps, but it is not a
standalone customer-facing product or direct business surface.

This app owns hosted AI run execution, provider adapter boundaries, server
credit controls, user credit debits, usage records, provider config, and run
audit. Here, `credit` means a non-purchasable internal accounting and quota
unit—not customer balance, product entitlement, or Agent Request task credit.
Payment and billing belong to product layers and plans, outside this service.

Provider execution and token streaming are optional. Shared Feed, Inbox, Live
A2A, delivery, and task state must work without this service; provider token
streams and payload streaming are distinct from Live, whose meaningful results
remain durable gulls records.

Run local tests from the repository root:

```text
make ai-provider-test
```
