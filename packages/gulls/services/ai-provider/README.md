# AI Provider Backend

Implementation of the Seagull AI provider backend.

This app owns hosted AI run execution, provider adapter boundaries, server
credit controls, user credit charges, usage records, provider config, and run
audit. Local tests use a deterministic fake provider; AWS dev also includes an
SQS-backed worker for queued AI runs.

Run local tests from the repository root:

```text
make ai-provider-test
```
