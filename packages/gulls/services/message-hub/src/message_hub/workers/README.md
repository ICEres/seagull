# Workers

Background workers for message hub async work.

Future workers may handle:

- Fanout.
- Delivery retries.
- Thread summary refresh.
- Inbox notifications.
- Dead-letter processing.
- Delivery timeout cleanup.

The first real worker is the outbound agent webhook worker:

```text
SQS FIFO agent job
-> re-read delivery, message, and recipient agent
-> skip missing, acked, or already-triggered deliveries
-> sign and POST seagull.delivery.created.v1 to webhook_url
-> mark trigger_status=sent on success
-> update retry metadata and let SQS retry on transient failures
-> send poison jobs to the DLQ after the queue redrive limit
```

The worker intentionally does not mark a message `acked`. Ack means the target
connector actually handled the message, not merely that Seagull delivered an
HTTP trigger.
