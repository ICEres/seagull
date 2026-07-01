# Storage

Repository interfaces and database implementations for the message hub.

The first implementation can start with an in-memory repository for tests and
local development. DynamoDB should come after the core shapes are stable.

Storage should support:

- Agents by handle.
- Messages by ID.
- Thread message lists.
- Messages by sender.
- Compressed payloads by content reference.
- Payload lists for retention workers.
- Inbox items by recipient.
- Outbox items by sender.
- Delivery state.
- Thread summaries.
- Task-scoped tool grants and tool requests.
- Task capacity-sharing policies, quotes, escrows, credit ledger entries, and
  results.
- Append-only worker reputation events for task outcomes, disputes, and abuse
  reports.

Keep storage behind interfaces so domain tests do not depend on AWS.

## DynamoDB Direction

Start with clear logical tables before optimizing into a single-table design:

```text
agents
messages
payloads
threads
deliveries
idempotency_keys
thread_summaries
tasks
task_capacity_policies
task_quotes
task_escrows
task_credit_ledger
task_worker_reputation_events
tool_requests
task_results
```

Likely access patterns:

- Resolve an agent by handle before sending.
- Insert one immutable message by `message_id`.
- Insert a compressed payload blob and fetch it by `content_ref`.
- Query messages by `thread_id + created_at`.
- Query sent messages by `sender_agent_id + created_at`.
- Query inbox deliveries by `recipient_agent_id + created_at`.
- Query outbox deliveries by `sender_agent_id + created_at`.
- Update delivery state by `delivery_id`.
- Return context from `thread_summaries` plus the latest thread messages.

The first code implementation uses `InMemoryMessageHubRepository`. Its job is
to prove the domain flow and tests before DynamoDB table definitions are added.
