from __future__ import annotations

from dataclasses import field
from datetime import datetime, timezone
from typing import Any

from dataclasses import dataclass

# Shared vocabulary lives in the protocol package; the hub imports it rather than
# re-declaring it. Only types whose hub shape genuinely differs from the protocol
# shape are defined below (storage records key agents by id, not by Handle).
from seagull_protocol.base import (
    DeliveryState,
    MessageIntent,
    MessageRef,
    RoutingRuleMode,
    Visibility,
    normalize_message_intent,
)
from seagull_protocol.work import (
    TASK_CREDIT_SETTLEMENT_SCOPE,
    TASK_LIFECYCLE_TRANSITIONS,
    TaskCapacityRole,
    TaskCapacityTier,
    TaskCreditLedgerEntryType,
    TaskState,
    TaskWorkerReputationEventType,
    task_lifecycle_allows,
    task_lifecycle_next_states,
)

# The hub spells this `DeliveryStatus`; the protocol spells it `DeliveryState`.
# Keep the hub name as an alias so call sites and stored values are untouched
# (terminology.md defers identifier renames to a separate migration).
DeliveryStatus = DeliveryState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


TASK_INACTIVE_STATES = frozenset(
    {
        TaskState.RELEASED,
        TaskState.COMPLETED,
        TaskState.CANCELED,
        TaskState.REFUSED,
        TaskState.FAILED,
    }
)


# ---------------------------------------------------------------------------
# Feed
#
# Feed is a gulls network capability: durable one-to-many publishing and
# subscription. These are the base source-of-truth records. seagulls keeps
# ranking and projections on top of them, not a second copy of the truth
# (packages/gulls/docs/terminology.md).
#
# Records key agents by id, matching the rest of the hub's storage shapes.
# ---------------------------------------------------------------------------


def normalize_visibility(visibility: Visibility | str) -> Visibility | str:
    """Coerce to the protocol enum, tolerating values it does not name.

    Same forgiving contract as ``normalize_message_intent``: an unrecognized
    value passes through as a string rather than failing the write. Feed
    records are migrated from a store that never constrained this field, so a
    strict enum here would reject rows that already exist.
    """
    if isinstance(visibility, Visibility):
        return visibility
    value = str(visibility).strip().lower()
    try:
        return Visibility(value)
    except ValueError:
        return value


@dataclass(frozen=True, slots=True)
class PostRecord:
    post_id: str
    author_agent_id: str
    content: str
    text: str
    refs: tuple[MessageRef, ...] = ()
    visibility: Visibility | str = Visibility.PUBLIC
    room_id: str | None = None
    reply_to_post_id: str | None = None
    mention_agent_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "visibility", normalize_visibility(self.visibility))

    @property
    def intent(self) -> MessageIntent:
        """Which Feed intent this post carries.

        The protocol already names these (``protocol/base.py``); a reply is a
        reply even when it also mentions someone, so ordering matters.
        """
        if self.reply_to_post_id is not None:
            return MessageIntent.REPLY
        if self.mention_agent_ids:
            return MessageIntent.MENTION
        return MessageIntent.POST


@dataclass(frozen=True, slots=True)
class FollowRecord:
    follower_agent_id: str
    followed_agent_id: str
    created_at: datetime = field(default_factory=utc_now)

    @property
    def intent(self) -> MessageIntent:
        return MessageIntent.FOLLOW


@dataclass(frozen=True, slots=True)
class RoomRecord:
    room_id: str
    slug: str
    name: str
    description: str | None = None
    visibility: Visibility | str = Visibility.PUBLIC
    created_by_user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "visibility", normalize_visibility(self.visibility))


@dataclass(frozen=True, slots=True)
class RoomMembershipRecord:
    room_id: str
    agent_id: str
    role: str = "member"
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class FeedEventRecord:
    event_id: str
    event_type: str
    actor_agent_id: str | None = None
    object_id: str | None = None
    target_agent_ids: tuple[str, ...] = ()
    room_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    @property
    def intent(self) -> MessageIntent | str:
        """Feed event types are the protocol's intent vocabulary."""
        return normalize_message_intent(self.event_type)


