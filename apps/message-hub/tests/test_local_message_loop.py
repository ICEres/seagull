from __future__ import annotations

import json
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

    def test_local_api_returns_budgeted_context_pack(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})
        post = self.api.create_message(
            {
                "sender_handle": "@researcher:seagull.local",
                "recipient_handles": ["@reviewer:seagull.local"],
                "content": "large context should be clipped",
                "content_ref": "payload://thread_1/message_1/full",
                "refs": [
                    {"type": "url", "url": "https://example.com/public"},
                    {"type": "mcp", "url": "mcp://private.local/session"},
                    {"type": "tool", "url": "tool://raw/private-browser"},
                    {"type": "url", "url": "http://localhost:8080/private-callback"},
                    {"type": "url", "url": "https://example.com/private?token=secret-token"},
                ],
            }
        )

        context_pack = self.api.read_context_pack(
            post["thread_id"],
            requester_handle="@reviewer:seagull.local",
            max_inline_chars=5,
            max_recent_messages=2,
            max_payload_refs=3,
        )

        self.assertEqual("context_pack_thread_1_agent_2", context_pack["context_pack_id"])
        self.assertEqual("large", context_pack["recent_messages"][0]["content_inline"])
        self.assertTrue(context_pack["budget"]["truncated"])
        self.assertEqual(["payload://thread_1/message_1/full"], [
            ref["content_ref"] for ref in context_pack["payload_refs"]
        ])
        self.assertEqual(["https://example.com/public"], [ref["url"] for ref in context_pack["selected_refs"]])
        self.assertEqual(
            [
                "message://message_1/content_inline",
                "message://message_1/ref",
                "message://message_1/ref",
                "message://message_1/ref",
                "message://message_1/ref",
            ],
            context_pack["redacted_refs"],
        )

        serialized = json.dumps(context_pack, sort_keys=True)
        self.assertNotIn("mcp://", serialized)
        self.assertNotIn("localhost", serialized)
        self.assertNotIn("tool://", serialized)
        self.assertNotIn("secret-token", serialized)

    def test_local_api_stores_large_payload_and_sends_ref(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})
        large_content = "Large payload.\n" * 500

        payload = self.api.create_payload(
            {
                "content": large_content,
                "media_type": "text/markdown",
                "access_scope": "thread",
            }
        )
        post = self.api.create_message(
            {
                "sender_handle": "@researcher:seagull.local",
                "recipient_handles": ["@reviewer:seagull.local"],
                "content_ref": payload["content_ref"],
            }
        )
        inbox = self.api.read_inbox("@reviewer:seagull.local")
        fetched = self.api.read_payload(payload["content_ref"])
        context_pack = self.api.read_context_pack(
            post["thread_id"],
            requester_handle="@reviewer:seagull.local",
        )

        self.assertEqual("payload://payload_1", payload["content_ref"])
        self.assertEqual("gzip", payload["payload"]["compression"])
        self.assertEqual("ready", payload["payload"]["retention_state"])
        self.assertEqual("thread", payload["payload"]["access_scope"])
        self.assertEqual("local_node", payload["payload"]["storage_provider"])
        self.assertEqual(payload["content_ref"], payload["payload"]["storage_ref"])
        self.assertLess(payload["payload"]["compressed_byte_length"], payload["payload"]["byte_length"])
        self.assertIsNone(post["message"]["content_inline"])
        self.assertEqual(payload["content_ref"], post["message"]["content_ref"])
        self.assertIsNone(post["deliveries"][0]["current_content_inline"])
        self.assertEqual(payload["content_ref"], inbox["items"][0]["current_message"]["content_ref"])
        self.assertEqual(large_content, fetched["content"])
        self.assertEqual(large_content.encode("utf-8"), fetched["content_bytes"])
        self.assertEqual([payload["content_ref"]], [ref["content_ref"] for ref in context_pack["payload_refs"]])

    def test_local_api_public_agent_profile_redacts_private_runtime_fields(self) -> None:
        result = self.api.register_agent(
            {
                "handle": "@runner:seagull.local",
                "display_name": "Runner",
                "capabilities": [
                    "repo_read",
                    "mcp://private.local/session",
                    "raw_tool:browser",
                    "http://localhost:8100/callback",
                ],
                "response_rules": {
                    "schema_version": "seagull.response_rules.v1",
                    "persona": "Use repo context.",
                    "ask_human_triggers": ["external_action", "bearer secret-token"],
                    "prohibited_behavior": ["send_without_approval"],
                },
                "trigger_mode": "webhook",
                "webhook_url": "https://runner.example.com/seagull",
            }
        )

        agent = result["agent"]
        self.assertEqual(["repo_read"], agent["capabilities"])
        self.assertEqual(["external_action"], agent["response_rules"]["ask_human_triggers"])
        self.assertNotIn("webhook_url", agent)
        self.assertTrue(agent["webhook_enabled"])

        serialized = json.dumps(agent, sort_keys=True)
        self.assertNotIn("mcp://", serialized)
        self.assertNotIn("raw_tool", serialized)
        self.assertNotIn("localhost", serialized)
        self.assertNotIn("secret-token", serialized)

    def test_local_api_manages_delegated_task_records(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})

        task_response = self.api.create_task(
            {
                "requester_handle": "@researcher:seagull.local",
                "recipient_handle": "@reviewer:seagull.local",
                "objective": "Review the referenced plan.",
                "context_refs": ["thread://thread_1"],
                "input_ref": "payload://task_1/input",
                "allowed_tool_names": ["repo_read"],
                "allowed_use_terms": ["no_memory"],
            }
        )

        self.assertEqual("task_1", task_response["task_id"])
        self.assertEqual("requested", task_response["task"]["state"])
        self.assertEqual("message_1", task_response["task"]["request_message_id"])
        self.assertIsNone(task_response["task"]["stream_id"])
        inbox = self.api.read_inbox("@reviewer:seagull.local")
        self.assertIsNone(inbox["items"][0]["message"]["content_inline"])
        self.assertEqual("task_request", inbox["items"][0]["message"]["intent"])
        self.assertEqual("seagull://tasks/task_1", inbox["items"][0]["message"]["refs"][0]["url"])

        accepted = self.api.accept_task(
            "task_1",
            {
                "worker_handle": "@reviewer:seagull.local",
                "note": "Accepted.",
            },
        )
        self.assertEqual("accepted", accepted["state"])

        tool_request = self.api.create_tool_request(
            "task_1",
            {
                "requester_handle": "@researcher:seagull.local",
                "worker_handle": "@reviewer:seagull.local",
                "tool_name": "repo_read",
                "purpose": "Read requested files only.",
                "requires_approval": True,
                "approval_id": "approval_1",
                "policy_decision_id": "policy_1",
            },
        )
        self.assertEqual("tool_request_1", tool_request["tool_request_id"])
        self.assertEqual("needs_approval", tool_request["tool_request"]["status"])

        completed_tool = self.api.complete_tool_request(
            "tool_request_1",
            {
                "actor_handle": "@reviewer:seagull.local",
                "state": "completed",
                "result_ref": "payload://task_1/tool_result",
            },
        )
        self.assertEqual("completed", completed_tool["state"])

        result = self.api.return_task_result(
            "task_1",
            {
                "responder_handle": "@reviewer:seagull.local",
                "content": "Done.",
                "content_ref": "payload://task_1/result",
                "artifact_refs": ["artifact://review"],
            },
        )
        self.assertEqual("completed", result["state"])
        self.assertEqual("task_result_1", result["result"]["result_id"])
        self.assertIsNone(result["result"]["stream_id"])
        self.assertEqual("payload://task_1/result", result["result"]["content_ref"])

        readback = self.api.read_task("task_1")
        self.assertEqual("completed", readback["task"]["state"])
        self.assertIsNone(readback["task"]["stream_id"])
        self.assertEqual(result["result"]["result_message_id"], readback["task"]["result_message_id"])

    def test_local_api_rejects_private_task_fields(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})

        with self.assertRaises(ApiError) as error:
            self.api.create_task(
                {
                    "requester_handle": "@researcher:seagull.local",
                    "recipient_handle": "@reviewer:seagull.local",
                    "objective": "Use private runtime config.",
                    "private_prompt": "secret system prompt",
                }
            )

        self.assertEqual(400, error.exception.status_code)
        self.assertIn("private_prompt", error.exception.message)

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
