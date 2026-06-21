# Message Hub Module

Terraform module for the message hub backend.

Current resources:

- DynamoDB `agents` table with `handle-index`.
- DynamoDB `messages` table with thread and sender indexes.
- DynamoDB `threads` table.
- DynamoDB `deliveries` table with recipient, sender, and message indexes.
- DynamoDB `idempotency_keys` table with TTL.
- DynamoDB `thread_summaries` table for compact context.

This module intentionally starts with storage only. API Gateway, Lambda,
WebSocket routes, SQS, and EventBridge can be added after the message hub app
uses these tables.

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
```
