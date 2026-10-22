from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest import TestCase

from message_hub.domain.models import Delivery, DeliveryStatus, Message
from message_hub.storage.dynamodb import (
    DynamoDbMessageHubRepository,
    delivery_to_item,
    message_to_item,
)


class QueryTable:
    """Small Query-only DynamoDB double exercising ExclusiveStartKey."""

    def __init__(
        self,
        items: list[dict[str, Any]],
        *,
        partition_key: str,
        id_key: str,
        sort_ties_by_id: bool = True,
    ) -> None:
        self.items = items
        self.partition_key = partition_key
        self.id_key = id_key
        self.sort_ties_by_id = sort_ties_by_id

    def query(self, **kwargs: Any) -> dict[str, Any]:
        partition_value = self._partition_value(kwargs["KeyConditionExpression"])
        rows = [
            item
            for item in self.items
            if item.get(self.partition_key) == partition_value
        ]
        if self.sort_ties_by_id:
            rows.sort(key=lambda item: (str(item["created_at"]), str(item[self.id_key])), reverse=True)
        else:
            # DynamoDB does not promise ID ordering when rows tie on the
            # queried sort key. Preserve the fixture's order for that case.
            rows.sort(key=lambda item: str(item["created_at"]), reverse=True)
        start = kwargs.get("ExclusiveStartKey")
        if start is not None:
            start_id = start[self.id_key]
            ids = [item[self.id_key] for item in rows]
            rows = rows[ids.index(start_id) + 1 :] if start_id in ids else []
        limit = int(kwargs["Limit"])
        selected = rows[:limit]
        result: dict[str, Any] = {"Items": selected}
        if len(rows) > limit and selected:
            last = selected[-1]
            result["LastEvaluatedKey"] = {
                self.id_key: last[self.id_key],
                self.partition_key: last[self.partition_key],
                "created_at": last["created_at"],
            }
        return result

    @staticmethod
    def _partition_value(expression: Any) -> str:
        # boto3 Key().eq() stores the literal in the expression object.
        values = getattr(expression, "_values", ())
        # boto3 Key expressions keep the Key object first and the literal
        # partition value last; the dependency-free fallback stores only the
        # literal. The last value works for both representations.
        return str(values[-1]) if values else ""


class DynamoPaginationTest(TestCase):
    def setUp(self) -> None:
        self.created_at = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        messages = [
            Message(
                message_id=f"message_{index:03d}",
                thread_id="thread_page",
                sender_agent_id="agent_sender",
                recipient_agent_ids=("agent_recipient",),
                intent="message",
                visibility="direct",
                content_inline=str(index),
                created_at=self.created_at,
            )
            for index in range(105)
        ]
        deliveries = [
            Delivery(
                delivery_id=f"delivery_{index:03d}",
                message_id=f"message_{index:03d}",
                thread_id="thread_page",
                sender_agent_id="agent_sender",
                recipient_agent_id="agent_recipient",
                status=DeliveryStatus.DELIVERED,
                created_at=self.created_at,
            )
            for index in range(105)
        ]
        self.repository = DynamoDbMessageHubRepository(
            agents_table=None,
            messages_table=QueryTable(
                [message_to_item(message) for message in messages],
                partition_key="thread_id",
                id_key="message_id",
            ),
            threads_table=None,
            deliveries_table=QueryTable(
                [delivery_to_item(delivery) for delivery in deliveries],
                partition_key="recipient_agent_id",
                id_key="delivery_id",
            ),
            idempotency_table=None,
            thread_summaries_table=None,
        )

    def test_thread_cursor_pages_all_equal_timestamp_rows(self) -> None:
        seen: list[str] = []
        cursor = None
        while True:
            page = self.repository.list_thread_messages_page(
                "thread_page", limit=13, cursor=cursor
            )
            seen.extend(message.message_id for message in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

        expected: list[str] = []
        for end in range(105, 0, -13):
            expected.extend(f"message_{index:03d}" for index in range(max(0, end - 13), end))
        self.assertEqual(expected, seen)
        self.assertEqual(105, len(set(seen)))

    def test_inbox_cursor_pages_all_rows_without_requerying_from_start(self) -> None:
        seen: list[str] = []
        cursor = None
        while True:
            page = self.repository.list_deliveries_by_recipient_page(
                "agent_recipient", limit=11, cursor=cursor
            )
            seen.extend(delivery.delivery_id for delivery in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

        expected: list[str] = []
        for end in range(105, 0, -11):
            expected.extend(
                f"delivery_{index:03d}" for index in range(end - 1, max(-1, end - 12), -1)
            )
        self.assertEqual(expected, seen)
        self.assertEqual(105, len(set(seen)))

    def test_thread_cursor_uses_last_raw_item_when_timestamps_tie(self) -> None:
        messages = [
            Message(
                message_id=f"message_{index:03d}",
                thread_id="thread_tie",
                sender_agent_id="agent_sender",
                recipient_agent_ids=("agent_recipient",),
                intent="message",
                visibility="direct",
                content_inline=str(index),
                created_at=self.created_at,
            )
            for index in (1, 3, 2)
        ]
        repository = DynamoDbMessageHubRepository(
            agents_table=None,
            messages_table=QueryTable(
                [message_to_item(message) for message in messages],
                partition_key="thread_id",
                id_key="message_id",
                sort_ties_by_id=False,
            ),
            threads_table=None,
            deliveries_table=None,
            idempotency_table=None,
            thread_summaries_table=None,
        )

        first = repository.list_thread_messages_page("thread_tie", limit=2)
        second = repository.list_thread_messages_page("thread_tie", limit=2, cursor=first.next_cursor)

        self.assertEqual(["message_001", "message_003"], [item.message_id for item in first.items])
        self.assertEqual(["message_002"], [item.message_id for item in second.items])

    def test_inbox_cursor_uses_last_raw_item_when_timestamps_tie(self) -> None:
        deliveries = [
            Delivery(
                delivery_id=f"delivery_{index:03d}",
                message_id=f"message_{index:03d}",
                thread_id="thread_tie",
                sender_agent_id="agent_sender",
                recipient_agent_id="agent_recipient",
                status=DeliveryStatus.DELIVERED,
                created_at=self.created_at,
            )
            for index in (1, 3, 2)
        ]
        repository = DynamoDbMessageHubRepository(
            agents_table=None,
            messages_table=None,
            threads_table=None,
            deliveries_table=QueryTable(
                [delivery_to_item(delivery) for delivery in deliveries],
                partition_key="recipient_agent_id",
                id_key="delivery_id",
                sort_ties_by_id=False,
            ),
            idempotency_table=None,
            thread_summaries_table=None,
        )

        first = repository.list_deliveries_by_recipient_page("agent_recipient", limit=2)
        second = repository.list_deliveries_by_recipient_page(
            "agent_recipient", limit=2, cursor=first.next_cursor
        )

        self.assertEqual(["delivery_001", "delivery_003"], [item.delivery_id for item in first.items])
        self.assertEqual(["delivery_002"], [item.delivery_id for item in second.items])
