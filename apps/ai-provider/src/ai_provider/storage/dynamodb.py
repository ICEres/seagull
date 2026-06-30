from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key

from ai_provider.domain.models import (
    AdminAuditEvent,
    AiRun,
    AiRunEvent,
    AiRunState,
    BudgetLimit,
    ModelPolicy,
    ProviderConfig,
    ServerCreditLedgerEntry,
    ServerCreditLedgerEntryType,
    UsageRecord,
    UserCreditLedgerEntry,
    UserCreditLedgerEntryType,
)
from ai_provider.storage.repository import InsufficientCreditBalanceError


SERVER_BALANCE_ENTRY_ID = "balance#server"
USER_BALANCE_ENTRY_PREFIX = "balance#user#"


class DynamoDbAiProviderRepository:
    def __init__(
        self,
        *,
        runs_table: Any,
        run_events_table: Any,
        usage_table: Any,
        user_credit_ledger_table: Any,
        server_credit_ledger_table: Any,
        provider_configs_table: Any,
        admin_audit_events_table: Any,
        model_policies_table: Any,
        budget_limits_table: Any,
    ) -> None:
        self._runs_table = runs_table
        self._run_events_table = run_events_table
        self._usage_table = usage_table
        self._user_credit_ledger_table = user_credit_ledger_table
        self._server_credit_ledger_table = server_credit_ledger_table
        self._provider_configs_table = provider_configs_table
        self._admin_audit_events_table = admin_audit_events_table
        self._model_policies_table = model_policies_table
        self._budget_limits_table = budget_limits_table

    def put_run(self, run: AiRun) -> None:
        self._runs_table.put_item(Item=run_to_item(run))

    def put_run_if_absent(self, run: AiRun) -> bool:
        try:
            self._runs_table.put_item(
                Item=run_to_item(run),
                ConditionExpression="attribute_not_exists(run_id)",
            )
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {}) if hasattr(exc, "response") else {}
            if error.get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def get_run(self, run_id: str) -> AiRun | None:
        item = self._runs_table.get_item(Key={"run_id": run_id}).get("Item")
        return None if item is None else item_to_run(item)

    def append_run_event(self, event: AiRunEvent) -> None:
        self._run_events_table.put_item(Item=run_event_to_item(event))

    def list_run_events(self, run_id: str) -> tuple[AiRunEvent, ...]:
        result = self._run_events_table.query(
            IndexName="run-created-at-index",
            KeyConditionExpression=Key("run_id").eq(run_id),
            ScanIndexForward=True,
        )
        return tuple(item_to_run_event(item) for item in result.get("Items", []))

    def put_usage_record(self, record: UsageRecord) -> None:
        self._usage_table.put_item(Item=usage_record_to_item(record))

    def list_usage_records(self) -> tuple[UsageRecord, ...]:
        result = self._usage_table.scan()
        return tuple(
            sorted(
                (item_to_usage_record(item) for item in result.get("Items", [])),
                key=lambda record: record.created_at,
            )
        )

    def list_usage_by_owner(self, owner_user_id: str) -> tuple[UsageRecord, ...]:
        result = self._usage_table.query(
            IndexName="owner-created-at-index",
            KeyConditionExpression=Key("owner_user_id").eq(owner_user_id),
            ScanIndexForward=True,
        )
        return tuple(item_to_usage_record(item) for item in result.get("Items", []))

    def list_usage_by_agent(self, agent_id: str) -> tuple[UsageRecord, ...]:
        result = self._usage_table.query(
            IndexName="agent-created-at-index",
            KeyConditionExpression=Key("agent_id").eq(agent_id),
            ScanIndexForward=True,
        )
        return tuple(item_to_usage_record(item) for item in result.get("Items", []))

    def append_user_credit_ledger_entry(
        self,
        entry: UserCreditLedgerEntry,
        *,
        minimum_available_balance: int = 0,
    ) -> None:
        try:
            update_credit_balance(
                table=self._user_credit_ledger_table,
                key={"entry_id": user_credit_balance_entry_id(entry.owner_user_id)},
                delta=entry.credit_delta,
                minimum_available_balance=minimum_available_balance,
            )
            self._user_credit_ledger_table.put_item(
                Item=user_credit_ledger_entry_to_item(entry),
                ConditionExpression="attribute_not_exists(entry_id)",
            )
        except Exception as exc:
            if is_conditional_check_failed(exc):
                raise InsufficientCreditBalanceError("insufficient user credits") from exc
            raise

    def list_user_credit_ledger_by_owner(self, owner_user_id: str) -> tuple[UserCreditLedgerEntry, ...]:
        result = self._user_credit_ledger_table.query(
            IndexName="owner-created-at-index",
            KeyConditionExpression=Key("owner_user_id").eq(owner_user_id),
            ScanIndexForward=True,
        )
        return tuple(
            item_to_user_credit_ledger_entry(item)
            for item in result.get("Items", [])
            if "entry_type" in item
        )

    def get_user_credit_balance(self, owner_user_id: str) -> int:
        item = self._user_credit_ledger_table.get_item(
            Key={"entry_id": user_credit_balance_entry_id(owner_user_id)}
        ).get("Item")
        if item is not None and "available_credits" in item:
            return int_value(item["available_credits"])
        return sum(entry.credit_delta for entry in self.list_user_credit_ledger_by_owner(owner_user_id))

    def append_server_credit_ledger_entry(
        self,
        entry: ServerCreditLedgerEntry,
        *,
        minimum_available_balance: int = 0,
    ) -> None:
        try:
            update_credit_balance(
                table=self._server_credit_ledger_table,
                key={"entry_id": SERVER_BALANCE_ENTRY_ID},
                delta=entry.credit_delta,
                minimum_available_balance=minimum_available_balance,
            )
            self._server_credit_ledger_table.put_item(
                Item=server_credit_ledger_entry_to_item(entry),
                ConditionExpression="attribute_not_exists(entry_id)",
            )
        except Exception as exc:
            if is_conditional_check_failed(exc):
                raise InsufficientCreditBalanceError("insufficient server credits") from exc
            raise

    def list_server_credit_ledger(self) -> tuple[ServerCreditLedgerEntry, ...]:
        result = self._server_credit_ledger_table.scan()
        return tuple(
            sorted(
                (
                    item_to_server_credit_ledger_entry(item)
                    for item in result.get("Items", [])
                    if "entry_type" in item
                ),
                key=lambda entry: entry.created_at,
            )
        )

    def get_server_credit_balance(self) -> int:
        item = self._server_credit_ledger_table.get_item(Key={"entry_id": SERVER_BALANCE_ENTRY_ID}).get("Item")
        if item is not None and "available_credits" in item:
            return int_value(item["available_credits"])
        return sum(entry.credit_delta for entry in self.list_server_credit_ledger())

    def transfer_server_credits_to_user(
        self,
        user_entry: UserCreditLedgerEntry,
        server_entry: ServerCreditLedgerEntry,
        *,
        minimum_server_available_balance: int,
    ) -> None:
        try:
            update_credit_balance(
                table=self._server_credit_ledger_table,
                key={"entry_id": SERVER_BALANCE_ENTRY_ID},
                delta=server_entry.credit_delta,
                minimum_available_balance=minimum_server_available_balance,
            )
            self._server_credit_ledger_table.put_item(
                Item=server_credit_ledger_entry_to_item(server_entry),
                ConditionExpression="attribute_not_exists(entry_id)",
            )
            update_credit_balance(
                table=self._user_credit_ledger_table,
                key={"entry_id": user_credit_balance_entry_id(user_entry.owner_user_id)},
                delta=user_entry.credit_delta,
            )
            self._user_credit_ledger_table.put_item(
                Item=user_credit_ledger_entry_to_item(user_entry),
                ConditionExpression="attribute_not_exists(entry_id)",
            )
        except Exception as exc:
            if is_conditional_check_failed(exc):
                raise InsufficientCreditBalanceError("insufficient server credits") from exc
            raise

    def put_provider_config(self, config: ProviderConfig) -> None:
        self._provider_configs_table.put_item(Item=provider_config_to_item(config))

    def get_provider_config(self, provider: str) -> ProviderConfig | None:
        item = self._provider_configs_table.get_item(Key={"provider": provider}).get("Item")
        return None if item is None else item_to_provider_config(item)

    def list_provider_configs(self) -> tuple[ProviderConfig, ...]:
        result = self._provider_configs_table.scan()
        return tuple(sorted((item_to_provider_config(item) for item in result.get("Items", [])), key=lambda config: config.provider))

    def append_admin_audit_event(self, event: AdminAuditEvent) -> None:
        self._admin_audit_events_table.put_item(Item=admin_audit_event_to_item(event))

    def list_admin_audit_events(self) -> tuple[AdminAuditEvent, ...]:
        result = self._admin_audit_events_table.scan()
        return tuple(
            sorted(
                (item_to_admin_audit_event(item) for item in result.get("Items", [])),
                key=lambda event: event.created_at,
            )
        )

    def put_model_policy(self, policy: ModelPolicy) -> None:
        self._model_policies_table.put_item(Item=model_policy_to_item(policy))

    def list_model_policies_by_scope(self, scope_key: str) -> tuple[ModelPolicy, ...]:
        result = self._model_policies_table.query(
            IndexName="scope-updated-at-index",
            KeyConditionExpression=Key("scope_key").eq(scope_key),
            ScanIndexForward=True,
        )
        return tuple(item_to_model_policy(item) for item in result.get("Items", []))

    def put_budget_limit(self, limit: BudgetLimit) -> None:
        self._budget_limits_table.put_item(Item=budget_limit_to_item(limit))

    def list_budget_limits_by_scope(self, scope_key: str) -> tuple[BudgetLimit, ...]:
        result = self._budget_limits_table.query(
            IndexName="scope-updated-at-index",
            KeyConditionExpression=Key("scope_key").eq(scope_key),
            ScanIndexForward=True,
        )
        return tuple(item_to_budget_limit(item) for item in result.get("Items", []))

