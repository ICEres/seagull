from __future__ import annotations

from threading import RLock

from ai_provider.domain.models import (
    AdminAuditEvent,
    AiRun,
    AiRunEvent,
    BudgetLimit,
    ModelPolicy,
    ProviderConfig,
    ServerCreditLedgerEntry,
    UsageRecord,
    UserCreditLedgerEntry,
)
from ai_provider.storage.repository import InsufficientCreditBalanceError


class InMemoryAiProviderRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._runs: dict[str, AiRun] = {}
        self._run_events: dict[str, list[AiRunEvent]] = {}
        self._usage_records: dict[str, UsageRecord] = {}
        self._user_credit_ledger: dict[str, UserCreditLedgerEntry] = {}
        self._user_credit_entry_ids_by_owner: dict[str, set[str]] = {}
        self._user_credit_balances: dict[str, int] = {}
        self._server_credit_ledger: list[ServerCreditLedgerEntry] = []
        self._server_credit_balance = 0
        self._provider_configs: dict[str, ProviderConfig] = {}
        self._admin_audit_events: list[AdminAuditEvent] = []
        self._model_policies: dict[str, ModelPolicy] = {}
        self._policy_ids_by_scope: dict[str, set[str]] = {}
        self._budget_limits: dict[str, BudgetLimit] = {}
        self._budget_ids_by_scope: dict[str, set[str]] = {}

    def put_run(self, run: AiRun) -> None:
        with self._lock:
            self._runs[run.run_id] = run

    def put_run_if_absent(self, run: AiRun) -> bool:
        with self._lock:
            if run.run_id in self._runs:
                return False
            self._runs[run.run_id] = run
            return True

    def get_run(self, run_id: str) -> AiRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def append_run_event(self, event: AiRunEvent) -> None:
        with self._lock:
            self._run_events.setdefault(event.run_id, []).append(event)

    def list_run_events(self, run_id: str) -> tuple[AiRunEvent, ...]:
        with self._lock:
            return tuple(self._run_events.get(run_id, ()))

    def put_usage_record(self, record: UsageRecord) -> None:
        with self._lock:
            self._usage_records[record.usage_id] = record

    def list_usage_records(self) -> tuple[UsageRecord, ...]:
        with self._lock:
            records = tuple(self._usage_records.values())
        return tuple(sorted(records, key=lambda record: record.created_at))

    def list_usage_by_owner(self, owner_user_id: str) -> tuple[UsageRecord, ...]:
        with self._lock:
            records = tuple(
                record for record in self._usage_records.values() if record.owner_user_id == owner_user_id
            )
        return tuple(sorted(records, key=lambda record: record.created_at))

    def list_usage_by_agent(self, agent_id: str) -> tuple[UsageRecord, ...]:
        with self._lock:
            records = tuple(record for record in self._usage_records.values() if record.agent_id == agent_id)
        return tuple(sorted(records, key=lambda record: record.created_at))

    def append_user_credit_ledger_entry(
        self,
        entry: UserCreditLedgerEntry,
        *,
        minimum_available_balance: int = 0,
    ) -> None:
        with self._lock:
            if minimum_available_balance > 0 and self._user_credit_balances.get(entry.owner_user_id, 0) < minimum_available_balance:
                raise InsufficientCreditBalanceError("insufficient user credits")
            self._append_user_credit_ledger_entry_unlocked(entry)

    def list_user_credit_ledger_by_owner(self, owner_user_id: str) -> tuple[UserCreditLedgerEntry, ...]:
        with self._lock:
            entry_ids = self._user_credit_entry_ids_by_owner.get(owner_user_id, set())
            entries = tuple(self._user_credit_ledger[entry_id] for entry_id in entry_ids)
        return tuple(sorted(entries, key=lambda entry: entry.created_at))

    def get_user_credit_balance(self, owner_user_id: str) -> int:
        with self._lock:
            return self._user_credit_balances.get(owner_user_id, 0)

    def append_server_credit_ledger_entry(
        self,
        entry: ServerCreditLedgerEntry,
        *,
        minimum_available_balance: int = 0,
    ) -> None:
        with self._lock:
            if minimum_available_balance > 0 and self._server_credit_balance < minimum_available_balance:
                raise InsufficientCreditBalanceError("insufficient server credits")
            self._append_server_credit_ledger_entry_unlocked(entry)

    def list_server_credit_ledger(self) -> tuple[ServerCreditLedgerEntry, ...]:
        with self._lock:
            return tuple(self._server_credit_ledger)

    def get_server_credit_balance(self) -> int:
        with self._lock:
            return self._server_credit_balance

    def transfer_server_credits_to_user(
        self,
        user_entry: UserCreditLedgerEntry,
        server_entry: ServerCreditLedgerEntry,
        *,
        minimum_server_available_balance: int,
    ) -> None:
        with self._lock:
            if self._server_credit_balance < minimum_server_available_balance:
                raise InsufficientCreditBalanceError("insufficient server credits")
            self._append_user_credit_ledger_entry_unlocked(user_entry)
            self._append_server_credit_ledger_entry_unlocked(server_entry)

    def _append_user_credit_ledger_entry_unlocked(self, entry: UserCreditLedgerEntry) -> None:
        self._user_credit_ledger[entry.entry_id] = entry
        self._user_credit_entry_ids_by_owner.setdefault(entry.owner_user_id, set()).add(entry.entry_id)
        self._user_credit_balances[entry.owner_user_id] = (
            self._user_credit_balances.get(entry.owner_user_id, 0) + entry.credit_delta
        )

    def _append_server_credit_ledger_entry_unlocked(self, entry: ServerCreditLedgerEntry) -> None:
        self._server_credit_ledger.append(entry)
        self._server_credit_balance += entry.credit_delta

    def put_provider_config(self, config: ProviderConfig) -> None:
        with self._lock:
            self._provider_configs[config.provider] = config

    def get_provider_config(self, provider: str) -> ProviderConfig | None:
        with self._lock:
            return self._provider_configs.get(provider)

    def list_provider_configs(self) -> tuple[ProviderConfig, ...]:
        with self._lock:
            configs = tuple(self._provider_configs.values())
        return tuple(sorted(configs, key=lambda config: config.provider))

    def append_admin_audit_event(self, event: AdminAuditEvent) -> None:
        with self._lock:
            self._admin_audit_events.append(event)

    def list_admin_audit_events(self) -> tuple[AdminAuditEvent, ...]:
        with self._lock:
            return tuple(self._admin_audit_events)

    def put_model_policy(self, policy: ModelPolicy) -> None:
        with self._lock:
            self._model_policies[policy.policy_id] = policy
            self._policy_ids_by_scope.setdefault(policy.scope_key, set()).add(policy.policy_id)

    def list_model_policies_by_scope(self, scope_key: str) -> tuple[ModelPolicy, ...]:
        with self._lock:
            policy_ids = self._policy_ids_by_scope.get(scope_key, set())
            policies = tuple(self._model_policies[policy_id] for policy_id in policy_ids)
        return tuple(sorted(policies, key=lambda policy: policy.created_at))

    def put_budget_limit(self, limit: BudgetLimit) -> None:
        with self._lock:
            self._budget_limits[limit.budget_id] = limit
            self._budget_ids_by_scope.setdefault(limit.scope_key, set()).add(limit.budget_id)

    def list_budget_limits_by_scope(self, scope_key: str) -> tuple[BudgetLimit, ...]:
        with self._lock:
            budget_ids = self._budget_ids_by_scope.get(scope_key, set())
            limits = tuple(self._budget_limits[budget_id] for budget_id in budget_ids)
        return tuple(sorted(limits, key=lambda limit: limit.created_at))