@dataclass(frozen=True, slots=True)
class NotificationRecord:
    notification_id: str
    recipient_agent_id: str
    notification_type: str
    owner_user_id: str | None = None
    actor_agent_id: str | None = None
    post_id: str | None = None
    room_id: str | None = None
    read_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)


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
    # Who may post into this agent's inbox through its public URL. Gates only
    # the token-less guest path in this slice: "open" admits guests, anything
    # else refuses them; "token_required" is reserved for later semantics and
    # currently behaves exactly like "contacts_only". Registered senders are
    # never gated by posture.
    inbox_posture: str = "contacts_only"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AgentTokenRecord:
    token_id: str
    token_hash: str
    agent_id: str
    agent_handle: str
    scopes: tuple[str, ...]
    name: str | None = None
    owner_user_id: str | None = None
    node_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IssuedAgentToken:
    token: str
    record: AgentTokenRecord


@dataclass(frozen=True, slots=True)
class AgentTokenPrincipal:
    token_id: str
    agent_id: str
    agent_handle: str
    scopes: frozenset[str]
    owner_user_id: str | None = None
    node_id: str | None = None


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
    runtime_mode: str | None = None
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
    # Monotonically increasing revision used by atomic message commits. Legacy
    # rows decode as zero and are advanced on their first transactional update.
    revision: int = 0


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
class ContactExplanation:
    explanation_id: str
    delivery_id: str
    message_id: str
    thread_id: str
    requester_agent_id: str
    requester_handle: str
    recipient_agent_id: str
    recipient_handle: str
    answering_asset_handle: str
    relationship: str
    reason: str
    allowed_reason: str
    shared_context_summary: str
    shared_context_refs: tuple[str, ...] = ()
    pending_action: str | None = None
    current_stage: str = "agent.wait"
    policy_refs: tuple[str, ...] = ()
    audit_event_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)


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
    replayed: bool = False


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
    quote_ids: tuple[str, ...] = ()
    escrow_ids: tuple[str, ...] = ()
    capacity_policy_ids: tuple[str, ...] = ()
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
class TaskCapacitySharingPolicyRecord:
    policy_id: str
    task_id: str
    thread_id: str
    requester_agent_id: str
    worker_agent_id: str
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


@dataclass(frozen=True, slots=True)
class TaskQuoteRecord:
    quote_id: str
    task_id: str
    thread_id: str
    requester_agent_id: str
    worker_agent_id: str
    task_reason: str
    expected_credit_cost: int
    shared_context_refs: tuple[str, ...] = ()
    requires_approval: bool = True
    approval_reason: str | None = None
    approved_by_agent_id: str | None = None
    approval_id: str | None = None
    policy_decision_id: str | None = None
    limits_ref: str | None = None
    abuse_policy_ref: str | None = None
    audit_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class TaskEscrowRecord:
    escrow_id: str
    task_id: str
    quote_id: str
    thread_id: str
    requester_agent_id: str
    worker_agent_id: str
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


@dataclass(frozen=True, slots=True)
class TaskCreditLedgerEntry:
    entry_id: str
    account_agent_id: str
    entry_type: TaskCreditLedgerEntryType
    credit_amount: int
    available_delta: int
    escrow_delta: int = 0
    task_id: str | None = None
    thread_id: str | None = None
    quote_id: str | None = None
    escrow_id: str | None = None
    counterparty_agent_id: str | None = None
    reason: str | None = None
    settlement_scope: str = TASK_CREDIT_SETTLEMENT_SCOPE
    policy_decision_id: str | None = None
    limits_ref: str | None = None
    abuse_policy_ref: str | None = None
    audit_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class TaskCreditBalance:
    account_agent_id: str
    available_balance: int
    escrow_balance: int
    settlement_scope: str = TASK_CREDIT_SETTLEMENT_SCOPE

    @property
    def total_balance(self) -> int:
        return self.available_balance + self.escrow_balance


@dataclass(frozen=True, slots=True)
class TaskWorkerReputationEventRecord:
    event_id: str
    worker_agent_id: str
    event_type: TaskWorkerReputationEventType
    task_id: str
    thread_id: str
    reporter_agent_id: str | None = None
    reason: str | None = None
    policy_decision_id: str | None = None
    limits_ref: str | None = None
    abuse_policy_ref: str | None = None
    audit_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class TaskWorkerReputationSummary:
    worker_agent_id: str
    completed_task_count: int = 0
    failed_task_count: int = 0
    accepted_result_count: int = 0
    dispute_count: int = 0
    abuse_report_count: int = 0
    last_event_id: str | None = None
    last_event_at: datetime | None = None

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
