from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from seagull_protocol.base import (
    ContentRef,
    Handle,
    Message,
    MessageRef,
    PayloadAccessScope,
    ProtocolError,
    required_string,
    require_non_negative_int,
    utc_now,
)


class TaskState(str, Enum):
    REQUESTED = "requested"
    QUOTED = "quoted"
    NEEDS_APPROVAL = "needs_approval"
    APPROVED = "approved"
    ESCROWED = "escrowed"
    ACCEPTED = "accepted"
    RUNNING = "running"
    RESULT_READY = "result_ready"
    RESULT_ACCEPTED = "result_accepted"
    RELEASED = "released"
    COMPLETED = "completed"
    CANCELED = "canceled"
    DISPUTED = "disputed"
    REFUSED = "refused"
    FAILED = "failed"


class TaskCreditLedgerEntryType(str, Enum):
    CREDIT_GRANT = "credit_grant"
    ESCROW_HOLD = "escrow_hold"
    ESCROW_RELEASE = "escrow_release"
    ESCROW_CANCEL = "escrow_cancel"
    DISPUTE_OPEN = "dispute_open"


class TaskCapacityRole(str, Enum):
    REQUESTER = "requester"
    WORKER = "worker"


class TaskCapacityTier(str, Enum):
    LOW = "low"
    STANDARD = "standard"
    HIGH = "high"


class TaskWorkerReputationEventType(str, Enum):
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    RESULT_ACCEPTED = "result_accepted"
    DISPUTE_OPENED = "dispute_opened"
    ABUSE_REPORTED = "abuse_reported"


TASK_CREDIT_SETTLEMENT_SCOPE = "internal_product_credit"


TASK_LIFECYCLE_TRANSITIONS: dict[TaskState, tuple[TaskState, ...]] = {
    TaskState.REQUESTED: (
        TaskState.QUOTED,
        TaskState.NEEDS_APPROVAL,
        TaskState.ACCEPTED,
        TaskState.CANCELED,
        TaskState.REFUSED,
    ),
    TaskState.QUOTED: (
        TaskState.NEEDS_APPROVAL,
        TaskState.APPROVED,
        TaskState.CANCELED,
        TaskState.REFUSED,
    ),
    TaskState.NEEDS_APPROVAL: (
        TaskState.APPROVED,
        TaskState.CANCELED,
        TaskState.REFUSED,
    ),
    TaskState.APPROVED: (
        TaskState.ESCROWED,
        TaskState.ACCEPTED,
        TaskState.CANCELED,
    ),
    TaskState.ESCROWED: (
        TaskState.ACCEPTED,
        TaskState.RUNNING,
        TaskState.CANCELED,
        TaskState.DISPUTED,
    ),
    TaskState.ACCEPTED: (
        TaskState.RUNNING,
        TaskState.RESULT_READY,
        TaskState.COMPLETED,
        TaskState.CANCELED,
        TaskState.REFUSED,
    ),
    TaskState.RUNNING: (
        TaskState.RESULT_READY,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.DISPUTED,
    ),
    TaskState.RESULT_READY: (
        TaskState.RESULT_ACCEPTED,
        TaskState.COMPLETED,
        TaskState.DISPUTED,
    ),
    TaskState.RESULT_ACCEPTED: (
        TaskState.RELEASED,
        TaskState.COMPLETED,
        TaskState.DISPUTED,
    ),
    TaskState.RELEASED: (TaskState.COMPLETED,),
    TaskState.DISPUTED: (
        TaskState.RESULT_ACCEPTED,
        TaskState.RELEASED,
        TaskState.COMPLETED,
        TaskState.CANCELED,
    ),
    TaskState.COMPLETED: (),
    TaskState.CANCELED: (),
    TaskState.REFUSED: (),
    TaskState.FAILED: (TaskState.DISPUTED,),
}


def normalize_task_state(state: TaskState | str) -> TaskState:
    if isinstance(state, TaskState):
        return state
    normalized = required_string(state, "state").lower()
    try:
        return TaskState(normalized)
    except ValueError as exc:
        allowed = ", ".join(task_state.value for task_state in TaskState)
        raise ProtocolError(f"state must be one of: {allowed}") from exc


def task_lifecycle_next_states(state: TaskState | str) -> tuple[TaskState, ...]:
    return TASK_LIFECYCLE_TRANSITIONS[normalize_task_state(state)]


def task_lifecycle_allows(current: TaskState | str, next_state: TaskState | str) -> bool:
    return normalize_task_state(next_state) in task_lifecycle_next_states(current)


