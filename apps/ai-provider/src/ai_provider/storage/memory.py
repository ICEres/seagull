from __future__ import annotations

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


class InMemoryAiProviderRepository:
    def __init__(self) -> None:
        self._runs: dict[str, AiRun] = {}
        self._run_events: dict[str, list[AiRunEvent]] = {}
        self._usage_records: dict[str, UsageRecord] = {}
        self._user_credit_ledger: dict[str, UserCreditLedgerEntry] = {}
        self._user_credit_entry_ids_by_owner: dict[str, set[str]] = {}
        self._server_credit_ledger: list[ServerCreditLedgerEntry] = []
        self._provider_configs: dict[str, ProviderConfig] = {}
        self._admin_audit_events: list[AdminAuditEvent] = []
        self._model_policies: dict[str, ModelPolicy] = {}
        self._policy_ids_by_scope: dict[str, set[str]] = {}
        self._budget_limits: dict[str, BudgetLimit] = {}
        self._budget_ids_by_scope: dict[str, set[str]] = {}

    def put_run(self, run: AiRun) -> None:
        self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> AiRun | None:
        return self._runs.get(run_id)

    def append_run_event(self, event: AiRunEvent) -> None:
        self._run_events.setdefault(event.run_id, []).append(event)

    def list_run_events(self, run_id: str) -> tuple[AiRunEvent, ...]:
        return tuple(self._run_events.get(run_id, ()))

    def put_usage_record(self, record: UsageRecord) -> None:
        self._usage_records[record.usage_id] = record

    def list_usage_records(self) -> tuple[UsageRecord, ...]:
        return tuple(sorted(self._usage_records.values(), key=lambda record: record.created_at))

    def list_usage_by_owner(self, owner_user_id: str) -> tuple[UsageRecord, ...]:
        return tuple(
            sorted(
                (record for record in self._usage_records.values() if record.owner_user_id == owner_user_id),
                key=lambda record: record.created_at,
            )
        )

    def list_usage_by_agent(self, agent_id: str) -> tuple[UsageRecord, ...]:
        return tuple(
            sorted(
                (record for record in self._usage_records.values() if record.agent_id == agent_id),
                key=lambda record: record.created_at,
            )
        )

    def append_user_credit_ledger_entry(self, entry: UserCreditLedgerEntry) -> None:
        self._user_credit_ledger[entry.entry_id] = entry
        self._user_credit_entry_ids_by_owner.setdefault(entry.owner_user_id, set()).add(entry.entry_id)

    def list_user_credit_ledger_by_owner(self, owner_user_id: str) -> tuple[UserCreditLedgerEntry, ...]:
        entry_ids = self._user_credit_entry_ids_by_owner.get(owner_user_id, set())
        return tuple(sorted((self._user_credit_ledger[entry_id] for entry_id in entry_ids), key=lambda entry: entry.created_at))

    def append_server_credit_ledger_entry(self, entry: ServerCreditLedgerEntry) -> None:
        self._server_credit_ledger.append(entry)

    def list_server_credit_ledger(self) -> tuple[ServerCreditLedgerEntry, ...]:
        return tuple(self._server_credit_ledger)

    def put_provider_config(self, config: ProviderConfig) -> None:
        self._provider_configs[config.provider] = config

    def get_provider_config(self, provider: str) -> ProviderConfig | None:
        return self._provider_configs.get(provider)

    def list_provider_configs(self) -> tuple[ProviderConfig, ...]:
        return tuple(sorted(self._provider_configs.values(), key=lambda config: config.provider))

    def append_admin_audit_event(self, event: AdminAuditEvent) -> None:
        self._admin_audit_events.append(event)

    def list_admin_audit_events(self) -> tuple[AdminAuditEvent, ...]:
        return tuple(self._admin_audit_events)

    def put_model_policy(self, policy: ModelPolicy) -> None:
        self._model_policies[policy.policy_id] = policy
        self._policy_ids_by_scope.setdefault(policy.scope_key, set()).add(policy.policy_id)

    def list_model_policies_by_scope(self, scope_key: str) -> tuple[ModelPolicy, ...]:
        policy_ids = self._policy_ids_by_scope.get(scope_key, set())
        return tuple(sorted((self._model_policies[policy_id] for policy_id in policy_ids), key=lambda policy: policy.created_at))

    def put_budget_limit(self, limit: BudgetLimit) -> None:
        self._budget_limits[limit.budget_id] = limit
        self._budget_ids_by_scope.setdefault(limit.scope_key, set()).add(limit.budget_id)

    def list_budget_limits_by_scope(self, scope_key: str) -> tuple[BudgetLimit, ...]:
        budget_ids = self._budget_ids_by_scope.get(scope_key, set())
        return tuple(sorted((self._budget_limits[budget_id] for budget_id in budget_ids), key=lambda limit: limit.created_at))
