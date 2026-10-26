from __future__ import annotations

import gzip
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from itertools import count
from unittest import TestCase

from message_hub.domain import (
    AgentTokenVerificationError,
    DeliveryStatus,
    ForbiddenDeliveryError,
    ForbiddenPayloadError,
    InvalidMessageError,
    IdempotencyConflictError,
    InvalidTaskTransitionError,
    MAX_ENVELOPE_INLINE_CHARS,
    MessageHubService,
    MessageRef,
    NotFoundError,
    PayloadUnavailableError,
    TASK_LIFECYCLE_TRANSITIONS,
    TaskCapacityTier,
    TaskCreditLedgerEntryType,
    TaskState,
    TaskWorkerReputationEventType,
    task_lifecycle_allows,
    task_lifecycle_next_states,
)
from message_hub.storage import InMemoryMessageHubRepository
from message_hub.storage.repository import AtomicCommitConflict


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

    def test_concurrent_keyed_sends_commit_one_resource_set(self) -> None:
        barrier = __import__("threading").Barrier(100)
        original = self.repository.get_idempotency_record
        calls = {"count": 0}
        calls_lock = __import__("threading").Lock()

        def synchronized(*args, **kwargs):
            value = original(*args, **kwargs)
            with calls_lock:
                should_wait = args[1] == "concurrent-key" and calls["count"] < 100
                calls["count"] += 1
            if should_wait:
                barrier.wait(timeout=10)
            return value

        self.repository.get_idempotency_record = synchronized  # type: ignore[method-assign]

        def send():
            return self.service.send_message(
                sender_handle="@researcher:gulls.ai",
                recipient_handles=["@reviewer:gulls.ai"],
                content="one accepted operation",
                idempotency_key="concurrent-key",
            )

        with ThreadPoolExecutor(max_workers=100) as pool:
            results = list(pool.map(lambda _: send(), range(100)))

        self.assertEqual(1, len(self.repository.list_messages_by_sender(self.sender.agent_id)))
        self.assertEqual(1, len({result.message.message_id for result in results}))
        self.assertEqual(1, len({result.thread.thread_id for result in results}))
        self.assertEqual({1}, {result.thread.message_count for result in results})
        self.assertEqual(1, len(self.repository.list_deliveries_by_recipient(self.recipient.agent_id)))

    def test_key_reuse_with_changed_content_is_rejected(self) -> None:
        self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="first",
            idempotency_key="same-key",
        )
        with self.assertRaisesRegex(IdempotencyConflictError, "different request"):
            self.service.send_message(
                sender_handle="@researcher:gulls.ai",
                recipient_handles=["@reviewer:gulls.ai"],
                content="changed",
                idempotency_key="same-key",
            )

    def test_keyed_task_retry_reuses_notification_and_task(self) -> None:
        first = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Review the queued task.",
            idempotency_key="task-key",
        )
        second = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Review the queued task.",
            idempotency_key="task-key",
        )
        self.assertEqual(first.task_id, second.task_id)
        self.assertEqual(first.request_message_id, second.request_message_id)
        self.assertEqual(1, len(self.repository.list_tasks_by_requester(self.sender.agent_id)))
        self.assertEqual(1, len(self.repository.list_messages_by_sender(self.sender.agent_id)))

    def test_same_task_payload_with_different_keys_creates_distinct_tasks(self) -> None:
        first = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Review the queued task.",
            idempotency_key="task-key-a",
        )
        second = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Review the queued task.",
            idempotency_key="task-key-b",
        )
        self.assertNotEqual(first.task_id, second.task_id)
        self.assertNotEqual(first.request_message_id, second.request_message_id)
        self.assertEqual(2, len(self.repository.list_tasks_by_requester(self.sender.agent_id)))

    def test_send_into_existing_thread_requires_participation(self) -> None:
        started = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Kicking off the thread.",
        )
        thread_id = started.thread.thread_id

        # A participant (the recipient) may reply into the thread.
        reply = self.service.send_message(
            sender_handle="@reviewer:gulls.ai",
            recipient_handles=["@researcher:gulls.ai"],
            content="Replying.",
            thread_id=thread_id,
        )
        self.assertEqual(thread_id, reply.thread.thread_id)

        # A non-participant may not inject a message by guessing the thread id.
        with self.assertRaises(ForbiddenDeliveryError):
            self.service.send_message(
                sender_handle="@map-reader:gulls.ai",
                recipient_handles=["@researcher:gulls.ai"],
                content="Injecting into a thread I am not part of.",
                thread_id=thread_id,
            )

    def test_needs_review_delivery_is_hidden_from_inbox_and_not_actionable(self) -> None:
        self.service.add_routing_rule(
            name="Hold for review",
            route_to_handles=["@map-reader:gulls.ai"],
            mode="review",
            url_contains=["maps.google.com"],
        )

        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Sensitive: please approve before I act.",
            refs=(MessageRef(type="url", url="https://maps.google.com/example", find="identify_place"),),
        )
        held = next(
            delivery
            for delivery in result.deliveries
            if delivery.recipient_agent_id == self.recipient.agent_id
        )
        self.assertEqual(DeliveryStatus.NEEDS_REVIEW, held.status)

        # The recipient must not see held content in their inbox...
        inbox = self.service.get_inbox("@reviewer:gulls.ai")
        self.assertEqual((), inbox)

        # ...nor be able to reply/act/ack on it until a human releases it.
        with self.assertRaises(ForbiddenDeliveryError):
            self.service.decide_delivery(
                held.delivery_id,
                agent_handle="@reviewer:gulls.ai",
                decision="reply",
                content="acting on unreviewed content",
            )

        # Acking is acting on it: the ack must not un-hide the held content.
        with self.assertRaises(ForbiddenDeliveryError):
            self.service.ack_delivery(held.delivery_id, recipient_handle="@reviewer:gulls.ai")
        self.assertEqual(
            DeliveryStatus.NEEDS_REVIEW,
            self.repository.get_delivery(held.delivery_id).status,
        )
        self.assertEqual((), self.service.get_inbox("@reviewer:gulls.ai"))

    def test_held_deliveries_do_not_evict_real_ones_from_the_inbox(self) -> None:
        self.service.add_routing_rule(
            name="Hold for review",
            route_to_handles=["@map-reader:gulls.ai"],
            mode="review",
            url_contains=["maps.google.com"],
        )

        delivered = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Real work that must stay visible.",
        )
        for index in range(25):
            self.service.send_message(
                sender_handle="@researcher:gulls.ai",
                recipient_handles=["@reviewer:gulls.ai"],
                content=f"Held flood {index}.",
                refs=(
                    MessageRef(
                        type="url",
                        url="https://maps.google.com/example",
                        find="identify_place",
                    ),
                ),
            )

        # The holds are all newer than the real delivery, so filtering after the
        # row limit would push the real one out of every allowed window.
        inbox = self.service.get_inbox("@reviewer:gulls.ai", limit=5)

        self.assertEqual(1, len(inbox))
        self.assertEqual(delivered.message.message_id, inbox[0].message.message_id)

    def test_task_state_transitions_are_enforced_and_settlement_is_requester_only(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Do the paid work.",
        )

        # Illegal jump: cannot go straight from requested to completed.
        with self.assertRaises(InvalidTaskTransitionError):
            self.service.update_task_state(
                task.task_id, actor_handle="@researcher:gulls.ai", state="completed"
            )

        # Walk to result_ready through valid transitions.
        self.service.update_task_state(task.task_id, actor_handle="@researcher:gulls.ai", state="accepted")
        self.service.update_task_state(task.task_id, actor_handle="@reviewer:gulls.ai", state="running")
        self.service.update_task_state(task.task_id, actor_handle="@reviewer:gulls.ai", state="result_ready")

        # The worker must not self-accept its own result and inflate its reputation.
        with self.assertRaises(ForbiddenDeliveryError):
            self.service.update_task_state(
                task.task_id, actor_handle="@reviewer:gulls.ai", state="result_accepted"
            )

        # ...and it must not reach around update_task_state to do the same thing
        # by naming a settlement state on its own result.
        with self.assertRaises(ForbiddenDeliveryError):
            self.service.return_task_result(
                task.task_id,
                responder_handle="@reviewer:gulls.ai",
                state="result_accepted",
                content="Self-awarding my own acceptance.",
            )
        with self.assertRaises(ForbiddenDeliveryError):
            self.service.return_task_result(
                task.task_id,
                responder_handle="@reviewer:gulls.ai",
                state="released",
                content="Self-releasing the escrow.",
            )
        # Nor may it strand the task in a state a result cannot produce.
        with self.assertRaises(InvalidTaskTransitionError):
            self.service.return_task_result(
                task.task_id,
                responder_handle="@reviewer:gulls.ai",
                state="canceled",
                content="Locking the requester out.",
            )
        self.assertEqual(TaskState.RESULT_READY, self.service.get_task(task.task_id).state)
        self.assertEqual(
            (),
            self.repository.list_task_worker_reputation_events_by_task(task.task_id),
        )

        # The requester (counterparty) can accept and complete it.
        accepted = self.service.update_task_state(
            task.task_id, actor_handle="@researcher:gulls.ai", state="result_accepted"
        )
        self.assertEqual(TaskState.RESULT_ACCEPTED, accepted.state)
        self.service.update_task_state(task.task_id, actor_handle="@researcher:gulls.ai", state="completed")

        # Terminal states are terminal: a completed task cannot be reactivated.
        with self.assertRaises(InvalidTaskTransitionError):
            self.service.update_task_state(
                task.task_id, actor_handle="@reviewer:gulls.ai", state="running"
            )
        # ...through accept_task either, which is the same lifecycle edge.
        with self.assertRaises(InvalidTaskTransitionError):
            self.service.accept_task(task.task_id, worker_handle="@reviewer:gulls.ai")
        self.assertEqual(TaskState.COMPLETED, self.service.get_task(task.task_id).state)

    def test_worker_can_still_settle_its_own_result_as_completed_or_failed(self) -> None:
        completed_task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Complete the work and return the result.",
        )
        failed_task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Fail the work and say so.",
        )

        # The default state of return_task_result is the worker's own contract.
        completed = self.service.return_task_result(
            completed_task.task_id,
            responder_handle="@reviewer:gulls.ai",
            content="Done.",
        )
        failed = self.service.return_task_result(
            failed_task.task_id,
            responder_handle="@reviewer:gulls.ai",
            state="failed",
            error="Worker could not finish.",
        )

        self.assertEqual(TaskState.COMPLETED, completed.state)
        self.assertEqual(TaskState.COMPLETED, self.service.get_task(completed_task.task_id).state)
        self.assertEqual(TaskState.FAILED, failed.state)
        self.assertEqual(TaskState.FAILED, self.service.get_task(failed_task.task_id).state)

    def test_agent_token_issue_stores_hash_and_validates_scope(self) -> None:
        issued = self.service.issue_agent_token(
            "@reviewer:gulls.ai",
            scopes=("agent:inbox", "agent:read", "agent:inbox"),
            name="reviewer runtime",
            owner_user_id="user_1",
            node_id="node_1",
            expires_at=datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(days=1),
        )

        self.assertTrue(issued.token.startswith("sga_"))
        self.assertNotEqual(issued.token, issued.record.token_hash)
        self.assertNotIn(issued.token, issued.record.token_hash)
        self.assertEqual(self.recipient.agent_id, issued.record.agent_id)
        self.assertEqual("@reviewer:gulls.ai", issued.record.agent_handle)
        self.assertEqual(("agent:inbox", "agent:read"), issued.record.scopes)
        self.assertEqual("user_1", issued.record.owner_user_id)
        self.assertEqual("node_1", issued.record.node_id)
        self.assertIsNone(issued.record.last_used_at)
        self.assertIsNone(issued.record.revoked_at)

        principal = self.service.verify_agent_token(
            issued.token,
            required_scope="agent:inbox",
            agent_handle="@reviewer:gulls.ai",
        )
        stored = self.repository.get_agent_token(issued.record.token_id)

        self.assertEqual(issued.record.token_id, principal.token_id)
        self.assertEqual(self.recipient.agent_id, principal.agent_id)
        self.assertEqual("@reviewer:gulls.ai", principal.agent_handle)
        self.assertEqual(frozenset({"agent:inbox", "agent:read"}), principal.scopes)
        self.assertEqual("user_1", principal.owner_user_id)
        self.assertEqual("node_1", principal.node_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(issued.record.token_hash, stored.token_hash)
        self.assertIsNotNone(stored.last_used_at)

    def test_agent_token_rejects_invalid_expired_revoked_scope_and_cross_agent_use(self) -> None:
        issued = self.service.issue_agent_token(
            "@reviewer:gulls.ai",
            scopes=("agent:read",),
        )

        with self.assertRaises(AgentTokenVerificationError):
            self.service.verify_agent_token("sgc_not_an_agent_token")
        with self.assertRaises(AgentTokenVerificationError):
            self.service.verify_agent_token(f"{issued.token}tampered")
        with self.assertRaises(AgentTokenVerificationError):
            self.service.verify_agent_token(issued.token, required_scope="agent:post")
        with self.assertRaises(AgentTokenVerificationError):
            self.service.verify_agent_token(issued.token, agent_handle="@researcher:gulls.ai")
        with self.assertRaises(InvalidMessageError):
            self.service.issue_agent_token(
                "@reviewer:gulls.ai",
                scopes=("messages:write",),
            )

        expired = self.service.issue_agent_token(
            "@reviewer:gulls.ai",
            scopes=("agent:read",),
            expires_at=datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(seconds=1),
        )
        with self.assertRaises(AgentTokenVerificationError):
            self.service.verify_agent_token(expired.token, required_scope="agent:read")

        revoked = self.service.issue_agent_token(
            "@reviewer:gulls.ai",
            scopes=("agent:read",),
        )
        revoked_record = self.service.revoke_agent_token(revoked.record.token_id)
        self.assertIsNotNone(revoked_record.revoked_at)
        with self.assertRaises(AgentTokenVerificationError):
            self.service.verify_agent_token(revoked.token, required_scope="agent:read")

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

    def test_task_credit_lifecycle_states_can_be_recorded(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Quote and complete paid review work.",
            allowed_use_terms=("paid_worker", "human_approval_required"),
        )
        lifecycle_path = (
            TaskState.REQUESTED,
            TaskState.QUOTED,
            TaskState.NEEDS_APPROVAL,
            TaskState.APPROVED,
            TaskState.ESCROWED,
            TaskState.ACCEPTED,
            TaskState.RUNNING,
            TaskState.RESULT_READY,
            TaskState.RESULT_ACCEPTED,
            TaskState.RELEASED,
            TaskState.COMPLETED,
        )
        for current, next_state in zip(lifecycle_path, lifecycle_path[1:]):
            self.assertTrue(task_lifecycle_allows(current, next_state))

        quoted = self.service.update_task_state(
            task.task_id,
            actor_handle="@reviewer:gulls.ai",
            state="quoted",
            note="3 credits.",
        )
        approval_needed = self.service.update_task_state(
            task.task_id,
            actor_handle="@researcher:gulls.ai",
            state="needs_approval",
            note="Owner approval required for paid private-context work.",
        )
        approved = self.service.update_task_state(
            task.task_id,
            actor_handle="@researcher:gulls.ai",
            state="approved",
        )
        escrowed = self.service.update_task_state(
            task.task_id,
            actor_handle="@researcher:gulls.ai",
            state="escrowed",
        )
        accepted = self.service.accept_task(
            task.task_id,
            worker_handle="@reviewer:gulls.ai",
        )
        running = self.service.update_task_state(
            task.task_id,
            actor_handle="@reviewer:gulls.ai",
            state="running",
        )
        result = self.service.return_task_result(
            task.task_id,
            responder_handle="@reviewer:gulls.ai",
            state="result_ready",
            content="Ready for requester acceptance.",
        )
        accepted_result = self.service.update_task_state(
            task.task_id,
            actor_handle="@researcher:gulls.ai",
            state="result_accepted",
        )
        released = self.service.update_task_state(
            task.task_id,
            actor_handle="@researcher:gulls.ai",
            state="released",
        )
        completed = self.service.update_task_state(
            task.task_id,
            actor_handle="@researcher:gulls.ai",
            state="completed",
        )

        self.assertEqual(TaskState.QUOTED, quoted.state)
        self.assertEqual(TaskState.NEEDS_APPROVAL, approval_needed.state)
        self.assertEqual(TaskState.APPROVED, approved.state)
        self.assertEqual(TaskState.ESCROWED, escrowed.state)
        self.assertEqual(TaskState.ACCEPTED, accepted.state)
        self.assertEqual(TaskState.RUNNING, running.state)
        self.assertEqual(TaskState.RESULT_READY, result.state)
        self.assertEqual(TaskState.RESULT_ACCEPTED, accepted_result.state)
        self.assertEqual(TaskState.RELEASED, released.state)
        self.assertEqual(TaskState.COMPLETED, completed.state)
        self.assertIn(TaskState.DISPUTED, task_lifecycle_next_states(TaskState.RESULT_READY))
        self.assertIn(TaskState.CANCELED, TASK_LIFECYCLE_TRANSITIONS[TaskState.DISPUTED])

    def test_task_quote_approval_and_escrow_flow_is_auditable(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Use reviewer capacity for private plan review.",
            context_refs=("thread://thread_1",),
            context_pack_ref="payload://context_pack_1",
            input_ref="payload://task_1/input",
            allowed_use_terms=("paid_worker", "human_approval_required"),
        )

        quote = self.service.create_task_quote(
            task.task_id,
            worker_handle="@reviewer:gulls.ai",
            expected_credit_cost=3,
            task_reason="Private plan review requires independent capacity.",
            shared_context_refs=("thread://thread_1", "payload://context_pack_1"),
            requires_approval=True,
            approval_reason="Paid private-context work requires owner approval.",
            limits_ref="seagull://tasks/task_1/limits",
            abuse_policy_ref="seagull://policies/task-credits/abuse-controls",
            policy_decision_id="policy_quote_1",
        )
        quoted_task = self.service.get_task(task.task_id)
        quote_messages = self.repository.list_thread_messages(task.thread_id)

        self.assertEqual("task_quote_1", quote.quote_id)
        self.assertEqual(3, quote.expected_credit_cost)
        self.assertEqual(("thread://thread_1", "payload://context_pack_1"), quote.shared_context_refs)
        self.assertEqual("Private plan review requires independent capacity.", quote.task_reason)
        self.assertEqual("Paid private-context work requires owner approval.", quote.approval_reason)
        self.assertEqual(TaskState.QUOTED, quoted_task.state)
        self.assertEqual(("task_quote_1",), quoted_task.quote_ids)
        self.assertEqual("task_quote", quote_messages[-1].intent)
        self.assertEqual("seagull://tasks/task_1/quotes/task_quote_1", quote_messages[-1].refs[0].url)

        with self.assertRaises(InvalidMessageError):
            self.service.create_task_escrow(
                task.task_id,
                requester_handle="@researcher:gulls.ai",
                quote_id=quote.quote_id,
            )

        approved = self.service.approve_task_quote(
            quote.quote_id,
            approver_handle="@researcher:gulls.ai",
            approval_id="approval_1",
            policy_decision_id="policy_approval_1",
        )
        self.assertEqual(self.sender.agent_id, approved.approved_by_agent_id)
        self.assertEqual("approval_1", approved.approval_id)
        self.assertEqual("policy_approval_1", approved.policy_decision_id)
        self.assertEqual(TaskState.APPROVED, self.service.get_task(task.task_id).state)

        grant = self.service.grant_task_credits(
            agent_handle="@researcher:gulls.ai",
            amount=10,
            reason="Internal test allocation.",
            limits_ref="seagull://task-credits/limits",
            abuse_policy_ref="seagull://policies/task-credits/abuse-controls",
        )
        self.assertEqual(TaskCreditLedgerEntryType.CREDIT_GRANT, grant.entry_type)
        self.assertEqual(10, self.service.get_task_credit_balance("@researcher:gulls.ai").available_balance)

        escrow = self.service.create_task_escrow(
            task.task_id,
            requester_handle="@researcher:gulls.ai",
            quote_id=quote.quote_id,
        )
        escrowed_task = self.service.get_task(task.task_id)
        requester_balance = self.service.get_task_credit_balance("@researcher:gulls.ai")
        task_ledger = self.service.list_task_credit_ledger_for_task(task.task_id)
        self.assertEqual("task_escrow_1", escrow.escrow_id)
        self.assertEqual(TaskState.ESCROWED, escrow.state)
        self.assertEqual(quote.expected_credit_cost, escrow.credit_amount)
        self.assertEqual("approval_1", escrow.approval_id)
        self.assertEqual("seagull://tasks/task_1/limits", escrow.limits_ref)
        self.assertEqual("seagull://policies/task-credits/abuse-controls", escrow.abuse_policy_ref)
        self.assertEqual(("seagull://tasks/task_1/escrows/task_escrow_1/audit",), escrow.audit_refs)
        self.assertEqual(TaskState.ESCROWED, escrowed_task.state)
        self.assertEqual(("task_escrow_1",), escrowed_task.escrow_ids)
        self.assertEqual(7, requester_balance.available_balance)
        self.assertEqual(3, requester_balance.escrow_balance)
        self.assertEqual(TaskCreditLedgerEntryType.ESCROW_HOLD, task_ledger[-1].entry_type)
        self.assertEqual(-3, task_ledger[-1].available_delta)
        self.assertEqual(3, task_ledger[-1].escrow_delta)

        self.service.update_task_state(
            task.task_id,
            actor_handle="@reviewer:gulls.ai",
            state="running",
        )
        self.service.return_task_result(
            task.task_id,
            responder_handle="@reviewer:gulls.ai",
            state="result_ready",
            content="Ready for acceptance.",
        )
        self.service.update_task_state(
            task.task_id,
            actor_handle="@researcher:gulls.ai",
            state="result_accepted",
        )
        released = self.service.release_task_escrow(
            escrow.escrow_id,
            releaser_handle="@researcher:gulls.ai",
            note="Accepted.",
        )

        self.assertEqual(TaskState.RELEASED, released.state)
        self.assertIsNotNone(released.released_at)
        self.assertEqual(TaskState.RELEASED, self.service.get_task(task.task_id).state)
        self.assertEqual(7, self.service.get_task_credit_balance("@researcher:gulls.ai").available_balance)
        self.assertEqual(0, self.service.get_task_credit_balance("@researcher:gulls.ai").escrow_balance)
        self.assertEqual(3, self.service.get_task_credit_balance("@reviewer:gulls.ai").available_balance)
        task_ledger = self.service.list_task_credit_ledger_for_task(task.task_id)
        self.assertEqual(
            (
                TaskCreditLedgerEntryType.ESCROW_HOLD,
                TaskCreditLedgerEntryType.ESCROW_RELEASE,
                TaskCreditLedgerEntryType.ESCROW_RELEASE,
            ),
            tuple(entry.entry_type for entry in task_ledger),
        )

    def test_capacity_policy_limits_and_gates_worker_quotes(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Use reviewer capacity under explicit sharing limits.",
            context_refs=("thread://thread_1",),
            context_pack_ref="payload://context_pack_1",
        )
        policy = self.service.define_task_capacity_policy(
            task.task_id,
            actor_handle="@researcher:gulls.ai",
            requester_capacity_tier="low",
            worker_capacity_tier="high",
            max_credit_cost=5,
            max_auto_escrow_credits=2,
            allow_private_context=True,
            private_context_requires_approval=True,
            paid_work_requires_approval=False,
            high_cost_requires_approval=True,
            limits_ref="seagull://tasks/task_1/capacity-limits",
            abuse_policy_ref="seagull://policies/task-credits/abuse-controls",
            policy_decision_id="policy_capacity_1",
        )
        stored_task = self.service.get_task(task.task_id)
        self.assertEqual("capacity_policy_1", policy.policy_id)
        self.assertEqual(TaskCapacityTier.LOW, policy.requester_capacity_tier)
        self.assertEqual(TaskCapacityTier.HIGH, policy.worker_capacity_tier)
        self.assertEqual(("capacity_policy_1",), stored_task.capacity_policy_ids)

        quote = self.service.create_task_quote(
            task.task_id,
            worker_handle="@reviewer:gulls.ai",
            expected_credit_cost=3,
            task_reason="Share higher-capacity reviewer work.",
            shared_context_refs=("thread://thread_1", "file://private/context"),
            requires_approval=False,
        )

        self.assertTrue(quote.requires_approval)
        self.assertEqual(
            "private-context sharing requires approval; expected cost exceeds auto-escrow limit",
            quote.approval_reason,
        )
        self.assertEqual("seagull://tasks/task_1/capacity-limits", quote.limits_ref)
        self.assertEqual("seagull://policies/task-credits/abuse-controls", quote.abuse_policy_ref)
        self.assertEqual("policy_capacity_1", quote.policy_decision_id)

        with self.assertRaises(InvalidMessageError):
            self.service.create_task_quote(
                task.task_id,
                worker_handle="@reviewer:gulls.ai",
                expected_credit_cost=6,
                task_reason="Too much delegated capacity.",
            )

        private_blocked_task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Block private context when policy forbids it.",
        )
        self.service.define_task_capacity_policy(
            private_blocked_task.task_id,
            actor_handle="@researcher:gulls.ai",
            max_credit_cost=5,
            allow_private_context=False,
        )
        with self.assertRaises(ForbiddenDeliveryError):
            self.service.create_task_quote(
                private_blocked_task.task_id,
                worker_handle="@reviewer:gulls.ai",
                expected_credit_cost=1,
                task_reason="Private context should be refused.",
                shared_context_refs=("file://private/context",),
            )

    def test_worker_reputation_tracks_lifecycle_and_abuse_events(self) -> None:
        self.service.grant_task_credits(
            agent_handle="@researcher:gulls.ai",
            amount=10,
            reason="Internal test allocation.",
        )
        completed_task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Complete a paid review.",
        )
        completed_quote = self.service.create_task_quote(
            completed_task.task_id,
            worker_handle="@reviewer:gulls.ai",
            expected_credit_cost=2,
            task_reason="Small paid review.",
            requires_approval=False,
        )
        completed_escrow = self.service.create_task_escrow(
            completed_task.task_id,
            requester_handle="@researcher:gulls.ai",
            quote_id=completed_quote.quote_id,
        )
        self.service.return_task_result(
            completed_task.task_id,
            responder_handle="@reviewer:gulls.ai",
            state="result_ready",
            content="Done.",
        )
        self.service.update_task_state(
            completed_task.task_id,
            actor_handle="@researcher:gulls.ai",
            state="result_accepted",
            note="Accepted.",
        )
        self.service.release_task_escrow(
            completed_escrow.escrow_id,
            releaser_handle="@researcher:gulls.ai",
            note="Released.",
        )

        failed_task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Return a failed task result.",
        )
        self.service.return_task_result(
            failed_task.task_id,
            responder_handle="@reviewer:gulls.ai",
            state="failed",
            error="Worker failed to complete the task.",
        )

        disputed_task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Open a dispute.",
        )
        disputed_quote = self.service.create_task_quote(
            disputed_task.task_id,
            worker_handle="@reviewer:gulls.ai",
            expected_credit_cost=1,
            task_reason="Disputable review.",
            requires_approval=False,
        )
        disputed_escrow = self.service.create_task_escrow(
            disputed_task.task_id,
            requester_handle="@researcher:gulls.ai",
            quote_id=disputed_quote.quote_id,
        )
        self.service.dispute_task_escrow(
            disputed_escrow.escrow_id,
            actor_handle="@researcher:gulls.ai",
            reason="Result did not match the requested scope.",
        )
        abuse_event = self.service.report_task_worker_abuse(
            disputed_task.task_id,
            reporter_handle="@researcher:gulls.ai",
            reason="Worker repeatedly ignored scope limits.",
            policy_decision_id="policy_abuse_1",
        )

        summary = self.service.get_task_worker_reputation("@reviewer:gulls.ai")
        events = self.service.list_task_worker_reputation_events("@reviewer:gulls.ai")

        self.assertEqual("task_reputation_event_5", abuse_event.event_id)
        self.assertEqual(TaskWorkerReputationEventType.ABUSE_REPORTED, abuse_event.event_type)
        self.assertEqual("policy_abuse_1", abuse_event.policy_decision_id)
        self.assertEqual(1, summary.completed_task_count)
        self.assertEqual(1, summary.failed_task_count)
        self.assertEqual(1, summary.accepted_result_count)
        self.assertEqual(1, summary.dispute_count)
        self.assertEqual(1, summary.abuse_report_count)
        self.assertEqual(2, summary.total_outcome_count)
        self.assertEqual(0.5, summary.completion_rate)
        self.assertEqual(0.5, summary.failure_rate)
        self.assertEqual("task_reputation_event_5", summary.last_event_id)
        self.assertEqual(
            (
                TaskWorkerReputationEventType.RESULT_ACCEPTED,
                TaskWorkerReputationEventType.TASK_COMPLETED,
                TaskWorkerReputationEventType.TASK_FAILED,
                TaskWorkerReputationEventType.DISPUTE_OPENED,
                TaskWorkerReputationEventType.ABUSE_REPORTED,
            ),
            tuple(event.event_type for event in events),
        )
        self.assertEqual(
            ("seagull://tasks/task_3/worker-reputation/task_reputation_event_5/audit",),
            abuse_event.audit_refs,
        )
        with self.assertRaises(InvalidMessageError):
            self.service.report_task_worker_abuse(
                disputed_task.task_id,
                reporter_handle="@researcher:gulls.ai",
                reason="Duplicate abuse report.",
            )

    def test_task_escrow_without_required_approval_can_be_created_after_quote(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Use reviewer capacity for a preapproved small task.",
            context_refs=("thread://thread_1",),
        )
        quote = self.service.create_task_quote(
            task.task_id,
            worker_handle="@reviewer:gulls.ai",
            expected_credit_cost=1,
            task_reason="Small preapproved review.",
            requires_approval=False,
        )
        self.service.grant_task_credits(
            agent_handle="@researcher:gulls.ai",
            amount=1,
            reason="Internal test allocation.",
        )

        escrow = self.service.create_task_escrow(
            task.task_id,
            requester_handle="@researcher:gulls.ai",
            quote_id=quote.quote_id,
        )

        self.assertIsNone(escrow.approval_id)
        self.assertEqual(TaskState.ESCROWED, escrow.state)

    def test_task_credit_ledger_handles_dispute_and_cancel(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Use reviewer capacity for a disputable task.",
        )
        quote = self.service.create_task_quote(
            task.task_id,
            worker_handle="@reviewer:gulls.ai",
            expected_credit_cost=4,
            task_reason="Disputable review.",
            requires_approval=False,
        )
        self.service.grant_task_credits(
            agent_handle="@researcher:gulls.ai",
            amount=4,
            reason="Internal test allocation.",
        )
        escrow = self.service.create_task_escrow(
            task.task_id,
            requester_handle="@researcher:gulls.ai",
            quote_id=quote.quote_id,
        )

        disputed = self.service.dispute_task_escrow(
            escrow.escrow_id,
            actor_handle="@reviewer:gulls.ai",
            reason="Result acceptance is blocked.",
        )
        requester_balance = self.service.get_task_credit_balance("@researcher:gulls.ai")
        self.assertEqual(TaskState.DISPUTED, disputed.state)
        self.assertEqual(TaskState.DISPUTED, self.service.get_task(task.task_id).state)
        self.assertEqual(0, requester_balance.available_balance)
        self.assertEqual(4, requester_balance.escrow_balance)

        canceled = self.service.cancel_task_escrow(
            escrow.escrow_id,
            actor_handle="@researcher:gulls.ai",
            note="Refund after dispute.",
        )
        requester_balance = self.service.get_task_credit_balance("@researcher:gulls.ai")
        task_ledger = self.service.list_task_credit_ledger_for_task(task.task_id)

        self.assertEqual(TaskState.CANCELED, canceled.state)
        self.assertEqual(TaskState.CANCELED, self.service.get_task(task.task_id).state)
        self.assertEqual(4, requester_balance.available_balance)
        self.assertEqual(0, requester_balance.escrow_balance)
        self.assertEqual(
            (
                TaskCreditLedgerEntryType.ESCROW_HOLD,
                TaskCreditLedgerEntryType.DISPUTE_OPEN,
                TaskCreditLedgerEntryType.ESCROW_CANCEL,
            ),
            tuple(entry.entry_type for entry in task_ledger),
        )
        self.assertEqual("Result acceptance is blocked.", task_ledger[1].reason)
        self.assertEqual(4, task_ledger[2].available_delta)
        self.assertEqual(-4, task_ledger[2].escrow_delta)

    def test_preapproved_tool_request_requires_active_tool_grant(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Read task-scoped repository files.",
            allowed_tool_names=("repo_read",),
        )

        with self.assertRaises(InvalidMessageError):
            self.service.create_tool_request(
                task.task_id,
                requester_handle="@researcher:gulls.ai",
                worker_handle="@reviewer:gulls.ai",
                tool_name="repo_read",
                purpose="Read requested files only.",
                requires_approval=False,
            )

        grant = self.service.create_tool_grant(
            task.task_id,
            issuer_handle="@researcher:gulls.ai",
            subject_handle="@reviewer:gulls.ai",
            audience="seagull://agents/agent_2/tools",
            scopes=("repo_read",),
            purpose="Allow read-only repo access for this task.",
            ttl_expires_at=datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(seconds=100),
            max_calls=2,
            allowed_resource_selectors=("docs/**",),
            approval_id="approval_1",
            policy_decision_id="policy_1",
        )
        self.assertEqual("tool_grant_1", grant.grant_id)
        self.assertEqual(("repo_read",), grant.scopes)
        self.assertEqual(("tool_grant_1",), self.service.get_task(task.task_id).tool_grant_ids)

        tool_request = self.service.create_tool_request(
            task.task_id,
            requester_handle="@researcher:gulls.ai",
            worker_handle="@reviewer:gulls.ai",
            tool_name="repo_read",
            purpose="Read requested files only.",
            requires_approval=False,
            tool_grant_id=grant.grant_id,
        )
        used_grant = self.service.get_tool_grant(grant.grant_id)
        self.assertEqual(TaskState.REQUESTED, tool_request.status)
        self.assertEqual(grant.grant_id, tool_request.tool_grant_id)
        self.assertEqual(1, used_grant.used_count)

        completed = self.service.complete_tool_request(
            tool_request.tool_request_id,
            actor_handle="@reviewer:gulls.ai",
            state="completed",
            result_ref="payload://task_1/tool_result",
        )
        self.assertEqual(TaskState.COMPLETED, completed.status)

    def test_tool_grant_enforces_expiry_tool_scope_and_agent_scope(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Use one narrow private tool.",
            allowed_tool_names=("repo_read",),
        )
        expired_grant = self.service.create_tool_grant(
            task.task_id,
            issuer_handle="@researcher:gulls.ai",
            subject_handle="@reviewer:gulls.ai",
            audience="seagull://agents/agent_2/tools",
            scopes=("repo_read",),
            purpose="Expired grant.",
            ttl_expires_at=datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(seconds=1),
        )
        wrong_tool_grant = self.service.create_tool_grant(
            task.task_id,
            issuer_handle="@researcher:gulls.ai",
            subject_handle="@reviewer:gulls.ai",
            audience="seagull://agents/agent_2/tools",
            scopes=("repo_write",),
            purpose="Wrong tool grant.",
            ttl_expires_at=datetime(2026, 6, 12, tzinfo=timezone.utc) + timedelta(seconds=100),
        )

        with self.assertRaises(ForbiddenDeliveryError):
            self.service.create_tool_request(
                task.task_id,
                requester_handle="@researcher:gulls.ai",
                worker_handle="@reviewer:gulls.ai",
                tool_name="repo_read",
                purpose="Read requested files only.",
                requires_approval=False,
                tool_grant_id=expired_grant.grant_id,
            )
        with self.assertRaises(InvalidMessageError):
            self.service.create_tool_request(
                task.task_id,
                requester_handle="@researcher:gulls.ai",
                worker_handle="@reviewer:gulls.ai",
                tool_name="repo_write",
                purpose="Write requested files.",
                requires_approval=False,
                tool_grant_id=wrong_tool_grant.grant_id,
            )
        with self.assertRaises(ForbiddenDeliveryError):
            self.service.create_tool_request(
                task.task_id,
                requester_handle="@researcher:gulls.ai",
                worker_handle="@reviewer:gulls.ai",
                tool_name="repo_read",
                purpose="Read requested files only.",
                requires_approval=False,
                tool_grant_id=wrong_tool_grant.grant_id,
            )
        with self.assertRaises(ForbiddenDeliveryError):
            self.service.create_tool_grant(
                task.task_id,
                issuer_handle="@map-reader:gulls.ai",
                subject_handle="@reviewer:gulls.ai",
                audience="seagull://agents/agent_2/tools",
                scopes=("repo_read",),
                purpose="Wrong issuer.",
            )
        with self.assertRaises(ForbiddenDeliveryError):
            self.service.create_tool_grant(
                task.task_id,
                issuer_handle="@researcher:gulls.ai",
                subject_handle="@map-reader:gulls.ai",
                audience="seagull://agents/agent_3/tools",
                scopes=("repo_read",),
                purpose="Wrong subject.",
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

    def test_delegated_reply_replays_and_recovers_by_publication_key(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Please inspect this.",
        )
        delivery_id = result.deliveries[0].delivery_id
        first = self.service.publish_delegated_reply(
            delivery_id,
            agent_handle="@reviewer:gulls.ai",
            publication_key="task-1",
            content="Inspected. Looks fine.",
        )
        second = self.service.publish_delegated_reply(
            delivery_id,
            agent_handle="@reviewer:gulls.ai",
            publication_key="task-1",
            content="Inspected. Looks fine.",
        )
        self.assertEqual(first.reply.message.message_id, second.reply.message.message_id)
        self.assertEqual(2, len(self.service.get_thread(result.thread.thread_id)))
        receipt = self.service.delegated_reply_receipt(
            delivery_id,
            agent_handle="@reviewer:gulls.ai",
            publication_key="task-1",
        )
        self.assertIsNotNone(receipt)
        self.assertEqual(first.reply.message.message_id, receipt.message.message_id)
        with self.assertRaises(InvalidMessageError):
            self.service.publish_delegated_reply(
                delivery_id,
                agent_handle="@reviewer:gulls.ai",
                publication_key="another-key",
                content="A second public reply",
            )

    def test_delegated_reply_key_is_bound_to_source_delivery_and_content(self) -> None:
        first = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="First",
        )
        second = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Second",
        )
        self.service.publish_delegated_reply(
            first.deliveries[0].delivery_id,
            agent_handle="@reviewer:gulls.ai",
            publication_key="same-key",
            content="Reply one",
        )
        with self.assertRaises(IdempotencyConflictError):
            self.service.publish_delegated_reply(
                first.deliveries[0].delivery_id,
                agent_handle="@reviewer:gulls.ai",
                publication_key="same-key",
                content="Different content",
            )
        second_reply = self.service.publish_delegated_reply(
            second.deliveries[0].delivery_id,
            agent_handle="@reviewer:gulls.ai",
            publication_key="same-key",
            content="Reply two",
        )
        self.assertNotEqual("Reply one", second_reply.reply.message.content_inline)

    def test_manual_reply_claim_blocks_later_delegated_publication(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Please inspect this.",
        )
        self.service.decide_delivery(
            result.deliveries[0].delivery_id,
            agent_handle="@reviewer:gulls.ai",
            decision="reply",
            content="Manual answer",
        )
        with self.assertRaises(InvalidMessageError):
            self.service.publish_delegated_reply(
                result.deliveries[0].delivery_id,
                agent_handle="@reviewer:gulls.ai",
                publication_key="late-task",
                content="Late agent answer",
            )

    def test_ack_does_not_overwrite_replied_delivery(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Please inspect this.",
        )
        delivery_id = result.deliveries[0].delivery_id
        self.service.publish_delegated_reply(
            delivery_id,
            agent_handle="@reviewer:gulls.ai",
            publication_key="ack-guard",
            content="Completed",
        )
        self.assertEqual(DeliveryStatus.REPLIED, self.service.ack_delivery(
            delivery_id,
            recipient_handle="@reviewer:gulls.ai",
        ).status)
        hooked = self.service.apply_hook_result(
            delivery_id,
            hook="reply.before",
            runtime="cloud_node",
            action="review",
            note="late hook",
        )
        self.assertEqual(DeliveryStatus.REPLIED, hooked.status)
        with self.assertRaises(InvalidMessageError):
            self.service.publish_delegated_reply(
                delivery_id,
                agent_handle="@reviewer:gulls.ai",
                publication_key="late-hook-reply",
                content="Duplicate after hook",
            )

    def test_concurrent_delegated_publications_claim_one_source_delivery(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Please inspect this.",
        )
        delivery_id = result.deliveries[0].delivery_id

        def publish(index: int):
            try:
                return self.service.publish_delegated_reply(
                    delivery_id,
                    agent_handle="@reviewer:gulls.ai",
                    publication_key=f"parallel-{index}",
                    content=f"Answer {index}",
                )
            except (InvalidMessageError, IdempotencyConflictError, AtomicCommitConflict):
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(publish, range(8)))
        self.assertEqual(1, sum(outcome is not None for outcome in outcomes))
        self.assertEqual(2, len(self.service.get_thread(result.thread.thread_id)))

    def test_delegated_reply_replays_after_commit_reports_uncertain_conflict(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Please inspect this.",
        )
        original_commit = self.repository.commit_message_send
        injected = {"done": False}

        def commit_then_report_uncertain(**kwargs):
            created = original_commit(**kwargs)
            if not injected["done"] and kwargs.get("source_delivery") is not None:
                injected["done"] = True
                raise AtomicCommitConflict("simulated lost response")
            return created

        self.repository.commit_message_send = commit_then_report_uncertain  # type: ignore[method-assign]
        published = self.service.publish_delegated_reply(
            result.deliveries[0].delivery_id,
            agent_handle="@reviewer:gulls.ai",
            publication_key="uncertain-1",
            content="Recovered answer",
        )
        self.assertEqual("Recovered answer", published.reply.message.content_inline)
        self.assertEqual(2, len(self.service.get_thread(result.thread.thread_id)))

    def test_delegated_reply_receipt_has_no_short_idempotency_expiry(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Please inspect this.",
        )
        delivery_id = result.deliveries[0].delivery_id
        published = self.service.publish_delegated_reply(
            delivery_id,
            agent_handle="@reviewer:gulls.ai",
            publication_key="durable-1",
            content="Durable answer",
        )
        runtime = self.repository.get_agent_by_handle("@reviewer:gulls.ai")
        self.assertIsNotNone(runtime)
        record = self.repository.get_idempotency_record(
            runtime.agent_id,
            f"gulls-delegated-reply:{delivery_id}:durable-1",
        )
        self.assertIsNotNone(record)
        self.assertIsNone(record[2])
        receipt = self.service.delegated_reply_receipt(
            delivery_id,
            agent_handle="@reviewer:gulls.ai",
            publication_key="durable-1",
        )
        self.assertEqual(published.reply.message.message_id, receipt.message.message_id)

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

    def test_contact_explanation_summarizes_delivery_and_pending_action(self) -> None:
        result = self.service.send_message(
            sender_handle="@researcher:gulls.ai",
            recipient_handles=["@reviewer:gulls.ai"],
            content="Open this URL when approved.",
            content_ref="payload://thread_1/message_1/full",
            refs=(MessageRef(type="url", url="https://example.com", remember_as="approval target"),),
        )
        self.service.save_thread_summary(result.thread.thread_id, "Researcher asked reviewer to inspect a URL.")

        explanation = self.service.explain_contact(result.deliveries[0].delivery_id)

        self.assertEqual("contact_explanation_delivery_1", explanation.explanation_id)
        self.assertEqual("@researcher:gulls.ai", explanation.requester_handle)
        self.assertEqual("@reviewer:gulls.ai", explanation.answering_asset_handle)
        self.assertEqual("needs_approval", explanation.relationship)
        self.assertIn("sent a message", explanation.reason)
        self.assertIn("message safety status is approved", explanation.allowed_reason)
        self.assertEqual("Researcher asked reviewer to inspect a URL.", explanation.shared_context_summary)
        self.assertEqual(
            ("payload://thread_1/message_1/full", "https://example.com"),
            explanation.shared_context_refs,
        )
        self.assertIsNone(explanation.pending_action)
        self.assertIn("message_safety:approved", explanation.policy_refs)
        self.assertIn("delivery:delivery_1:delivered", explanation.audit_event_refs)

        decision = self.service.decide_delivery(
            result.deliveries[0].delivery_id,
            agent_handle="@reviewer:gulls.ai",
            decision="action",
            action_type="open_url",
            action_target="https://example.com",
            action_runtime="cloud_node",
        )
        action_explanation = self.service.explain_contact(decision.delivery.delivery_id)

        self.assertEqual("action.before", action_explanation.current_stage)
        self.assertEqual("open_url for https://example.com (requires approval)", action_explanation.pending_action)
        self.assertIn("action_approval_required:true", action_explanation.policy_refs)
        self.assertIn("action_request:action_1:pending", action_explanation.audit_event_refs)

    def test_contact_explanation_includes_task_policy_state(self) -> None:
        task = self.service.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Review the referenced plan.",
            context_refs=("payload://task_1/context",),
            input_ref="payload://task_1/input",
        )
        delivery = self.service.get_inbox("@reviewer:gulls.ai")[0].delivery

        explanation = self.service.explain_contact(delivery.delivery_id)

        self.assertEqual(task.request_message_id, explanation.message_id)
        self.assertIn("requested delegated task work", explanation.reason)
        self.assertEqual("task task_1 is requested", explanation.pending_action)
        self.assertIn("payload://task_1/context", explanation.shared_context_refs)
        self.assertIn("payload://task_1/input", explanation.shared_context_refs)
        self.assertIn("policy_decision:local_safety_allow", explanation.policy_refs)

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