def require_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(f"{field_name} must be an integer")


def require_bool(value: bool, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ProtocolError(f"{field_name} must be a boolean")


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_inline_chars: int | None = None
    max_recent_messages: int | None = None
    max_payload_refs: int | None = None
    token_budget_estimate: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "max_inline_chars",
            "max_recent_messages",
            "max_payload_refs",
            "token_budget_estimate",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_non_negative_int(value, field_name)


@dataclass(frozen=True, slots=True)
class ContextPack:
    context_pack_id: str
    thread_id: str
    requester: Handle
    summary: str | None = None
    summary_ref: str | None = None
    recent_messages: tuple[Message, ...] = ()
    selected_refs: tuple[MessageRef, ...] = ()
    payload_refs: tuple[ContentRef, ...] = ()
    budget: ContextBudget = field(default_factory=ContextBudget)
    access_scope: PayloadAccessScope = PayloadAccessScope.RECIPIENTS
    allowed_recipients: tuple[Handle, ...] = ()
    policy_decision_id: str | None = None
    expires_at: datetime | None = None
    redacted_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "context_pack_id",
            required_string(self.context_pack_id, "context_pack_id"),
        )
        object.__setattr__(self, "thread_id", required_string(self.thread_id, "thread_id"))
        if self.summary_ref is not None:
            object.__setattr__(
                self,
                "summary_ref",
                required_string(self.summary_ref, "summary_ref"),
            )
        if self.policy_decision_id is not None:
            object.__setattr__(
                self,
                "policy_decision_id",
                required_string(self.policy_decision_id, "policy_decision_id"),
            )
        object.__setattr__(
            self,
            "redacted_refs",
            tuple(required_string(ref, "redacted_ref") for ref in self.redacted_refs),
        )

    def allows(self, handle: Handle) -> bool:
        if self.access_scope == PayloadAccessScope.PUBLIC:
            return True
        if handle == self.requester:
            return True
        return handle in self.allowed_recipients


@dataclass(frozen=True, slots=True)
class ToolGrant:
    grant_id: str
    task_id: str
    issuer: Handle
    subject: Handle
    audience: str
    scopes: tuple[str, ...]
    ttl_expires_at: datetime | None = None
    max_calls: int | None = None
    budget_ref: str | None = None
    allowed_resource_selectors: tuple[str, ...] = ()
    read_only: bool = True
    approval_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_id", required_string(self.grant_id, "grant_id"))
        object.__setattr__(self, "task_id", required_string(self.task_id, "task_id"))
        object.__setattr__(self, "audience", required_string(self.audience, "audience"))
        if not self.scopes:
            raise ProtocolError("scopes must not be empty")
        object.__setattr__(
            self,
            "scopes",
            tuple(required_string(scope, "scope") for scope in self.scopes),
        )
        if self.max_calls is not None:
            require_non_negative_int(self.max_calls, "max_calls")
        if self.budget_ref is not None:
            object.__setattr__(self, "budget_ref", required_string(self.budget_ref, "budget_ref"))
        if self.approval_id is not None:
            object.__setattr__(
                self,
                "approval_id",
                required_string(self.approval_id, "approval_id"),
            )
        object.__setattr__(
            self,
            "allowed_resource_selectors",
            tuple(
                required_string(selector, "allowed_resource_selector")
                for selector in self.allowed_resource_selectors
            ),
        )


@dataclass(frozen=True, slots=True)
class TaskToolRequest:
    tool_request_id: str
    task_id: str
    thread_id: str
    requester: Handle
    worker: Handle
    tool_name: str
    purpose: str
    input_ref: str | None = None
    requires_approval: bool = True
    state: TaskState = TaskState.NEEDS_APPROVAL
    approval_id: str | None = None
    policy_decision_id: str | None = None
    tool_grant_id: str | None = None
    accepted_by: Handle | None = None
    result_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    tool_use_summary_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tool_request_id",
            required_string(self.tool_request_id, "tool_request_id"),
        )
        object.__setattr__(self, "task_id", required_string(self.task_id, "task_id"))
        object.__setattr__(self, "thread_id", required_string(self.thread_id, "thread_id"))
        object.__setattr__(self, "tool_name", required_string(self.tool_name, "tool_name"))
        object.__setattr__(self, "purpose", required_string(self.purpose, "purpose"))
        for field_name in (
            "input_ref",
            "approval_id",
            "policy_decision_id",
            "tool_grant_id",
            "result_ref",
            "tool_use_summary_ref",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))
        object.__setattr__(
            self,
            "artifact_refs",
            tuple(required_string(ref, "artifact_ref") for ref in self.artifact_refs),
        )
        object.__setattr__(self, "state", normalize_task_state(self.state))


