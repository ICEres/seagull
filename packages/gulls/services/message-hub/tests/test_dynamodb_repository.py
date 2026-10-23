"""Tests for DynamoDbMessageHubRepository against emulated AWS (moto).

These tests need the optional dev dependencies ``moto`` and ``boto3``
(``pip install 'moto[dynamodb,s3]' boto3``). They are skipped automatically
when moto is unavailable so the base suite stays dependency-free; the lambda
adapter tests cover the routing layer with the in-memory repository either
way.

The legacy-item tests pin compatibility with data written by the previous
standalone Lambda implementation: string sets, denormalized ``sender_handle``
attributes, ``safety_*`` detail attributes, millisecond ``Z`` timestamps, and
``task:``-prefixed idempotency keys.
"""

from __future__ import annotations

import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

try:  # pragma: no cover - environment probe
    import boto3
    from moto import mock_aws

    HAS_MOTO = True
except ImportError:  # pragma: no cover
    HAS_MOTO = False

from message_hub.domain.models import (
    Agent,
    AgentTokenRecord,
    Delivery,
    DeliveryStatus,
    Message,
    MessageRef,
    PayloadCompaction,
    PayloadRecord,
    RoutingRule,
    RoutingRuleMode,
    StoredPayload,
    TaskCreditLedgerEntry,
    TaskCreditLedgerEntryType,
    TaskEscrowRecord,
    TaskQuoteRecord,
    TaskRecord,
    TaskResultRecord,
    TaskState,
    TaskToolRequest,
    TaskWorkerReputationEventRecord,
    TaskWorkerReputationEventType,
    ThreadRecord,
    ThreadSummary,
    ToolGrant,
)
from message_hub.domain.service import MessageHubService
from message_hub.domain import IdempotencyConflictError
from message_hub.storage.dynamodb import (
    DynamoDbMessageHubRepository,
    RepositoryTableNotConfiguredError,
)
from message_hub.storage.repository import SendTooLargeError

REGION = "us-east-1"
BUCKET = "test-payload-objects"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _table(
    dynamodb,
    name: str,
    *,
    hash_key: str,
    range_key: str | None = None,
    gsis: tuple[tuple[str, str, str | None], ...] = (),
):
    attribute_names = {hash_key}
    if range_key:
        attribute_names.add(range_key)
    for _, gsi_hash, gsi_range in gsis:
        attribute_names.add(gsi_hash)
        if gsi_range:
            attribute_names.add(gsi_range)

    key_schema = [{"AttributeName": hash_key, "KeyType": "HASH"}]
    if range_key:
        key_schema.append({"AttributeName": range_key, "KeyType": "RANGE"})

    kwargs = {
        "TableName": name,
        "KeySchema": key_schema,
        "AttributeDefinitions": [
            {"AttributeName": attr, "AttributeType": "S"} for attr in sorted(attribute_names)
        ],
        "BillingMode": "PAY_PER_REQUEST",
    }
    if gsis:
        kwargs["GlobalSecondaryIndexes"] = [
            {
                "IndexName": index_name,
                "KeySchema": (
                    [{"AttributeName": gsi_hash, "KeyType": "HASH"}]
                    + (
                        [{"AttributeName": gsi_range, "KeyType": "RANGE"}]
                        if gsi_range
                        else []
                    )
                ),
                "Projection": {"ProjectionType": "ALL"},
            }
            for index_name, gsi_hash, gsi_range in gsis
        ]
    dynamodb.create_table(**kwargs)
    return dynamodb.Table(name)


