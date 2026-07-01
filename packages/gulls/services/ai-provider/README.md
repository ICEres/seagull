# AI Provider Backend

Local implementation of the Seagull AI provider backend.

This app owns hosted AI run execution, provider adapter boundaries, server
credit controls, user credit charges, usage records, provider config, and run
audit. The first implementation is dependency-free and uses a fake provider so
the contract can settle before adding real provider SDKs or AWS workers.

Run local tests from the repository root:

```text
make ai-provider-test
```
