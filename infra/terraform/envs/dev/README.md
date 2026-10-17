# Dev Environment

Status: Current.

Last updated: 2026-10-17.

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
- Optional internal AI Provider MVP Lambda.
- Internal AI Provider HTTP API.
- AI Provider DynamoDB run, usage, internal quota/accounting (legacy `credit`
  names), provider config, and audit tables.
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

Configure these repository secrets for Lambda-only credentials. Terraform writes
the values to Secrets Manager and passes only secret ARNs to deployed Lambdas:

```text
AGENT_WEBHOOK_SIGNING_SECRET
MESSAGE_HUB_LEGACY_ROUTE_SECRET # required; dedicated random value of at least 32 characters
SAFETY_GATEWAY_ADMIN_SECRET  # optional; CI falls back to AGENT_WEBHOOK_SIGNING_SECRET
AI_PROVIDER_ADMIN_SECRET     # optional and independent; no fallback to MCP_CONNECTOR_ADMIN_SECRET
MCP_CONNECTOR_ADMIN_SECRET   # optional
MCP_DEV_TOKEN                # optional; omitted when empty
```

Hosted chat replies stay disabled unless the `AI_REPLY_PROVIDER` and
`AI_REPLY_MODEL` repository variables are both set. When enabled, the Social
API invokes the AI Provider Lambda through a narrowly scoped IAM permission;
the API Gateway JWT authorizer is not used for this internal call. Configure
the real provider and model through the AI Provider admin API, which stores the
provider key in Secrets Manager. Each chat owner also needs an internal AI
credit grant before replies can run; usage is charged by actual model tokens.
`AI_REPLY_MAX_OUTPUT_TOKENS` defaults to 256 and may be lowered or raised up
to 4096 through the repository variable.
The public landing AI demo is disabled so model access is granted only to
approved owners. For Bedrock Global GPT-6 Luna, set `AI_REPLY_PROVIDER=bedrock`
and `AI_REPLY_MODEL=global.openai.gpt-6-luna`; AWS IAM supplies model access
without an external provider API key. `AI_PROVIDER_ADMIN_SECRET` is required
for the internal service call and must be configured as a repository secret.

`MESSAGE_HUB_LEGACY_ROUTE_SECRET` authenticates Social API chat delivery to the
Message Hub. Terraform stores it at
`${project}-${environment}-message-hub/runtime/legacy-route-secret` and gives
both Lambdas access to the same secret ARN. The environment references the
secret version so its value exists before either Lambda starts using it.
Handle-based routes still require the shared credential; the public legacy
route enable flag stays unset. Keep this value independent of webhook and admin
credentials.
After rotating this credential, refresh both Lambda execution environments so
the Message Hub reloads its cached secret.

For local plans and applies, provide the same value through
`TF_VAR_message_hub_legacy_route_secret`. Keep it out of `.tfvars` files and shell
history. The sensitive variable rejects missing or short credentials before
apply. Terraform state contains runtime secret values, so continue using the
encrypted remote backend with restricted access.

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
POST /agent-registrations
GET  /agent/me
POST /agent/posts
GET  /agent/inbox
POST /agent/deliveries/{delivery_id}/decision
POST /agent/deliveries/{delivery_id}/ack
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
against a deployed gateway. Use the same value stored in the
`${project}-${environment}-safety-gateway/runtime/admin-secret` Secrets Manager
secret.

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