@dataclass(frozen=True, slots=True)
class TaskRequest:
    task_id: str
    thread_id: str
    requester: Handle
    recipient: Handle
    objective: str
    context_pack_id: str | None = None
    context_pack_ref: str | None = None
    input_ref: str | None = None
    stream_id: str | None = None
    allowed_tool_names: tuple[str, ...] = ()
    allowed_use_terms: tuple[str, ...] = ()
    tool_grant_ids: tuple[str, ...] = ()
    state: TaskState = TaskState.REQUESTED
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", required_string(self.task_id, "task_id"))
        object.__setattr__(self, "thread_id", required_string(self.thread_id, "thread_id"))
        object.__setattr__(self, "objective", required_string(self.objective, "objective"))
        for field_name in ("context_pack_id", "context_pack_ref", "input_ref", "stream_id"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))
        object.__setattr__(
            self,
            "allowed_tool_names",
            tuple(required_string(name, "allowed_tool_name") for name in self.allowed_tool_names),
        )
        object.__setattr__(
            self,
            "allowed_use_terms",
            tuple(required_string(term, "allowed_use_term") for term in self.allowed_use_terms),
        )
        object.__setattr__(
            self,
            "tool_grant_ids",
            tuple(required_string(grant_id, "tool_grant_id") for grant_id in self.tool_grant_ids),
        )
        object.__setattr__(self, "state", normalize_task_state(self.state))


@dataclass(frozen=True, slots=True)
class TaskQuote:
    quote_id: str
    task_id: str
    thread_id: str
    requester: Handle
    worker: Handle
    task_reason: str
    expected_credit_cost: int
    shared_context_refs: tuple[str, ...] = ()
    requires_approval: bool = True
    approval_reason: str | None = None
    approved_by: Handle | None = None
    approval_id: str | None = None
    policy_decision_id: str | None = None
    limits_ref: str | None = None
    abuse_policy_ref: str | None = None
    audit_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "quote_id", required_string(self.quote_id, "quote_id"))
        object.__setattr__(self, "task_id", required_string(self.task_id, "task_id"))
        object.__setattr__(self, "thread_id", required_string(self.thread_id, "thread_id"))
        object.__setattr__(self, "task_reason", required_string(self.task_reason, "task_reason"))
        require_non_negative_int(self.expected_credit_cost, "expected_credit_cost")
        if not isinstance(self.requires_approval, bool):
            raise ProtocolError("requires_approval must be a boolean")
        for field_name in (
            "approval_reason",
            "approval_id",
            "policy_decision_id",
            "limits_ref",
            "abuse_policy_ref",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))
        object.__setattr__(
            self,
            "shared_context_refs",
            tuple(required_string(ref, "shared_context_ref") for ref in self.shared_context_refs),
        )
        object.__setattr__(
            self,
            "audit_refs",
            tuple(required_string(ref, "audit_ref") for ref in self.audit_refs),
        )


@dataclass(frozen=True, slots=True)
class TaskEscrow:
    escrow_id: str
    task_id: str
    quote_id: str
    thread_id: str
    requester: Handle
    worker: Handle
    credit_amount: int
    state: TaskState = TaskState.ESCROWED
    approval_id: str | None = None
    policy_decision_id: str | None = None
    limits_ref: str | None = None
    abuse_policy_ref: str | None = None
    audit_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    released_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "escrow_id", required_string(self.escrow_id, "escrow_id"))
        object.__setattr__(self, "task_id", required_string(self.task_id, "task_id"))
        object.__setattr__(self, "quote_id", required_string(self.quote_id, "quote_id"))
        object.__setattr__(self, "thread_id", required_string(self.thread_id, "thread_id"))
        require_non_negative_int(self.credit_amount, "credit_amount")
        state = normalize_task_state(self.state)
        if state not in {
            TaskState.ESCROWED,
            TaskState.RELEASED,
            TaskState.CANCELED,
            TaskState.DISPUTED,
        }:
            raise ProtocolError("escrow state must be escrowed, released, canceled, or disputed")
        object.__setattr__(self, "state", state)
        for field_name in (
            "approval_id",
            "policy_decision_id",
            "limits_ref",
            "abuse_policy_ref",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))
        object.__setattr__(
            self,
            "audit_refs",
            tuple(required_string(ref, "audit_ref") for ref in self.audit_refs),
        )


