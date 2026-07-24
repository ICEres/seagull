from __future__ import annotations

from dataclasses import field
from datetime import datetime
from enum import Enum

from dataclasses import dataclass
from seagull_protocol.base import required_string, require_non_negative_int, utc_now


class StreamEventType(str, Enum):
    STARTED = "stream.started"
    DELTA = "stream.delta"
    CHECKPOINT = "stream.checkpoint"
    COMPLETED = "stream.completed"
    FAILED = "stream.failed"


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


def normalize_stream_event_type(event_type: StreamEventType | str) -> StreamEventType | str:
    if isinstance(event_type, StreamEventType):
        return event_type
    value = required_string(event_type, "event_type")
    try:
        return StreamEventType(value)
    except ValueError:
        return value


__all__ = [
    "StreamEvent",
    "StreamEventType",
    "normalize_stream_event_type",
]
