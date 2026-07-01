from __future__ import annotations

import re
from dataclasses import field
from datetime import datetime, timezone
from enum import Enum

from seagull_protocol._compat import dataclass


HANDLE_RE = re.compile(r"^@[a-z0-9][a-z0-9_.-]*:[a-z0-9][a-z0-9.-]*$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProtocolError(ValueError):
    """Raised when a protocol object is invalid."""


class MessageIntent(str, Enum):
    MESSAGE = "message"
    POST = "post"
    REPLY = "reply"
    MENTION = "mention"
    DIRECT_MESSAGE = "direct_message"
    QUESTION = "question"
    TASK_REQUEST = "task_request"
    TASK_RESULT = "task_result"
    HANDOFF = "handoff"
    STATUS_UPDATE = "status_update"
    ARTIFACT_SHARE = "artifact_share"
    FOLLOW = "follow"
    INVITE = "invite"
    MODERATION_EVENT = "moderation_event"


class Visibility(str, Enum):
    DIRECT = "direct"
    LIMITED = "limited"
    PUBLIC = "public"


class DeliveryState(str, Enum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    READ = "read"
    ACKED = "acked"
    FAILED = "failed"
    REPLIED = "replied"
    IGNORED = "ignored"
    NEEDS_REVIEW = "needs_review"
    PENDING_ACTION = "pending_action"


class ArtifactKind(str, Enum):
    INLINE = "inline"
    URI = "uri"


class PayloadCompression(str, Enum):
    NONE = "none"
    GZIP = "gzip"
    ZSTD = "zstd"


class PayloadRetentionState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    COMPACTED = "compacted"
    EXPIRED = "expired"
    DELETED = "deleted"


class PayloadAccessScope(str, Enum):
    OWNER = "owner"
    THREAD = "thread"
    RECIPIENTS = "recipients"
    PUBLIC = "public"


class PayloadStorageProvider(str, Enum):
    LOCAL_NODE = "local_node"
    CLOUD_OBJECT = "cloud_object"
    EXTERNAL = "external"


class HookType(str, Enum):
    SEND_BEFORE = "send.before"
    ROUTE_RESOLVE = "route.resolve"
    DELIVERY_BEFORE = "delivery.before"
    RECEIVE_BEFORE = "receive.before"
    ACTION_BEFORE = "action.before"
    REPLY_BEFORE = "reply.before"
    AFTER = "after"


class HookRuntime(str, Enum):
    CLOUD = "cloud"
    CLOUD_NODE = "cloud_node"
    LAN_NODE = "lan_node"
    AGENT_CLIENT = "agent_client"


class RoutingRuleMode(str, Enum):
    DIRECT = "direct"
    COPY = "copy"
    HANDOFF = "handoff"
    REVIEW = "review"
    BLOCK = "block"


class AgentDecision(str, Enum):
    REPLY = "reply"
    ACTION = "action"
    IGNORE = "ignore"
    ASK_HUMAN = "ask_human"


class RelationshipPreset(str, Enum):
    NEEDS_APPROVAL = "needs_approval"
    TRUSTED_REVIEWER = "trusted_reviewer"
    SUMMARY_HELPER = "summary_helper"
    RESEARCH_HELPER = "research_helper"
    BLOCKED = "blocked"
    PAID_WORKER = "paid_worker"


DEFAULT_APPROVAL_REQUIRED_FOR = (
    "private_context",
    "tool_use",
    "high_cost_work",
)

BLOCKED_APPROVAL_REQUIRED_FOR = (
    "contact",
    "private_context",
    "tool_use",
    "high_cost_work",
    "paid_work",
)


@dataclass(frozen=True, slots=True)
class RelationshipPresetDefaults:
    preset: RelationshipPreset
    trust_label: str
    routing_mode: RoutingRuleMode
    approval_required_for: tuple[str, ...]
    allowed_use_terms: tuple[str, ...]


RELATIONSHIP_PRESET_DEFAULTS = {
    RelationshipPreset.NEEDS_APPROVAL: RelationshipPresetDefaults(
        preset=RelationshipPreset.NEEDS_APPROVAL,
        trust_label="unknown",
        routing_mode=RoutingRuleMode.REVIEW,
        approval_required_for=DEFAULT_APPROVAL_REQUIRED_FOR,
        allowed_use_terms=(),
    ),
    RelationshipPreset.TRUSTED_REVIEWER: RelationshipPresetDefaults(
        preset=RelationshipPreset.TRUSTED_REVIEWER,
        trust_label="trusted",
        routing_mode=RoutingRuleMode.REVIEW,
        approval_required_for=DEFAULT_APPROVAL_REQUIRED_FOR,
        allowed_use_terms=("inspect_shared_context", "return_feedback", "return_artifacts"),
    ),
    RelationshipPreset.SUMMARY_HELPER: RelationshipPresetDefaults(
        preset=RelationshipPreset.SUMMARY_HELPER,
        trust_label="limited",
        routing_mode=RoutingRuleMode.REVIEW,
        approval_required_for=DEFAULT_APPROVAL_REQUIRED_FOR,
        allowed_use_terms=("inspect_shared_context", "return_summary", "no_long_term_memory"),
    ),
    RelationshipPreset.RESEARCH_HELPER: RelationshipPresetDefaults(
        preset=RelationshipPreset.RESEARCH_HELPER,
        trust_label="limited",
        routing_mode=RoutingRuleMode.REVIEW,
        approval_required_for=DEFAULT_APPROVAL_REQUIRED_FOR,
        allowed_use_terms=("inspect_shared_context", "return_research_notes", "cite_sources"),
    ),
    RelationshipPreset.BLOCKED: RelationshipPresetDefaults(
        preset=RelationshipPreset.BLOCKED,
        trust_label="blocked",
        routing_mode=RoutingRuleMode.BLOCK,
        approval_required_for=BLOCKED_APPROVAL_REQUIRED_FOR,
        allowed_use_terms=(),
    ),
    RelationshipPreset.PAID_WORKER: RelationshipPresetDefaults(
        preset=RelationshipPreset.PAID_WORKER,
        trust_label="limited",
        routing_mode=RoutingRuleMode.REVIEW,
        approval_required_for=(*DEFAULT_APPROVAL_REQUIRED_FOR, "paid_work"),
        allowed_use_terms=("inspect_shared_context", "return_artifacts", "metered_work"),
    ),
}


@dataclass(frozen=True, slots=True)
class Handle:
    value: str

    def __post_init__(self) -> None:
        normalized = normalize_handle(self.value)
        object.__setattr__(self, "value", normalized)

    @property
    def local_part(self) -> str:
        return self.value[1:].split(":", 1)[0]

    @property
    def server(self) -> str:
        return self.value.split(":", 1)[1]

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AgentProfile:
    handle: Handle
    display_name: str | None = None
    capabilities: tuple[str, ...] = ()
    relationship_posture: str = "needs_approval"
    approval_required_for: tuple[str, ...] = DEFAULT_APPROVAL_REQUIRED_FOR
    allowed_use_terms: tuple[str, ...] = ()
    contact_explanation: str | None = None
    protocols: tuple[str, ...] = ("seagull",)
    status: str = "active"
    owner_user_id: str | None = None
    node_id: str | None = None
    trust_label: str = "unknown"
    visibility: Visibility = Visibility.PUBLIC
    supported_extension_namespaces: tuple[str, ...] = ()
    public_key: str | None = None

    def __post_init__(self) -> None:
        if self.display_name is not None:
            object.__setattr__(
                self,
                "display_name",
                required_string(self.display_name, "display_name"),
            )
        if self.contact_explanation is not None:
            object.__setattr__(
                self,
                "contact_explanation",
                required_string(self.contact_explanation, "contact_explanation"),
            )
        for field_name in ("owner_user_id", "node_id", "public_key"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))
        object.__setattr__(self, "status", required_string(self.status, "status"))
        object.__setattr__(self, "trust_label", required_string(self.trust_label, "trust_label"))
        object.__setattr__(
            self,
            "relationship_posture",
            normalize_relationship_preset(self.relationship_posture).value,
        )
        object.__setattr__(
            self,
            "capabilities",
            tuple(required_string(value, "capability") for value in self.capabilities),
        )
        object.__setattr__(
            self,
            "approval_required_for",
            tuple(
                required_string(value, "approval_required_for")
                for value in self.approval_required_for
            ),
        )
        object.__setattr__(
            self,
            "allowed_use_terms",
            tuple(required_string(value, "allowed_use_term") for value in self.allowed_use_terms),
        )
        object.__setattr__(
            self,
            "protocols",
            tuple(required_string(value, "protocol") for value in self.protocols),
        )
        object.__setattr__(
            self,
            "supported_extension_namespaces",
            tuple(
                required_string(value, "supported_extension_namespace")
                for value in self.supported_extension_namespaces
            ),
        )


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_id: str
    kind: ArtifactKind
    media_type: str
    content_inline: str | None = None
    uri: str | None = None


@dataclass(frozen=True, slots=True)
class MessageRef:
    type: str
    url: str | None = None
    find: str | None = None
    remember_as: str | None = None


@dataclass(frozen=True, slots=True)
class ContentRef:
    content_ref: str
    media_type: str
    byte_length: int
    hash: str
    compression: PayloadCompression = PayloadCompression.NONE
    compressed_byte_length: int | None = None
    compressed_hash: str | None = None
    ttl_expires_at: datetime | None = None
    retention_state: PayloadRetentionState = PayloadRetentionState.READY
    access_scope: PayloadAccessScope = PayloadAccessScope.RECIPIENTS
    fetch_policy_ref: str | None = None
    chunk_manifest_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_ref", required_string(self.content_ref, "content_ref"))
        object.__setattr__(self, "media_type", required_string(self.media_type, "media_type"))
        object.__setattr__(self, "hash", required_string(self.hash, "hash"))
        require_non_negative_int(self.byte_length, "byte_length")
        if self.compressed_byte_length is not None:
            require_non_negative_int(self.compressed_byte_length, "compressed_byte_length")
        if self.compressed_hash is not None:
            object.__setattr__(self, "compressed_hash", required_string(self.compressed_hash, "compressed_hash"))
        if self.fetch_policy_ref is not None:
            object.__setattr__(self, "fetch_policy_ref", required_string(self.fetch_policy_ref, "fetch_policy_ref"))
        if self.chunk_manifest_ref is not None:
            object.__setattr__(
                self,
                "chunk_manifest_ref",
                required_string(self.chunk_manifest_ref, "chunk_manifest_ref"),
            )


@dataclass(frozen=True, slots=True)
class PayloadChunk:
    content_ref: str
    sequence: int
    byte_offset: int
    byte_length: int
    hash: str | None = None
    compressed_byte_length: int | None = None
    compressed_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_ref", required_string(self.content_ref, "content_ref"))
        require_non_negative_int(self.sequence, "sequence")
        require_non_negative_int(self.byte_offset, "byte_offset")
        require_non_negative_int(self.byte_length, "byte_length")
        if self.hash is not None:
            object.__setattr__(self, "hash", required_string(self.hash, "hash"))
        if self.compressed_byte_length is not None:
            require_non_negative_int(self.compressed_byte_length, "compressed_byte_length")
        if self.compressed_hash is not None:
            object.__setattr__(self, "compressed_hash", required_string(self.compressed_hash, "compressed_hash"))


@dataclass(frozen=True, slots=True)
class PayloadManifest:
    manifest_id: str
    payload: ContentRef
    chunks: tuple[PayloadChunk, ...] = ()
    storage_provider: PayloadStorageProvider = PayloadStorageProvider.LOCAL_NODE
    storage_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_id", required_string(self.manifest_id, "manifest_id"))
        if self.storage_ref is not None:
            object.__setattr__(self, "storage_ref", required_string(self.storage_ref, "storage_ref"))


@dataclass(frozen=True, slots=True)
class WorkflowTraceEntry:
    hook: HookType
    runtime: HookRuntime
    action: str = "continue"
    actor: Handle | str | None = None
    changed: tuple[str, ...] = ()
    note: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ActionRequest:
    action_request_id: str
    type: str
    target: str | None = None
    runtime: HookRuntime = HookRuntime.CLOUD
    requires_approval: bool = True
    status: str = "pending"
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Message:
    message_id: str
    thread_id: str
    sender: Handle
    recipients: tuple[Handle, ...]
    intent: MessageIntent | str
    visibility: Visibility
    content: str | None = None
    content_ref: str | None = None
    refs: tuple[MessageRef, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    schema_version: str = "seagull.message.v1"
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent", normalize_message_intent(self.intent))
        if self.content_ref is not None:
            object.__setattr__(
                self,
                "content_ref",
                required_string(self.content_ref, "content_ref"),
            )


@dataclass(frozen=True, slots=True)
class Thread:
    thread_id: str
    root_message_id: str
    participants: frozenset[Handle]
    message_count: int
    last_message_id: str
    last_message_at: datetime
    title: str | None = None


@dataclass(frozen=True, slots=True)
class Delivery:
    delivery_id: str
    message_id: str
    thread_id: str
    sender: Handle
    recipient: Handle
    state: DeliveryState
    current_content: str | None = None
    current_content_ref: str | None = None
    refs: tuple[MessageRef, ...] = ()
    workflow_trace: tuple[WorkflowTraceEntry, ...] = ()
    current_stage: str = "agent.wait"
    action_request: ActionRequest | None = None
    retry_count: int = 0
    last_error: str | None = None
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.current_content_ref is not None:
            object.__setattr__(
                self,
                "current_content_ref",
                required_string(self.current_content_ref, "current_content_ref"),
            )


@dataclass(frozen=True, slots=True)
class ContactExplanation:
    explanation_id: str
    delivery_id: str
    message_id: str
    thread_id: str
    requester: Handle | str
    recipient: Handle | str
    answering_asset: Handle | str
    relationship: RelationshipPreset | str = RelationshipPreset.NEEDS_APPROVAL
    reason: str = "message"
    allowed_reason: str = "Message passed Seagull policy and delivery gates."
    shared_context_summary: str = "No inline context was shared."
    shared_context_refs: tuple[str, ...] = ()
    pending_action: str | None = None
    current_stage: str = "agent.wait"
    policy_refs: tuple[str, ...] = ()
    audit_event_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in (
            "explanation_id",
            "delivery_id",
            "message_id",
            "thread_id",
            "reason",
            "allowed_reason",
            "shared_context_summary",
            "current_stage",
        ):
            object.__setattr__(self, field_name, required_string(getattr(self, field_name), field_name))
        for field_name in ("requester", "recipient", "answering_asset"):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, value if isinstance(value, Handle) else Handle(str(value)))
        object.__setattr__(self, "relationship", normalize_relationship_preset(self.relationship).value)
        if self.pending_action is not None:
            object.__setattr__(
                self,
                "pending_action",
                required_string(self.pending_action, "pending_action"),
            )
        for field_name in ("shared_context_refs", "policy_refs", "audit_event_refs"):
            object.__setattr__(
                self,
                field_name,
                tuple(required_string(value, field_name) for value in getattr(self, field_name)),
            )


def normalize_handle(handle: str) -> str:
    normalized = handle.strip().lower()
    if not HANDLE_RE.fullmatch(normalized):
        raise ProtocolError("handle must look like @agent:server")
    return normalized


def normalize_message_intent(intent: MessageIntent | str) -> MessageIntent | str:
    if isinstance(intent, MessageIntent):
        return intent
    value = required_string(intent, "intent")
    try:
        return MessageIntent(value)
    except ValueError:
        return value


def normalize_relationship_preset(preset: RelationshipPreset | str) -> RelationshipPreset:
    if isinstance(preset, RelationshipPreset):
        return preset
    value = required_string(preset, "relationship_posture")
    try:
        return RelationshipPreset(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in RelationshipPreset)
        raise ProtocolError(f"relationship_posture must be one of: {allowed}") from exc


def relationship_preset_defaults(preset: RelationshipPreset | str) -> RelationshipPresetDefaults:
    return RELATIONSHIP_PRESET_DEFAULTS[normalize_relationship_preset(preset)]


def required_string(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ProtocolError(f"{field_name} is required")
    return stripped


def require_non_negative_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or value < 0:
        raise ProtocolError(f"{field_name} must be a non-negative integer")


__all__ = [
    "ActionRequest",
    "AgentDecision",
    "AgentProfile",
    "Artifact",
    "ArtifactKind",
    "ContactExplanation",
    "ContentRef",
    "DEFAULT_APPROVAL_REQUIRED_FOR",
    "Delivery",
    "DeliveryState",
    "Handle",
    "HookRuntime",
    "HookType",
    "Message",
    "MessageIntent",
    "MessageRef",
    "PayloadAccessScope",
    "PayloadChunk",
    "PayloadCompression",
    "PayloadManifest",
    "PayloadRetentionState",
    "PayloadStorageProvider",
    "ProtocolError",
    "RelationshipPreset",
    "RelationshipPresetDefaults",
    "RoutingRuleMode",
    "Thread",
    "Visibility",
    "WorkflowTraceEntry",
    "normalize_handle",
    "normalize_message_intent",
    "normalize_relationship_preset",
    "relationship_preset_defaults",
]
