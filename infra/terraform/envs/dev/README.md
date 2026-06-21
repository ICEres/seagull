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
- Social API MVP Lambda.
- Social API HTTP API.
- Social API DynamoDB tables.
- Message router Go Lambda.
- API Gateway WebSocket API.
- DynamoDB storage tables.
- Web frontend S3 bucket.
- Web frontend CloudFront distribution.
- `sea.gulls.ai` Route 53 aliases and CloudFront ACM certificate.
- CloudWatch log group.
- IAM role and inline policy.

Deploy:

```text
terraform init
terraform plan
terraform apply
```

The default profile is `personal` and the default region is `ap-southeast-2`.

From the repository root:

```text
make aws-dev-init
make aws-dev-plan
make aws-dev-apply
make aws-dev-smoke
make aws-dev-safety-smoke
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
Social API URL through `sea.gulls.ai`.

Destroy the dev stack when it is no longer needed:

```text
make aws-dev-destroy
```