def run_to_item(run: AiRun) -> dict[str, Any]:
    return without_none(
        {
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
            "idempotency_key": run.idempotency_key,
            "created_at": run.created_at.isoformat(),
            "updated_at": run.updated_at.isoformat(),
        }
    )


def item_to_run(item: dict[str, Any]) -> AiRun:
    return AiRun(
        run_id=item["run_id"],
        provider=item["provider"],
        model=item["model"],
        actor_agent_id=item["actor_agent_id"],
        owner_user_id=item["owner_user_id"],
        state=AiRunState(item.get("state", AiRunState.REQUESTED.value)),
        task_id=item.get("task_id"),
        message_id=item.get("message_id"),
        input_ref=item.get("input_ref"),
        output_text=item.get("output_text"),
        output_ref=item.get("output_ref"),
        provider_run_id=item.get("provider_run_id"),
        finish_reason=item.get("finish_reason"),
        usage_id=item.get("usage_id"),
        denial_reason=item.get("denial_reason"),
        safety_reason=item.get("safety_reason"),
        budget_reason=item.get("budget_reason"),
        credit_reason=item.get("credit_reason"),
        trace_id=item.get("trace_id"),
        idempotency_key=item.get("idempotency_key"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def run_event_to_item(event: AiRunEvent) -> dict[str, Any]:
    return without_none(
        {
            "event_id": event.event_id,
            "run_id": event.run_id,
            "state": event.state.value,
            "reason": event.reason,
            "policy_ids": list(event.policy_ids),
            "usage_id": event.usage_id,
            "trace_id": event.trace_id,
            "created_at": event.created_at.isoformat(),
        }
    )


def item_to_run_event(item: dict[str, Any]) -> AiRunEvent:
    return AiRunEvent(
        event_id=item["event_id"],
        run_id=item["run_id"],
        state=AiRunState(item["state"]),
        reason=item["reason"],
        policy_ids=tuple(item.get("policy_ids", [])),
        usage_id=item.get("usage_id"),
        trace_id=item.get("trace_id"),
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def usage_record_to_item(record: UsageRecord) -> dict[str, Any]:
    return without_none(
        {
            "usage_id": record.usage_id,
            "run_id": record.run_id,
            "provider": record.provider,
            "model": record.model,
            "owner_user_id": record.owner_user_id,
            "agent_id": record.agent_id,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "cached_tokens": record.cached_tokens,
            "estimated_cost_units": record.estimated_cost_units,
            "task_id": record.task_id,
            "message_id": record.message_id,
            "approval_state": record.approval_state,
            "created_at": record.created_at.isoformat(),
        }
    )


def item_to_usage_record(item: dict[str, Any]) -> UsageRecord:
    return UsageRecord(
        usage_id=item["usage_id"],
        run_id=item["run_id"],
        provider=item["provider"],
        model=item["model"],
        owner_user_id=item["owner_user_id"],
        agent_id=item["agent_id"],
        input_tokens=int_value(item.get("input_tokens", 0)),
        output_tokens=int_value(item.get("output_tokens", 0)),
        cached_tokens=int_value(item.get("cached_tokens", 0)),
        estimated_cost_units=int_value(item.get("estimated_cost_units", 0)),
        task_id=item.get("task_id"),
        message_id=item.get("message_id"),
        approval_state=item.get("approval_state", "auto_approved"),
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def user_credit_ledger_entry_to_item(entry: UserCreditLedgerEntry) -> dict[str, Any]:
    return without_none(
        {
            "entry_id": entry.entry_id,
            "owner_user_id": entry.owner_user_id,
            "entry_type": entry.entry_type.value,
            "credit_delta": entry.credit_delta,
            "reason": entry.reason,
            "run_id": entry.run_id,
            "usage_id": entry.usage_id,
            "created_at": entry.created_at.isoformat(),
        }
    )


def item_to_user_credit_ledger_entry(item: dict[str, Any]) -> UserCreditLedgerEntry:
    return UserCreditLedgerEntry(
        entry_id=item["entry_id"],
        owner_user_id=item["owner_user_id"],
        entry_type=UserCreditLedgerEntryType(item["entry_type"]),
        credit_delta=int_value(item["credit_delta"]),
        reason=item["reason"],
        run_id=item.get("run_id"),
        usage_id=item.get("usage_id"),
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def server_credit_ledger_entry_to_item(entry: ServerCreditLedgerEntry) -> dict[str, Any]:
    return without_none(
        {
            "entry_id": entry.entry_id,
            "entry_type": entry.entry_type.value,
            "credit_delta": entry.credit_delta,
            "reason": entry.reason,
            "admin_actor_id": entry.admin_actor_id,
            "owner_user_id": entry.owner_user_id,
            "user_credit_entry_id": entry.user_credit_entry_id,
            "created_at": entry.created_at.isoformat(),
        }
    )


def item_to_server_credit_ledger_entry(item: dict[str, Any]) -> ServerCreditLedgerEntry:
    return ServerCreditLedgerEntry(
        entry_id=item["entry_id"],
        entry_type=ServerCreditLedgerEntryType(item["entry_type"]),
        credit_delta=int_value(item["credit_delta"]),
        reason=item["reason"],
        admin_actor_id=item["admin_actor_id"],
        owner_user_id=item.get("owner_user_id"),
        user_credit_entry_id=item.get("user_credit_entry_id"),
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def provider_config_to_item(config: ProviderConfig) -> dict[str, Any]:
    return without_none(
        {
            "provider_config_id": config.provider_config_id,
            "provider": config.provider,
            "enabled": config.enabled,
            "allowed_models": list(config.allowed_models),
            "secret_ref": config.secret_ref,
            "region": config.region,
            "created_at": config.created_at.isoformat(),
            "updated_at": config.updated_at.isoformat(),
        }
    )


def item_to_provider_config(item: dict[str, Any]) -> ProviderConfig:
    return ProviderConfig(
        provider_config_id=item["provider_config_id"],
        provider=item["provider"],
        enabled=bool(item.get("enabled", True)),
        allowed_models=tuple(item.get("allowed_models", [])),
        secret_ref=item.get("secret_ref"),
        region=item.get("region"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def admin_audit_event_to_item(event: AdminAuditEvent) -> dict[str, Any]:
    return {
        "audit_id": event.audit_id,
        "admin_actor_id": event.admin_actor_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "reason": event.reason,
        "metadata": dict(event.metadata),
        "created_at": event.created_at.isoformat(),
    }


def item_to_admin_audit_event(item: dict[str, Any]) -> AdminAuditEvent:
    return AdminAuditEvent(
        audit_id=item["audit_id"],
        admin_actor_id=item["admin_actor_id"],
        action=item["action"],
        target_type=item["target_type"],
        target_id=item["target_id"],
        reason=item["reason"],
        metadata=dict(item.get("metadata", {})),
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def model_policy_to_item(policy: ModelPolicy) -> dict[str, Any]:
    return without_none(
        {
            "policy_id": policy.policy_id,
            "scope_key": policy.scope_key,
            "allowed_providers": list(policy.allowed_providers),
            "allowed_models": list(policy.allowed_models),
            "max_output_tokens": policy.max_output_tokens,
            "enabled": policy.enabled,
            "created_at": policy.created_at.isoformat(),
            "updated_at": policy.updated_at.isoformat(),
        }
    )


def item_to_model_policy(item: dict[str, Any]) -> ModelPolicy:
    return ModelPolicy(
        policy_id=item["policy_id"],
        scope_key=item["scope_key"],
        allowed_providers=tuple(item.get("allowed_providers", [])),
        allowed_models=tuple(item.get("allowed_models", [])),
        max_output_tokens=None if item.get("max_output_tokens") is None else int_value(item["max_output_tokens"]),
        enabled=bool(item.get("enabled", True)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def budget_limit_to_item(limit: BudgetLimit) -> dict[str, Any]:
    return {
        "budget_id": limit.budget_id,
        "scope_key": limit.scope_key,
        "max_total_tokens": limit.max_total_tokens,
        "created_at": limit.created_at.isoformat(),
        "updated_at": limit.updated_at.isoformat(),
    }


def item_to_budget_limit(item: dict[str, Any]) -> BudgetLimit:
    return BudgetLimit(
        budget_id=item["budget_id"],
        scope_key=item["scope_key"],
        max_total_tokens=int_value(item["max_total_tokens"]),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def int_value(value: Any) -> int:
    if isinstance(value, Decimal):
        return int(value)
    return int(value)


def user_credit_balance_entry_id(owner_user_id: str) -> str:
    return f"{USER_BALANCE_ENTRY_PREFIX}{owner_user_id}"


def update_credit_balance(
    *,
    table: Any,
    key: dict[str, Any],
    delta: int,
    minimum_available_balance: int = 0,
) -> None:
    update_args: dict[str, Any] = {
        "Key": key,
        "UpdateExpression": "ADD available_credits :delta",
        "ExpressionAttributeValues": {
            ":delta": delta,
        },
    }
    if minimum_available_balance > 0:
        update_args["ConditionExpression"] = "available_credits >= :minimum_available_balance"
        update_args["ExpressionAttributeValues"][":minimum_available_balance"] = minimum_available_balance
    table.update_item(**update_args)


def is_conditional_check_failed(exc: Exception) -> bool:
    response = getattr(exc, "response", {})
    code = response.get("Error", {}).get("Code")
    if code in {"ConditionalCheckFailedException", "TransactionCanceledException"}:
        return True
    reasons = response.get("CancellationReasons", [])
    return any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons)


def without_none(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}