@unittest.skipUnless(HAS_MOTO, "moto and boto3 are required for DynamoDB repository tests")
class DynamoDbRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
        os.environ.setdefault("AWS_DEFAULT_REGION", REGION)
        self._mock = mock_aws()
        self._mock.start()
        self.addCleanup(self._mock.stop)

        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        self.s3 = boto3.client("s3", region_name=REGION)
        self.s3.create_bucket(Bucket=BUCKET)

        self.agents = _table(
            dynamodb, "agents", hash_key="agent_id", gsis=(("handle-index", "handle", None),)
        )
        self.agent_tokens = _table(
            dynamodb,
            "agent-tokens",
            hash_key="token_id",
            gsis=(("agent-created-at-index", "agent_id", "created_at"),),
        )
        self.messages = _table(
            dynamodb,
            "messages",
            hash_key="message_id",
            gsis=(
                ("thread-created-at-index", "thread_id", "created_at"),
                ("sender-created-at-index", "sender_agent_id", "created_at"),
            ),
        )
        self.threads = _table(dynamodb, "threads", hash_key="thread_id")
        self.deliveries = _table(
            dynamodb,
            "deliveries",
            hash_key="delivery_id",
            gsis=(
                ("recipient-created-at-index", "recipient_agent_id", "created_at"),
                ("sender-created-at-index", "sender_agent_id", "created_at"),
                ("message-recipient-index", "message_id", "recipient_agent_id"),
            ),
        )
        self.routing_rules = _table(dynamodb, "routing-rules", hash_key="rule_id")
        self.idempotency = _table(
            dynamodb, "idempotency", hash_key="sender_agent_id", range_key="idempotency_key"
        )
        self.thread_summaries = _table(
            dynamodb, "thread-summaries", hash_key="thread_id", range_key="created_at"
        )
        self.payloads = _table(dynamodb, "payloads", hash_key="content_ref")
        self.tasks = _table(
            dynamodb,
            "tasks",
            hash_key="task_id",
            gsis=(("thread-created-at-index", "thread_id", "created_at"),),
        )
        self.tool_requests = _table(
            dynamodb,
            "tool-requests",
            hash_key="tool_request_id",
            gsis=(("task-created-at-index", "task_id", "created_at"),),
        )
        self.task_results = _table(
            dynamodb,
            "task-results",
            hash_key="result_id",
            gsis=(("task-created-at-index", "task_id", "created_at"),),
        )
        self.task_quotes = _table(
            dynamodb,
            "task-quotes",
            hash_key="quote_id",
            gsis=(("task-created-at-index", "task_id", "created_at"),),
        )
        self.task_escrows = _table(
            dynamodb,
            "task-escrows",
            hash_key="escrow_id",
            gsis=(("task-created-at-index", "task_id", "created_at"),),
        )
        self.capacity_policies = _table(
            dynamodb,
            "task-capacity-policies",
            hash_key="policy_id",
            gsis=(("task-created-at-index", "task_id", "created_at"),),
        )
        self.credit_ledger = _table(
            dynamodb,
            "task-credit-ledger",
            hash_key="entry_id",
            gsis=(
                ("account-created-at-index", "account_agent_id", "created_at"),
                ("task-created-at-index", "task_id", "created_at"),
            ),
        )
        self.reputation_events = _table(
            dynamodb,
            "task-reputation-events",
            hash_key="event_id",
            gsis=(
                ("worker-created-at-index", "worker_agent_id", "created_at"),
                ("task-created-at-index", "task_id", "created_at"),
            ),
        )
        self.tool_grants = _table(
            dynamodb,
            "tool-grants",
            hash_key="grant_id",
            gsis=(("task-created-at-index", "task_id", "created_at"),),
        )

        self.repository = DynamoDbMessageHubRepository(
            agents_table=self.agents,
            messages_table=self.messages,
            threads_table=self.threads,
            deliveries_table=self.deliveries,
            idempotency_table=self.idempotency,
            thread_summaries_table=self.thread_summaries,
            payloads_table=self.payloads,
            routing_rules_table=self.routing_rules,
            agent_tokens_table=self.agent_tokens,
            tasks_table=self.tasks,
            tool_requests_table=self.tool_requests,
            task_results_table=self.task_results,
            task_quotes_table=self.task_quotes,
            task_escrows_table=self.task_escrows,
            task_capacity_policies_table=self.capacity_policies,
            task_credit_ledger_table=self.credit_ledger,
            task_reputation_events_table=self.reputation_events,
            tool_grants_table=self.tool_grants,
            payload_objects_bucket=BUCKET,
            s3_client=self.s3,
        )

    # -- agents & tokens

    def test_agent_round_trip_and_handle_lookup(self) -> None:
        agent = Agent(
            agent_id="agent_1",
            handle="@worker:gulls.ai",
            display_name="Worker",
            capabilities=("chat", "review"),
            response_rules={"source": "connector_config", "max_reply_chars": 280},
            created_at=_utc(2026, 7, 1, 9, 0, 0),
            updated_at=_utc(2026, 7, 1, 9, 0, 0),
        )
        self.repository.add_agent(agent)

        loaded = self.repository.get_agent("agent_1")
        assert loaded is not None
        self.assertEqual(loaded.handle, "@worker:gulls.ai")
        self.assertEqual(loaded.capabilities, ("chat", "review"))
        self.assertEqual(
            loaded.response_rules,
            {"source": "connector_config", "max_reply_chars": 280},
        )

        by_handle = self.repository.get_agent_by_handle("@worker:gulls.ai")
        assert by_handle is not None
        self.assertEqual(by_handle.agent_id, "agent_1")
        self.assertIsNone(self.repository.get_agent_by_handle("@missing:gulls.ai"))

    def test_parses_legacy_lambda_agent_item(self) -> None:
        # Shape written by the previous standalone Lambda: capabilities as a
        # string set, millisecond Z timestamps, no response_rules.
        self.agents.put_item(
            Item={
                "agent_id": "agent_legacy",
                "handle": "@legacy:gulls.ai",
                "display_name": "Legacy",
                "capabilities": {"chat"},
                "status": "active",
                "trigger_mode": "manual",
                "created_at": "2026-01-05T08:30:00.123Z",
                "updated_at": "2026-01-05T08:30:00.123Z",
            }
        )
        loaded = self.repository.get_agent("agent_legacy")
        assert loaded is not None
        self.assertEqual(loaded.capabilities, ("chat",))
        self.assertEqual(loaded.created_at, _utc(2026, 1, 5, 8, 30, 0, 123000))

    def test_agent_token_round_trip_and_listing_order(self) -> None:
        for index in (1, 2):
            self.repository.put_agent_token(
                AgentTokenRecord(
                    token_id=f"token_{index}",
                    token_hash=f"hash_{index}",
                    agent_id="agent_1",
                    agent_handle="@worker:gulls.ai",
                    scopes=("agent:inbox", "agent:send"),
                    created_at=_utc(2026, 7, index, 12, 0, 0),
                )
            )
        tokens = self.repository.list_agent_tokens_by_agent("agent_1")
        self.assertEqual([token.token_id for token in tokens], ["token_2", "token_1"])

        revoked = AgentTokenRecord(
            token_id="token_1",
            token_hash="hash_1",
            agent_id="agent_1",
            agent_handle="@worker:gulls.ai",
            scopes=("agent:inbox",),
            created_at=_utc(2026, 7, 1, 12, 0, 0),
            revoked_at=_utc(2026, 7, 3, 12, 0, 0),
        )
        self.repository.update_agent_token(revoked)
        loaded = self.repository.get_agent_token("token_1")
        assert loaded is not None
        self.assertIsNotNone(loaded.revoked_at)

    # -- messages, threads, deliveries

    def _message(self, index: int, *, thread_id: str = "thread_1") -> Message:
        return Message(
            message_id=f"message_{index}",
            thread_id=thread_id,
            sender_agent_id="agent_sender",
            recipient_agent_ids=("agent_recipient",),
            intent="message",
            visibility="direct",
            content_inline=f"hello {index}",
            refs=(MessageRef(type="doc", url=f"https://example.test/{index}"),),
            created_at=_utc(2026, 7, 10, 9, index, 0),
        )

    def test_message_round_trip_and_orderings(self) -> None:
        for index in (3, 1, 2):
            self.repository.put_message(self._message(index))

        loaded = self.repository.get_message("message_1")
        assert loaded is not None
        self.assertEqual(loaded.recipient_agent_ids, ("agent_recipient",))
        self.assertEqual(loaded.refs[0].url, "https://example.test/1")

        chronological = self.repository.list_thread_messages("thread_1")
        self.assertEqual(
            [message.message_id for message in chronological],
            ["message_1", "message_2", "message_3"],
        )
        limited = self.repository.list_thread_messages("thread_1", limit=2)
        self.assertEqual(
            [message.message_id for message in limited],
            ["message_2", "message_3"],
        )

        newest_first = self.repository.list_messages_by_sender("agent_sender")
        self.assertEqual(
            [message.message_id for message in newest_first],
            ["message_3", "message_2", "message_1"],
        )

    def test_public_message_without_recipients_round_trips(self) -> None:
        message = Message(
            message_id="message_public",
            thread_id="thread_public",
            sender_agent_id="agent_sender",
            recipient_agent_ids=(),
            intent="post",
            visibility="public",
            content_inline="public post",
            created_at=_utc(2026, 7, 10, 10, 0, 0),
        )
        self.repository.put_message(message)
        loaded = self.repository.get_message("message_public")
        assert loaded is not None
        self.assertEqual(loaded.recipient_agent_ids, ())
        self.assertEqual(loaded.visibility, "public")

    def test_parses_legacy_lambda_message_item(self) -> None:
        # Legacy items carry denormalized handles and safety detail fields the
        # domain model doesn't know; they must be tolerated, not fatal.
        self.messages.put_item(
            Item={
                "message_id": "message_legacy",
                "thread_id": "thread_legacy",
                "sender_agent_id": "agent_sender",
                "sender_handle": "@sender:gulls.ai",
                "recipient_agent_ids": {"agent_recipient"},
                "recipient_handles": {"@recipient:gulls.ai"},
                "intent": "message",
                "visibility": "direct",
                "content_inline": "legacy",
                "schema_version": "seagull.message.v1",
                "safety_status": "approved",
                "safety_action": "allow",
                "safety_decision_id": "safety_123",
                "safety_policy_ids": ["policy_1"],
                "safety_reasons": [],
                "created_at": "2026-02-01T10:00:00.000Z",
            }
        )
        loaded = self.repository.get_message("message_legacy")
        assert loaded is not None
        self.assertEqual(loaded.recipient_agent_ids, ("agent_recipient",))
        self.assertEqual(loaded.safety_status, "approved")

    def test_messages_by_content_ref_scan(self) -> None:
        ref = "payload://abc"
        for index in (2, 1):
            message = Message(
                message_id=f"message_ref_{index}",
                thread_id="thread_ref",
                sender_agent_id="agent_sender",
                recipient_agent_ids=("agent_recipient",),
                intent="message",
                visibility="direct",
                content_ref=ref,
                created_at=_utc(2026, 7, 11, 8, index, 0),
            )
            self.repository.put_message(message)
        self.repository.put_message(self._message(9, thread_id="thread_other"))

        matches = self.repository.list_messages_by_content_ref(ref)
        self.assertEqual(
            [message.message_id for message in matches],
            ["message_ref_1", "message_ref_2"],
        )

    def test_thread_and_delivery_round_trip(self) -> None:
        thread = ThreadRecord(
            thread_id="thread_1",
            root_message_id="message_1",
            participants=frozenset({"agent_sender", "agent_recipient"}),
            message_count=2,
            last_message_id="message_2",
            last_message_at=_utc(2026, 7, 10, 9, 2, 0),
            created_at=_utc(2026, 7, 10, 9, 1, 0),
            updated_at=_utc(2026, 7, 10, 9, 2, 0),
        )
        self.repository.put_thread(thread)
        loaded_thread = self.repository.get_thread("thread_1")
        assert loaded_thread is not None
        self.assertEqual(
            loaded_thread.participants, frozenset({"agent_sender", "agent_recipient"})
        )
        self.assertEqual(loaded_thread.message_count, 2)

        for index in (1, 2):
            delivery = Delivery(
                delivery_id=f"delivery_{index}",
                message_id=f"message_{index}",
                thread_id="thread_1",
                sender_agent_id="agent_sender",
                recipient_agent_id="agent_recipient",
                status=DeliveryStatus.DELIVERED,
                current_content_inline=f"hello {index}",
                created_at=_utc(2026, 7, 10, 9, index, 30),
                updated_at=_utc(2026, 7, 10, 9, index, 30),
            )
            self.repository.put_delivery(delivery)

        inbox = self.repository.list_deliveries_by_recipient("agent_recipient")
        self.assertEqual(
            [delivery.delivery_id for delivery in inbox], ["delivery_2", "delivery_1"]
        )
        outbox = self.repository.list_deliveries_by_sender("agent_sender", limit=1)
        self.assertEqual([delivery.delivery_id for delivery in outbox], ["delivery_2"])
        by_message = self.repository.list_deliveries_by_message("message_1")
        self.assertEqual(
            [delivery.delivery_id for delivery in by_message], ["delivery_1"]
        )

        acked = Delivery(
            delivery_id="delivery_1",
            message_id="message_1",
            thread_id="thread_1",
            sender_agent_id="agent_sender",
            recipient_agent_id="agent_recipient",
            status=DeliveryStatus.ACKED,
            acked_at=_utc(2026, 7, 10, 10, 0, 0),
            created_at=_utc(2026, 7, 10, 9, 1, 30),
            updated_at=_utc(2026, 7, 10, 10, 0, 0),
        )
        self.repository.update_delivery(acked)
        loaded = self.repository.get_delivery("delivery_1")
        assert loaded is not None
        self.assertEqual(loaded.status, DeliveryStatus.ACKED)
        self.assertIsNotNone(loaded.acked_at)

    # -- routing rules

    def test_routing_rule_round_trip(self) -> None:
        for index in (2, 1):
            self.repository.put_routing_rule(
                RoutingRule(
                    rule_id=f"rule_{index}",
                    name=f"rule {index}",
                    mode=RoutingRuleMode.REVIEW,
                    url_contains=("private",),
                    created_at=_utc(2026, 7, 1, 8, index, 0),
                    updated_at=_utc(2026, 7, 1, 8, index, 0),
                )
            )
        rules = self.repository.list_routing_rules()
        self.assertEqual([rule.rule_id for rule in rules], ["rule_1", "rule_2"])
        self.assertEqual(rules[0].mode, RoutingRuleMode.REVIEW)

    # -- idempotency

    def test_message_and_task_idempotency_do_not_collide(self) -> None:
        self.repository.put_idempotency_key("agent_1", "key", "message_1")
        self.repository.put_task_idempotency_key("agent_1", "key", "task_1")

        self.assertEqual(
            self.repository.get_idempotent_message_id("agent_1", "key"), "message_1"
        )
        self.assertEqual(
            self.repository.get_idempotent_task_id("agent_1", "key"), "task_1"
        )
        self.assertIsNone(self.repository.get_idempotent_message_id("agent_1", "other"))

    def test_guest_send_counter_reuses_the_idempotency_table(self) -> None:
        # A live (future-TTL) window, so the replay-read assertion below
        # exercises the missing-message_id path rather than TTL expiry.
        window = int(time.time()) // 3_600 * 3_600
        ttl = window + 7_200

        first = self.repository.increment_guest_send_count("guest-ip:203.0.113.7", window, ttl_epoch=ttl)
        second = self.repository.increment_guest_send_count("guest-ip:203.0.113.7", window, ttl_epoch=ttl)
        other_window = self.repository.increment_guest_send_count(
            "guest-ip:203.0.113.7", window + 3_600, ttl_epoch=ttl + 3_600
        )
        other_scope = self.repository.increment_guest_send_count(
            "guest-recipient:@weather-jp:gulls.ai", window, ttl_epoch=ttl
        )
        self.assertEqual([1, 2, 1, 1], [first, second, other_window, other_scope])

        # The counter row lives in the reserved partition with the TTL set.
        item = self.idempotency.get_item(
            Key={
                "sender_agent_id": "__guest_rate__",
                "idempotency_key": f"guest-ip:203.0.113.7:{window}",
            }
        )["Item"]
        self.assertEqual(2, int(item["send_count"]))
        self.assertEqual(ttl, int(item["expires_at"]))
        # A counter row never reads back as a message idempotency replay.
        self.assertIsNone(
            self.repository.get_idempotent_message_id("__guest_rate__", f"guest-ip:203.0.113.7:{window}")
        )

    def test_expired_idempotency_keys_are_ignored(self) -> None:
        expired = datetime.now(timezone.utc) - timedelta(seconds=5)
        self.repository.put_idempotency_key(
            "agent_1", "old", "message_1", expires_at=expired
        )
        self.assertIsNone(self.repository.get_idempotent_message_id("agent_1", "old"))

    # -- payloads

    def test_payload_round_trip_through_s3(self) -> None:
        record = PayloadRecord(
            content_ref="payload://abc123",
            media_type="text/plain; charset=utf-8",
            byte_length=5,
            hash="sha256:x",
            compressed_byte_length=25,
            compressed_hash="sha256:y",
            ttl_expires_at=_utc(2026, 8, 1, 0, 0, 0),
            created_at=_utc(2026, 7, 12, 7, 0, 0),
        )
        payload = StoredPayload(record=record, compressed_content=b"gzip-bytes")
        self.repository.put_payload(payload)

        loaded = self.repository.get_payload("payload://abc123")
        assert loaded is not None
        self.assertEqual(loaded.compressed_content, b"gzip-bytes")
        self.assertEqual(loaded.record.storage_provider, "aws_s3")
        self.assertEqual(
            loaded.record.storage_ref, f"s3://{BUCKET}/payloads/abc123.gz"
        )
        self.assertEqual(loaded.record.ttl_expires_at, _utc(2026, 8, 1, 0, 0, 0))

        item = self.payloads.get_item(Key={"content_ref": "payload://abc123"}).get("Item")
        assert item is not None
        self.assertEqual(int(item["ttl_expires_at_epoch"]), int(record.ttl_expires_at.timestamp()))

        compacted = StoredPayload(
            record=loaded.record,
            compressed_content=None,
            compaction=PayloadCompaction(
                manifest_ref="manifest://abc123",
                summary="compact",
                selected_chunk_refs=("chunk-0",),
                selected_chunks=(b"chunk-bytes",),
                created_at=_utc(2026, 7, 13, 7, 0, 0),
            ),
        )
        self.repository.update_payload(compacted)
        reloaded = self.repository.get_payload("payload://abc123")
        assert reloaded is not None and reloaded.compaction is not None
        self.assertEqual(reloaded.compaction.selected_chunks, (b"chunk-bytes",))
        self.assertEqual(reloaded.compaction.manifest_ref, "manifest://abc123")
        self.assertIsNone(reloaded.compressed_content)
        self.assertIsNone(reloaded.record.storage_ref)
        remaining = [
            entry["Key"]
            for entry in self.s3.list_objects_v2(Bucket=BUCKET).get("Contents", [])
        ]
        self.assertNotIn("payloads/abc123.gz", remaining)

        listed = self.repository.list_payloads()
        self.assertEqual(len(listed), 1)

    # -- thread summaries

    def test_latest_thread_summary(self) -> None:
        for index in (1, 2):
            self.repository.put_thread_summary(
                ThreadSummary(
                    thread_id="thread_1",
                    summary_id=f"summary_{index}",
                    summary_text=f"summary {index}",
                    created_at=_utc(2026, 7, 10, 12, index, 0),
                )
            )
        latest = self.repository.get_latest_thread_summary("thread_1")
        assert latest is not None
        self.assertEqual(latest.summary_id, "summary_2")
        self.assertIsNone(self.repository.get_latest_thread_summary("thread_other"))

    # -- task-work entities

    def test_task_and_tool_and_result_round_trip(self) -> None:
        task = TaskRecord(
            task_id="task_1",
            thread_id="thread_1",
            requester_agent_id="agent_requester",
            recipient_agent_id="agent_worker",
            objective="summarize",
            request_message_id="message_1",
            allowed_tool_names=("search",),
            state=TaskState.REQUESTED,
            created_at=_utc(2026, 7, 14, 9, 0, 0),
            updated_at=_utc(2026, 7, 14, 9, 0, 0),
        )
        self.repository.put_task(task)
        loaded = self.repository.get_task("task_1")
        assert loaded is not None
        self.assertEqual(loaded.state, TaskState.REQUESTED)
        self.assertEqual(loaded.allowed_tool_names, ("search",))

        self.repository.update_task(
            TaskRecord(
                **{
                    **{f: getattr(task, f) for f in task.__dataclass_fields__},
                    "state": TaskState.ACCEPTED,
                    "accepted_by_agent_id": "agent_worker",
                }
            )
        )
        self.assertEqual(
            self.repository.get_task("task_1").state, TaskState.ACCEPTED  # type: ignore[union-attr]
        )
        by_thread = self.repository.list_tasks_by_thread("thread_1")
        self.assertEqual([item.task_id for item in by_thread], ["task_1"])

        for index in (3, 2):
            self.repository.put_task(
                TaskRecord(
                    **{
                        **{f: getattr(task, f) for f in task.__dataclass_fields__},
                        "task_id": f"task_{index}",
                        "created_at": _utc(2026, 7, 14, 9, index, 0),
                        "updated_at": _utc(2026, 7, 14, 9, index, 0),
                    }
                )
            )
        self.assertEqual(
            [item.task_id for item in self.repository.list_tasks_by_thread("thread_1")],
            ["task_1", "task_2", "task_3"],
        )
        self.assertEqual(
            [
                item.task_id
                for item in self.repository.list_tasks_by_thread("thread_1", limit=2)
            ],
            ["task_2", "task_3"],
        )

        tool_request = TaskToolRequest(
            tool_request_id="tool_request_1",
            task_id="task_1",
            thread_id="thread_1",
            requester_agent_id="agent_requester",
            worker_agent_id="agent_worker",
            tool_name="search",
            purpose="lookup",
            status=TaskState.NEEDS_APPROVAL,
            created_at=_utc(2026, 7, 14, 9, 5, 0),
            updated_at=_utc(2026, 7, 14, 9, 5, 0),
        )
        self.repository.put_tool_request(tool_request)
        listed_requests = self.repository.list_tool_requests_by_task("task_1")
        self.assertEqual(
            [item.tool_request_id for item in listed_requests], ["tool_request_1"]
        )

        result = TaskResultRecord(
            result_id="result_1",
            task_id="task_1",
            thread_id="thread_1",
            responder_agent_id="agent_worker",
            state=TaskState.RESULT_READY,
            result_message_id="message_9",
            content_inline="done",
            created_at=_utc(2026, 7, 14, 10, 0, 0),
        )
        self.repository.put_task_result(result)
        results = self.repository.list_task_results("task_1")
        self.assertEqual([item.result_id for item in results], ["result_1"])

    def test_marketplace_entities_round_trip(self) -> None:
        quote = TaskQuoteRecord(
            quote_id="quote_1",
            task_id="task_1",
            thread_id="thread_1",
            requester_agent_id="agent_requester",
            worker_agent_id="agent_worker",
            task_reason="paid work",
            expected_credit_cost=5,
            created_at=_utc(2026, 7, 14, 11, 0, 0),
            updated_at=_utc(2026, 7, 14, 11, 0, 0),
        )
        self.repository.put_task_quote(quote)
        self.assertEqual(
            self.repository.list_task_quotes_by_task("task_1")[0].expected_credit_cost, 5
        )

        escrow = TaskEscrowRecord(
            escrow_id="escrow_1",
            task_id="task_1",
            quote_id="quote_1",
            thread_id="thread_1",
            requester_agent_id="agent_requester",
            worker_agent_id="agent_worker",
            credit_amount=5,
            created_at=_utc(2026, 7, 14, 11, 5, 0),
            updated_at=_utc(2026, 7, 14, 11, 5, 0),
        )
        self.repository.put_task_escrow(escrow)
        self.assertEqual(
            self.repository.list_task_escrows_by_task("task_1")[0].state,
            TaskState.ESCROWED,
        )

        entry = TaskCreditLedgerEntry(
            entry_id="entry_1",
            account_agent_id="agent_requester",
            entry_type=TaskCreditLedgerEntryType.ESCROW_HOLD,
            credit_amount=5,
            available_delta=-5,
            escrow_delta=5,
            task_id="task_1",
            created_at=_utc(2026, 7, 14, 11, 6, 0),
        )
        self.repository.put_task_credit_ledger_entry(entry)
        by_agent = self.repository.list_task_credit_ledger_entries_by_agent(
            "agent_requester"
        )
        self.assertEqual(by_agent[0].available_delta, -5)
        by_task = self.repository.list_task_credit_ledger_entries_by_task("task_1")
        self.assertEqual([item.entry_id for item in by_task], ["entry_1"])

        event = TaskWorkerReputationEventRecord(
            event_id="event_1",
            worker_agent_id="agent_worker",
            event_type=TaskWorkerReputationEventType.TASK_COMPLETED,
            task_id="task_1",
            thread_id="thread_1",
            created_at=_utc(2026, 7, 14, 12, 0, 0),
        )
        self.repository.put_task_worker_reputation_event(event)
        self.assertEqual(
            self.repository.list_task_worker_reputation_events_by_worker(
                "agent_worker"
            )[0].event_type,
            TaskWorkerReputationEventType.TASK_COMPLETED,
        )

        grant = ToolGrant(
            grant_id="grant_1",
            task_id="task_1",
            thread_id="thread_1",
            issuer_agent_id="agent_requester",
            subject_agent_id="agent_worker",
            audience="worker",
            scopes=("search",),
            purpose="lookup",
            max_calls=3,
            created_at=_utc(2026, 7, 14, 12, 5, 0),
            updated_at=_utc(2026, 7, 14, 12, 5, 0),
        )
        self.repository.put_tool_grant(grant)
        loaded_grant = self.repository.get_tool_grant("grant_1")
        assert loaded_grant is not None
        self.assertEqual(loaded_grant.max_calls, 3)
        self.assertEqual(
            self.repository.list_tool_grants_by_task("task_1")[0].grant_id, "grant_1"
        )

    # -- guardrails

    def test_missing_table_raises_clear_error(self) -> None:
        repository = DynamoDbMessageHubRepository(
            agents_table=self.agents,
            messages_table=self.messages,
            threads_table=self.threads,
            deliveries_table=self.deliveries,
            idempotency_table=self.idempotency,
            thread_summaries_table=self.thread_summaries,
        )
        with self.assertRaises(RepositoryTableNotConfiguredError):
            repository.put_task_quote(
                TaskQuoteRecord(
                    quote_id="quote_x",
                    task_id="task_x",
                    thread_id="thread_x",
                    requester_agent_id="a",
                    worker_agent_id="b",
                    task_reason="r",
                    expected_credit_cost=1,
                )
            )

    # -- end to end through the domain service

    def test_message_hub_service_send_flow_over_dynamodb(self) -> None:
        service = MessageHubService(repository=self.repository)
        service.register_agent("@sender:gulls.ai")
        service.register_agent("@recipient:gulls.ai")

        result = service.send_message(
            sender_handle="@sender:gulls.ai",
            recipient_handles=("@recipient:gulls.ai",),
            content="hello over dynamodb",
            idempotency_key="send-1",
        )
        self.assertEqual(len(result.deliveries), 1)
        self.assertEqual(result.deliveries[0].status, DeliveryStatus.DELIVERED)

        # Idempotent replay returns the same message.
        replay = service.send_message(
            sender_handle="@sender:gulls.ai",
            recipient_handles=("@recipient:gulls.ai",),
            content="hello over dynamodb",
            idempotency_key="send-1",
        )
        self.assertEqual(replay.message.message_id, result.message.message_id)

        inbox = service.get_inbox("@recipient:gulls.ai")
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0].message.content_inline, "hello over dynamodb")

    def test_atomic_idempotency_and_task_commit_over_dynamodb(self) -> None:
        service = MessageHubService(repository=self.repository)
        service.register_agent("@atomic-sender:gulls.ai")
        service.register_agent("@atomic-recipient:gulls.ai")

        def send():
            return service.send_message(
                sender_handle="@atomic-sender:gulls.ai",
                recipient_handles=("@atomic-recipient:gulls.ai",),
                content="one transaction",
                idempotency_key="atomic-key",
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: send(), range(4)))
        self.assertEqual(1, len(self.repository.list_messages_by_sender(
            service.get_agent("@atomic-sender:gulls.ai").agent_id  # type: ignore[union-attr]
        )))
        self.assertEqual(1, len({result.message.message_id for result in results}))

        with self.assertRaises(IdempotencyConflictError):
            service.send_message(
                sender_handle="@atomic-sender:gulls.ai",
                recipient_handles=("@atomic-recipient:gulls.ai",),
                content="changed",
                idempotency_key="atomic-key",
            )

        first_task = service.create_task(
            requester_handle="@atomic-sender:gulls.ai",
            recipient_handle="@atomic-recipient:gulls.ai",
            objective="run once",
            idempotency_key="task-atomic-key",
        )
        replay_task = service.create_task(
            requester_handle="@atomic-sender:gulls.ai",
            recipient_handle="@atomic-recipient:gulls.ai",
            objective="run once",
            idempotency_key="task-atomic-key",
        )
        self.assertEqual(first_task.task_id, replay_task.task_id)
        self.assertIsNotNone(self.repository.get_task(first_task.task_id))

    def test_keyed_message_action_limit_accepts_97_and_rejects_98_atomically(self) -> None:
        service = MessageHubService(repository=self.repository)
        service.register_agent("@many-sender:gulls.ai")
        handles = []
        for index in range(98):
            handle = f"@recipient-{index}:gulls.ai"
            service.register_agent(handle)
            handles.append(handle)

        accepted = service.send_message(
            sender_handle="@many-sender:gulls.ai",
            recipient_handles=tuple(handles[:97]),
            content="boundary",
            idempotency_key="boundary-97",
        )
        self.assertEqual(97, len(accepted.deliveries))

        with self.assertRaises(SendTooLargeError):
            service.send_message(
                sender_handle="@many-sender:gulls.ai",
                recipient_handles=tuple(handles),
                content="too many deliveries",
                idempotency_key="boundary-98",
            )
        sender = service.get_agent("@many-sender:gulls.ai")
        assert sender is not None
        self.assertEqual(1, len(self.repository.list_messages_by_sender(sender.agent_id)))
        self.assertEqual(97, len(self.repository.list_deliveries_by_sender(sender.agent_id)))

    def test_dynamodb_rejects_item_and_transaction_size_before_writes(self) -> None:
        with self.assertRaises(SendTooLargeError):
            self.repository._transact_write([
                {
                    "Put": {
                        "TableName": self.messages.name,
                        "Item": {"message_id": "oversize", "blob": "x" * (400 * 1024)},
                    }
                }
            ])

        with self.assertRaises(SendTooLargeError):
            self.repository._transact_write([
                {
                    "Put": {
                        "TableName": self.messages.name,
                        "Item": {"message_id": f"aggregate-{index}", "blob": "x" * 50000},
                    }
                }
                for index in range(85)
            ])
        self.assertIsNone(self.messages.get_item(Key={"message_id": "oversize"}).get("Item"))

    def test_concurrent_keyed_tasks_are_one_set_and_different_keys_are_distinct(self) -> None:
        service = MessageHubService(repository=self.repository)
        service.register_agent("@task-sender:gulls.ai")
        service.register_agent("@task-worker:gulls.ai")

        def create(key: str):
            return service.create_task(
                requester_handle="@task-sender:gulls.ai",
                recipient_handle="@task-worker:gulls.ai",
                objective="same objective",
                idempotency_key=key,
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            same_key = list(pool.map(lambda _: create("same-key"), range(4)))
        self.assertEqual(1, len({task.task_id for task in same_key}))
        with ThreadPoolExecutor(max_workers=2) as pool:
            different_keys = list(pool.map(create, ("key-a", "key-b")))
        self.assertEqual(2, len({task.task_id for task in different_keys}))

    def test_expired_idempotency_key_can_be_replaced(self) -> None:
        service = MessageHubService(repository=self.repository)
        service.register_agent("@expiry-sender:gulls.ai")
        service.register_agent("@expiry-recipient:gulls.ai")
        sender = service.get_agent("@expiry-sender:gulls.ai")
        assert sender is not None
        self.idempotency.put_item(Item={
            "sender_agent_id": sender.agent_id,
            "idempotency_key": "expired-key",
            "message_id": "old-message",
            "expires_at": int(time.time()) - 1,
        })
        result = service.send_message(
            sender_handle="@expiry-sender:gulls.ai",
            recipient_handles=("@expiry-recipient:gulls.ai",),
            content="replacement",
            idempotency_key="expired-key",
        )
        self.assertNotEqual("old-message", result.message.message_id)
        self.assertEqual(result.message.message_id, self.repository.get_idempotent_message_id(sender.agent_id, "expired-key"))

    def test_legacy_thread_without_revision_can_advance(self) -> None:
        service = MessageHubService(repository=self.repository)
        service.register_agent("@legacy-sender:gulls.ai")
        service.register_agent("@legacy-recipient:gulls.ai")
        first = service.send_message(
            sender_handle="@legacy-sender:gulls.ai",
            recipient_handles=("@legacy-recipient:gulls.ai",),
            content="root",
        )
        self.threads.update_item(
            Key={"thread_id": first.thread.thread_id},
            UpdateExpression="REMOVE revision",
        )
        second = service.send_message(
            sender_handle="@legacy-sender:gulls.ai",
            recipient_handles=("@legacy-recipient:gulls.ai",),
            content="after legacy row",
            thread_id=first.thread.thread_id,
        )
        self.assertEqual(1, second.thread.revision)

    def test_concurrent_different_keys_on_same_thread_both_commit(self) -> None:
        service = MessageHubService(repository=self.repository)
        service.register_agent("@race-sender:gulls.ai")
        service.register_agent("@race-recipient:gulls.ai")
        root = service.send_message(
            sender_handle="@race-sender:gulls.ai",
            recipient_handles=("@race-recipient:gulls.ai",),
            content="root",
        )

        def send(key: str):
            return service.send_message(
                sender_handle="@race-sender:gulls.ai",
                recipient_handles=("@race-recipient:gulls.ai",),
                content=key,
                thread_id=root.thread.thread_id,
                idempotency_key=key,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, ("race-a", "race-b")))
        self.assertEqual(2, len({result.message.message_id for result in results}))
        thread = self.repository.get_thread(root.thread.thread_id)
        assert thread is not None
        self.assertEqual(3, thread.message_count)
        self.assertEqual(2, thread.revision)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
