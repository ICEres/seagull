from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

from message_hub.api import ApiError, LocalMessageHubApi
from message_hub.domain import DeliveryStatus, MessageHubService
from message_hub.domain.models import Delivery, Message, ThreadRecord
from message_hub.storage import InMemoryMessageHubRepository


class MessagePaginationTest(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMessageHubRepository()
        self.service = MessageHubService(self.repository)
        self.sender = self.service.register_agent("@sender:gulls.ai")
        self.recipient = self.service.register_agent("@recipient:gulls.ai")
        self.api = LocalMessageHubApi(self.service)

    def test_thread_pages_are_stable_with_equal_timestamps_and_more_than_one_hundred_rows(self) -> None:
        created_at = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        thread = ThreadRecord(
            thread_id="thread_page",
            root_message_id="message_000",
            participants=frozenset({self.sender.agent_id, self.recipient.agent_id}),
            message_count=105,
            last_message_id="message_104",
            last_message_at=created_at,
            created_at=created_at,
            updated_at=created_at,
        )
        self.repository.put_thread(thread)
        for index in range(105):
            self.repository.put_message(
                Message(
                    message_id=f"message_{index:03d}",
                    thread_id=thread.thread_id,
                    sender_agent_id=self.sender.agent_id,
                    recipient_agent_ids=(self.recipient.agent_id,),
                    intent="message",
                    visibility="direct",
                    content_inline=str(index),
                    created_at=created_at,
                )
            )

        seen: list[str] = []
        cursor = None
        while True:
            page = self.api.read_thread(thread.thread_id, limit=17, cursor=cursor)
            seen.extend(message["message_id"] for message in page["messages"])
            cursor = page.get("next_cursor")
            if cursor is None:
                break

        self.assertEqual(105, len(seen))
        self.assertEqual(len(seen), len(set(seen)))
        expected: list[str] = []
        for end in range(105, 0, -17):
            start = max(0, end - 17)
            expected.extend(f"message_{i:03d}" for i in range(start, end))
        self.assertEqual(expected, seen)

    def test_inbox_pages_filter_held_deliveries_without_skipping_visible_rows(self) -> None:
        created_at = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        for index in range(8):
            message_id = f"message_{index:03d}"
            delivery_id = f"delivery_{index:03d}"
            self.repository.put_message(
                Message(
                    message_id=message_id,
                    thread_id=f"thread_{index:03d}",
                    sender_agent_id=self.sender.agent_id,
                    recipient_agent_ids=(self.recipient.agent_id,),
                    intent="message",
                    visibility="direct",
                    content_inline=str(index),
                    created_at=created_at,
                )
            )
            self.repository.put_delivery(
                Delivery(
                    delivery_id=delivery_id,
                    message_id=message_id,
                    thread_id=f"thread_{index:03d}",
                    sender_agent_id=self.sender.agent_id,
                    recipient_agent_id=self.recipient.agent_id,
                    status=DeliveryStatus.NEEDS_REVIEW if index in {1, 3, 5} else DeliveryStatus.DELIVERED,
                    created_at=created_at,
                )
            )

        first = self.api.read_inbox(self.recipient.handle, limit=2)
        second = self.api.read_inbox(
            self.recipient.handle,
            limit=2,
            cursor=first["next_cursor"],
        )
        self.assertEqual(["delivery_007", "delivery_006"], [item["delivery"]["delivery_id"] for item in first["items"]])
        self.assertEqual(["delivery_004", "delivery_002"], [item["delivery"]["delivery_id"] for item in second["items"]])

    def test_cursor_cannot_cross_thread_or_inbox_scope(self) -> None:
        created_at = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        thread = ThreadRecord(
            thread_id="thread_scope",
            root_message_id="message_scope",
            participants=frozenset({self.sender.agent_id, self.recipient.agent_id}),
            message_count=1,
            last_message_id="message_scope",
            last_message_at=created_at,
            created_at=created_at,
            updated_at=created_at,
        )
        self.repository.put_thread(thread)
        self.repository.put_message(
            Message(
                message_id="message_scope",
                thread_id=thread.thread_id,
                sender_agent_id=self.sender.agent_id,
                recipient_agent_ids=(self.recipient.agent_id,),
                intent="message",
                visibility="direct",
                content_inline="scope",
                created_at=created_at,
            )
        )
        cursor = self.api.read_thread(thread.thread_id, limit=1).get("next_cursor")
        self.assertIsNone(cursor)

        # A syntactically valid inbox cursor must not be accepted by a thread.
        from message_hub.storage.pagination import encode_cursor

        inbox_cursor = encode_cursor(
            kind="inbox",
            scope=self.recipient.agent_id,
            created_at=created_at,
            record_id="delivery_missing",
        )
        with self.assertRaises(ApiError) as raised:
            self.api.read_thread(thread.thread_id, cursor=inbox_cursor)
        self.assertEqual(400, raised.exception.status_code)

        with self.assertRaises(ApiError) as raised:
            self.api.read_thread(thread.thread_id, cursor="not-a-cursor")
        self.assertEqual(400, raised.exception.status_code)
