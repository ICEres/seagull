from __future__ import annotations

from dataclasses import field
from datetime import datetime
from enum import Enum

from dataclasses import dataclass
from seagull_protocol.base import (
    Handle,
    ProtocolError,
    required_string,
    require_non_negative_int,
    utc_now,
)


class StreamEventType(str, Enum):
    STARTED = "stream.started"
    DELTA = "stream.delta"
    CHECKPOINT = "stream.checkpoint"
    COMPLETED = "stream.completed"
    FAILED = "stream.failed"


class LiveSessionState(str, Enum):
    """Lifecycle of an optional real-time session.

    ``DEGRADED`` is the state that makes Live optional in practice: a
    participant dropped, so delivery has fallen back to the durable Inbox. The
    session stays addressable so a reconnecting participant can resume from
    durable state rather than starting a new conversation.
    """

    PENDING = "pending"
    ACTIVE = "active"
    DEGRADED = "degraded"
    CLOSED = "closed"


class LiveSubjectType(str, Enum):
    THREAD = "thread"
    TASK = "task"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    stream_id: str
    sequence: int
    event_type: StreamEventType | str
    subject_type: str
    subject_id: str
    resume_after: int | None = None
    final_message_id: str | None = None
    content_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_id", required_string(self.stream_id, "stream_id"))
        object.__setattr__(self, "event_type", normalize_stream_event_type(self.event_type))
        object.__setattr__(self, "subject_type", required_string(self.subject_type, "subject_type"))
        object.__setattr__(self, "subject_id", required_string(self.subject_id, "subject_id"))
        require_non_negative_int(self.sequence, "sequence")
        if self.resume_after is not None:
            require_non_negative_int(self.resume_after, "resume_after")
        for field_name in ("final_message_id", "content_ref"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))


@dataclass(frozen=True, slots=True)
class LiveSession:
    """An optional real-time projection of a thread or task.

    A Live session carries no content of its own. Meaningful messages,
    decisions, task state, artifacts, and results stay durable gulls records
    (see ``packages/gulls/docs/concept.md``); this type only tracks who is
    live, how far the real-time stream has advanced, and where a reconnecting
    participant should resume.

    ``delivered_sequence`` is the high-water mark that *is* durable. On
    fallback, ``resume_point()`` yields the sequence a participant should
    resume after, so a dropped connection replays from the Inbox instead of
    losing the tail of the conversation.
    """

    live_session_id: str
    subject_type: LiveSubjectType | str
    subject_id: str
    participants: tuple[Handle, ...] = ()
    state: LiveSessionState | str = LiveSessionState.PENDING
    stream_id: str | None = None
    delivered_sequence: int = 0
    resume_after: int | None = None
    fallback_thread_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "live_session_id",
            required_string(self.live_session_id, "live_session_id"),
        )
        object.__setattr__(self, "subject_id", required_string(self.subject_id, "subject_id"))
        object.__setattr__(self, "subject_type", normalize_live_subject_type(self.subject_type))
        object.__setattr__(self, "state", normalize_live_session_state(self.state))
        require_non_negative_int(self.delivered_sequence, "delivered_sequence")
        if self.resume_after is not None:
            require_non_negative_int(self.resume_after, "resume_after")
        for field_name in ("stream_id", "fallback_thread_id"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, required_string(value, field_name))
        object.__setattr__(
            self,
            "participants",
            tuple(
                value if isinstance(value, Handle) else Handle(str(value))
                for value in self.participants
            ),
        )

    @property
    def is_live(self) -> bool:
        return self.state == LiveSessionState.ACTIVE

    def resume_point(self) -> int:
        """Sequence a reconnecting participant should resume after."""
        if self.resume_after is not None:
            return self.resume_after
        return self.delivered_sequence

    def includes(self, handle: Handle | str) -> bool:
        value = handle if isinstance(handle, Handle) else Handle(str(handle))
        return value in self.participants


def normalize_stream_event_type(event_type: StreamEventType | str) -> StreamEventType | str:
    if isinstance(event_type, StreamEventType):
        return event_type
    value = required_string(event_type, "event_type")
    try:
        return StreamEventType(value)
    except ValueError:
        return value


def normalize_live_session_state(state: LiveSessionState | str) -> LiveSessionState:
    if isinstance(state, LiveSessionState):
        return state
    value = required_string(state, "state").lower()
    try:
        return LiveSessionState(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in LiveSessionState)
        raise ProtocolError(f"state must be one of: {allowed}") from exc


def normalize_live_subject_type(subject_type: LiveSubjectType | str) -> LiveSubjectType:
    if isinstance(subject_type, LiveSubjectType):
        return subject_type
    value = required_string(subject_type, "subject_type").lower()
    try:
        return LiveSubjectType(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in LiveSubjectType)
        raise ProtocolError(f"subject_type must be one of: {allowed}") from exc


__all__ = [
    "LiveSession",
    "LiveSessionState",
    "LiveSubjectType",
    "StreamEvent",
    "StreamEventType",
    "normalize_live_session_state",
    "normalize_live_subject_type",
    "normalize_stream_event_type",
]
