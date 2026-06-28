from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from unittest import TestCase

from message_hub.api import ApiError, LocalMessageHubApi
from message_hub.domain import (
    DELIVERY_CREATED_EVENT_TYPE,
    MAX_ENVELOPE_INLINE_CHARS,
    MessageHubService,
    sign_webhook_body,
)
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
        self._base = datetime(2026, 6, 14, tzinfo=timezone.utc)
        self._ticks = count()

    def __call__(self) -> datetime:
        return self._base + timedelta(seconds=next(self._ticks))


class DeliveryEventTest(TestCase):
    def test_registering_webhook_agent_returns_safe_public_config(self) -> None:
        api = LocalMessageHubApi.in_memory()
        response_rules = {
            "schema_version": "seagull.response_rules.v1",
            "persona": "Pragmatic runner.",
            "style": "Short and factual.",
            "reply_posture": "draft_reply",
            "max_reply_chars": 1200,
            "ask_human_triggers": ["external_action"],
            "prohibited_behavior": ["send_without_approval"],
        }

        result = api.register_agent(
            {
                "handle": "@runner:gulls.ai",
                "trigger_mode": "webhook",
                "webhook_url": "https://runner.example.com/seagull",
                "response_rules": response_rules,
            }
        )

        self.assertEqual("webhook", result["agent"]["trigger_mode"])
        self.assertTrue(result["agent"]["webhook_enabled"])
        self.assertEqual(response_rules, result["agent"]["response_rules"])
        self.assertNotIn("webhook_url", result["agent"])

    def test_agent_response_rules_reject_private_config_fields(self) -> None:
        api = LocalMessageHubApi.in_memory()

        with self.assertRaises(ApiError) as error:
            api.register_agent(
                {
                    "handle": "@runner:gulls.ai",
                    "response_rules": {
                        "schema_version": "seagull.response_rules.v1",
                        "persona": "Runner.",
                        "connector_token": "secret-token",
                    },
                }
            )

        self.assertEqual(400, error.exception.status_code)
        self.assertEqual("bad_request", error.exception.error)

    def test_webhook_mode_requires_webhook_url(self) -> None:
        api = LocalMessageHubApi.in_memory()

        with self.assertRaises(ApiError) as error:
            api.register_agent({"handle": "@runner:gulls.ai", "trigger_mode": "webhook"})

        self.assertEqual(400, error.exception.status_code)
        self.assertEqual("bad_request", error.exception.error)

    def test_manual_agent_does_not_publish_delivery_event(self) -> None:
        events: list[dict[str, object]] = []
        service = MessageHubService(
            InMemoryMessageHubRepository(),
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
            delivery_event_publisher=events.append,
        )
        service.register_agent("@sender:gulls.ai")
        service.register_agent("@manual:gulls.ai")

        service.send_message(
            sender_handle="@sender:gulls.ai",
            recipient_handles=["@manual:gulls.ai"],
            content="No webhook for this recipient.",
        )

        self.assertEqual([], events)

    def test_webhook_agent_publishes_stable_delivery_event(self) -> None:
        events: list[dict[str, object]] = []
        service = MessageHubService(
            InMemoryMessageHubRepository(),
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
            delivery_event_publisher=events.append,
        )
        service.register_agent("@sender:gulls.ai")
        service.register_agent(
            "@runner:gulls.ai",
            trigger_mode="webhook",
            webhook_url="https://runner.example.com/seagull",
        )

        result = service.send_message(
            sender_handle="@sender:gulls.ai",
            recipient_handles=["@runner:gulls.ai"],
            content="Run this from the event queue.",
            intent="task",
        )

        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual("1.0", event["specversion"])
        self.assertEqual(DELIVERY_CREATED_EVENT_TYPE, event["type"])
        self.assertEqual("event_delivery_1", event["event_id"])
        self.assertEqual("delivery_1", event["subject"])
        self.assertEqual("2026-06-14T00:00:02.000Z", event["time"])
        self.assertEqual(result.message.message_id, event["data"]["message_id"])
        self.assertEqual(
            {
                "event_id": "event_delivery_1",
                "delivery_id": "delivery_1",
                "message_id": "message_1",
                "thread_id": "thread_1",
                "sender_agent_id": "agent_1",
                "sender_handle": "@sender:gulls.ai",
                "recipient_agent_id": "agent_2",
                "recipient_handle": "@runner:gulls.ai",
                "intent": "task",
                "visibility": "direct",
                "content_inline": "Run this from the event queue.",
                "content_ref": None,
                "created_at": "2026-06-14T00:00:02.000Z",
            },
            event["data"],
        )

    def test_webhook_delivery_event_uses_ref_for_large_payload(self) -> None:
        events: list[dict[str, object]] = []
        service = MessageHubService(
            InMemoryMessageHubRepository(),
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
            delivery_event_publisher=events.append,
        )
        service.register_agent("@sender:gulls.ai")
        service.register_agent(
            "@runner:gulls.ai",
            trigger_mode="webhook",
            webhook_url="https://runner.example.com/seagull",
        )
        large_content = "x" * (MAX_ENVELOPE_INLINE_CHARS + 1)

        result = service.send_message(
            sender_handle="@sender:gulls.ai",
            recipient_handles=["@runner:gulls.ai"],
            content=large_content,
            content_ref="payload://thread_1/message_1/full",
            intent="task",
        )

        self.assertIsNone(result.message.content_inline)
        self.assertIsNone(result.deliveries[0].current_content_inline)
        self.assertEqual(1, len(events))
        event = events[0]
        self.assertIsNone(event["data"]["content_inline"])
        self.assertEqual("payload://thread_1/message_1/full", event["data"]["content_ref"])
        self.assertNotIn(large_content, json.dumps(event, sort_keys=True))

    def test_webhook_signature_is_deterministic(self) -> None:
        body = json.dumps({"hello": "seagull"}, sort_keys=True).encode("utf-8")

        first = sign_webhook_body(body, "dev-secret")
        second = sign_webhook_body(body, "dev-secret")

        self.assertEqual(first, second)
        self.assertEqual(
            "sha256=5ce6652085fed206dd0b3496570e9deaac5b66a058f5caa6e12e1a2c5ca89d0e",
            first,
        )


