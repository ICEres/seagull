from __future__ import annotations

from typing import Protocol

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


class AiProviderRepository(Protocol):
    def put_run(self, run: AiRun) -> None:
        """Create or replace an AI run."""

    def put_run_if_absent(self, run: AiRun) -> bool:
        """Create an AI run only when its ID does not already exist."""

    def get_run(self, run_id: str) -> AiRun | None:
        """Return an AI run by ID."""

    def append_run_event(self, event: AiRunEvent) -> None:
        """Append an immutable AI run event."""

    def list_run_events(self, run_id: str) -> tuple[AiRunEvent, ...]:
        """Return run events in creation order."""

    def put_usage_record(self, record: UsageRecord) -> None:
        """Create or replace a usage ledger record."""

    def list_usage_records(self) -> tuple[UsageRecord, ...]:
        """Return all usage records."""

    def list_usage_by_owner(self, owner_user_id: str) -> tuple[UsageRecord, ...]:
        """Return usage records for one owner."""

    def list_usage_by_agent(self, agent_id: str) -> tuple[UsageRecord, ...]:
        """Return usage records for one agent."""

    def append_user_credit_ledger_entry(self, entry: UserCreditLedgerEntry) -> None:
        """Append a human user credit ledger entry."""

    def list_user_credit_ledger_by_owner(self, owner_user_id: str) -> tuple[UserCreditLedgerEntry, ...]:
        """Return user credit ledger entries for one owner."""

    def append_server_credit_ledger_entry(self, entry: ServerCreditLedgerEntry) -> None:
        """Append a server owner credit ledger entry."""

    def list_server_credit_ledger(self) -> tuple[ServerCreditLedgerEntry, ...]:
        """Return server credit ledger entries."""

    def put_provider_config(self, config: ProviderConfig) -> None:
        """Create or replace a provider config."""

    def get_provider_config(self, provider: str) -> ProviderConfig | None:
        """Return the latest config for a provider."""

    def list_provider_configs(self) -> tuple[ProviderConfig, ...]:
        """Return all provider configs."""

    def append_admin_audit_event(self, event: AdminAuditEvent) -> None:
        """Append a server owner admin audit event."""

    def list_admin_audit_events(self) -> tuple[AdminAuditEvent, ...]:
        """Return admin audit events."""

    def put_model_policy(self, policy: ModelPolicy) -> None:
        """Create or replace a model policy."""

    def list_model_policies_by_scope(self, scope_key: str) -> tuple[ModelPolicy, ...]:
        """Return model policies for a scope."""

    def put_budget_limit(self, limit: BudgetLimit) -> None:
        """Create or replace a token budget limit."""

    def list_budget_limits_by_scope(self, scope_key: str) -> tuple[BudgetLimit, ...]:
        """Return budget limits for a scope."""
