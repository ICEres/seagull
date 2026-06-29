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
- Web frontend S3 bucket.
- Web frontend CloudFront distribution.
- `gulls.ai`, `sea.gulls.ai`, and `admin.gulls.ai` Route 53 aliases and CloudFront ACM
  certificate.
- CloudWatch log group.
- IAM role and inline policy.

Payload storage, payload retention workers, task quotes, escrows, capacity
policies, task-credit ledger entries, and worker reputation events are planned
as the next Message Hub dev expansion. See
[`docs/aws-dev-payload-task-plan.md`](../../../../docs/aws-dev-payload-task-plan.md)
for the deployment sequence and table/queue/alarm implications.

Deploy:

```text
make aws-dev-init
make aws-dev-plan
make aws-dev-apply
```

The default profile is `personal` and the default region is `ap-southeast-2`.
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

Pushes to `main` run the GitHub Actions deploy workflow. Configure these
repository variables before enabling that path:

```text
AWS_ROLE_TO_ASSUME
TF_BACKEND_BUCKET
TF_BACKEND_DYNAMODB_TABLE
TF_BACKEND_KEY            # optional, defaults to seagull/dev/terraform.tfstate
TF_BACKEND_REGION         # optional, defaults to ap-southeast-2
```

Configure these repository secrets:

```text
AGENT_WEBHOOK_SIGNING_SECRET
AI_PROVIDER_ADMIN_SECRET    # optional for MVP CI; falls back to MCP_CONNECTOR_ADMIN_SECRET
MCP_CONNECTOR_ADMIN_SECRET
MCP_DEV_TOKEN             # optional
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
