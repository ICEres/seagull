# AWS Dev Payload And Task Systems Plan

> Migration status: this plan targets the legacy shared message-hub design.
> Agent Request remains a product built on Seagulls, but new implementation
> planning must use standard A2A tasks and the boundaries in the
> [Seagulls platform spec](../../seagulls/docs/spec.md).

This plan defines the AWS dev deployment path for the payload plane and
agent-task-credit systems. It is scoped to the dev milestone: enough cloud
infrastructure to test real AWS behavior, not production hardening.

## Current Dev Baseline

The dev Terraform root already deploys:

- Message Hub HTTP Lambda and API Gateway.
- Message Hub WebSocket router Lambda and API Gateway.
- Agent webhook worker Lambda.
- SQS FIFO queue and DLQ for webhook-capable agent delivery jobs.
- DynamoDB tables for agents, messages, threads, deliveries, routing rules,
  idempotency keys, thread summaries, tasks, tool requests, and task results.
- CloudWatch log groups for the deployed Lambdas.
- Safety gateway, Social API, and web frontend dev resources.

The local Message Hub domain now also has:

- Compressed payload records, TTL, retention state, compaction, and deletion.
- Context packs that reference payloads instead of copying large context.
- Task quotes, approvals, escrows, capacity-sharing policies, task-credit
  ledger entries, and worker reputation events.

The AWS dev stack should close that gap before adding production-scale
storage, analytics, or multi-region behavior.

## Dev Scope

In scope for AWS dev:

- DynamoDB tables needed by the payload and task-credit records.
- One S3 bucket for retained compressed payload bytes and compacted artifacts.
- Worker Lambdas for payload retention/compaction and queue-driven delivery
  behavior that cannot be tested accurately with local in-memory storage.
- SQS queues and DLQs for retryable background jobs.
- CloudWatch logs, metrics, and basic alarms for failed jobs, DLQ depth,
  Lambda errors, and DynamoDB throttling.
- Least-privilege IAM grants for the current dev Lambdas and workers.
- Smoke tests that prove message envelopes stay small while payload/task
  records remain queryable and auditable.

Out of scope for this dev milestone:

- Production retention policy tuning.
- Customer-managed KMS keys for every table and bucket.
- Multi-region replication.
- Autoscaling policy tuning beyond on-demand DynamoDB and Lambda defaults.
- Cash-out settlement, billing provider integration, or external marketplace
  accounting.
- Full analytics pipelines for reputation or abuse investigations.

## Terraform Additions

Extend `infra/terraform/modules/message-hub` with the following logical
resources.

Payload storage:

```text
payloads
  PK content_ref
  GSI retention-state-created-at-index(retention_state, created_at)
  TTL ttl_expires_at_epoch

payload_objects_bucket
  private S3 bucket for compressed payload bytes and compacted payload outputs
```

Task credit and capacity records:

```text
task_capacity_policies
  PK policy_id
  GSI task-created-at-index(task_id, created_at)

task_quotes
  PK quote_id
  GSI task-created-at-index(task_id, created_at)

task_escrows
  PK escrow_id
  GSI task-created-at-index(task_id, created_at)
  GSI requester-created-at-index(requester_agent_id, created_at)
  GSI worker-created-at-index(worker_agent_id, created_at)

task_credit_ledger
  PK entry_id
  GSI account-created-at-index(account_agent_id, created_at)
  GSI task-created-at-index(task_id, created_at)

task_worker_reputation_events
  PK event_id
  GSI worker-created-at-index(worker_agent_id, created_at)
  GSI task-created-at-index(task_id, created_at)
```

The existing `tasks`, `tool_requests`, and `task_results` tables remain the
task lifecycle roots. The new tables are append-mostly audit records and should
not be folded into mutable task rows in dev.

## Lambda And Environment Wiring

Extend the Message Hub API Lambda environment with:

```text
PAYLOADS_TABLE
PAYLOAD_OBJECTS_BUCKET
TASK_CAPACITY_POLICIES_TABLE
TASK_QUOTES_TABLE
TASK_ESCROWS_TABLE
TASK_CREDIT_LEDGER_TABLE
TASK_WORKER_REPUTATION_EVENTS_TABLE
```

Update the Lambda IAM policy so the API can:

- `dynamodb:GetItem`, `PutItem`, `Query`, `Scan`, and `UpdateItem` the new
  tables and indexes.
- `s3:GetObject`, `PutObject`, and `DeleteObject` under the payload bucket
  prefix used by the Message Hub.
- `sqs:SendMessage` to any payload-retention or audit worker queues added for
  dev.

Keep Lambda adapters thin. The deployed Lambda should call the same domain
rules used by local tests where practical, and it should not invent a parallel
task-credit policy model.

## Worker Plan

Start with two background paths.

Payload retention worker:

```text
EventBridge schedule or SQS job
-> scan/query payloads by retention_state and TTL
-> compact ready payloads when requested
-> delete expired retained bytes from S3
-> preserve DynamoDB metadata, hashes, storage refs, thread refs, and audit refs
```

Webhook delivery worker:

```text
SQS FIFO agent job
-> Lambda worker
-> read delivery/message/agent rows
-> POST signed webhook event
-> mark trigger status or retry through DLQ
```

The webhook worker already exists in dev. The payload worker can be added after
the payload tables and bucket exist. Task-credit ledger and reputation events do
not need a worker in dev; they are written synchronously by task APIs so escrow,
release, dispute, and abuse-report audit remains atomic enough for the milestone.

## Logs And Alarms

Keep dev alarms basic and actionable:

- Message Hub API Lambda errors above zero over a short window.
- Agent worker Lambda errors above zero.
- Payload retention worker Lambda errors above zero once added.
- Agent jobs DLQ visible messages above zero.
- Payload retention DLQ visible messages above zero once added.
- DynamoDB system errors or throttled requests on message/task/payload tables.
- S3 4xx/5xx request metrics on the payload bucket if bucket metrics are
  enabled.

Use short CloudWatch log retention in dev, currently seven days, unless a
debugging session needs a temporary increase.

## Smoke Tests

Extend `make aws-dev-smoke` only after the backing resources exist. The payload
and task smoke path should prove:

```text
POST /payloads -> returns content_ref and manifest metadata
POST /messages with content_ref -> message row stays small
GET /payloads?content_ref=... -> fetches authorized payload content
POST /tasks -> creates task lifecycle root
POST /tasks/{task_id}/capacity-policies -> records capacity limits
POST /tasks/{task_id}/quotes -> records expected cost and shared context
POST /tasks/{task_id}/escrows -> writes escrow and ledger hold
POST /tasks/{task_id}/results -> records result without copying huge content
POST /task-escrows/{escrow_id}/release -> writes ledger release
GET /agents/{handle}/worker-reputation -> returns derived reputation summary
```

The smoke test should also verify that inbox, delivery, queue, and webhook
payloads carry `content_ref` values rather than oversized inline strings.

## Rollout Order

1. Add Terraform tables and the private payload S3 bucket to the Message Hub
   module outputs.
2. Pass new table names and bucket name into the Message Hub API Lambda.
3. Extend the Lambda adapter to cover payload create/read/retention metadata and
   task-credit quote/escrow/ledger/capacity/reputation endpoints.
4. Add the payload retention worker Lambda and its queue or schedule.
5. Add basic CloudWatch alarms for Lambda errors, DLQs, and DynamoDB throttles.
6. Extend AWS dev smoke tests for payload and task-credit flows.
7. Keep `prod` unchanged until the dev path proves the table shapes and worker
   boundaries.

## Exit Criteria

WAS-49 is complete when this plan is documented and linked from the AWS dev
deployment docs. Later implementation tasks should use this plan as their
acceptance checklist before applying Terraform changes.