@dataclass(frozen=True, slots=True)
class TaskCapacitySharingPolicy:
    policy_id: str
    task_id: str
    thread_id: str
    requester: Handle
    worker: Handle
    requester_role: TaskCapacityRole = TaskCapacityRole.REQUESTER
    worker_role: TaskCapacityRole = TaskCapacityRole.WORKER
    requester_capacity_tier: TaskCapacityTier = TaskCapacityTier.LOW
    worker_capacity_tier: TaskCapacityTier = TaskCapacityTier.HIGH
    max_credit_cost: int = 0
    max_auto_escrow_credits: int = 0
    allow_private_context: bool = False
    private_context_requires_approval: bool = True
    paid_work_requires_approval: bool = True
    high_cost_requires_approval: bool = True
    abuse_policy_ref: str | None = None
    limits_ref: str | None = None
    policy_decision_id: str | None = None
    audit_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", required_string(self.policy_id, "policy_id"))
        object.__setattr__(self, "task_id", required_string(self.task_id, "task_id"))
        object.__setattr__(self, "thread_id", required_string(self.thread_id, "thread_id"))
        if self.requester_role != TaskCapacityRole.REQUESTER:
            raise ProtocolError("requester_role must be requester")
        if self.worker_role != TaskCapacityRole.WORKER:
            raise ProtocolError("worker_role must be worker")
        if not isinstance(self.requester_capacity_tier, TaskCapacityTier):
            try:
                object.__setattr__(
                    self,
                    "requester_capacity_tier",
                    TaskCapacityTier(self.requester_capacity_tier),
                )
            except ValueError as exc:
                allowed = ", ".join(tier.value for tier in TaskCapacityTier)
                raise ProtocolError(f"requester_capacity_tier must be one of: {allowed}") from exc
        if not isinstance(self.worker_capacity_tier, TaskCapacityTier):
            try:
                object.__setattr__(
                    self,
                    "worker_capacity_tier",
                    TaskCapacityTier(self.worker_capacity_tier),
                )
            except ValueError as exc:
                allowed = ", ".join(tier.value for tier in TaskCapacityTier)
                raise ProtocolError(f"worker_capacity_tier must be one of: {allowed}") from exc
        require_non_negative_int(self.max_credit_cost, "max_credit_cost")
        require_non_negative_int(self.max_auto_escrow_credits, "max_auto_escrow_credits")
        if self.max_auto_escrow_credits > self.max_credit_cost:
            raise ProtocolError("max_auto_escrow_credits cannot exceed max_credit_cost")
        for field_name in (
            "allow_private_context",
            "private_context_requires_approval",
            "paid_work_requires_approval",
            "high_cost_requires_approval",
        ):
            require_bool(getattr(self, field_name), field_name)
        for field_name in (
            "abuse_policy_ref",
            "limits_ref",
            "policy_decision_id",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))
        object.__setattr__(
            self,
            "audit_refs",
            tuple(required_string(ref, "audit_ref") for ref in self.audit_refs),
        )


@dataclass(frozen=True, slots=True)
class TaskCreditLedgerEntry:
    entry_id: str
    account: Handle
    entry_type: TaskCreditLedgerEntryType
    credit_amount: int
    available_delta: int
    escrow_delta: int = 0
    task_id: str | None = None
    thread_id: str | None = None
    quote_id: str | None = None
    escrow_id: str | None = None
    counterparty: Handle | None = None
    reason: str | None = None
    settlement_scope: str = TASK_CREDIT_SETTLEMENT_SCOPE
    policy_decision_id: str | None = None
    limits_ref: str | None = None
    abuse_policy_ref: str | None = None
    audit_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", required_string(self.entry_id, "entry_id"))
        require_non_negative_int(self.credit_amount, "credit_amount")
        require_int(self.available_delta, "available_delta")
        require_int(self.escrow_delta, "escrow_delta")
        if self.settlement_scope != TASK_CREDIT_SETTLEMENT_SCOPE:
            raise ProtocolError("task credits must remain internal product credits")
        if not isinstance(self.entry_type, TaskCreditLedgerEntryType):
            try:
                object.__setattr__(self, "entry_type", TaskCreditLedgerEntryType(self.entry_type))
            except ValueError as exc:
                allowed = ", ".join(entry_type.value for entry_type in TaskCreditLedgerEntryType)
                raise ProtocolError(f"entry_type must be one of: {allowed}") from exc
        for field_name in (
            "task_id",
            "thread_id",
            "quote_id",
            "escrow_id",
            "reason",
            "policy_decision_id",
            "limits_ref",
            "abuse_policy_ref",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))
        object.__setattr__(
            self,
            "audit_refs",
            tuple(required_string(ref, "audit_ref") for ref in self.audit_refs),
        )


