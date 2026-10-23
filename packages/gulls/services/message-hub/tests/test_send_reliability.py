"""Replay and API regressions for atomic message/task creation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from message_hub.api import ApiError, LocalMessageHubApi
from message_hub.domain import DeliveryStatus, MessageHubService
from message_hub.storage import InMemoryMessageHubRepository
from message_hub.storage.repository import (
    AtomicCommitConflict,
    IdempotencyRecoveryConflict,
    SendTooLargeError,
)


class SendReliabilityTests(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMessageHubRepository()
        self.service = MessageHubService(self.repository)
        self.api = LocalMessageHubApi(self.service)
        self.sender = "@sender:gulls.ai"
        self.recipient = "@recipient:gulls.ai"
        registration = self.api.agent_registration({"handle": self.sender})
        self.authorization = "Bearer " + registration["token"]
        self.api.register_agent({"handle": self.recipient})
        self.message_body = {
            "sender_handle": self.sender,
            "recipient_handles": [self.recipient],
            "content": "One accepted operation.",
            "idempotency_key": "message-key",
        }
        self.task_body = {
            "requester_handle": self.sender,
            "recipient_handle": self.recipient,
            "objective": "Review the proposed change.",
            "idempotency_key": "task-key",
        }

    def test_replay_uses_committed_delivery_ids_during_index_lag(self) -> None:
        first = self.api.create_message(self.message_body)
        with patch.object(
            self.repository, "list_deliveries_by_message", side_effect=AssertionError("GSI must not be used")
        ):
            replay = self.api.create_message(self.message_body)
        self.assertEqual(first, replay)

    def test_task_replay_uses_committed_delivery_ids_before_policy_changes(self) -> None:
        first = self.api.create_task(self.task_body)
        with (
            patch.object(self.repository, "list_deliveries_by_message", side_effect=AssertionError("GSI lag")),
            patch.object(self.service._safety_evaluator, "evaluate_send", side_effect=AssertionError("policy changed")),
        ):
            replay = self.api.create_task(self.task_body)
        self.assertEqual(first, replay)

    def test_missing_replay_resources_require_recovery_instead_of_rejection(self) -> None:
        first = self.api.create_message(self.message_body)
        for method in ("get_message", "get_thread"):
            with self.subTest(method=method), patch.object(self.repository, method, return_value=None):
                self.assert_recovery_required()
        with patch.object(
            self.repository, "list_deliveries_by_ids",
            side_effect=IdempotencyRecoveryConflict("delivery is missing"),
        ):
            self.assert_recovery_required()
        self.assertEqual(first, self.api.create_message(self.message_body))

    def assert_recovery_required(self) -> None:
        with self.assertRaises(ApiError) as error:
            self.api.create_message(self.message_body)
        self.assertEqual((409, "idempotency_recovery_required"), (error.exception.status_code, error.exception.error))

    def test_legacy_replay_with_incomplete_index_remains_retryable(self) -> None:
        result = self.service.send_message(
            sender_handle=self.sender, recipient_handles=[self.recipient], content="Legacy accepted message."
        )
        self.repository.put_idempotency_key(result.message.sender_agent_id, "legacy", result.message.message_id)
        body = {**self.message_body, "content": "Legacy accepted message.", "idempotency_key": "legacy"}
        with patch.object(self.repository, "list_deliveries_by_message", return_value=()):
            with self.assertRaises(ApiError) as error:
                self.api.create_message(body)
        self.assertEqual(409, error.exception.status_code)
        self.assertEqual(result.message.message_id, self.api.create_message(body)["message_id"])

    def test_late_older_send_cannot_move_thread_head_backwards(self) -> None:
        newest_time = datetime(2026, 10, 23, tzinfo=timezone.utc)
        self.service._clock = lambda: newest_time
        first = self.service.send_message(
            sender_handle=self.sender, recipient_handles=[self.recipient], content="Newest."
        )
        self.service._clock = lambda: newest_time - timedelta(seconds=1)
        second = self.service.send_message(
            sender_handle=self.sender, recipient_handles=[self.recipient], content="Older timestamp.",
            thread_id=first.thread.thread_id,
        )
        self.assertEqual(2, second.thread.message_count)
        self.assertEqual(first.message.message_id, second.thread.last_message_id)
        self.assertEqual(newest_time, second.thread.last_message_at)
        self.assertEqual(newest_time, second.thread.updated_at)

    def test_equal_time_thread_head_uses_message_id_tiebreak(self) -> None:
        moment = datetime(2026, 10, 23, tzinfo=timezone.utc)
        self.service._clock = lambda: moment
        original_id_factory = self.service._id_factory
        message_ids = iter(("message_z", "message_a"))
        self.service._id_factory = lambda prefix: next(message_ids) if prefix == "message" else original_id_factory(prefix)
        first = self.service.send_message(
            sender_handle=self.sender, recipient_handles=[self.recipient], content="First."
        )
        second = self.service.send_message(
            sender_handle=self.sender, recipient_handles=[self.recipient], content="Second.",
            thread_id=first.thread.thread_id,
        )
        self.assertEqual("message_z", second.thread.last_message_id)
        self.assertEqual(2, second.thread.message_count)

    def test_message_routes_map_transaction_capacity_to_413(self) -> None:
        calls = (
            lambda: self.api.create_message(self.message_body),
            lambda: self.api.personal_agent_send(self.sender, self.message_body),
            lambda: self.api.agent_post(self.authorization, self.message_body),
            lambda: self.api.public_agent_send(self.authorization, "recipient:gulls.ai", self.message_body),
        )
        for index, call in enumerate(calls):
            with self.subTest(route=index), patch.object(
                self.repository, "commit_message_send", side_effect=SendTooLargeError("transaction exceeds limit")
            ):
                with self.assertRaises(ApiError) as error:
                    call()
                self.assertEqual((413, "send_too_large"), (error.exception.status_code, error.exception.error))

    def test_task_routes_map_transaction_capacity_to_413(self) -> None:
        calls = (
            lambda: self.api.create_task(self.task_body),
            lambda: self.api.personal_agent_request_task(self.sender, self.task_body),
            lambda: self.api.agent_request_task(self.authorization, self.task_body),
        )
        for index, call in enumerate(calls):
            with self.subTest(route=index), patch.object(
                self.repository, "commit_task_creation", side_effect=SendTooLargeError("transaction exceeds limit")
            ):
                with self.assertRaises(ApiError) as error:
                    call()
                self.assertEqual((413, "send_too_large"), (error.exception.status_code, error.exception.error))

    def test_exhausted_transaction_conflicts_are_retryable(self) -> None:
        with patch.object(self.repository, "commit_message_send", side_effect=AtomicCommitConflict("busy")) as commit:
            with self.assertRaises(ApiError) as error:
                self.api.create_message(self.message_body)
        self.assertEqual((409, "send_conflict"), (error.exception.status_code, error.exception.error))
        self.assertEqual(3, commit.call_count)
        self.assertEqual((), self.repository.list_messages_by_sender(self.service.get_agent(self.sender).agent_id))

    def test_task_review_decision_holds_all_notification_deliveries(self) -> None:
        decisions = [
            SimpleNamespace(deliverable=True, decision_id="task-review", action=SimpleNamespace(value="needs_review")),
            SimpleNamespace(deliverable=True, decision_id="message-allow", action=SimpleNamespace(value="allow")),
        ]
        with patch.object(self.service._safety_evaluator, "evaluate_send", side_effect=decisions):
            task = self.api.create_task(self.task_body)
        deliveries = self.repository.list_deliveries_by_message(task["task"]["request_message_id"])
        self.assertEqual((DeliveryStatus.NEEDS_REVIEW,), tuple(delivery.status for delivery in deliveries))
        self.assertEqual(("human.review",), tuple(delivery.current_stage for delivery in deliveries))

    def test_concurrent_changed_task_request_conflicts_without_extra_resources(self) -> None:
        bodies = (self.task_body, {**self.task_body, "objective": "A different task."})

        def create(body):
            try:
                return self.api.create_task(body)
            except ApiError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, bodies))
        errors = [result for result in results if isinstance(result, ApiError)]
        self.assertEqual(1, len(errors))
        self.assertEqual((409, "idempotency_key_reused"), (errors[0].status_code, errors[0].error))
        sender_id = self.service.get_agent(self.sender).agent_id
        self.assertEqual(1, len(self.repository.list_messages_by_sender(sender_id)))
        self.assertEqual(1, len(self.repository.list_tasks_by_requester(sender_id)))
