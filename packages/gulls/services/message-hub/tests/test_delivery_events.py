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
                resolve_host=public_resolver,
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
                resolve_host=public_resolver,
            )

        delivery = tables.deliveries.items["delivery_1"]
        self.assertEqual("failed", delivery["trigger_status"])
        self.assertEqual(1, delivery["retry_count"])
        self.assertIn("503", delivery["last_error"])

    def test_worker_dispatches_to_vetted_resolved_ip(self) -> None:
        worker = load_agent_worker()
        calls: list[object] = []
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

        worker.handle_delivery_event(
            {"data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda endpoint, body, headers: calls.append(endpoint) or 204,
            signing_secret="dev-secret",
            resolve_host=lambda host, port: ["8.8.8.8"],
        )

        self.assertEqual(1, len(calls))
        endpoint = calls[0]
        self.assertEqual("8.8.8.8", endpoint.address)
        self.assertEqual("runner.example.com", endpoint.host_header)
        self.assertEqual("/seagull", endpoint.request_target)
        self.assertEqual("sent", tables.deliveries.items["delivery_1"]["trigger_status"])

    def test_worker_blocks_metadata_webhook_url_without_dispatch(self) -> None:
        worker = load_agent_worker()
        calls: list[str] = []
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
            agents={"agent_2": {"agent_id": "agent_2", "webhook_url": "http://169.254.169.254/latest/meta-data"}},
        )

        worker.handle_delivery_event(
            {"data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda url, body, headers: calls.append(url) or 204,
            signing_secret="dev-secret",
        )

        delivery = tables.deliveries.items["delivery_1"]
        self.assertEqual([], calls)
        self.assertEqual("failed", delivery["trigger_status"])
        self.assertIn("must use https", delivery["last_error"])

    def test_worker_blocks_dns_private_address_without_dispatch(self) -> None:
        worker = load_agent_worker()
        calls: list[str] = []
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

        worker.handle_delivery_event(
            {"data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda url, body, headers: calls.append(url) or 204,
            signing_secret="dev-secret",
            resolve_host=lambda host, port: ["10.0.0.5"],
        )

        delivery = tables.deliveries.items["delivery_1"]
        self.assertEqual([], calls)
        self.assertEqual("failed", delivery["trigger_status"])
        self.assertIn("non-public address", delivery["last_error"])

    def test_worker_requires_signing_secret(self) -> None:
        worker = load_agent_worker()
        calls: list[str] = []
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

        worker.handle_delivery_event(
            {"data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda url, body, headers: calls.append(url) or 204,
            signing_secret="",
            resolve_host=public_resolver,
        )

        delivery = tables.deliveries.items["delivery_1"]
        self.assertEqual([], calls)
        self.assertEqual("failed", delivery["trigger_status"])
        self.assertIn("signing secret", delivery["last_error"])

    def test_worker_rejects_placeholder_signing_secret(self) -> None:
        worker = load_agent_worker()
        calls: list[str] = []
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

        worker.handle_delivery_event(
            {"data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda url, body, headers: calls.append(url) or 204,
            signing_secret="dev-only-change-me",
            resolve_host=public_resolver,
        )

        delivery = tables.deliveries.items["delivery_1"]
        self.assertEqual([], calls)
        self.assertEqual("failed", delivery["trigger_status"])
        self.assertIn("insecure development placeholder", delivery["last_error"])


class AgentWorkerSocketPushTest(TestCase):
    def make_tables(self, *, trigger_mode: str = "manual", webhook_url: str | None = None) -> "FakeTables":
        agent: dict[str, object] = {"agent_id": "agent_2", "trigger_mode": trigger_mode}
        if webhook_url is not None:
            agent["webhook_url"] = webhook_url
        return FakeTables(
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
            agents={"agent_2": agent},
        )

    def test_manual_recipient_gets_socket_push_without_trigger_status(self) -> None:
        worker = load_agent_worker()
        tables = self.make_tables(trigger_mode="manual")
        connections = FakeConnectionsTable(
            [
                {"connection_id": "conn_1", "agent_id": "agent_2"},
                {"connection_id": "conn_2", "agent_id": "agent_2"},
                {"connection_id": "conn_other", "agent_id": "agent_9"},
            ]
        )
        management = FakeManagementClient()
        webhook_calls: list[object] = []

        worker.handle_delivery_event(
            {"type": "seagull.delivery.created.v1", "data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda url, body, headers: webhook_calls.append(url) or 204,
            signing_secret="test-secret",
            connections_table=connections,
            management_client=management,
        )

        self.assertEqual(["conn_1", "conn_2"], [connection_id for connection_id, _ in management.posted])
        self.assertEqual([], webhook_calls)
        delivery = tables.deliveries.items["delivery_1"]
        self.assertNotIn("trigger_status", delivery)
        self.assertNotIn("last_error", delivery)
        self.assertEqual(0, delivery["retry_count"])

    def test_manual_recipient_without_push_config_is_a_no_op(self) -> None:
        worker = load_agent_worker()
        tables = self.make_tables(trigger_mode="manual")

        worker.handle_delivery_event(
            {"data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda url, body, headers: 204,
            signing_secret="test-secret",
        )

        delivery = tables.deliveries.items["delivery_1"]
        self.assertNotIn("trigger_status", delivery)
        self.assertNotIn("last_error", delivery)

    def test_gone_connection_is_deleted(self) -> None:
        worker = load_agent_worker()
        tables = self.make_tables(trigger_mode="manual")
        connections = FakeConnectionsTable(
            [
                {"connection_id": "conn_gone", "agent_id": "agent_2"},
                {"connection_id": "conn_live", "agent_id": "agent_2"},
            ]
        )
        management = FakeManagementClient(gone={"conn_gone"})

        worker.handle_delivery_event(
            {"data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda url, body, headers: 204,
            signing_secret="test-secret",
            connections_table=connections,
            management_client=management,
        )

        self.assertEqual(["conn_gone"], connections.deleted)
        self.assertEqual(["conn_live"], [connection_id for connection_id, _ in management.posted])

    def test_socket_push_failure_never_raises(self) -> None:
        worker = load_agent_worker()
        tables = self.make_tables(trigger_mode="manual")
        connections = FakeConnectionsTable([{"connection_id": "conn_1", "agent_id": "agent_2"}])
        management = FakeManagementClient(fail=True)

        worker.handle_delivery_event(
            {"data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda url, body, headers: 204,
            signing_secret="test-secret",
            connections_table=connections,
            management_client=management,
        )

        delivery = tables.deliveries.items["delivery_1"]
        self.assertNotIn("trigger_status", delivery)

    def test_webhook_recipient_gets_socket_push_and_webhook(self) -> None:
        worker = load_agent_worker()
        tables = self.make_tables(trigger_mode="webhook", webhook_url="https://runner.example.com/seagull")
        connections = FakeConnectionsTable([{"connection_id": "conn_1", "agent_id": "agent_2"}])
        management = FakeManagementClient()
        webhook_calls: list[object] = []

        worker.handle_delivery_event(
            {"type": "seagull.delivery.created.v1", "data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda endpoint, body, headers: webhook_calls.append(endpoint) or 204,
            signing_secret="test-secret",
            resolve_host=public_resolver,
            connections_table=connections,
            management_client=management,
        )

        self.assertEqual(1, len(management.posted))
        self.assertEqual(1, len(webhook_calls))
        self.assertEqual("sent", tables.deliveries.items["delivery_1"]["trigger_status"])

    def test_already_sent_delivery_skips_socket_push(self) -> None:
        worker = load_agent_worker()
        tables = self.make_tables(trigger_mode="manual")
        tables.deliveries.items["delivery_1"]["trigger_status"] = "sent"
        connections = FakeConnectionsTable([{"connection_id": "conn_1", "agent_id": "agent_2"}])
        management = FakeManagementClient()

        worker.handle_delivery_event(
            {"data": {"delivery_id": "delivery_1"}},
            tables=tables,
            http_post=lambda url, body, headers: 204,
            signing_secret="test-secret",
            connections_table=connections,
            management_client=management,
        )

        self.assertEqual([], management.posted)


class FakeConnectionsTable:
    def __init__(self, items: list[dict[str, str]]) -> None:
        self.items = items
        self.deleted: list[str] = []

    def query(self, *, IndexName: str, KeyConditionExpression: str, ExpressionAttributeValues: dict[str, str]) -> dict[str, object]:
        assert IndexName == "agent-index"
        agent_id = ExpressionAttributeValues[":agent_id"]
        return {"Items": [item for item in self.items if item["agent_id"] == agent_id]}

    def delete_item(self, *, Key: dict[str, str]) -> None:
        self.deleted.append(Key["connection_id"])


class FakeGoneError(Exception):
    def __init__(self) -> None:
        super().__init__("gone")
        self.response = {"Error": {"Code": "GoneException"}}


class FakeManagementClient:
    def __init__(self, *, gone: set[str] | None = None, fail: bool = False) -> None:
        self.posted: list[tuple[str, bytes]] = []
        self.gone = gone or set()
        self.fail = fail

    def post_to_connection(self, *, ConnectionId: str, Data: bytes) -> None:
        if ConnectionId in self.gone:
            raise FakeGoneError()
        if self.fail:
            raise RuntimeError("post_to_connection failed")
        self.posted.append((ConnectionId, Data))


def load_agent_worker():
    path = Path(__file__).resolve().parents[1] / "aws" / "agent_worker.py"
    spec = importlib.util.spec_from_file_location("agent_worker_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load agent worker module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_resolver(host: str, port: int | None) -> list[str]:
    return ["8.8.8.8"]


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
