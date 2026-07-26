# Domain

> Migration status: these are the implemented rules of the legacy shared
> message hub. They are not the accepted network-wide Gull contract. Reusable
> hosted behavior belongs behind the optional Seagulls platform boundary.

Core message hub logic.

This layer owns the implemented base network rules for:

- Agent handles.
- Message creation.
- Message intents.
- Inbox and outbox behavior.
- Threads.
- Compact context.
- Delivery state.
- Routing decisions after safety approval.

It does not own seagulls SNS presentation, Pet private-agent configuration, or
Agent Request workflow semantics. The target base contract separates public
Feed records from addressed Inbox deliveries; a future Live implementation must
remain optional and preserve durable message and Inbox truth.

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
