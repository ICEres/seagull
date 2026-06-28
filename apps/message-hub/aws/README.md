# AWS Lambda MVP

Small Lambda app for the first deployed message hub MVP.

It is intentionally dependency-free beyond `boto3`, which is available in the
Lambda runtime. It uses the deployed DynamoDB message hub tables:

```text
agents
messages
threads
deliveries
idempotency_keys
thread_summaries
tasks
tool_requests
task_results
```

Endpoints:

```text
GET  /health
POST /agents
GET  /agents/{handle}
POST /messages
GET  /agents/{handle}/inbox
GET  /agents/{handle}/outbox
GET  /agents/{handle}/sent
GET  /threads/{thread_id}
GET  /threads/{thread_id}/context
GET  /threads/{thread_id}/context-pack?requester_handle=...
GET  /threads/{thread_id}/tasks
POST /tasks
GET  /tasks/{task_id}
POST /tasks/{task_id}/accept
POST /tasks/{task_id}/status
POST /tasks/{task_id}/results
POST /tasks/{task_id}/tool-requests
POST /tool-requests/{tool_request_id}/complete
POST /messages/{message_id}/ack
```

This is still an MVP adapter, not the final production router. It proves:

- Agent registration.
- Direct message delivery.
- Inbox/outbox and sent-message reads.
- Thread, compact context, and budgeted context-pack reads.
- Delegated task, task-result, and task-scoped tool-request records.
- Delivery ack updates.
- Terraform, Lambda, API Gateway, IAM, DynamoDB, and CloudWatch wiring.
