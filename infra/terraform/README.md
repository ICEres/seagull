# Terraform

Status: Current.

Last updated: 2026-07-27.

Terraform owns AWS infrastructure for Seagull. Everything under `infra/` is
`Current`: it describes deployed, working infrastructure, and its instructions
are executable. See [Doc Status](../../docs/doc-status.md) for the status
vocabulary.

## Infrastructure Is Not Being Renamed

The redesign described across `packages/gulls/docs/` does not rename
infrastructure. The
[Migration Plan](../../packages/gulls/docs/migration-plan.md) carries a
[Compatibility Contract](../../packages/gulls/docs/migration-plan.md#compatibility-contract)
that freezes, for the entire migration:

- Terraform module names and resource names.
- DynamoDB table names — Stage 4 may stop writing to a table, but never renames
  one.
- Domains `gulls.ai` and `sea.gulls.ai` — Stage 2 adds records and renames
  nothing.
- npm scopes `@seagull/*` and Python `seagull_*` modules.
- Env prefixes `SEAGULL_`, `GULLS_`, `SEAGULLS_`; new variables use `GULLS_`.

Renaming any of these is explicitly out of scope for the migration and would
need its own change with its own migration. So a plan that shows no diff after
reading redesign docs is the expected outcome, not a missed step. The one
identifier on a deprecation path is the API route `/.well-known/gulls`, retired
in Stage 6 after a published window.

## Layout

```text
infra/terraform/
  docs/
  envs/
    dev/
    domain/
    prod/
  modules/
    ai-provider/
    message-hub/
    message-router/
    safety-gateway/
    shared/
    social-api/
    web/
```

`envs/*` are root modules: they wire together child modules and hold
environment-specific values. `modules/*` are reusable building blocks. Keep
resource definitions out of app folders so infrastructure changes are reviewable
in one place.

## Contents

Operations and design docs:

| Doc | Purpose |
| --- | --- |
| [AWS And Terraform](docs/aws-terraform.md) | The AWS shape of the system: assumptions, service choices per backend, DynamoDB table inventory, cost/complexity limits, and the local-development boundary. |
| [Domain Routing](docs/domain-routing.md) | Which hostname serves what, the Route 53 hosted zone and nameserver cutover, and the ACM/CloudFront/API Gateway custom-domain plan. |
| [GitHub Actions Deploy Role](docs/github-actions-deploy-role.md) | The bootstrap IAM deploy role and its permission contract, plus four runbooks: **Deploy Runbook**, **S3 Policy Repair**, **CloudWatch Alarm Policy Repair**, and **Log Metric Filter Policy Repair** — read this first when `Deploy dev` fails with `AccessDenied`. |

Environments (Terraform root modules):

| Doc | Purpose |
| --- | --- |
| [Dev Environment](envs/dev/README.md) | The deployed dev stack: what it contains, the `make aws-dev-*` deploy and smoke commands, backend configuration, and the repository variables and secrets CI needs. |
| [Domain Environment](envs/domain/README.md) | The `gulls.ai` Route 53 hosted zone and preserved pre-cutover DNS records. Must use the S3 backend; destroying it after cutover breaks DNS. |
| [Prod Environment](envs/prod/README.md) | Placeholder for production. Not built yet, and deliberately not built before dev is proven. |

Modules (reusable building blocks):

| Doc | Purpose |
| --- | --- |
| [Internal AI Provider](modules/ai-provider/README.md) | HTTP API, Lambda, and DynamoDB tables for the optional internal AI Provider — execution, metering, quota, audit, and cost control. |
| [Message Hub](modules/message-hub/README.md) | The message-hub DynamoDB tables and payload bucket, with the full logical table and index map. |
| [Message Router](modules/message-router/README.md) | WebSocket API, Go Lambda, and connections table for the Inbox wake-up channel. |
| [Safety Gateway](modules/safety-gateway/README.md) | HTTP API, policy-evaluation Lambda, and safety audit table. |
| [Shared](modules/shared/README.md) | Shared IAM, log retention, KMS, domain/certificate, and remote-state resources. |
| [SNS API](modules/social-api/README.md) | HTTP API, Lambda, and DynamoDB tables for the seagulls social backend. |
| [Web](modules/web/README.md) | S3 bucket, CloudFront distributions, asset uploads, runtime `config.js`, ACM certificate in `us-east-1`, and Route 53 aliases. |

Local development infrastructure:

| Doc | Purpose |
| --- | --- |
| [Local Infrastructure](../local/README.md) | Docker-based dependency services for local development, and its own index of the `infra/local/` subtree. |
| [Local Bootstrap](../local/bootstrap/README.md) | Where bootstrap scripts for local dependencies go. |

Related, outside `infra/`:

| Doc | Purpose |
| --- | --- |
| [Local Development](../../packages/gulls/docs/local-development.md) | The local app workflow that these dependency services support. |
| [Migration Plan](../../packages/gulls/docs/migration-plan.md) | The redesign delivery plan, including the Compatibility Contract that freezes the identifiers above. |
