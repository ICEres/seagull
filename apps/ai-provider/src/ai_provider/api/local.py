from __future__ import annotations

from datetime import datetime
from typing import Any

from ai_provider._compat import dataclass
from ai_provider.domain import (
    AdminAuditEvent,
    AiProviderService,
    AiRun,
    AiRunEvent,
    BudgetLimit,
    InvalidAiRunError,
    ModelPolicy,
    ProviderConfig,
    ProviderMessage,
    ServerCreditBalance,
    ServerCreditLedgerEntry,
    UsageRecord,
    UserCreditBalance,
    UserCreditLedgerEntry,
)
from ai_provider.providers import FakeProviderAdapter
from ai_provider.storage import InMemoryAiProviderRepository


@dataclass(frozen=True, slots=True)
class ApiError(Exception):
    status_code: int
    error: str
    message: str


class LocalAiProviderApi:
    """Dependency-free local API adapter for AI provider runs."""

    def __init__(self, service: AiProviderService, repository: InMemoryAiProviderRepository) -> None:
        self._service = service
        self._repository = repository

    @classmethod
    def in_memory(cls) -> LocalAiProviderApi:
        repository = InMemoryAiProviderRepository()
        service = AiProviderService(repository, {"fake": FakeProviderAdapter()})
        return cls(service, repository)

    def health(self) -> dict[str, Any]:
        return {"ok": True, "app": "ai-provider", "storage": "memory"}

    def create_run(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            run = self._service.create_run(
                provider=required_string(body, "provider"),
                model=required_string(body, "model"),
                actor_agent_id=required_string(body, "actor_agent_id"),
                owner_user_id=required_string(body, "owner_user_id"),
                input_messages=provider_messages(body.get("input_messages", ())),
                system_instructions=optional_string(body, "system_instructions"),
                system_instructions_ref=optional_string(body, "system_instructions_ref"),
                context_refs=string_list(body.get("context_refs", ()), "context_refs"),
                content_ref=optional_string(body, "content_ref"),
                max_output_tokens=optional_int(body, "max_output_tokens", default=512),
                temperature=optional_float(body, "temperature", default=0.2),
                response_format=optional_string(body, "response_format") or "text",
                tool_policy=optional_string(body, "tool_policy") or "disabled",
                task_id=optional_string(body, "task_id"),
                message_id=optional_string(body, "message_id"),
                trace_id=optional_string(body, "trace_id"),
                idempotency_key=optional_string(body, "idempotency_key"),
            )
            return {"run": run_to_dict(run)}
        except InvalidAiRunError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

    def read_run(self, run_id: str) -> dict[str, Any]:
        try:
            return {"run": run_to_dict(self._service.get_run(run_id))}
        except InvalidAiRunError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

    def read_run_events(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "events": [run_event_to_dict(event) for event in self._service.list_run_events(run_id)]}

    def read_owner_usage(self, owner_user_id: str) -> dict[str, Any]:
        records = self._service.list_usage_by_owner(owner_user_id)
        return {"owner_user_id": owner_user_id, "usage": [usage_record_to_dict(record) for record in records]}

    def read_agent_usage(self, agent_id: str) -> dict[str, Any]:
        records = self._service.list_usage_by_agent(agent_id)
        return {"agent_id": agent_id, "usage": [usage_record_to_dict(record) for record in records]}

    def grant_user_credits(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            entry = self._service.grant_user_credits(
                admin_actor_id=required_string(body, "admin_actor_id"),
                owner_user_id=required_string(body, "owner_user_id"),
                credit_amount=required_int(body, "credit_amount"),
                reason=optional_string(body, "reason") or "manual credit grant",
            )
            return {"entry": user_credit_ledger_entry_to_dict(entry)}
        except InvalidAiRunError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

    def read_user_credit_balance(self, owner_user_id: str) -> dict[str, Any]:
        return {"balance": user_credit_balance_to_dict(self._service.get_user_credit_balance(owner_user_id))}

    def read_user_credit_ledger(self, owner_user_id: str) -> dict[str, Any]:
        entries = self._service.list_user_credit_ledger(owner_user_id)
        return {"owner_user_id": owner_user_id, "entries": [user_credit_ledger_entry_to_dict(entry) for entry in entries]}

    def grant_server_credits(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            entry = self._service.grant_server_credits(
                admin_actor_id=required_string(body, "admin_actor_id"),
                credit_amount=required_int(body, "credit_amount"),
                reason=optional_string(body, "reason") or "server credit grant",
            )
            return {"entry": server_credit_ledger_entry_to_dict(entry)}
        except InvalidAiRunError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

    def read_server_credit_balance(self) -> dict[str, Any]:
        return {"balance": server_credit_balance_to_dict(self._service.get_server_credit_balance())}

    def read_server_credit_ledger(self) -> dict[str, Any]:
        return {"entries": [server_credit_ledger_entry_to_dict(entry) for entry in self._service.list_server_credit_ledger()]}

    def save_provider_config(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            config = self._service.save_provider_config(
                admin_actor_id=required_string(body, "admin_actor_id"),
                provider=required_string(body, "provider"),
                enabled=optional_bool(body, "enabled", default=True),
                allowed_models=string_list(body.get("allowed_models", ()), "allowed_models"),
                secret_ref=optional_string(body, "secret_ref"),
                region=optional_string(body, "region"),
                reason=optional_string(body, "reason") or "provider config update",
            )
            return {"provider_config": provider_config_to_dict(config)}
        except InvalidAiRunError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

    def read_provider_configs(self) -> dict[str, Any]:
        return {"provider_configs": [provider_config_to_dict(config) for config in self._service.list_provider_configs()]}

    def read_admin_audit_events(self) -> dict[str, Any]:
        return {"events": [admin_audit_event_to_dict(event) for event in self._service.list_admin_audit_events()]}

    def put_model_policy(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            policy = ModelPolicy(
                policy_id=required_string(body, "policy_id"),
                scope_key=required_string(body, "scope_key"),
                allowed_providers=string_list(body.get("allowed_providers", ()), "allowed_providers"),
                allowed_models=string_list(body.get("allowed_models", ()), "allowed_models"),
                max_output_tokens=optional_nullable_int(body, "max_output_tokens"),
                enabled=optional_bool(body, "enabled", default=True),
            )
            self._service.put_model_policy(policy)
            return {"policy": model_policy_to_dict(policy)}
        except InvalidAiRunError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

    def put_budget_limit(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            limit = BudgetLimit(
                budget_id=required_string(body, "budget_id"),
                scope_key=required_string(body, "scope_key"),
                max_total_tokens=required_int(body, "max_total_tokens"),
            )
            self._service.put_budget_limit(limit)
            return {"budget_limit": budget_limit_to_dict(limit)}
        except InvalidAiRunError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc


def run_to_dict(run: AiRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "provider": run.provider,
        "model": run.model,
        "actor_agent_id": run.actor_agent_id,
        "owner_user_id": run.owner_user_id,
        "state": run.state.value,
        "task_id": run.task_id,
        "message_id": run.message_id,
        "input_ref": run.input_ref,
        "output_text": run.output_text,
        "output_ref": run.output_ref,
        "provider_run_id": run.provider_run_id,
        "finish_reason": run.finish_reason,
        "usage_id": run.usage_id,
        "denial_reason": run.denial_reason,
        "safety_reason": run.safety_reason,
        "budget_reason": run.budget_reason,
        "credit_reason": run.credit_reason,
        "trace_id": run.trace_id,
        "created_at": datetime_to_string(run.created_at),
        "updated_at": datetime_to_string(run.updated_at),
    }


def run_event_to_dict(event: AiRunEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "run_id": event.run_id,
        "state": event.state.value,
        "reason": event.reason,
        "policy_ids": list(event.policy_ids),
        "usage_id": event.usage_id,
        "trace_id": event.trace_id,
        "created_at": datetime_to_string(event.created_at),
    }


def usage_record_to_dict(record: UsageRecord) -> dict[str, Any]:
    return {
        "usage_id": record.usage_id,
        "run_id": record.run_id,
        "provider": record.provider,
        "model": record.model,
        "owner_user_id": record.owner_user_id,
        "agent_id": record.agent_id,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "cached_tokens": record.cached_tokens,
        "total_tokens": record.total_tokens,
        "estimated_cost_units": record.estimated_cost_units,
        "task_id": record.task_id,
        "message_id": record.message_id,
        "approval_state": record.approval_state,
        "created_at": datetime_to_string(record.created_at),
    }


def user_credit_ledger_entry_to_dict(entry: UserCreditLedgerEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "owner_user_id": entry.owner_user_id,
        "entry_type": entry.entry_type.value,
        "credit_delta": entry.credit_delta,
        "reason": entry.reason,
        "run_id": entry.run_id,
        "usage_id": entry.usage_id,
        "created_at": datetime_to_string(entry.created_at),
    }


def user_credit_balance_to_dict(balance: UserCreditBalance) -> dict[str, Any]:
    return {
        "owner_user_id": balance.owner_user_id,
        "available_credits": balance.available_credits,
    }


def server_credit_ledger_entry_to_dict(entry: ServerCreditLedgerEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "entry_type": entry.entry_type.value,
        "credit_delta": entry.credit_delta,
        "reason": entry.reason,
        "admin_actor_id": entry.admin_actor_id,
        "owner_user_id": entry.owner_user_id,
        "user_credit_entry_id": entry.user_credit_entry_id,
        "created_at": datetime_to_string(entry.created_at),
    }


def server_credit_balance_to_dict(balance: ServerCreditBalance) -> dict[str, Any]:
    return {"available_credits": balance.available_credits}


def provider_config_to_dict(config: ProviderConfig) -> dict[str, Any]:
    return {
        "provider_config_id": config.provider_config_id,
        "provider": config.provider,
        "enabled": config.enabled,
        "allowed_models": list(config.allowed_models),
        "secret_ref": config.secret_ref,
        "region": config.region,
        "created_at": datetime_to_string(config.created_at),
        "updated_at": datetime_to_string(config.updated_at),
    }


def admin_audit_event_to_dict(event: AdminAuditEvent) -> dict[str, Any]:
    return {
        "audit_id": event.audit_id,
        "admin_actor_id": event.admin_actor_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "reason": event.reason,
        "metadata": dict(event.metadata),
        "created_at": datetime_to_string(event.created_at),
    }


def model_policy_to_dict(policy: ModelPolicy) -> dict[str, Any]:
    return {
        "policy_id": policy.policy_id,
        "scope_key": policy.scope_key,
        "allowed_providers": list(policy.allowed_providers),
        "allowed_models": list(policy.allowed_models),
        "max_output_tokens": policy.max_output_tokens,
        "enabled": policy.enabled,
        "created_at": datetime_to_string(policy.created_at),
        "updated_at": datetime_to_string(policy.updated_at),
    }


def budget_limit_to_dict(limit: BudgetLimit) -> dict[str, Any]:
    return {
        "budget_id": limit.budget_id,
        "scope_key": limit.scope_key,
        "max_total_tokens": limit.max_total_tokens,
        "created_at": datetime_to_string(limit.created_at),
        "updated_at": datetime_to_string(limit.updated_at),
    }


def provider_messages(value: Any) -> tuple[ProviderMessage, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ApiError(400, "bad_request", "input_messages must be a list")
    messages: list[ProviderMessage] = []
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(400, "bad_request", "input_messages must contain objects")
        messages.append(
            ProviderMessage(
                role=required_string(item, "role"),
                content=required_string(item, "content"),
                content_ref=optional_string(item, "content_ref"),
            )
        )
    return tuple(messages)


def required_string(body: dict[str, Any], field_name: str) -> str:
    value = optional_string(body, field_name)
    if value is None:
        raise ApiError(400, "bad_request", f"{field_name} is required")
    return value


def optional_string(body: dict[str, Any], field_name: str) -> str | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, "bad_request", f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None


def string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ApiError(400, "bad_request", f"{field_name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ApiError(400, "bad_request", f"{field_name} must contain only strings")
    return tuple(item.strip() for item in value if item.strip())


def required_int(body: dict[str, Any], field_name: str) -> int:
    value = optional_nullable_int(body, field_name)
    if value is None:
        raise ApiError(400, "bad_request", f"{field_name} is required")
    return value


def optional_int(body: dict[str, Any], field_name: str, *, default: int) -> int:
    value = optional_nullable_int(body, field_name)
    return default if value is None else value


def optional_nullable_int(body: dict[str, Any], field_name: str) -> int | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ApiError(400, "bad_request", f"{field_name} must be an integer")
    return value


def optional_float(body: dict[str, Any], field_name: str, *, default: float) -> float:
    value = body.get(field_name)
    if value is None:
        return default
    if not isinstance(value, (int, float)):
        raise ApiError(400, "bad_request", f"{field_name} must be a number")
    return float(value)


def optional_bool(body: dict[str, Any], field_name: str, *, default: bool) -> bool:
    value = body.get(field_name)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ApiError(400, "bad_request", f"{field_name} must be a boolean")
    return value


def datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
