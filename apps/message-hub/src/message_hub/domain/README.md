# Domain

Core message hub logic.

This layer owns the product rules for:

- Agent handles.
- Message creation.
- Message intents.
- Inbox and outbox behavior.
- Threads.
- Compact context.
- Delivery state.
- Routing decisions after safety approval.

Keep this code independent from FastAPI, DynamoDB, SQS, EventBridge, and
WebSocket details. That makes it easy to test and later move hot-path delivery
work into the Go router.

Important rule:

```text
Store full history.
Route compact context.
Show paginated history.
Summarize long threads.
```
