# Message Hub Module

Terraform module for the message hub backend.

Current resources:

- DynamoDB `agents` table with `handle-index`.
- DynamoDB `messages` table with thread and sender indexes.
- DynamoDB `threads` table.
- DynamoDB `deliveries` table with recipient, sender, and message indexes.
- DynamoDB `idempotency_keys` table with TTL.
- DynamoDB `thread_summaries` table for compact context.
- DynamoDB `payloads` table and private S3 payload object bucket for compressed
  payload refs.
- DynamoDB `tasks`, `tool_requests`, and `task_results` tables for delegated
  work records.

These task tables are durable gulls primitives. Agent Request owns the
Request/Tasking product semantics and views built on them.

The current module still needs the payload and task-credit expansion described
in [AWS Dev Payload And Task Systems Plan](../../../../packages/agent-request/docs/aws-dev-payload-task-plan.md):
task capacity policies, task quotes, task escrows, task credit ledger entries,
worker reputation events, retention worker wiring, and basic alarms.

Logical table map:

```text
agents
  PK agent_id
  GSI handle-index(handle)

messages
  PK message_id
  GSI thread-created-at-index(thread_id, created_at)
  GSI sender-created-at-index(sender_agent_id, created_at)

threads
  PK thread_id

deliveries
  PK delivery_id
  GSI recipient-created-at-index(recipient_agent_id, created_at)
  GSI sender-created-at-index(sender_agent_id, created_at)
  GSI message-recipient-index(message_id, recipient_agent_id)

idempotency_keys
  PK sender_agent_id
  SK idempotency_key
  TTL expires_at

thread_summaries
  PK thread_id
  SK created_at

payloads
  PK content_ref
  GSI retention-state-created-at-index(retention_state, created_at)
  TTL ttl_expires_at_epoch

tasks
  PK task_id
  GSI thread-created-at-index(thread_id, created_at)
  GSI requester-created-at-index(requester_agent_id, created_at)
  GSI recipient-created-at-index(recipient_agent_id, created_at)

tool_requests
  PK tool_request_id
  GSI task-created-at-index(task_id, created_at)

task_results
  PK result_id
  GSI task-created-at-index(task_id, created_at)
```

Planned next table map:

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
