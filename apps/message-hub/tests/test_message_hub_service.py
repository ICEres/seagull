from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count
from unittest import TestCase

from message_hub.domain import DeliveryStatus, ForbiddenDeliveryError, MessageHubService, MessageRef, NotFoundError
from message_hub.storage import InMemoryMessageHubRepository


class DeterministicIds:
    def __init__(self) -> None:
        self._counts: dict[str, count] = {}

    def __call__(self, prefix: str) -> str:
        if prefix not in self._counts:
            self._counts[prefix] = count(1)
        return f"{prefix}_{next(self._counts[prefix])}"


class DeterministicClock:
    def __init__(self) -> None:
        self._base = datetime(2026, 6, 12, tzinfo=timezone.utc)
        self._ticks = count()

    def __call__(self) -> datetime:
        return self._base + timedelta(seconds=next(self._ticks))


class MessageHubServiceTest(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMessageHubRepository()
        self.service = MessageHubService(
            self.repository,
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
        )
        self.sender = self.service.register_agent("@researcher:gulls.ai")
        self.recipient = self.service.register_agent("@reviewer:gulls.ai")
        self.map_reader = self.service.register_agent("@map-reader:gulls.ai")

    def test_send_message_creates_thread_delivery_and_context(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Please review this plan.",
            intent="post",
        )

        self.assertEqual("message_1", result.message.message_id)
        self.assertEqual("thread_1", result.thread.thread_id)
        self.assertEqual(1, result.thread.message_count)
        self.assertEqual({self.sender.agent_id, self.recipient.agent_id}, set(result.thread.participants))
        self.assertEqual(1, len(result.deliveries))
        self.assertEqual(DeliveryStatus.DELIVERED, result.deliveries[0].status)

        inbox = self.service.get_inbox("@reviewer:gulls.ai")
        self.assertEqual(1, len(inbox))
        self.assertEqual(result.message, inbox[0].message)

        context = self.service.get_thread_context(result.thread.thread_id)
        self.assertIsNone(context.summary)
        self.assertEqual((result.message,), context.recent_messages)

    def test_context_pack_applies_budget_and_redacts_private_refs(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="abcdefghijklmnopqrstuvwxyz",
            content_ref="payload://thread_1/message_1/full",
            refs=(
                MessageRef(type="url", url="https://example.com/context", remember_as="public link"),
                MessageRef(type="mcp", url="mcp://private-tools.local/session"),
            ),
        )
        self.service.save_thread_summary(
            result.thread.thread_id,
            "Compact summary.",
            content_ref="payload://thread_1/summary",
        )

        context_pack = self.service.get_context_pack(
            result.thread.thread_id,
            requester_handle="@reviewer:gulls.ai",
            max_inline_chars=8,
            max_recent_messages=5,
            max_payload_refs=5,
            token_budget_estimate=1000,
        )

        self.assertEqual("context_pack_thread_1_agent_2", context_pack.context_pack_id)
        self.assertEqual("@reviewer:gulls.ai", context_pack.requester_handle)
        self.assertEqual("abcdefgh", context_pack.recent_messages[0].content_inline)
        self.assertTrue(context_pack.budget.truncated)
        self.assertEqual(8, context_pack.budget.inline_chars_used)
        self.assertEqual(("payload://thread_1/message_1/full", "payload://thread_1/summary"), tuple(
            ref.content_ref for ref in context_pack.payload_refs
        ))
        self.assertEqual(("https://example.com/context",), tuple(ref.url for ref in context_pack.selected_refs))
        self.assertIn("message://message_1/ref", context_pack.redacted_refs)
        self.assertEqual(("@researcher:gulls.ai", "@reviewer:gulls.ai"), context_pack.allowed_recipients)

    def test_context_pack_requires_thread_participant(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Private thread.",
        )

        with self.assertRaises(ForbiddenDeliveryError):
            self.service.get_context_pack(
                result.thread.thread_id,
                requester_handle="@map-reader:gulls.ai",
            )

    def test_reply_updates_existing_thread(self) -> None:
        first = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="First message.",
        )
        reply = self.service.send_message(
            sender_handle="@reviewer:gulls.ai",
            recipient_handles=["@researcher:gulls.ai"],
            content="Reply message.",
            thread_id=first.thread.thread_id,
        )

        self.assertEqual(first.thread.thread_id, reply.thread.thread_id)
        self.assertEqual(2, reply.thread.message_count)
        self.assertEqual(reply.message.message_id, reply.thread.last_message_id)

        messages = self.service.get_thread(first.thread.thread_id)
        self.assertEqual(["message_1", "message_2"], [message.message_id for message in messages])

    def test_idempotency_key_returns_existing_message(self) -> None:
        first = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Only send once.",
            idempotency_key="client-send-1",
        )
        second = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Only send once.",
            idempotency_key="client-send-1",
        )

        self.assertEqual(first.message.message_id, second.message.message_id)
        self.assertEqual(1, len(self.service.get_thread(first.thread.thread_id)))
        self.assertEqual(1, len(self.service.get_inbox("@reviewer:gulls.ai")))

    def test_ack_message_updates_delivery(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Ack this.",
        )

        updated = self.service.ack_message(
            result.message.message_id,
            recipient_handle="@reviewer:gulls.ai",
        )

        self.assertEqual(1, len(updated))
        self.assertEqual(DeliveryStatus.ACKED, updated[0].status)
        self.assertIsNotNone(updated[0].acked_at)
        self.assertEqual(DeliveryStatus.ACKED, self.service.get_inbox("@reviewer:gulls.ai")[0].delivery.status)

    def test_public_post_can_have_no_delivery(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            content="Public hello.",
            intent="post",
            visibility="public",
        )

        self.assertEqual((), result.deliveries)
        self.assertEqual(1, len(self.service.get_thread(result.thread.thread_id)))
        self.assertEqual((result.message,), self.service.get_sent_messages("@researcher:gulls.ai"))

        with self.assertRaises(NotFoundError):
            self.service.ack_message(result.message.message_id)

    def test_routing_rule_copies_matching_url_to_helper_agent(self) -> None:
        self.service.add_routing_rule(
            name="Map links",
            route_to_handles=["@map-reader:gulls.ai"],
            mode="copy",
            url_contains=["maps.google.com"],
        )

        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Can you check this place?",
            refs=(
                MessageRef(
                    type="url",
                    url="https://maps.google.com/example",
                    find="identify_place",
                    remember_as="possible meeting place",
                ),
            ),
        )

        self.assertEqual(
            {self.recipient.agent_id, self.map_reader.agent_id},
            set(result.message.recipient_agent_ids),
        )
        self.assertEqual(2, len(result.deliveries))
        self.assertEqual("Can you check this place?", result.message.content_inline)
        self.assertEqual("route.resolve", result.deliveries[0].workflow_trace[0].hook)
        self.assertEqual("copy", result.deliveries[0].workflow_trace[0].action)

    def test_hook_result_updates_delivery_current_message_not_original(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Can you check this?",
        )

        updated = self.service.apply_hook_result(
            result.deliveries[0].delivery_id,
            hook="receive.before",
            runtime="cloud_node",
            actor="@reviewer:gulls.ai",
            content="Can you check this map link?",
            refs=(
                MessageRef(
                    type="url",
                    url="https://maps.google.com/example",
                    find="identify_place_or_route",
                ),
            ),
        )

        self.assertEqual("Can you check this?", result.message.content_inline)
        self.assertEqual("Can you check this?", self.service.get_thread(result.thread.thread_id)[0].content_inline)
        self.assertEqual("Can you check this map link?", updated.current_content_inline)
        self.assertEqual("agent.wait", updated.current_stage)
        self.assertEqual(("current_content_inline", "refs"), updated.workflow_trace[-1].changed)

    def test_agent_reply_decision_creates_reply_and_marks_delivery(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Please inspect this.",
        )

        decision = self.service.decide_delivery(
            result.deliveries[0].delivery_id,
            agent_handle="@reviewer:gulls.ai",
            decision="reply",
            content="Inspected. Looks fine.",
        )

        self.assertEqual(DeliveryStatus.REPLIED, decision.delivery.status)
        self.assertEqual("done", decision.delivery.current_stage)
        self.assertIsNotNone(decision.reply)
        self.assertEqual(result.thread.thread_id, decision.reply.thread.thread_id)

        messages = self.service.get_thread(result.thread.thread_id)
        self.assertEqual(["Please inspect this.", "Inspected. Looks fine."], [message.content_inline for message in messages])

    def test_agent_action_decision_creates_pending_action_request(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Open this URL when approved.",
        )

        decision = self.service.decide_delivery(
            result.deliveries[0].delivery_id,
            agent_handle="@reviewer:gulls.ai",
            decision="action",
            action_type="open_url",
            action_target="https://example.com",
            action_runtime="cloud_node",
        )

        self.assertEqual(DeliveryStatus.PENDING_ACTION, decision.delivery.status)
        self.assertEqual("action.before", decision.delivery.current_stage)
        self.assertIsNotNone(decision.action_request)
        self.assertEqual("cloud_node", decision.action_request.runtime)
        self.assertTrue(decision.action_request.requires_approval)

    def test_agent_cannot_decide_another_agents_delivery(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Private delivery.",
        )

        with self.assertRaises(ForbiddenDeliveryError):
            self.service.decide_delivery(
                result.deliveries[0].delivery_id,
                agent_handle="@map-reader:gulls.ai",
                decision="ignore",
            )
