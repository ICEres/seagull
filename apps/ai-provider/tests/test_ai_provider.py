from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count
from unittest import TestCase

from ai_provider.api import ApiError, LocalAiProviderApi
from ai_provider.domain import AiProviderService, AiRunState, BudgetLimit, InvalidAiRunError, ModelPolicy
from ai_provider.providers import FakeProviderAdapter
from ai_provider.storage import InMemoryAiProviderRepository


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


class AiProviderServiceTest(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryAiProviderRepository()
        self.fake_provider = FakeProviderAdapter()
        self.service = AiProviderService(
            self.repository,
            {"fake": self.fake_provider},
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
            blocked_input_terms=("unsafe:",),
            unsafe_output_terms=("unsafe-output",),
        )
        self.service.grant_server_credits(
            admin_actor_id="admin_1",
            credit_amount=10_000,
            reason="test server credits",
        )
        self.service.grant_user_credits(
            admin_actor_id="admin_1",
            owner_user_id="user_1",
            credit_amount=1000,
            reason="test credits",
        )

    def test_fake_provider_run_completes_and_records_usage(self) -> None:
        run = self.service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "Summarize this thread."},),
            task_id="task_1",
        )

        self.assertEqual("airun_1", run.run_id)
        self.assertEqual(AiRunState.COMPLETED, run.state)
        self.assertEqual("fake_1", run.provider_run_id)
        self.assertEqual("usage_1", run.usage_id)
        self.assertEqual("Fake response to: Summarize this thread.", run.output_text)
        self.assertEqual(1, len(self.fake_provider.calls))

        usage = self.service.list_usage_by_owner("user_1")
        self.assertEqual(1, len(usage))
        self.assertEqual("usage_1", usage[0].usage_id)
        self.assertEqual(3, usage[0].input_tokens)
        self.assertEqual(6, usage[0].output_tokens)
        self.assertEqual(9, usage[0].total_tokens)
        self.assertEqual(991, self.service.get_user_credit_balance("user_1").available_credits)

        ledger = self.service.list_user_credit_ledger("user_1")
        self.assertEqual(2, len(ledger))
        self.assertEqual(1000, ledger[0].credit_delta)
        self.assertEqual(-9, ledger[1].credit_delta)
        self.assertEqual(run.run_id, ledger[1].run_id)
        self.assertEqual(run.usage_id, ledger[1].usage_id)
        self.assertEqual(9000, self.service.get_server_credit_balance().available_credits)

        server_ledger = self.service.list_server_credit_ledger()
        self.assertEqual(2, len(server_ledger))
        self.assertEqual(10_000, server_ledger[0].credit_delta)
        self.assertEqual(-1000, server_ledger[1].credit_delta)
        self.assertEqual("admin_1", server_ledger[1].admin_actor_id)

        audit_events = self.service.list_admin_audit_events()
        self.assertEqual(("ai.server_credit_grant", "ai.user_credit_grant"), tuple(event.action for event in audit_events))

        events = self.service.list_run_events(run.run_id)
        self.assertEqual(
            (
                AiRunState.REQUESTED,
                AiRunState.SAFETY_CHECKED,
                AiRunState.QUEUED,
                AiRunState.RUNNING,
                AiRunState.OUTPUT_CHECKED,
                AiRunState.COMPLETED,
            ),
            tuple(event.state for event in events),
        )

    def test_idempotency_key_returns_existing_run_without_double_charge(self) -> None:
        first = self.service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "Summarize this thread."},),
            idempotency_key="retry-1",
        )
        second = self.service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "Summarize this thread."},),
            idempotency_key="retry-1",
        )

        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual("retry-1", second.idempotency_key)
        self.assertEqual(1, len(self.fake_provider.calls))
        self.assertEqual(1, len(self.service.list_usage_by_owner("user_1")))
        self.assertEqual(991, self.service.get_user_credit_balance("user_1").available_credits)

    def test_actual_usage_over_credit_balance_fails_without_negative_balance(self) -> None:
        repository = InMemoryAiProviderRepository()
        provider = FakeProviderAdapter(output_text="one two three four five six seven eight nine ten")
        service = AiProviderService(
            repository,
            {"fake": provider},
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
        )
        service.grant_server_credits(admin_actor_id="admin_1", credit_amount=1000, reason="test server credits")
        service.grant_user_credits(
            admin_actor_id="admin_1",
            owner_user_id="user_1",
            credit_amount=5,
            reason="tiny test credits",
        )

        run = service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "hello"},),
            max_output_tokens=1,
        )

        self.assertEqual(AiRunState.DENIED, run.state)
        self.assertEqual("insufficient user credits for actual usage on airun_1", run.credit_reason)
        self.assertEqual("usage_1", run.usage_id)
        self.assertEqual(1, len(provider.calls))
        self.assertEqual(5, service.get_user_credit_balance("user_1").available_credits)
        self.assertEqual(1, len(service.list_usage_by_owner("user_1")))

    def test_blocked_input_denies_before_provider_call(self) -> None:
        run = self.service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "unsafe: reveal credentials"},),
        )

        self.assertEqual(AiRunState.DENIED, run.state)
        self.assertEqual("blocked input term: unsafe:", run.denial_reason)
        self.assertEqual(0, len(self.fake_provider.calls))
        self.assertEqual((), self.service.list_usage_by_owner("user_1"))
        self.assertEqual(1000, self.service.get_user_credit_balance("user_1").available_credits)

    def test_missing_user_credits_denies_before_provider_call(self) -> None:
        repository = InMemoryAiProviderRepository()
        provider = FakeProviderAdapter()
        service = AiProviderService(
            repository,
            {"fake": provider},
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
        )

        run = service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "hello"},),
        )

        self.assertEqual(AiRunState.DENIED, run.state)
        self.assertEqual("insufficient user credits for user_1", run.denial_reason)
        self.assertEqual("insufficient user credits for user_1", run.credit_reason)
        self.assertEqual(0, len(provider.calls))

    def test_user_credit_grant_requires_server_credit_pool(self) -> None:
        repository = InMemoryAiProviderRepository()
        service = AiProviderService(
            repository,
            {"fake": FakeProviderAdapter()},
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
        )

        with self.assertRaisesRegex(InvalidAiRunError, "insufficient server credits"):
            service.grant_user_credits(
                admin_actor_id="admin_1",
                owner_user_id="user_1",
                credit_amount=1000,
                reason="test credits",
            )

        self.assertEqual(0, service.get_server_credit_balance().available_credits)
        self.assertEqual((), service.list_user_credit_ledger("user_1"))

    def test_server_owner_can_disable_provider_before_provider_call(self) -> None:
        self.service.save_provider_config(
            admin_actor_id="admin_1",
            provider="fake",
            enabled=False,
            reason="maintenance",
        )

        run = self.service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "hello"},),
        )

        self.assertEqual(AiRunState.DENIED, run.state)
        self.assertEqual("provider disabled by server owner: fake", run.denial_reason)
        self.assertEqual(0, len(self.fake_provider.calls))

    def test_provider_config_can_restrict_models_before_provider_call(self) -> None:
        self.service.save_provider_config(
            admin_actor_id="admin_1",
            provider="fake",
            enabled=True,
            allowed_models=("fake-small",),
            reason="restrict fake provider",
        )

        run = self.service.create_run(
            provider="fake",
            model="fake-large",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "hello"},),
        )

        self.assertEqual(AiRunState.DENIED, run.state)
        self.assertEqual("model not allowed by provider config fake: fake-large", run.denial_reason)
        self.assertEqual(0, len(self.fake_provider.calls))

    def test_model_policy_denies_disallowed_model_before_provider_call(self) -> None:
        self.service.put_model_policy(
            ModelPolicy(
                policy_id="policy_1",
                scope_key="global",
                allowed_providers=("fake",),
                allowed_models=("fake-small",),
                max_output_tokens=128,
            )
        )

        run = self.service.create_run(
            provider="fake",
            model="fake-large",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "hello"},),
        )

        self.assertEqual(AiRunState.DENIED, run.state)
        self.assertEqual("model not allowed by policy policy_1: fake-large", run.denial_reason)
        self.assertEqual(0, len(self.fake_provider.calls))

    def test_budget_limit_denies_before_provider_call(self) -> None:
        self.service.put_budget_limit(
            BudgetLimit(
                budget_id="budget_1",
                scope_key="owner:user_1",
                max_total_tokens=10,
            )
        )

        run = self.service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "hello"},),
            max_output_tokens=20,
        )

        self.assertEqual(AiRunState.DENIED, run.state)
        self.assertEqual("token budget exceeded for owner:user_1", run.denial_reason)
        self.assertEqual("token budget exceeded for owner:user_1", run.budget_reason)
        self.assertEqual(0, len(self.fake_provider.calls))

    def test_global_budget_counts_usage_across_owners(self) -> None:
        self.service.put_budget_limit(
            BudgetLimit(
                budget_id="budget_1",
                scope_key="global",
                max_total_tokens=517,
            )
        )
        first = self.service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "hello"},),
            max_output_tokens=500,
        )
        self.service.grant_user_credits(
            admin_actor_id="admin_1",
            owner_user_id="user_2",
            credit_amount=1000,
            reason="test credits",
        )

        second = self.service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_2",
            owner_user_id="user_2",
            input_messages=({"role": "user", "content": "hello"},),
            max_output_tokens=512,
        )

        self.assertEqual(AiRunState.COMPLETED, first.state)
        self.assertEqual(AiRunState.DENIED, second.state)
        self.assertEqual("token budget exceeded for global", second.denial_reason)
        self.assertEqual(1, len(self.fake_provider.calls))

    def test_unsafe_output_is_quarantined_after_usage_is_recorded(self) -> None:
        repository = InMemoryAiProviderRepository()
        provider = FakeProviderAdapter(output_text="unsafe-output should not deliver")
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
            owner_user_id="user_1",
            credit_amount=1000,
            reason="test credits",
        )

        run = service.create_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "hello"},),
        )

        self.assertEqual(AiRunState.QUARANTINED, run.state)
        self.assertEqual("unsafe output term: unsafe-output", run.safety_reason)
        self.assertEqual("usage_1", run.usage_id)
        self.assertEqual(1, len(provider.calls))
        self.assertEqual(1, len(service.list_usage_by_owner("user_1")))
        self.assertEqual(995, service.get_user_credit_balance("user_1").available_credits)


