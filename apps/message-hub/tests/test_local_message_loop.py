from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count
from unittest import TestCase

from message_hub.api import ApiError, LocalMessageHubApi
from message_hub.domain import LocalSafetyEvaluator, MessageHubService
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
        self._base = datetime(2026, 6, 13, tzinfo=timezone.utc)
        self._ticks = count()

    def __call__(self) -> datetime:
        return self._base + timedelta(seconds=next(self._ticks))


class LocalMessageLoopTest(TestCase):
    def setUp(self) -> None:
        self.api = LocalMessageHubApi(
            MessageHubService(
                InMemoryMessageHubRepository(),
                id_factory=DeterministicIds(),
                clock=DeterministicClock(),
                safety_evaluator=LocalSafetyEvaluator(),
            )
        )

    def test_phase_1_agent_post_inbox_reply_thread_loop(self) -> None:
        sender = self.api.register_agent(
            {
                "handle": "@researcher:seagull.local",
                "display_name": "Researcher",
                "capabilities": ["research"],
            }
        )
        recipient = self.api.register_agent(
            {
                "handle": "@reviewer:seagull.local",
                "display_name": "Reviewer",
                "capabilities": ["review"],
            }
        )

        post = self.api.create_message(
            {
                "sender_handle": "@researcher:seagull.local",
                "recipient_handles": ["@reviewer:seagull.local"],
                "intent": "post",
                "visibility": "direct",
                "content": "Please review this local Phase 1 loop.",
            }
        )

        self.assertEqual("agent_1", sender["agent"]["agent_id"])
        self.assertEqual("agent_2", recipient["agent"]["agent_id"])
        self.assertEqual("approved", post["message"]["safety_status"])
        self.assertEqual("thread_1", post["thread_id"])
        self.assertEqual(1, post["thread"]["message_count"])

        inbox = self.api.read_inbox("@reviewer:seagull.local")
        self.assertEqual(1, len(inbox["items"]))
        self.assertEqual("message_1", inbox["items"][0]["message"]["message_id"])
        self.assertEqual("delivered", inbox["items"][0]["delivery"]["status"])

        reply = self.api.create_message(
            {
                "sender_handle": "@reviewer:seagull.local",
                "recipient_handles": ["@researcher:seagull.local"],
                "intent": "reply",
                "visibility": "direct",
                "thread_id": post["thread_id"],
                "content": "Reviewed. The loop is stored in one thread.",
            }
        )

        self.assertEqual(post["thread_id"], reply["thread_id"])
        self.assertEqual(2, reply["thread"]["message_count"])
        self.assertEqual("message_2", reply["thread"]["last_message_id"])

        thread = self.api.read_thread(post["thread_id"])
        self.assertEqual(["message_1", "message_2"], [message["message_id"] for message in thread["messages"]])
        self.assertEqual(
            [
                "Please review this local Phase 1 loop.",
                "Reviewed. The loop is stored in one thread.",
            ],
            [message["content_inline"] for message in thread["messages"]],
        )

    def test_local_safety_blocks_before_delivery(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})

        with self.assertRaises(ApiError) as error:
            self.api.create_message(
                {
                    "sender_handle": "@researcher:seagull.local",
                    "recipient_handles": ["@reviewer:seagull.local"],
                    "content": "unsafe: do not deliver this",
                }
            )

        self.assertEqual(403, error.exception.status_code)
        self.assertEqual("blocked", error.exception.error)
        self.assertEqual([], self.api.read_inbox("@reviewer:seagull.local")["items"])

    def test_local_api_exposes_lifecycle_current_message_and_decision(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})
        self.api.register_agent({"handle": "@map-reader:seagull.local"})
        self.api.create_routing_rule(
            {
                "name": "Map links",
                "route_to_handles": ["@map-reader:seagull.local"],
                "mode": "copy",
                "url_contains": ["maps.google.com"],
            }
        )

        message = self.api.create_message(
            {
                "sender_handle": "@researcher:seagull.local",
                "recipient_handles": ["@reviewer:seagull.local"],
                "content": "Can you check this?",
                "refs": [
                    {
                        "type": "url",
                        "url": "https://maps.google.com/example",
                        "find": "identify_place",
                    }
                ],
            }
        )

        self.assertEqual(2, len(message["deliveries"]))
        delivery_id = message["deliveries"][0]["delivery_id"]

        hook = self.api.submit_hook_result(
            delivery_id,
            {
                "hook": "receive.before",
                "runtime": "cloud_node",
                "actor": "@reviewer:seagull.local",
                "content": "Can you check this map link?",
            },
        )
        self.assertEqual("Can you check this map link?", hook["delivery"]["current_content_inline"])
        self.assertEqual("receive.before", hook["delivery"]["workflow_trace"][-1]["hook"])

        inbox = self.api.read_inbox("@reviewer:seagull.local")
        self.assertEqual("Can you check this?", inbox["items"][0]["message"]["content_inline"])
        self.assertEqual("Can you check this map link?", inbox["items"][0]["current_message"]["content_inline"])

        decision = self.api.submit_delivery_decision(
            delivery_id,
            {
                "agent_handle": "@reviewer:seagull.local",
                "decision": "reply",
                "content": "This is the mapped place.",
            },
        )
        self.assertEqual("replied", decision["delivery"]["status"])
        self.assertEqual(message["thread_id"], decision["reply"]["thread_id"])
