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
        self.service = MessageHubService(
            InMemoryMessageHubRepository(),
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
            safety_evaluator=LocalSafetyEvaluator(),
        )
        self.api = LocalMessageHubApi(self.service)

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
        fetched = self.api.read_payload(
            payload["content_ref"],
            requester_handle="@reviewer:seagull.local",
        )
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

    def test_local_api_expired_payload_returns_gone_and_keeps_metadata(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})
        payload = self.api.create_payload(
            {
                "content": "short lived payload",
                "media_type": "text/plain",
                "ttl_expires_at": "2026-06-13T00:00:00+00:00",
            }
        )
        post = self.api.create_message(
            {
                "sender_handle": "@researcher:seagull.local",
                "recipient_handles": ["@reviewer:seagull.local"],
                "content_ref": payload["content_ref"],
            }
        )

        with self.assertRaises(ApiError) as context:
            self.api.read_payload(
                payload["content_ref"],
                requester_handle="@reviewer:seagull.local",
            )

        metadata = self.api.read_payload_metadata(payload["content_ref"])
        inbox = self.api.read_inbox("@reviewer:seagull.local")
        context_pack = self.api.read_context_pack(
            post["thread_id"],
            requester_handle="@reviewer:seagull.local",
        )
        self.assertEqual(410, context.exception.status_code)
        self.assertEqual("payload_unavailable", context.exception.error)
        self.assertEqual("expired", metadata["payload"]["retention_state"])
        self.assertEqual(payload["payload"]["hash"], metadata["payload"]["hash"])
        self.assertEqual(payload["payload"]["compressed_hash"], metadata["payload"]["compressed_hash"])
        self.assertEqual(payload["payload"]["storage_ref"], metadata["payload"]["storage_ref"])
        self.assertEqual(payload["content_ref"], post["message"]["content_ref"])
        self.assertEqual(payload["content_ref"], inbox["items"][0]["current_message"]["content_ref"])
        self.assertEqual([payload["content_ref"]], [ref["content_ref"] for ref in context_pack["payload_refs"]])
        self.assertNotIn("content", metadata)
        self.assertNotIn("content_bytes", metadata)

    def test_local_api_compacted_payload_metadata_includes_manifest_summary(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})
        payload = self.api.create_payload(
            {
                "content": "Compaction metadata payload.\n" * 100,
                "media_type": "text/plain",
                "access_scope": "thread",
            }
        )
        self.api.create_message(
            {
                "sender_handle": "@researcher:seagull.local",
                "recipient_handles": ["@reviewer:seagull.local"],
                "content_ref": payload["content_ref"],
            }
        )

        self.service.run_payload_retention_worker(
            compact_ready_before=datetime(2026, 6, 13, tzinfo=timezone.utc) + timedelta(seconds=100),
            compact_summary_chars=32,
            compact_chunk_bytes=16,
        )

        metadata = self.api.read_payload_metadata(payload["content_ref"])
        self.assertEqual("compacted", metadata["payload"]["retention_state"])
        self.assertEqual(f"{payload['content_ref']}/manifest/compact", metadata["payload"]["chunk_manifest_ref"])
        self.assertEqual(metadata["payload"]["chunk_manifest_ref"], metadata["compaction"]["manifest_ref"])
        self.assertTrue(metadata["compaction"]["summary"].startswith("Compaction metadata"))
        self.assertEqual(2, metadata["compaction"]["selected_chunk_count"])
        self.assertEqual([16, 16], metadata["compaction"]["selected_chunk_byte_lengths"])
        self.assertNotIn("selected_chunks", metadata["compaction"])

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

    def test_local_api_manages_quote_approval_and_escrow_flow(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})
        task_response = self.api.create_task(
            {
                "requester_handle": "@researcher:seagull.local",
                "recipient_handle": "@reviewer:seagull.local",
                "objective": "Review private context with paid capacity.",
                "context_refs": ["thread://thread_1"],
                "context_pack_ref": "payload://context_pack_1",
            }
        )
        policy = self.api.define_task_capacity_policy(
            task_response["task_id"],
            {
                "actor_handle": "@researcher:seagull.local",
                "requester_capacity_tier": "low",
                "worker_capacity_tier": "high",
                "max_credit_cost": 5,
                "max_auto_escrow_credits": 2,
                "allow_private_context": True,
                "private_context_requires_approval": True,
                "paid_work_requires_approval": False,
                "high_cost_requires_approval": True,
            },
        )
        policies = self.api.read_task_capacity_policies(task_response["task_id"])

        quote = self.api.create_task_quote(
            task_response["task_id"],
            {
                "worker_handle": "@reviewer:seagull.local",
                "expected_credit_cost": 3,
                "task_reason": "Review private context with independent capacity.",
                "shared_context_refs": ["thread://thread_1", "payload://context_pack_1"],
                "requires_approval": False,
            },
        )
        self.assertEqual("capacity_policy_1", policy["policy_id"])
        self.assertEqual("requester", policy["policy"]["requester_role"])
        self.assertEqual("worker", policy["policy"]["worker_role"])
        self.assertEqual("low", policy["policy"]["requester_capacity_tier"])
        self.assertEqual("high", policy["policy"]["worker_capacity_tier"])
        self.assertEqual(["capacity_policy_1"], [item["policy_id"] for item in policies["policies"]])
        self.assertEqual("task_quote_1", quote["quote_id"])
        self.assertEqual(3, quote["quote"]["expected_credit_cost"])
        self.assertTrue(quote["quote"]["requires_approval"])
        self.assertEqual("expected cost exceeds auto-escrow limit", quote["quote"]["approval_reason"])
        self.assertEqual(["thread://thread_1", "payload://context_pack_1"], quote["quote"]["shared_context_refs"])

        with self.assertRaises(ApiError) as unapproved:
            self.api.create_task_escrow(
                task_response["task_id"],
                {
                    "requester_handle": "@researcher:seagull.local",
                    "quote_id": quote["quote_id"],
                },
            )
        self.assertEqual(400, unapproved.exception.status_code)

        approved = self.api.approve_task_quote(
            quote["quote_id"],
            {
                "approver_handle": "@researcher:seagull.local",
                "approval_id": "approval_1",
            },
        )
        grant = self.api.grant_task_credits(
            {
                "agent_handle": "@researcher:seagull.local",
                "amount": 10,
                "reason": "Internal test allocation.",
            }
        )
        escrow = self.api.create_task_escrow(
            task_response["task_id"],
            {
                "requester_handle": "@researcher:seagull.local",
                "quote_id": quote["quote_id"],
            },
        )

        self.assertEqual("approval_1", approved["quote"]["approval_id"])
        self.assertEqual("task_credit_entry_1", grant["entry_id"])
        self.assertEqual("internal_product_credit", grant["entry"]["settlement_scope"])
        self.assertEqual("task_escrow_1", escrow["escrow_id"])
        self.assertEqual("escrowed", escrow["state"])
        self.assertEqual(3, escrow["escrow"]["credit_amount"])
        self.assertEqual("approval_1", escrow["escrow"]["approval_id"])
        balance = self.api.read_task_credit_balance("@researcher:seagull.local")
        ledger = self.api.read_task_credit_ledger(task_response["task_id"])
        self.assertEqual(7, balance["balance"]["available_balance"])
        self.assertEqual(3, balance["balance"]["escrow_balance"])
        self.assertEqual("escrow_hold", ledger["entries"][0]["entry_type"])
        self.assertEqual(-3, ledger["entries"][0]["available_delta"])
        self.assertEqual(3, ledger["entries"][0]["escrow_delta"])
        readback = self.api.read_task(task_response["task_id"])
        self.assertEqual(["task_quote_1"], readback["task"]["quote_ids"])
        self.assertEqual(["task_escrow_1"], readback["task"]["escrow_ids"])
        self.assertEqual(["capacity_policy_1"], readback["task"]["capacity_policy_ids"])

    def test_local_api_reports_worker_reputation_events(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})
        task_response = self.api.create_task(
            {
                "requester_handle": "@researcher:seagull.local",
                "recipient_handle": "@reviewer:seagull.local",
                "objective": "Review scoped context.",
            }
        )

        event = self.api.report_task_worker_abuse(
            task_response["task_id"],
            {
                "reporter_handle": "@researcher:seagull.local",
                "reason": "Worker ignored scope limits.",
                "policy_decision_id": "policy_abuse_1",
            },
        )
        summary = self.api.read_task_worker_reputation("@reviewer:seagull.local")
        events = self.api.read_task_worker_reputation_events("@reviewer:seagull.local")

        self.assertEqual("task_reputation_event_1", event["event_id"])
        self.assertEqual("abuse_reported", event["event"]["event_type"])
        self.assertEqual("policy_abuse_1", event["event"]["policy_decision_id"])
        self.assertEqual(1, summary["reputation"]["abuse_report_count"])
        self.assertEqual(0, summary["reputation"]["completed_task_count"])
        self.assertIsNone(summary["reputation"]["completion_rate"])
        self.assertEqual(["task_reputation_event_1"], [item["event_id"] for item in events["events"]])

    def test_local_api_enforces_scoped_tool_grants(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})
        task_response = self.api.create_task(
            {
                "requester_handle": "@researcher:seagull.local",
                "recipient_handle": "@reviewer:seagull.local",
                "objective": "Read a narrow repo path.",
                "allowed_tool_names": ["repo_read"],
            }
        )

        with self.assertRaises(ApiError) as private_context:
            self.api.create_tool_grant(
                task_response["task_id"],
                {
                    "issuer_handle": "@researcher:seagull.local",
                    "subject_handle": "@reviewer:seagull.local",
                    "audience": "seagull://agents/agent_2/tools",
                    "scopes": ["repo_read"],
                    "purpose": "Read requested files only.",
                    "mcp_server_url": "mcp://private-tools.local/session",
                },
            )
        self.assertEqual(400, private_context.exception.status_code)

        grant = self.api.create_tool_grant(
            task_response["task_id"],
            {
                "issuer_handle": "@researcher:seagull.local",
                "subject_handle": "@reviewer:seagull.local",
                "audience": "seagull://agents/agent_2/tools",
                "scopes": ["repo_read"],
                "purpose": "Read requested files only.",
                "ttl_expires_at": "2026-06-13T00:01:00+00:00",
                "max_calls": 1,
                "allowed_resource_selectors": ["docs/**"],
                "approval_id": "approval_1",
            },
        )
        self.assertEqual("tool_grant_1", grant["tool_grant_id"])
        self.assertEqual(["repo_read"], grant["tool_grant"]["scopes"])
        self.assertEqual(["tool_grant_1"], self.api.read_task("task_1")["task"]["tool_grant_ids"])
        serialized_grant = json.dumps(grant, sort_keys=True)
        self.assertNotIn("mcp://", serialized_grant)
        self.assertNotIn("credential", serialized_grant)

        tool_request = self.api.create_tool_request(
            task_response["task_id"],
            {
                "requester_handle": "@researcher:seagull.local",
                "worker_handle": "@reviewer:seagull.local",
                "tool_name": "repo_read",
                "purpose": "Read requested files only.",
                "requires_approval": False,
                "tool_grant_id": grant["tool_grant_id"],
            },
        )
        self.assertEqual("requested", tool_request["tool_request"]["status"])
        self.assertEqual("tool_grant_1", tool_request["tool_request"]["tool_grant_id"])

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

    def test_local_api_reads_contact_explanation(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})
        message = self.api.create_message(
            {
                "sender_handle": "@researcher:seagull.local",
                "recipient_handles": ["@reviewer:seagull.local"],
                "content": "Open this URL when approved.",
                "refs": [{"type": "url", "url": "https://example.com", "remember_as": "approval target"}],
            }
        )
        delivery_id = message["deliveries"][0]["delivery_id"]
        self.api.submit_delivery_decision(
            delivery_id,
            {
                "agent_handle": "@reviewer:seagull.local",
                "decision": "action",
                "action_type": "open_url",
                "action_target": "https://example.com",
            },
        )

        explanation = self.api.read_contact_explanation(delivery_id)["explanation"]

        self.assertEqual("contact_explanation_delivery_1", explanation["explanation_id"])
        self.assertEqual("@researcher:seagull.local", explanation["requester_handle"])
        self.assertEqual("@reviewer:seagull.local", explanation["answering_asset_handle"])
        self.assertEqual("needs_approval", explanation["relationship"])
        self.assertIn("message safety status is approved", explanation["allowed_reason"])
        self.assertEqual("Open this URL when approved.", explanation["shared_context_summary"])
        self.assertEqual(["https://example.com"], explanation["shared_context_refs"])
        self.assertEqual("open_url for https://example.com (requires approval)", explanation["pending_action"])
        self.assertIn("action_approval_required:true", explanation["policy_refs"])
        self.assertIn("action_request:action_1:pending", explanation["audit_event_refs"])

    def test_personal_agent_api_wraps_existing_message_and_task_flows(self) -> None:
        self.api.register_agent({"handle": "@researcher:seagull.local"})
        self.api.register_agent({"handle": "@reviewer:seagull.local"})

        sent = self.api.personal_agent_send(
            "@researcher:seagull.local",
            {
                "recipient_handles": ["@reviewer:seagull.local"],
                "content": "Please review this through the personal-agent surface.",
                "sender_handle": "@spoofed:seagull.local",
            },
        )
        inbox = self.api.personal_agent_inbox("@reviewer:seagull.local")
        delivery_id = inbox["items"][0]["delivery"]["delivery_id"]

        self.assertEqual("agent_1", sent["message"]["sender_agent_id"])
        self.assertEqual("message_1", inbox["items"][0]["message"]["message_id"])

        reply = self.api.personal_agent_reply(
            "@reviewer:seagull.local",
            delivery_id,
            {
                "agent_handle": "@spoofed:seagull.local",
                "decision": "ignore",
                "content": "Reviewed from the normal reply flow.",
            },
        )
        self.assertEqual("replied", reply["delivery"]["status"])
        self.assertEqual("reply", reply["reply"]["message"]["intent"])

        ask = self.api.personal_agent_send(
            "@researcher:seagull.local",
            {
                "recipient_handles": ["@reviewer:seagull.local"],
                "content": "Should the owner approve this?",
            },
        )
        ask_owner = self.api.personal_agent_ask_owner(
            "@reviewer:seagull.local",
            ask["deliveries"][0]["delivery_id"],
            {"note": "Owner review requested."},
        )
        self.assertEqual("needs_review", ask_owner["delivery"]["status"])
        self.assertEqual("human.review", ask_owner["delivery"]["current_stage"])
        self.assertEqual("ask_human", ask_owner["delivery"]["workflow_trace"][-1]["action"])

        ignored = self.api.personal_agent_send(
            "@researcher:seagull.local",
            {
                "recipient_handles": ["@reviewer:seagull.local"],
                "content": "Ignore this.",
            },
        )
        ignore = self.api.personal_agent_ignore(
            "@reviewer:seagull.local",
            ignored["deliveries"][0]["delivery_id"],
        )
        self.assertEqual("ignored", ignore["delivery"]["status"])

        task = self.api.personal_agent_request_task(
            "@researcher:seagull.local",
            {
                "recipient_handle": "@reviewer:seagull.local",
                "requester_handle": "@spoofed:seagull.local",
                "objective": "Return a task result.",
                "context_refs": ["payload://task_1/context"],
            },
        )
        self.assertEqual("task_1", task["task_id"])
        self.assertEqual("agent_1", task["task"]["requester_agent_id"])

        accepted = self.api.personal_agent_accept_task(
            "@reviewer:seagull.local",
            task["task_id"],
            {"worker_handle": "@spoofed:seagull.local"},
        )
        self.assertEqual("accepted", accepted["state"])
        self.assertEqual("agent_2", accepted["task"]["accepted_by_agent_id"])

        result = self.api.personal_agent_return_result(
            "@reviewer:seagull.local",
            task["task_id"],
            {
                "responder_handle": "@spoofed:seagull.local",
                "content": "Done through the existing task-result flow.",
            },
        )
        self.assertEqual("completed", result["state"])
        self.assertEqual("agent_2", result["result"]["responder_agent_id"])

    def test_agent_runtime_api_requires_scoped_agent_tokens(self) -> None:
        researcher_registration = self.api.agent_registration(
            {
                "handle": "@researcher:seagull.local",
                "scopes": ["agent:read", "agent:post", "agent:ack"],
                "owner_user_id": "user_researcher",
                "node_id": "node_researcher",
            }
        )
        reviewer_registration = self.api.agent_registration(
            {
                "handle": "@reviewer:seagull.local",
                "scopes": ["agent:read", "agent:inbox", "agent:post", "agent:ack"],
                "name": "reviewer runtime",
                "owner_user_id": "user_reviewer",
                "node_id": "node_reviewer",
            }
        )
        repeat_registration = self.api.agent_registration(
            {
                "handle": "@reviewer:seagull.local",
                "scopes": ["agent:read"],
            }
        )
        self.assertTrue(researcher_registration["created"])
        self.assertTrue(reviewer_registration["created"])
        self.assertFalse(repeat_registration["created"])
        self.assertTrue(researcher_registration["token"].startswith("sga_"))
        self.assertEqual("@reviewer:seagull.local", reviewer_registration["record"]["agent_handle"])
        self.assertEqual("reviewer runtime", reviewer_registration["record"]["name"])
        self.assertNotIn("token_hash", reviewer_registration["record"])

        researcher_token = researcher_registration["token"]
        reviewer_token = reviewer_registration["token"]
        read_only = self.service.issue_agent_token(
            "@reviewer:seagull.local",
            scopes=("agent:read",),
        )
        expired = self.service.issue_agent_token(
            "@reviewer:seagull.local",
            scopes=("agent:read",),
            expires_at=datetime(2026, 6, 13, tzinfo=timezone.utc) + timedelta(seconds=1),
        )
        revoked = self.service.issue_agent_token(
            "@reviewer:seagull.local",
            scopes=("agent:read",),
        )
        self.service.revoke_agent_token(revoked.record.token_id)

        with self.assertRaises(ApiError) as missing:
            self.api.agent_me(None)
        self.assertEqual(401, missing.exception.status_code)
        self.assertEqual("unauthorized", missing.exception.error)

        with self.assertRaises(ApiError) as malformed:
            self.api.agent_me("Bearer sgc_not_an_agent_token")
        self.assertEqual(401, malformed.exception.status_code)

        with self.assertRaises(ApiError) as expired_error:
            self.api.agent_me(f"Bearer {expired.token}")
        self.assertEqual(401, expired_error.exception.status_code)

        with self.assertRaises(ApiError) as revoked_error:
            self.api.agent_me(f"Bearer {revoked.token}")
        self.assertEqual(401, revoked_error.exception.status_code)

        with self.assertRaises(ApiError) as wrong_scope:
            self.api.agent_inbox(f"Bearer {read_only.token}")
        self.assertEqual(403, wrong_scope.exception.status_code)
        self.assertEqual("forbidden", wrong_scope.exception.error)

        me = self.api.agent_me(f"Bearer {reviewer_token}")
        self.assertEqual("@reviewer:seagull.local", me["agent"]["handle"])
        self.assertEqual("agent_2", me["principal"]["agent_id"])
        self.assertEqual("user_reviewer", me["principal"]["owner_user_id"])
        self.assertEqual("node_reviewer", me["principal"]["node_id"])

        post = self.api.agent_post(
            f"Bearer {researcher_token}",
            {
                "sender_handle": "@spoofed:seagull.local",
                "recipient_handles": ["@reviewer:seagull.local"],
                "content": "Runtime post ignores caller-supplied sender.",
            },
        )
        inbox = self.api.agent_inbox(f"Bearer {reviewer_token}")
        delivery_id = inbox["items"][0]["delivery"]["delivery_id"]

        self.assertEqual("agent_1", post["message"]["sender_agent_id"])
        self.assertEqual("message_1", inbox["items"][0]["message"]["message_id"])

        decision = self.api.agent_decide_delivery(
            f"Bearer {reviewer_token}",
            delivery_id,
            {
                "agent_handle": "@spoofed:seagull.local",
                "decision": "reply",
                "content": "Runtime decision ignores caller-supplied agent handle.",
            },
        )
        self.assertEqual("replied", decision["delivery"]["status"])
        self.assertEqual("agent_2", decision["delivery"]["recipient_agent_id"])
        self.assertEqual("agent_2", decision["reply"]["message"]["sender_agent_id"])

        with self.assertRaises(ApiError) as wrong_agent:
            self.api.agent_ack_delivery(f"Bearer {researcher_token}", delivery_id)
        self.assertEqual(403, wrong_agent.exception.status_code)

        ack = self.api.agent_ack_delivery(f"Bearer {reviewer_token}", delivery_id)
        self.assertEqual("acked", ack["delivery"]["status"])
        self.assertEqual("agent_2", ack["delivery"]["recipient_agent_id"])
