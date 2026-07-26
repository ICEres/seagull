# Local Infrastructure

Status: Current.

Last updated: 2026-07-27.

Local infrastructure supports local development.

Use it for dependency services, not for running the whole app stack.

Planned dependencies:

- DynamoDB Local for message hub development.
- LocalStack later for SQS, EventBridge, S3, and other AWS-like services.
- Optional local Inbox wake-up WebSocket support, with shared Live A2A support
  only after its session and durable-fallback contract is implemented.

Do not add Docker Compose until the first implementation needs it.
Docker Compose is now present for DynamoDB Local because the message hub is the
first implementation target.

Current layout:

```text
infra/local/
  docker-compose.yml
  bootstrap/
```

Local apps should run directly with `uvicorn`, `pnpm`, or `go run`, while
dependency services run through Docker.

Docker Desktop is not required. Colima is enough as long as `docker` and
`docker compose` work.

Start dependencies:

```text
make setup
```

Start optional LocalStack too:

```text
./scripts/setup-local.sh --with-localstack
```

## Contents

| Path | Purpose |
| --- | --- |
| `docker-compose.yml` | DynamoDB Local, plus optional LocalStack under the `localstack` profile. Started by `make setup`. |
| [bootstrap/](bootstrap/README.md) | Where bootstrap scripts for local dependencies (tables, queues) go. Empty on purpose until the message hub schema needs them. |

Related:

| Doc | Purpose |
| --- | --- |
| [Local Development](../../packages/gulls/docs/local-development.md) | The local app workflow these dependency services support. |
| [Terraform](../terraform/README.md) | Cloud infrastructure, and the index for everything else under `infra/`. |
| [AWS And Terraform](../terraform/docs/aws-terraform.md) | Where the local-vs-cloud boundary is drawn, and which behavior only AWS dev can reproduce. |
