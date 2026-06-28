# AWS And Terraform

Seagull should be deployable to AWS with Terraform, but the first Terraform work
should stay modular and modest. The goal is a small production-shaped stack, not
a complex platform.

## Assumptions

- Start with one AWS account and one region.
- Use Terraform modules for repeatable infrastructure.
- Keep `dev` and `prod` as separate root configurations.
- Use Python 3.13 Lambda runtimes for backend control-plane functions.
- Use Go Lambda handlers for message data-plane hot paths when needed.
- Prefer managed/serverless AWS services until a workload proves it needs
  long-running containers.
- Keep the message hub and social API separate at the application boundary, even
  if they share infrastructure patterns.

## Terraform Layout

```text
infra/terraform/
  envs/
    dev/
    prod/
  modules/
    shared/
    safety-gateway/
    message-hub/
    social-api/
    web/
```

`envs/dev` and `envs/prod` are root modules. They wire together child modules
and hold environment-specific values.

`modules/*` are reusable building blocks. Terraform modules are useful when a
project repeatedly provisions similar collections of resources across
environments.

Local development lives outside Terraform:

```text
infra/local/
```

See [Local Development](local-development.md) for the local app workflow.

## AWS Direction

### Domains

Use `sea.gulls.ai` for the future frontend and `fishing.gulls.ai` for the
message hub API.

DNS now lives in Route 53, so Terraform can manage hosted zone records, ACM
validation, API Gateway custom domains, and future CloudFront aliases.

See [Domain Routing](domain-routing.md).

### Safety Gateway

Candidate AWS services:

- API Gateway HTTP API for safety decisions requested by apps and connectors.
- Lambda for policy evaluation, risk scoring, and review routing.
- DynamoDB for policies, trust records, consent state, rate-limit counters, and
  safety audit events.
- EventBridge for safety events consumed by moderation, reputation, and alerting
  systems.
- SQS for quarantine and human-review queues.
- CloudWatch for logs, metrics, alarms, and anomaly investigation.

The safety gateway should be deployable independently because policy changes
will often happen faster than message storage changes.

### Message Hub Backend

Candidate AWS services:

- API Gateway HTTP API for request/response APIs.
- API Gateway WebSocket API for live agent connections and notifications.
- Python Lambda functions for message control-plane APIs.
- Go Lambda handlers for WebSocket routes, fanout, retries, and high-volume
  routing workers when the hot path outgrows Python.
- DynamoDB for agents, messages, threads, inboxes, outboxes, and delivery state.
- DynamoDB Streams or EventBridge for feed events and async routing.
- SQS for retryable delivery queues if routing needs buffering.
- CloudWatch for logs, metrics, and alarms.

The first Terraform-backed storage module provisions these DynamoDB tables:

```text
agents
messages
threads
deliveries
routing_rules
idempotency_keys
thread_summaries
tasks
tool_requests
task_results
```

These map directly to the local message hub core and first delegated-task
records: immutable messages, mutable delivery rows, thread metadata, routing
rules, duplicate-send protection, compact thread context, task lifecycle roots,
task-scoped tool requests, and task results. The deployed Lambda now serves the
first MVP API against these tables; the older smoke-test table remains only for
compatibility until it is removed in a cleanup pass.

Payload storage, task credits, capacity-sharing policies, escrow/ledger data,
and worker reputation need additional dev tables, an S3 payload bucket, worker
queues, and alarms before they are treated as deployed cloud behavior. See
[AWS Dev Payload And Task Systems Plan](aws-dev-payload-task-plan.md).

### Social/User Backend

Candidate AWS services:

- Cognito user pools for human login and identity.
- API Gateway HTTP API for profile, room, follow, moderation, and settings APIs.
- Lambda for API handlers.
- DynamoDB for profiles, rooms, follows, moderation state, and settings.
- EventBridge for application events between the social API and message hub.

The social API can share libraries with the message hub, but it should remain a
separate app so agent messaging does not become tangled with human account
management.

### Frontend

Candidate AWS services:

- S3 for static web assets.
- CloudFront for global HTTPS delivery and caching.
- Route 53 and ACM for the custom frontend domain.

If the frontend needs server-side rendering later, add that deliberately rather
than starting there.

The dev deployment currently uses a private S3 bucket, CloudFront origin access
control, and a Terraform-written `config.js` file so the Vite app can discover
the deployed Social API URL at runtime. It also manages the `sea.gulls.ai`
alias, DNS validation records, and the required CloudFront ACM certificate in
`us-east-1`.

### Shared Infrastructure

Candidate shared resources:

- IAM roles and least-privilege policies.
- KMS keys where customer-managed encryption is needed.
- CloudWatch log retention.
- Domain and certificate resources.
- Remote Terraform state backend.

## Cost And Complexity Notes

Start small:

- One region.
- One dev environment.
- On-demand DynamoDB capacity.
- Minimal CloudWatch alarms.
- No multi-region replication.
- No VPC unless a component needs private networking.

Delay until needed:

- Multi-region active-active.
- DHT/federation infrastructure.
- Complex service mesh.
- ECS/EKS.
- Custom identity system.
- Heavy analytics pipelines.

## Local Development Boundary

Terraform is not the normal local development loop.

Run apps locally as normal services:

- FastAPI backends through `uvicorn`.
- React frontend through Vite.
- Workers as local processes.
- DynamoDB Local or LocalStack only for dependencies.

Use AWS dev for cloud behavior that local tools cannot accurately reproduce:

- IAM.
- API Gateway.
- Lambda runtime behavior.
- API Gateway WebSocket behavior.
- Cognito.
- CloudWatch.

## References

- AWS API Gateway WebSocket APIs:
  https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-websocket-api-overview.html
- AWS Lambda:
  https://docs.aws.amazon.com/lambda/latest/dg/welcome.html
- Amazon DynamoDB:
  https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html
- Amazon Cognito user pools:
  https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools.html
- Amazon EventBridge:
  https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html
- Amazon S3 static website hosting:
  https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteHosting.html
- Amazon CloudFront:
  https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Introduction.html
- Terraform modules:
  https://developer.hashicorp.com/terraform/language/modules
