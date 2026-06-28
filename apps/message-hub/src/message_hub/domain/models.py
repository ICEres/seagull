from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeliveryStatus(str, Enum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    READ = "read"
    ACKED = "acked"
    FAILED = "failed"
    REPLIED = "replied"
    IGNORED = "ignored"
    NEEDS_REVIEW = "needs_review"
    PENDING_ACTION = "pending_action"


class RoutingRuleMode(str, Enum):
    DIRECT = "direct"
    COPY = "copy"
    HANDOFF = "handoff"
    REVIEW = "review"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class MessageRef:
    type: str
    url: str | None = None
    find: str | None = None
    remember_as: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowTraceEntry:
    hook: str
    runtime: str
    action: str = "continue"
    actor: str | None = None
    changed: tuple[str, ...] = ()
    note: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class RoutingRule:
    rule_id: str
    name: str
    mode: RoutingRuleMode
    route_to_handles: tuple[str, ...] = ()
    url_contains: tuple[str, ...] = ()
    enabled: bool = True
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ActionRequest:
    action_request_id: str
    type: str
    target: str | None = None
    runtime: str = "cloud"
    requires_approval: bool = True
    status: str = "pending"
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Agent:
    agent_id: str
    handle: str
    display_name: str | None = None
    capabilities: tuple[str, ...] = ()
    response_rules: dict[str, Any] | None = None
    status: str = "active"
    trigger_mode: str = "manual"
    webhook_url: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Message:
    message_id: str
    thread_id: str
    sender_agent_id: str
    recipient_agent_ids: tuple[str, ...]
    intent: str
    visibility: str
    content_inline: str | None = None
    content_ref: str | None = None
    refs: tuple[MessageRef, ...] = ()
    schema_version: str = "seagull.message.v1"
    safety_status: str = "approved"
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ThreadRecord:
    thread_id: str
    root_message_id: str
    participants: frozenset[str]
    message_count: int
    last_message_id: str
    last_message_at: datetime
    title: str | None = None
    summary_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Delivery:
    delivery_id: str
    message_id: str
    thread_id: str
    sender_agent_id: str
    recipient_agent_id: str
    status: DeliveryStatus
    retry_count: int = 0
    last_error: str | None = None
    current_content_inline: str | None = None
    current_content_ref: str | None = None
    refs: tuple[MessageRef, ...] = ()
    workflow_trace: tuple[WorkflowTraceEntry, ...] = ()
    current_stage: str = "agent.wait"
    action_request: ActionRequest | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    acked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ThreadSummary:
    thread_id: str
    summary_id: str
    summary_text: str
    message_start_id: str | None = None
    message_end_id: str | None = None
    token_count_estimate: int | None = None
    content_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class InboxItem:
    delivery: Delivery
    message: Message


@dataclass(frozen=True, slots=True)
class SendMessageResult:
    message: Message
    thread: ThreadRecord
    deliveries: tuple[Delivery, ...]


@dataclass(frozen=True, slots=True)
class AgentDecisionResult:
    delivery: Delivery
    reply: SendMessageResult | None = None
    action_request: ActionRequest | None = None


@dataclass(frozen=True, slots=True)
class ThreadContext:
    thread: ThreadRecord
    summary: ThreadSummary | None
    recent_messages: tuple[Message, ...]


@dataclass(frozen=True, slots=True)
class ContextPayloadRef:
    content_ref: str
    source_type: str
    source_id: str


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_inline_chars: int
    max_recent_messages: int
    max_payload_refs: int
    token_budget_estimate: int | None = None
    inline_chars_used: int = 0
    recent_messages_returned: int = 0
    payload_refs_returned: int = 0
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class ContextPack:
    context_pack_id: str
    thread: ThreadRecord
    requester_handle: str
    summary: ThreadSummary | None
    recent_messages: tuple[Message, ...]
    selected_refs: tuple[MessageRef, ...]
    payload_refs: tuple[ContextPayloadRef, ...]
    budget: ContextBudget
    access_scope: str = "recipients"
    allowed_recipients: tuple[str, ...] = ()
    redacted_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