class AgentWorkerTest(TestCase):
    def test_worker_skips_missing_acked_and_already_sent_deliveries(self) -> None:
        worker = load_agent_worker()
        calls: list[tuple[str, bytes, dict[str, str]]] = []
        tables = FakeTables(
            deliveries={
                "acked": {"delivery_id": "acked", "status": "acked"},
                "sent": {"delivery_id": "sent", "status": "delivered", "trigger_status": "sent"},
            }
        )

        for delivery_id in ("missing", "acked", "sent"):
            worker.handle_delivery_event(
                {"data": {"delivery_id": delivery_id}},
                tables=tables,
                http_post=lambda url, body, headers: calls.append((url, body, headers)) or 204,
                signing_secret="dev-secret",
            )

        self.assertEqual([], calls)

    def test_worker_marks_failed_dispatch_retryable(self) -> None:
        worker = load_agent_worker()
        tables = FakeTables(
            deliveries={
                "delivery_1": {
                    "delivery_id": "delivery_1",
                    "message_id": "message_1",
                    "recipient_agent_id": "agent_2",
                    "status": "delivered",
                    "retry_count": 0,
                }
            },
            messages={"message_1": {"message_id": "message_1"}},
            agents={"agent_2": {"agent_id": "agent_2", "webhook_url": "https://runner.example.com/seagull"}},
        )

        with self.assertRaises(worker.RetryableDispatchError):
            worker.handle_delivery_event(
                {"data": {"delivery_id": "delivery_1"}},
                tables=tables,
                http_post=lambda url, body, headers: 503,
                signing_secret="dev-secret",
            )

        delivery = tables.deliveries.items["delivery_1"]
        self.assertEqual("failed", delivery["trigger_status"])
        self.assertEqual(1, delivery["retry_count"])
        self.assertIn("503", delivery["last_error"])


def load_agent_worker():
    path = Path(__file__).resolve().parents[1] / "aws" / "agent_worker.py"
    spec = importlib.util.spec_from_file_location("agent_worker_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load agent worker module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTables:
    def __init__(
        self,
        *,
        deliveries: dict[str, dict[str, object]] | None = None,
        messages: dict[str, dict[str, object]] | None = None,
        agents: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.deliveries = FakeTable(deliveries or {}, "delivery_id")
        self.messages = FakeTable(messages or {}, "message_id")
        self.agents = FakeTable(agents or {}, "agent_id")


class FakeTable:
    def __init__(self, items: dict[str, dict[str, object]], key_name: str) -> None:
        self.items = items
        self.key_name = key_name

    def get_item(self, *, Key: dict[str, str]) -> dict[str, dict[str, object]]:
        item = self.items.get(Key[self.key_name])
        return {} if item is None else {"Item": item}

    def update_item(
        self,
        *,
        Key: dict[str, str],
        ExpressionAttributeValues: dict[str, object],
        **kwargs: object,
    ) -> None:
        item = self.items[Key[self.key_name]]
        if ":status" in ExpressionAttributeValues:
            item["trigger_status"] = ExpressionAttributeValues[":status"]
        if ":triggered_at" in ExpressionAttributeValues:
            item["last_triggered_at"] = ExpressionAttributeValues[":triggered_at"]
        if ":error" in ExpressionAttributeValues:
            item["last_error"] = ExpressionAttributeValues[":error"]
        if ":one" in ExpressionAttributeValues:
            item["retry_count"] = int(item.get("retry_count", 0)) + int(ExpressionAttributeValues[":one"])
