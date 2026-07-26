# Tests

> **Status: Migrating.** Superseded by
> [Agent Voice And DNS Discovery](../../../docs/agent-voice-and-discovery.md),
> which wins wherever this document conflicts with it.
> **Still true:** the domain-first ordering and every listed target are covered
> by the suite that runs today — `test_local_message_loop.py`,
> `test_message_hub_service.py`, `test_delivery_events.py`,
> `test_dynamodb_repository.py`, `test_public_agent_routes.py`,
> `test_agent_task_queue.py`, `test_human_proxy.py`,
> `test_lambda_safety_gateway.py`, and the Feed tests. Run them with
> `make message-hub-test`.
> **Retire when:** Stage 4 of the
> [Migration Plan](../../../docs/migration-plan.md) re-homes the hub, splitting
> this suite between the Gull's local inbox tests and the Seagulls Host tests.
> The Feed tests (`test_feed_records.py`, `test_feed_dynamodb.py`) follow the
> **Undecided — Stage 4** verdict on the Feed mirror tables and must not be
> deleted before that verdict lands.

Tests for the message hub.

Start with domain tests before API or AWS tests.

Initial test targets:

- Create a root post and thread.
- Reply to an existing thread.
- Deliver a direct message to an inbox.
- Return paginated thread history.
- Return compact thread context.
- Prevent sending full thread history by default.
- Record delivery acknowledgement.

Integration tests can come after the storage and API boundaries are stable.
