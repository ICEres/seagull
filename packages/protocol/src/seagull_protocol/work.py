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
    ACCEPTED = "accepted"
    RUNNING = "running"
    NEEDS_APPROVAL = "needs_approval"
    RESULT_READY = "result_ready"
    COMPLETED = "completed"
    REFUSED = "refused"
    FAILED = "failed"


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
class TaskRequest:
    task_id: str
    thread_id: str
    requester: Handle
    recipient: Handle
    objective: str
    context_pack_id: str | None = None
    context_pack_ref: str | None = None
    input_ref: str | None = None
    allowed_tool_names: tuple[str, ...] = ()
    allowed_use_terms: tuple[str, ...] = ()
    tool_grant_ids: tuple[str, ...] = ()
    state: TaskState = TaskState.REQUESTED
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", required_string(self.task_id, "task_id"))
        object.__setattr__(self, "thread_id", required_string(self.thread_id, "thread_id"))
        object.__setattr__(self, "objective", required_string(self.objective, "objective"))
        for field_name in ("context_pack_id", "context_pack_ref", "input_ref"):
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


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    responder: Handle
    state: TaskState
    result_message_id: str | None = None
    content: str | None = None
    content_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    tool_use_summary_refs: tuple[str, ...] = ()
    error: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", required_string(self.task_id, "task_id"))
        for field_name in ("result_message_id", "content_ref", "error"):
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


__all__ = [
    "ContextBudget",
    "ContextPack",
    "TaskRequest",
    "TaskResult",
    "TaskState",
    "ToolGrant",
]
