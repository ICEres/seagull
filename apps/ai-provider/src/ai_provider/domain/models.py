from __future__ import annotations

from dataclasses import field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from ai_provider._compat import dataclass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


EMPTY_METADATA: Mapping[str, str] = MappingProxyType({})


class AiRunState(str, Enum):
    REQUESTED = "requested"
    SAFETY_CHECKED = "safety_checked"
    QUEUED = "queued"
    RUNNING = "running"
    OUTPUT_CHECKED = "output_checked"
    COMPLETED = "completed"
    DENIED = "denied"
    FAILED = "failed"
    CANCELED = "canceled"
    QUARANTINED = "quarantined"


class UserCreditLedgerEntryType(str, Enum):
    CREDIT_GRANT = "credit_grant"
    AI_RUN_CHARGE = "ai_run_charge"


class ServerCreditLedgerEntryType(str, Enum):
    CREDIT_GRANT = "credit_grant"
    USER_CREDIT_GRANT = "user_credit_grant"


@dataclass(frozen=True, slots=True)
class ProviderMessage:
    role: str
    content: str
    content_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cached_tokens


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    provider: str
    model: str
    actor_agent_id: str
    owner_user_id: str
    input_messages: tuple[ProviderMessage, ...]
    system_instructions: str | None = None
    system_instructions_ref: str | None = None
    context_refs: tuple[str, ...] = ()
    content_ref: str | None = None
    max_output_tokens: int = 512
    temperature: float = 0.2
    response_format: str = "text"
    tool_policy: str = "disabled"
    task_id: str | None = None
    message_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    output_text: str | None = None
    output_ref: str | None = None
    finish_reason: str = "stop"
    provider_run_id: str | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    safety_metadata: Mapping[str, str] = field(default=EMPTY_METADATA)
    latency_ms: int | None = None
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class AiRun:
    run_id: str
    provider: str
    model: str
    actor_agent_id: str
    owner_user_id: str
    state: AiRunState = AiRunState.REQUESTED
    task_id: str | None = None
    message_id: str | None = None
    input_ref: str | None = None
    output_text: str | None = None
    output_ref: str | None = None
    provider_run_id: str | None = None
    finish_reason: str | None = None
    usage_id: str | None = None
    denial_reason: str | None = None
    safety_reason: str | None = None
    budget_reason: str | None = None
    credit_reason: str | None = None
    trace_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AiRunEvent:
    event_id: str
    run_id: str
    state: AiRunState
    reason: str
    policy_ids: tuple[str, ...] = ()
    usage_id: str | None = None
    trace_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class UsageRecord:
    usage_id: str
    run_id: str
    provider: str
    model: str
    owner_user_id: str
    agent_id: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    estimated_cost_units: int = 0
    task_id: str | None = None
    message_id: str | None = None
    approval_state: str = "auto_approved"
    created_at: datetime = field(default_factory=utc_now)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cached_tokens


@dataclass(frozen=True, slots=True)
class UserCreditLedgerEntry:
    entry_id: str
    owner_user_id: str
    entry_type: UserCreditLedgerEntryType
    credit_delta: int
    reason: str
    run_id: str | None = None
    usage_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class UserCreditBalance:
    owner_user_id: str
    available_credits: int


@dataclass(frozen=True, slots=True)
class ServerCreditLedgerEntry:
    entry_id: str
    entry_type: ServerCreditLedgerEntryType
    credit_delta: int
    reason: str
    admin_actor_id: str
    owner_user_id: str | None = None
    user_credit_entry_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ServerCreditBalance:
    available_credits: int


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    provider_config_id: str
    provider: str
    enabled: bool = True
    allowed_models: tuple[str, ...] = ()
    secret_ref: str | None = None
    region: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AdminAuditEvent:
    audit_id: str
    admin_actor_id: str
    action: str
    target_type: str
    target_id: str
    reason: str
    metadata: Mapping[str, str] = field(default=EMPTY_METADATA)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    policy_id: str
    scope_key: str
    allowed_providers: tuple[str, ...] = ()
    allowed_models: tuple[str, ...] = ()
    max_output_tokens: int | None = None
    enabled: bool = True
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class BudgetLimit:
    budget_id: str
    scope_key: str
    max_total_tokens: int
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
