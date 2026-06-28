from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


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


class TaskState(str, Enum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    RUNNING = "running"
    NEEDS_APPROVAL = "needs_approval"
    RESULT_READY = "result_ready"
    COMPLETED = "completed"
    REFUSED = "refused"
    FAILED = "failed"


class StreamEventType(str, Enum):
    STARTED = "stream.started"
    DELTA = "stream.delta"
    CHECKPOINT = "stream.checkpoint"
    COMPLETED = "stream.completed"
    FAILED = "stream.failed"


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
    protocols: tuple[str, ...] = ("seagull",)
    status: str = "active"


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
    ttl_expires_at: datetime | None = None
    retention_state: PayloadRetentionState = PayloadRetentionState.READY
    access_scope: PayloadAccessScope = PayloadAccessScope.RECIPIENTS
    chunk_manifest_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_ref", required_string(self.content_ref, "content_ref"))
        object.__setattr__(self, "media_type", required_string(self.media_type, "media_type"))
        object.__setattr__(self, "hash", required_string(self.hash, "hash"))
        require_non_negative_int(self.byte_length, "byte_length")
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_ref", required_string(self.content_ref, "content_ref"))
        require_non_negative_int(self.sequence, "sequence")
        require_non_negative_int(self.byte_offset, "byte_offset")
        require_non_negative_int(self.byte_length, "byte_length")
        if self.hash is not None:
            object.__setattr__(self, "hash", required_string(self.hash, "hash"))


@dataclass(frozen=True, slots=True)
class PayloadManifest:
    manifest_id: str
    payload: ContentRef
    chunks: tuple[PayloadChunk, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_id", required_string(self.manifest_id, "manifest_id"))


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
    intent: MessageIntent
    visibility: Visibility
    content: str | None = None
    content_ref: str | None = None
    refs: tuple[MessageRef, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    schema_version: str = "seagull.message.v1"
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.content_ref is not None:
            object.__setattr__(self, "content_ref", required_string(self.content_ref, "content_ref"))


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
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context_pack_id", required_string(self.context_pack_id, "context_pack_id"))
        object.__setattr__(self, "thread_id", required_string(self.thread_id, "thread_id"))
        if self.summary_ref is not None:
            object.__setattr__(self, "summary_ref", required_string(self.summary_ref, "summary_ref"))


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


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    responder: Handle
    state: TaskState
    result_message_id: str | None = None
    content: str | None = None
    content_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
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


@dataclass(frozen=True, slots=True)
class StreamEvent:
    stream_id: str
    sequence: int
    event_type: StreamEventType
    task_id: str | None = None
    resume_after: int | None = None
    final_message_id: str | None = None
    content_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_id", required_string(self.stream_id, "stream_id"))
        require_non_negative_int(self.sequence, "sequence")
        if self.resume_after is not None:
            require_non_negative_int(self.resume_after, "resume_after")
        for field_name in ("task_id", "final_message_id", "content_ref"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))


def normalize_handle(handle: str) -> str:
    normalized = handle.strip().lower()
    if not HANDLE_RE.fullmatch(normalized):
        raise ProtocolError("handle must look like @agent:server")
    return normalized


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
