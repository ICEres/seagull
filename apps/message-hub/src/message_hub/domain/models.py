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
class MessageRef:
    type: str
    url: str | None = None
    find: str | None = None
    remember_as: str | None = None


@dataclass(frozen=True, slots=True)
class PayloadRecord:
    content_ref: str
    media_type: str
    byte_length: int
    hash: str
    compression: str = "gzip"
    compressed_byte_length: int = 0
    compressed_hash: str | None = None
    ttl_expires_at: datetime | None = None
    retention_state: str = "ready"
    access_scope: str = "recipients"
    fetch_policy_ref: str | None = None
    chunk_manifest_ref: str | None = None
    storage_provider: str = "local_node"
    storage_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class PayloadCompaction:
    manifest_ref: str
    summary: str | None = None
    selected_chunk_refs: tuple[str, ...] = ()
    selected_chunks: tuple[bytes, ...] = ()
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class StoredPayload:
    record: PayloadRecord
    compressed_content: bytes | None
    compaction: PayloadCompaction | None = None


@dataclass(frozen=True, slots=True)
class PayloadRetentionWorkerResult:
    scanned_count: int = 0
    expired_refs: tuple[str, ...] = ()
    compacted_refs: tuple[str, ...] = ()
    deleted_refs: tuple[str, ...] = ()


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
class ToolGrant:
    grant_id: str
    task_id: str
    thread_id: str
    issuer_agent_id: str
    subject_agent_id: str
    audience: str
    scopes: tuple[str, ...]
    purpose: str
    ttl_expires_at: datetime | None = None
    max_calls: int | None = None
    used_count: int = 0
    budget_ref: str | None = None
    allowed_resource_selectors: tuple[str, ...] = ()
    read_only: bool = True
    approval_id: str | None = None
    policy_decision_id: str | None = None
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    thread_id: str
    requester_agent_id: str
    recipient_agent_id: str
    objective: str
    request_message_id: str
    context_refs: tuple[str, ...] = ()
    context_pack_id: str | None = None
    context_pack_ref: str | None = None
    input_ref: str | None = None
    stream_id: str | None = None
    allowed_tool_names: tuple[str, ...] = ()
    allowed_use_terms: tuple[str, ...] = ()
    tool_grant_ids: tuple[str, ...] = ()
    state: TaskState = TaskState.REQUESTED
    policy_decision_id: str | None = None
    accepted_by_agent_id: str | None = None
    result_message_id: str | None = None
    result_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    tool_request_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class TaskToolRequest:
    tool_request_id: str
    task_id: str
    thread_id: str
    requester_agent_id: str
    worker_agent_id: str
    tool_name: str
    purpose: str
    input_ref: str | None = None
    requires_approval: bool = True
    status: TaskState = TaskState.NEEDS_APPROVAL
    approval_id: str | None = None
    policy_decision_id: str | None = None
    accepted_by_agent_id: str | None = None
    tool_grant_id: str | None = None
    result_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    tool_use_summary_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class TaskResultRecord:
    result_id: str
    task_id: str
    thread_id: str
    responder_agent_id: str
    state: TaskState
    result_message_id: str
    stream_id: str | None = None
    content_inline: str | None = None
    content_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    tool_use_summary_refs: tuple[str, ...] = ()
    error: str | None = None
    created_at: datetime = field(default_factory=utc_now)


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
