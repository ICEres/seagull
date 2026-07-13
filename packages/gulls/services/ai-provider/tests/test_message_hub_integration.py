from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count
from unittest import TestCase

from ai_provider.domain import AiProviderService, AiRunState, ProviderRequest, ProviderResponse, ProviderUsage
from ai_provider.integrations import AiTaskNotApprovedError, MessageHubAiTaskRunner
from ai_provider.providers import FakeProviderAdapter
from ai_provider.storage import InMemoryAiProviderRepository
from message_hub.domain import MessageHubService, TaskState
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
        self._base = datetime(2026, 6, 29, tzinfo=timezone.utc)
        self._ticks = count()

    def __call__(self) -> datetime:
        return self._base + timedelta(seconds=next(self._ticks))


class RefProviderAdapter:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request)
        return ProviderResponse(
            output_text="provider stored this output by ref",
            output_ref="payload://ai-runs/airun_1/output",
            provider_run_id="provider_ref_1",
            usage=ProviderUsage(input_tokens=3, output_tokens=4),
        )


class MessageHubAiTaskRunnerTest(TestCase):
    def setUp(self) -> None:
        self.ai_repository = InMemoryAiProviderRepository()
        self.fake_provider = FakeProviderAdapter()
        self.ai_service = AiProviderService(
            self.ai_repository,
            {"fake": self.fake_provider},
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
            blocked_input_terms=("blocked-input",),
            unsafe_output_terms=("unsafe-output",),
        )
        self.ai_service.grant_server_credits(
            admin_actor_id="admin_1",
            credit_amount=10_000,
            reason="test server credits",
        )
        self.ai_service.grant_user_credits(
            admin_actor_id="admin_1",
            owner_user_id="user_1",
            credit_amount=1000,
            reason="test user credits",
        )

        self.message_repository = InMemoryMessageHubRepository()
        self.message_hub = MessageHubService(
            self.message_repository,
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
        )
        self.message_hub.register_agent("@researcher:gulls.ai")
        self.message_hub.register_agent("@reviewer:gulls.ai")
        self.runner = MessageHubAiTaskRunner(self.ai_service, self.message_hub)

    def test_approved_task_run_records_usage_and_returns_task_result(self) -> None:
        task = self._approved_task("Summarize this thread.")

        result = self.runner.run_task(
            task.task_id,
            provider="fake",
            model="fake-small",
            responder_handle="@reviewer:gulls.ai",
            owner_user_id="user_1",
        )

        self.assertEqual(AiRunState.COMPLETED, result.run.state)
        self.assertTrue(result.run.run_id.startswith("airun_idem_"))
        self.assertIsNotNone(result.task_result)
        assert result.task_result is not None
        self.assertEqual(TaskState.COMPLETED, result.task_result.state)
        self.assertEqual("Fake response to: Summarize this thread.", result.task_result.content_inline)
        self.assertEqual((f"seagull://ai-runs/{result.run.run_id}",), result.task_result.artifact_refs)

        usage = self.ai_service.list_usage_by_owner("user_1")
        self.assertEqual(1, len(usage))
        self.assertEqual(task.task_id, usage[0].task_id)
        self.assertEqual(task.request_message_id, usage[0].message_id)
        self.assertEqual(1, len(self.fake_provider.calls))

        task_results = self.message_repository.list_task_results(task.task_id)
        self.assertEqual((result.task_result,), task_results)
        result_message = self.message_repository.get_message(result.task_result.result_message_id)
        self.assertIsNotNone(result_message)
        assert result_message is not None
        self.assertEqual("task_result", result_message.intent)

    def test_unapproved_task_does_not_call_provider(self) -> None:
        task = self.message_hub.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective="Summarize this thread.",
        )

        with self.assertRaises(AiTaskNotApprovedError):
            self.runner.run_task(
                task.task_id,
                provider="fake",
                model="fake-small",
                responder_handle="@reviewer:gulls.ai",
                owner_user_id="user_1",
            )

        self.assertEqual(0, len(self.fake_provider.calls))
        self.assertEqual((), self.ai_service.list_usage_by_owner("user_1"))
        self.assertEqual((), self.message_repository.list_task_results(task.task_id))

    def test_denied_ai_run_does_not_return_task_result(self) -> None:
        task = self._approved_task("blocked-input should not reach a provider.")

        result = self.runner.run_task(
            task.task_id,
            provider="fake",
            model="fake-small",
            responder_handle="@reviewer:gulls.ai",
            owner_user_id="user_1",
        )

        self.assertEqual(AiRunState.DENIED, result.run.state)
        self.assertIsNone(result.task_result)
        self.assertEqual(0, len(self.fake_provider.calls))
        self.assertEqual((), self.message_repository.list_task_results(task.task_id))
        self.assertEqual(TaskState.APPROVED, self.message_hub.get_task(task.task_id).state)

    def test_quarantined_ai_output_does_not_return_task_result(self) -> None:
        provider = FakeProviderAdapter(output_text="unsafe-output must not be delivered")
        repository = InMemoryAiProviderRepository()
        service = AiProviderService(
            repository,
            {"fake": provider},
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
            unsafe_output_terms=("unsafe-output",),
        )
        service.grant_server_credits(admin_actor_id="admin_1", credit_amount=1000, reason="test server credits")
        service.grant_user_credits(
            admin_actor_id="admin_1",
            owner_user_id="user_2",
            credit_amount=1000,
            reason="test user credits",
        )
        runner = MessageHubAiTaskRunner(service, self.message_hub)
        task = self._approved_task("Summarize this thread.")

        result = runner.run_task(
            task.task_id,
            provider="fake",
            model="fake-small",
            responder_handle="@reviewer:gulls.ai",
            owner_user_id="user_2",
        )

        self.assertEqual(AiRunState.QUARANTINED, result.run.state)
        self.assertIsNone(result.task_result)
        self.assertEqual(1, len(provider.calls))
        self.assertEqual((), self.message_repository.list_task_results(task.task_id))

    def test_output_ref_is_delivered_without_inline_content(self) -> None:
        provider = RefProviderAdapter()
        repository = InMemoryAiProviderRepository()
        service = AiProviderService(
            repository,
            {"ref": provider},
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
        )
        service.grant_server_credits(admin_actor_id="admin_1", credit_amount=1000, reason="test server credits")
        service.grant_user_credits(
            admin_actor_id="admin_1",
            owner_user_id="user_3",
            credit_amount=1000,
            reason="test user credits",
        )
        runner = MessageHubAiTaskRunner(service, self.message_hub)
        task = self._approved_task("Summarize a large input.", input_ref="payload://task_1/input")

        result = runner.run_task(
            task.task_id,
            provider="ref",
            model="ref-model",
            responder_handle="@reviewer:gulls.ai",
            owner_user_id="user_3",
        )

        self.assertEqual(AiRunState.COMPLETED, result.run.state)
        self.assertIsNotNone(result.task_result)
        assert result.task_result is not None
        self.assertIsNone(result.task_result.content_inline)
        self.assertEqual("payload://ai-runs/airun_1/output", result.task_result.content_ref)
        result_message = self.message_repository.get_message(result.task_result.result_message_id)
        self.assertIsNotNone(result_message)
        assert result_message is not None
        self.assertIsNone(result_message.content_inline)
        self.assertEqual("payload://ai-runs/airun_1/output", result_message.content_ref)

    def _approved_task(self, objective: str, *, input_ref: str | None = None) -> object:
        task = self.message_hub.create_task(
            requester_handle="@researcher:gulls.ai",
            recipient_handle="@reviewer:gulls.ai",
            objective=objective,
            input_ref=input_ref,
        )
        self.message_hub.update_task_state(
            task.task_id,
            actor_handle="@researcher:gulls.ai",
            state="needs_approval",
        )
        return self.message_hub.update_task_state(
            task.task_id,
            actor_handle="@researcher:gulls.ai",
            state="approved",
        )
