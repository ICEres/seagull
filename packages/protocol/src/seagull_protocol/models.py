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
    refs: tuple[MessageRef, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    schema_version: str = "seagull.message.v1"
    created_at: datetime = field(default_factory=utc_now)


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
    refs: tuple[MessageRef, ...] = ()
    workflow_trace: tuple[WorkflowTraceEntry, ...] = ()
    current_stage: str = "agent.wait"
    action_request: ActionRequest | None = None
    retry_count: int = 0
    last_error: str | None = None
    updated_at: datetime = field(default_factory=utc_now)


def normalize_handle(handle: str) -> str:
    normalized = handle.strip().lower()
    if not HANDLE_RE.fullmatch(normalized):
        raise ProtocolError("handle must look like @agent:server")
    return normalized
