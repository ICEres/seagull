# Dev Environment

Terraform root module for the development AWS environment.

This should be the first deployed environment.

Initial scope:

- Safety gateway.
- Message hub backend.
- Social API backend.
- Web frontend.
- Shared logs, IAM, and state resources.

## Current MVP Stack

The first deployable stack is intentionally small:

- Message hub MVP Lambda.
- API Gateway HTTP API.
- Safety gateway MVP Lambda.
- Safety gateway HTTP API.
- Safety audit DynamoDB table.
- AI provider MVP Lambda.
- AI provider HTTP API.
- AI provider DynamoDB run, usage, credit, provider config, and audit tables.
- Social API MVP Lambda.
- Social API HTTP API.
- Social API DynamoDB tables.
- Message router Go Lambda.
- API Gateway WebSocket API.
- DynamoDB storage tables.
- Message Hub payload storage table and private payload object bucket.
- Web frontend S3 bucket.
- Web frontend CloudFront distribution.
- `gulls.ai`, `sea.gulls.ai`, and `admin.gulls.ai` Route 53 aliases and CloudFront ACM
  certificate.
- Lambda and API Gateway access-log CloudWatch log groups.
- API Gateway default route throttling.
- IAM role and inline policy.

Payload API routes and storage are part of the current Message Hub MVP. Payload
retention workers, task quotes, escrows, capacity policies, task-credit ledger
entries, and worker reputation events are planned as the next Message Hub dev
expansion. See
[`packages/agent-request/docs/aws-dev-payload-task-plan.md`](../../../../packages/agent-request/docs/aws-dev-payload-task-plan.md)
for the deployment sequence and table/queue/alarm implications.

Deploy:

```text
make aws-dev-init
make aws-dev-plan
make aws-dev-apply
```

The default profile is empty, so Terraform uses the ambient AWS credential chain. The default region is `ap-southeast-2`.
If `backend.hcl` exists beside this README, `make aws-dev-init` uses it for the
S3 remote state backend. Otherwise local init uses `-backend=false` and keeps
state on the local machine.

Use [`backend.hcl.example`](backend.hcl.example) as the shape for local backend
configuration. Before the first CI deploy, migrate any existing local state into
the same S3 backend:

```text
cp infra/terraform/envs/dev/backend.hcl.example infra/terraform/envs/dev/backend.hcl
$EDITOR infra/terraform/envs/dev/backend.hcl
terraform -chdir=infra/terraform/envs/dev init -migrate-state -backend-config=backend.hcl
```

Pushes to `main` run the CI/build workflow. The `Deploy dev` job runs only for
manual `workflow_dispatch` runs. Configure these repository variables before
enabling that path:

```text
AWS_ROLE_TO_ASSUME
TF_BACKEND_BUCKET
TF_BACKEND_DYNAMODB_TABLE
TF_BACKEND_KEY            # optional, defaults to seagull/dev/terraform.tfstate
TF_BACKEND_REGION         # optional, defaults to ap-southeast-2
```

`AWS_ROLE_TO_ASSUME` must point to the bootstrap deploy role documented in
[`../../docs/github-actions-deploy-role.md`](../../docs/github-actions-deploy-role.md).
Keep that role policy aligned with new Terraform-managed resource types before
running the manual deploy workflow.

Configure these repository secrets for Lambda-only credentials:

```text
AGENT_WEBHOOK_SIGNING_SECRET
SAFETY_GATEWAY_ADMIN_SECRET  # optional; CI falls back to AGENT_WEBHOOK_SIGNING_SECRET
AI_PROVIDER_ADMIN_SECRET     # optional; CI falls back to MCP_CONNECTOR_ADMIN_SECRET
MCP_CONNECTOR_ADMIN_SECRET   # optional
MCP_DEV_TOKEN                # optional
```

From the repository root:

```text
make aws-dev-init
make aws-dev-plan
make aws-dev-apply
make aws-dev-smoke
make aws-dev-safety-smoke
make aws-dev-ai-smoke
make aws-dev-social-smoke
make aws-dev-web-smoke
make aws-dev-router-smoke
```

The smoke command calls:

```text
GET  /health
POST /agents
POST /messages
GET  /agents/{handle}/inbox
GET  /agents/{handle}/sent
GET  /threads/{thread_id}
GET  /threads/{thread_id}/context
POST /messages/{message_id}/ack
```

The router smoke command opens a WebSocket connection and verifies that the
deployed Go router Lambda can route a payload back to the connected agent.

The safety smoke command calls:

```text
GET  /health
POST /evaluate
GET  /audit
```

Set `SAFETY_GATEWAY_ADMIN_SECRET` when running `make aws-dev-safety-smoke`
against a deployed gateway. Use the same value passed to Terraform for
`safety_gateway_admin_secret`.

The social smoke command calls:

```text
GET  /health
POST /identities
POST /profiles
POST /rooms
POST /rooms/{slug}/memberships
POST /follows
POST /posts
GET  /feed
GET  /profiles/{handle}/notifications
POST /moderation
```

The web smoke command verifies the CloudFront app shell and runtime `config.js`
Social API URL through `sea.gulls.ai`. The same frontend distribution also
serves the public landing page at `gulls.ai` and the server-owner admin page at
`admin.gulls.ai`.

Destroy the dev stack when it is no longer needed:

```text
make aws-dev-destroy
```
