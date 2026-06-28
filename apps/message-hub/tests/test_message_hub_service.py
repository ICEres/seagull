from __future__ import annotations

import gzip
import hashlib
from datetime import datetime, timedelta, timezone
from itertools import count
from unittest import TestCase

from message_hub.domain import (
    DeliveryStatus,
    ForbiddenDeliveryError,
    ForbiddenPayloadError,
    InvalidMessageError,
    MAX_ENVELOPE_INLINE_CHARS,
    MessageHubService,
    MessageRef,
    NotFoundError,
    PayloadUnavailableError,
    TaskState,
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

    def test_local_payload_storage_compresses_and_hashes_payload(self) -> None:
        content = ("Large local payload.\n" * 500).encode("utf-8")

        payload = self.service.create_payload(
            content=content,
            media_type="text/plain",
            access_scope="thread",
        )
        self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content_ref=payload.record.content_ref,
        )
        record, fetched_content = self.service.read_payload_content(
            payload.record.content_ref,
            requester_handle="@reviewer:gulls.ai",
        )

        self.assertEqual("payload://payload_1", payload.record.content_ref)
        self.assertEqual("text/plain", payload.record.media_type)
        self.assertEqual(len(content), payload.record.byte_length)
        self.assertEqual(f"sha256:{hashlib.sha256(content).hexdigest()}", payload.record.hash)
        self.assertEqual("gzip", payload.record.compression)
        self.assertEqual("ready", payload.record.retention_state)
        self.assertEqual("thread", payload.record.access_scope)
        self.assertIsNone(payload.record.fetch_policy_ref)
        self.assertIsNone(payload.record.chunk_manifest_ref)
        self.assertEqual("local_node", payload.record.storage_provider)
        self.assertEqual(payload.record.content_ref, payload.record.storage_ref)
        self.assertLess(payload.record.compressed_byte_length, payload.record.byte_length)
        self.assertIsNotNone(payload.compressed_content)
        self.assertEqual(
            f"sha256:{hashlib.sha256(payload.compressed_content).hexdigest()}",
            payload.record.compressed_hash,
        )
        self.assertEqual(content, gzip.decompress(payload.compressed_content))
        self.assertEqual(payload.record, record)
        self.assertEqual(content, fetched_content)

    def test_non_public_payload_fetch_requires_registered_requester(self) -> None:
        payload = self.service.create_payload(
            content="private payload",
            media_type="text/plain",
            access_scope="recipients",
        )
        self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content_ref=payload.record.content_ref,
        )

        with self.assertRaises(ForbiddenPayloadError):
            self.service.read_payload_content(payload.record.content_ref)
        with self.assertRaises(ForbiddenPayloadError):
            self.service.read_payload_content(
                payload.record.content_ref,
                requester_handle="@unknown:gulls.ai",
            )
        with self.assertRaises(ForbiddenPayloadError):
            self.service.read_payload_content(
                payload.record.content_ref,
                requester_handle="@map-reader:gulls.ai",
            )

        _, private_content = self.service.read_payload_content(
            payload.record.content_ref,
            requester_handle="@reviewer:gulls.ai",
        )
        self.assertEqual(b"private payload", private_content)

        public_payload = self.service.create_payload(
            content="public payload",
            media_type="text/plain",
            access_scope="public",
        )
        _, public_content = self.service.read_payload_content(public_payload.record.content_ref)
        self.assertEqual(b"public payload", public_content)

    def test_expired_payload_content_is_unavailable_but_metadata_remains(self) -> None:
        content = b"payload with a short ttl"
        expires_at = datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(seconds=1)
        payload = self.service.create_payload(
            content=content,
            media_type="text/plain",
            ttl_expires_at=expires_at,
        )
        self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content_ref=payload.record.content_ref,
        )

        with self.assertRaises(PayloadUnavailableError):
            self.service.read_payload_content(
                payload.record.content_ref,
                requester_handle="@reviewer:gulls.ai",
            )

        stored = self.service.get_payload(payload.record.content_ref)
        self.assertEqual("expired", stored.record.retention_state)
        self.assertIsNone(stored.compressed_content)
        self.assertEqual(payload.record.content_ref, stored.record.content_ref)
        self.assertEqual(payload.record.media_type, stored.record.media_type)
        self.assertEqual(payload.record.byte_length, stored.record.byte_length)
        self.assertEqual(payload.record.hash, stored.record.hash)
        self.assertEqual(payload.record.compressed_hash, stored.record.compressed_hash)
        self.assertEqual(payload.record.ttl_expires_at, stored.record.ttl_expires_at)
        self.assertEqual(payload.record.access_scope, stored.record.access_scope)
        self.assertEqual(payload.record.storage_ref, stored.record.storage_ref)

    def test_payload_ttl_requires_timezone(self) -> None:
        with self.assertRaises(InvalidMessageError):
            self.service.create_payload(
                content="payload",
                media_type="text/plain",
                ttl_expires_at=datetime(2026, 6, 12),
            )

    def test_payload_retention_can_compact_and_delete_without_losing_metadata(self) -> None:
        payload = self.service.create_payload(
            content=b"payload that can be compacted",
            media_type="application/octet-stream",
        )
        self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content_ref=payload.record.content_ref,
        )

        compacted = self.service.update_payload_retention(
            payload.record.content_ref,
            retention_state="compacted",
        )
        stored = self.service.get_payload(payload.record.content_ref)
        self.assertEqual("compacted", compacted.retention_state)
        self.assertEqual(compacted, stored.record)
        self.assertIsNone(stored.compressed_content)
        self.assertEqual(payload.record.content_ref, stored.record.content_ref)
        self.assertEqual(payload.record.hash, stored.record.hash)
        self.assertEqual(payload.record.compressed_hash, stored.record.compressed_hash)
        self.assertEqual(payload.record.storage_ref, stored.record.storage_ref)
        with self.assertRaises(PayloadUnavailableError):
            self.service.read_payload_content(
                payload.record.content_ref,
                requester_handle="@reviewer:gulls.ai",
            )

        deleted = self.service.update_payload_retention(
            payload.record.content_ref,
            retention_state="deleted",
        )
        self.assertEqual("deleted", deleted.retention_state)
        self.assertEqual(payload.record.hash, deleted.hash)

    def test_payload_retention_worker_compacts_ready_payloads(self) -> None:
        content = ("Worker compaction keeps a selected chunk.\n" * 200).encode("utf-8")
        payload = self.service.create_payload(
            content=content,
            media_type="text/plain",
            access_scope="thread",
        )
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content_ref=payload.record.content_ref,
        )

        worker_result = self.service.run_payload_retention_worker(
            compact_ready_before=datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(seconds=100),
            compact_summary_chars=48,
            compact_chunk_bytes=32,
        )

        stored = self.service.get_payload(payload.record.content_ref)
        context_pack = self.service.get_context_pack(
            result.thread.thread_id,
            requester_handle="@reviewer:gulls.ai",
        )
        self.assertEqual(1, worker_result.scanned_count)
        self.assertEqual((payload.record.content_ref,), worker_result.compacted_refs)
        self.assertEqual((), worker_result.deleted_refs)
        self.assertEqual("compacted", stored.record.retention_state)
        self.assertIsNone(stored.compressed_content)
        self.assertIsNotNone(stored.compaction)
        assert stored.compaction is not None
        self.assertEqual(f"{payload.record.content_ref}/manifest/compact", stored.record.chunk_manifest_ref)
        self.assertEqual(stored.record.chunk_manifest_ref, stored.compaction.manifest_ref)
        self.assertEqual(payload.record.hash, stored.record.hash)
        self.assertEqual(payload.record.compressed_hash, stored.record.compressed_hash)
        self.assertLess(sum(len(chunk) for chunk in stored.compaction.selected_chunks), len(content))
        self.assertTrue(stored.compaction.summary.startswith("Worker compaction"))
        self.assertEqual([payload.record.content_ref], [ref.content_ref for ref in context_pack.payload_refs])
        with self.assertRaises(PayloadUnavailableError):
            self.service.read_payload_content(
                payload.record.content_ref,
                requester_handle="@reviewer:gulls.ai",
            )

    def test_payload_retention_worker_deletes_expired_payloads(self) -> None:
        content = b"payload that should expire and delete"
        payload = self.service.create_payload(
            content=content,
            media_type="text/plain",
            ttl_expires_at=datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(seconds=1),
        )
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content_ref=payload.record.content_ref,
        )

        worker_result = self.service.run_payload_retention_worker(
            delete_expired_before=datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(seconds=100),
        )

        stored = self.service.get_payload(payload.record.content_ref)
        context_pack = self.service.get_context_pack(
            result.thread.thread_id,
            requester_handle="@reviewer:gulls.ai",
        )
        self.assertEqual(1, worker_result.scanned_count)
        self.assertEqual((payload.record.content_ref,), worker_result.expired_refs)
        self.assertEqual((payload.record.content_ref,), worker_result.deleted_refs)
        self.assertEqual("deleted", stored.record.retention_state)
        self.assertIsNone(stored.compressed_content)
        self.assertIsNone(stored.compaction)
        self.assertEqual(payload.record.content_ref, stored.record.content_ref)
        self.assertEqual(payload.record.hash, stored.record.hash)
        self.assertEqual(payload.record.compressed_hash, stored.record.compressed_hash)
        self.assertEqual(payload.record.storage_ref, stored.record.storage_ref)
        self.assertEqual([payload.record.content_ref], [ref.content_ref for ref in context_pack.payload_refs])
        with self.assertRaises(PayloadUnavailableError):
            self.service.read_payload_content(
                payload.record.content_ref,
                requester_handle="@reviewer:gulls.ai",
            )

    def test_context_pack_applies_budget_and_redacts_private_refs(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="abcdefghijklmnopqrstuvwxyz",
            content_ref="payload://thread_1/message_1/full",
            refs=(
                MessageRef(type="url", url="https://example.com/context", remember_as="public link"),
                MessageRef(type="mcp", url="mcp://private-tools.local/session"),
                MessageRef(type="tool", url="tool://raw/private-browser", remember_as="raw_tool_handle"),
                MessageRef(type="url", url="http://localhost:9000/callback"),
                MessageRef(type="url", url="https://example.com/private?token=secret-token"),
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
        self.assertEqual("message://message_1/content_inline", context_pack.redacted_refs[0])
        self.assertEqual(("message://message_1/ref",) * 4, context_pack.redacted_refs[1:])
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

    def test_context_pack_redacts_private_content_refs(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Referenced private payload.",
            content_ref="file:///Users/alice/private-plan.md",
        )
        self.service.save_thread_summary(
            result.thread.thread_id,
            "Private summary ref.",
            content_ref="mcp://private-summary/session",
        )

        context_pack = self.service.get_context_pack(
            result.thread.thread_id,
            requester_handle="@reviewer:gulls.ai",
        )

        self.assertIsNone(context_pack.recent_messages[0].content_ref)
        self.assertIsNotNone(context_pack.summary)
        assert context_pack.summary is not None
        self.assertIsNone(context_pack.summary.content_ref)
        self.assertEqual((), context_pack.payload_refs)
        self.assertIn("message://message_1/content_ref", context_pack.redacted_refs)
        self.assertIn("summary://summary_1/content_ref", context_pack.redacted_refs)

    def test_large_inline_message_requires_content_ref_before_delivery(self) -> None:
        large_content = "x" * (MAX_ENVELOPE_INLINE_CHARS + 1)

        with self.assertRaises(InvalidMessageError):
            self.service.send_message(
                sender_handle="@researcher:gulls.ai",
                recipient_handles=["@reviewer:gulls.ai"],
                content=large_content,
            )

        self.assertIsNone(self.repository.get_thread("thread_1"))
        self.assertEqual((), self.repository.list_deliveries_by_recipient(self.recipient.agent_id))

    def test_large_message_with_content_ref_stays_out_of_inbox_rows(self) -> None:
        large_content = "x" * (MAX_ENVELOPE_INLINE_CHARS + 1)

        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content=large_content,
            content_ref="payload://thread_1/message_1/full",
        )
        inbox = self.service.get_inbox("@reviewer:gulls.ai")

        self.assertIsNone(result.message.content_inline)
        self.assertEqual("payload://thread_1/message_1/full", result.message.content_ref)
        self.assertIsNone(result.deliveries[0].current_content_inline)
        self.assertEqual("payload://thread_1/message_1/full", result.deliveries[0].current_content_ref)
        self.assertIsNone(inbox[0].message.content_inline)
        self.assertIsNone(inbox[0].delivery.current_content_inline)
        self.assertEqual("payload://thread_1/message_1/full", inbox[0].message.content_ref)

    def test_hook_result_large_inline_requires_content_ref(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Small delivery.",
        )
        large_content = "x" * (MAX_ENVELOPE_INLINE_CHARS + 1)

        with self.assertRaises(InvalidMessageError):
            self.service.apply_hook_result(
                result.deliveries[0].delivery_id,
                hook="receive.before",
                runtime="cloud_node",
                content=large_content,
            )

        updated = self.service.apply_hook_result(
            result.deliveries[0].delivery_id,
            hook="receive.before",
            runtime="cloud_node",
            content=large_content,
            content_ref="payload://delivery_1/current",
        )

        self.assertIsNone(updated.current_content_inline)
        self.assertEqual("payload://delivery_1/current", updated.current_content_ref)
        self.assertEqual(("current_content_inline", "current_content_ref"), updated.workflow_trace[-1].changed)

    def test_task_result_is_durable_without_live_stream(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Return a durable result without a live stream.",
        )
        self.service.accept_task(task.task_id, worker_handle="@reviewer:gulls.ai")

        result = self.service.return_task_result(
            task.task_id,
            responder_handle="@reviewer:gulls.ai",
            content_ref="payload://task_1/result",
            artifact_refs=("artifact://review",),
        )

        stored_results = self.repository.list_task_results(task.task_id)
        updated_task = self.service.get_task(task.task_id)
        result_message = self.repository.get_message(result.result_message_id)

        self.assertIsNone(task.stream_id)
        self.assertIsNone(result.stream_id)
        self.assertIsNone(updated_task.stream_id)
        self.assertEqual((result,), stored_results)
        self.assertEqual(TaskState.COMPLETED, updated_task.state)
        self.assertEqual(result.result_message_id, updated_task.result_message_id)
        self.assertEqual("seagull://tasks/task_1/results/task_result_1", updated_task.result_ref)
        self.assertIsNotNone(result_message)
        assert result_message is not None
        self.assertEqual("task_result", result_message.intent)
        self.assertEqual("payload://task_1/result", result.content_ref)

    def test_large_task_result_content_requires_content_ref(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Return a large result by ref.",
        )
        large_content = "x" * (MAX_ENVELOPE_INLINE_CHARS + 1)

        with self.assertRaises(InvalidMessageError):
            self.service.return_task_result(
                task.task_id,
                responder_handle="@reviewer:gulls.ai",
                content=large_content,
            )

        result = self.service.return_task_result(
            task.task_id,
            responder_handle="@reviewer:gulls.ai",
            content=large_content,
            content_ref="payload://task_1/result",
        )
        result_message = self.repository.get_message(result.result_message_id)

        self.assertIsNone(result.content_inline)
        self.assertEqual("payload://task_1/result", result.content_ref)
        self.assertIsNotNone(result_message)
        assert result_message is not None
        self.assertIsNone(result_message.content_inline)
        self.assertEqual("payload://task_1/result", result_message.content_ref)

    def test_large_task_objective_is_rejected(self) -> None:
        with self.assertRaises(InvalidMessageError):
            self.service.create_task(
                requester_handle="@researcher:gulls.ai",
                recipient_handle="@reviewer:gulls.ai",
                objective="x" * (MAX_ENVELOPE_INLINE_CHARS + 1),
                input_ref="payload://task_1/input",
            )

    def test_task_result_can_link_optional_stream_without_stream_events(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Return a result that links to an optional stream.",
            stream_id="stream_1",
        )

        result = self.service.return_task_result(
            task.task_id,
            responder_handle="@reviewer:gulls.ai",
            content="Done.",
        )

        updated_task = self.service.get_task(task.task_id)
        messages = self.repository.list_thread_messages(task.thread_id)

        self.assertEqual("stream_1", task.stream_id)
        self.assertEqual("stream_1", result.stream_id)
        self.assertEqual("stream_1", updated_task.stream_id)
        self.assertEqual(TaskState.COMPLETED, updated_task.state)
        self.assertEqual("task_result", messages[-1].intent)
        self.assertNotIn("stream.delta", [message.intent for message in messages])

    def test_task_result_rejects_mismatched_stream_id(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Return a result for the task stream.",
            stream_id="stream_1",
        )

        with self.assertRaises(InvalidMessageError):
            self.service.return_task_result(
                task.task_id,
                responder_handle="@reviewer:gulls.ai",
                stream_id="stream_2",
                content="Wrong stream.",
            )

    def test_delegated_task_records_lifecycle_without_inline_task_payload_messages(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Review the private plan without copying private prompts.",
            context_refs=("thread://thread_1",),
            context_pack_id="context_pack_1",
            input_ref="payload://task_1/input",
            allowed_tool_names=("repo_read",),
            allowed_use_terms=("no_memory",),
        )

        self.assertEqual("task_1", task.task_id)
        self.assertEqual(TaskState.REQUESTED, task.state)
        self.assertEqual("local_safety_allow", task.policy_decision_id)
        self.assertEqual(("repo_read",), task.allowed_tool_names)
        request_message = self.repository.get_message(task.request_message_id)
        self.assertIsNotNone(request_message)
        assert request_message is not None
        self.assertIsNone(request_message.content_inline)
        self.assertEqual("task_request", request_message.intent)
        self.assertEqual(("seagull://tasks/task_1",), tuple(ref.url for ref in request_message.refs))

        accepted = self.service.accept_task(
            task.task_id,
            worker_handle="@reviewer:gulls.ai",
            note="Accepted after owner policy check.",
        )
        self.assertEqual(TaskState.ACCEPTED, accepted.state)
        self.assertEqual(self.recipient.agent_id, accepted.accepted_by_agent_id)

        tool_request = self.service.create_tool_request(
            task.task_id,
            requester_handle="@researcher:gulls.ai",
            worker_handle="@reviewer:gulls.ai",
            tool_name="repo_read",
            purpose="Read only the requested files.",
            input_ref="payload://task_1/tool_input",
            requires_approval=True,
            approval_id="approval_1",
            policy_decision_id="policy_1",
        )
        self.assertEqual("tool_request_1", tool_request.tool_request_id)
        self.assertEqual(TaskState.NEEDS_APPROVAL, tool_request.status)
        self.assertEqual("policy_1", tool_request.policy_decision_id)
        self.assertEqual(("tool_request_1",), self.service.get_task(task.task_id).tool_request_ids)

        completed_tool = self.service.complete_tool_request(
            tool_request.tool_request_id,
            actor_handle="@reviewer:gulls.ai",
            state="result_ready",
            result_ref="payload://task_1/tool_result",
            artifact_refs=("artifact://tool_summary",),
            tool_use_summary_ref="payload://task_1/tool_summary",
        )
        self.assertEqual(TaskState.RESULT_READY, completed_tool.status)
        self.assertEqual(self.recipient.agent_id, completed_tool.accepted_by_agent_id)
        self.assertEqual("payload://task_1/tool_result", completed_tool.result_ref)

        result = self.service.return_task_result(
            task.task_id,
            responder_handle="@reviewer:gulls.ai",
            state="completed",
            content="Reviewed. See referenced artifact.",
            content_ref="payload://task_1/result",
            artifact_refs=("artifact://review",),
            tool_use_summary_refs=("payload://task_1/tool_summary",),
        )

        self.assertEqual("task_result_1", result.result_id)
        self.assertEqual(TaskState.COMPLETED, result.state)
        updated_task = self.service.get_task(task.task_id)
        self.assertEqual(TaskState.COMPLETED, updated_task.state)
        self.assertEqual("artifact://review", updated_task.artifact_refs[0])
        result_message = self.repository.get_message(result.result_message_id)
        self.assertIsNotNone(result_message)
        assert result_message is not None
        self.assertIsNone(result_message.content_inline)
        self.assertEqual("payload://task_1/result", result_message.content_ref)
        self.assertEqual("task_result", result_message.intent)
        self.assertEqual(
            ("seagull://tasks/task_1/results/task_result_1",),
            tuple(ref.url for ref in result_message.refs),
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