@dataclass(frozen=True, slots=True)
class TaskWorkerReputationEvent:
    event_id: str
    worker: Handle
    event_type: TaskWorkerReputationEventType
    task_id: str
    thread_id: str
    reporter: Handle | None = None
    reason: str | None = None
    policy_decision_id: str | None = None
    limits_ref: str | None = None
    abuse_policy_ref: str | None = None
    audit_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", required_string(self.event_id, "event_id"))
        object.__setattr__(self, "task_id", required_string(self.task_id, "task_id"))
        object.__setattr__(self, "thread_id", required_string(self.thread_id, "thread_id"))
        if not isinstance(self.event_type, TaskWorkerReputationEventType):
            try:
                object.__setattr__(
                    self,
                    "event_type",
                    TaskWorkerReputationEventType(self.event_type),
                )
            except ValueError as exc:
                allowed = ", ".join(event_type.value for event_type in TaskWorkerReputationEventType)
                raise ProtocolError(f"event_type must be one of: {allowed}") from exc
        for field_name in (
            "reason",
            "policy_decision_id",
            "limits_ref",
            "abuse_policy_ref",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))
        object.__setattr__(
            self,
            "audit_refs",
            tuple(required_string(ref, "audit_ref") for ref in self.audit_refs),
        )


@dataclass(frozen=True, slots=True)
class TaskWorkerReputationSummary:
    worker: Handle
    completed_task_count: int = 0
    failed_task_count: int = 0
    accepted_result_count: int = 0
    dispute_count: int = 0
    abuse_report_count: int = 0
    last_event_id: str | None = None
    audit_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "completed_task_count",
            "failed_task_count",
            "accepted_result_count",
            "dispute_count",
            "abuse_report_count",
        ):
            require_non_negative_int(getattr(self, field_name), field_name)
        if self.last_event_id is not None:
            object.__setattr__(self, "last_event_id", required_string(self.last_event_id, "last_event_id"))
        object.__setattr__(
            self,
            "audit_refs",
            tuple(required_string(ref, "audit_ref") for ref in self.audit_refs),
        )

    @property
    def total_outcome_count(self) -> int:
        return self.completed_task_count + self.failed_task_count

    @property
    def completion_rate(self) -> float | None:
        if self.total_outcome_count == 0:
            return None
        return self.completed_task_count / self.total_outcome_count

    @property
    def failure_rate(self) -> float | None:
        if self.total_outcome_count == 0:
            return None
        return self.failed_task_count / self.total_outcome_count


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    responder: Handle
    state: TaskState
    result_message_id: str | None = None
    stream_id: str | None = None
    content: str | None = None
    content_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    tool_use_summary_refs: tuple[str, ...] = ()
    error: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", required_string(self.task_id, "task_id"))
        for field_name in ("result_message_id", "stream_id", "content_ref", "error"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))
        object.__setattr__(
            self,
            "artifact_refs",
            tuple(required_string(ref, "artifact_ref") for ref in self.artifact_refs),
        )
        object.__setattr__(
            self,
            "tool_use_summary_refs",
            tuple(
                required_string(ref, "tool_use_summary_ref")
                for ref in self.tool_use_summary_refs
            ),
        )
        object.__setattr__(self, "state", normalize_task_state(self.state))


__all__ = [
    "ContextBudget",
    "ContextPack",
    "TASK_LIFECYCLE_TRANSITIONS",
    "TASK_CREDIT_SETTLEMENT_SCOPE",
    "TaskCapacityRole",
    "TaskCapacitySharingPolicy",
    "TaskCapacityTier",
    "TaskCreditLedgerEntry",
    "TaskCreditLedgerEntryType",
    "TaskEscrow",
    "TaskQuote",
    "TaskRequest",
    "TaskResult",
    "TaskState",
    "TaskToolRequest",
    "TaskWorkerReputationEvent",
    "TaskWorkerReputationEventType",
    "TaskWorkerReputationSummary",
    "ToolGrant",
    "normalize_task_state",
    "task_lifecycle_allows",
    "task_lifecycle_next_states",
]
