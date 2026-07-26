# Workers

> **Status: Migrating.** Superseded by
> [Agent Voice And DNS Discovery](../../../../../docs/agent-voice-and-discovery.md),
> which wins wherever this document conflicts with it.
> **Still true:** the outbound webhook worker described below is deployed, and
> so is the rule that it never marks a message `acked`. This directory holds no
> code — the shipped implementation is
> [`aws/agent_worker.py`](../../../aws/agent_worker.py), driven by an SQS FIFO
> queue with a DLQ after the redrive limit.
> **Retire when:** Stage 4 of the
> [Migration Plan](../../../../../docs/migration-plan.md) moves fan-out and
> retry to the Seagulls Host; the wake-up path a Gull keeps is A2A streaming and
> task push-notification configuration, not this queue.

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