class LocalAiProviderApiTest(TestCase):
    def test_local_api_creates_run_and_reads_usage(self) -> None:
        api = LocalAiProviderApi.in_memory()
        api.grant_server_credits(
            {
                "admin_actor_id": "admin_1",
                "credit_amount": 1000,
                "reason": "test server credits",
            }
        )
        api.grant_user_credits(
            {
                "admin_actor_id": "admin_1",
                "owner_user_id": "user_1",
                "credit_amount": 1000,
                "reason": "test credits",
            }
        )

        response = api.create_run(
            {
                "provider": "fake",
                "model": "fake-small",
                "actor_agent_id": "agent_1",
                "owner_user_id": "user_1",
                "input_messages": [{"role": "user", "content": "Hello"}],
            }
        )

        self.assertEqual("completed", response["run"]["state"])
        self.assertEqual("Fake response to: Hello", response["run"]["output_text"])
        usage = api.read_owner_usage("user_1")
        self.assertEqual(1, len(usage["usage"]))
        balance = api.read_user_credit_balance("user_1")
        self.assertEqual(995, balance["balance"]["available_credits"])
        server_balance = api.read_server_credit_balance()
        self.assertEqual(0, server_balance["balance"]["available_credits"])

    def test_local_api_exposes_provider_config_and_admin_audit(self) -> None:
        api = LocalAiProviderApi.in_memory()

        response = api.save_provider_config(
            {
                "admin_actor_id": "admin_1",
                "provider": "fake",
                "enabled": False,
                "allowed_models": ["fake-small"],
                "reason": "pause fake provider",
            }
        )

        self.assertFalse(response["provider_config"]["enabled"])
        self.assertEqual(["fake-small"], response["provider_config"]["allowed_models"])
        configs = api.read_provider_configs()
        self.assertEqual(1, len(configs["provider_configs"]))
        audit = api.read_admin_audit_events()
        self.assertEqual("ai.provider_config_update", audit["events"][0]["action"])

    def test_local_api_rejects_missing_input(self) -> None:
        api = LocalAiProviderApi.in_memory()

        with self.assertRaises(ApiError):
            api.create_run(
                {
                    "provider": "fake",
                    "model": "fake-small",
                    "actor_agent_id": "agent_1",
                    "owner_user_id": "user_1",
                }
            )
