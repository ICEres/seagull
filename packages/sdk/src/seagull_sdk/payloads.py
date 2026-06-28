from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, Sequence


DEFAULT_INLINE_CHAR_LIMIT = 4000
DEFAULT_PAYLOAD_MEDIA_TYPE = "text/plain; charset=utf-8"
DEFAULT_PAYLOAD_ACCESS_SCOPE = "recipients"


class PayloadMessageClient(Protocol):
    def create_payload(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a payload and return a response containing content_ref."""

    def create_message(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a message using inline content or content_ref."""


@dataclass(frozen=True, slots=True)
class AutoPayloadMessageResult:
    response: dict[str, Any]
    payload: dict[str, Any] | None = None


def send_message_with_auto_payload(
    client: PayloadMessageClient,
    *,
    sender_handle: str,
    recipient_handles: Sequence[str],
    content: str,
    media_type: str = DEFAULT_PAYLOAD_MEDIA_TYPE,
    access_scope: str = DEFAULT_PAYLOAD_ACCESS_SCOPE,
    inline_char_limit: int = DEFAULT_INLINE_CHAR_LIMIT,
    refs: Sequence[dict[str, Any]] = (),
    intent: str = "message",
    visibility: str = "direct",
    thread_id: str | None = None,
    idempotency_key: str | None = None,
    ttl_expires_at: datetime | str | None = None,
) -> AutoPayloadMessageResult:
    if inline_char_limit < 0:
        raise ValueError("inline_char_limit must be non-negative")

    body = without_none({
        "sender_handle": sender_handle,
        "recipient_handles": list(recipient_handles),
        "refs": list(refs),
        "intent": intent,
        "visibility": visibility,
        "thread_id": thread_id,
        "idempotency_key": idempotency_key,
    })

    if len(content) <= inline_char_limit:
        body["content"] = content
        return AutoPayloadMessageResult(response=client.create_message(body))

    payload_body = without_none({
        "content": content,
        "media_type": media_type,
        "access_scope": access_scope,
        "ttl_expires_at": datetime_to_string(ttl_expires_at),
    })
    payload = client.create_payload(payload_body)
    content_ref = require_content_ref(payload)
    body["content_ref"] = content_ref
    return AutoPayloadMessageResult(response=client.create_message(body), payload=payload)


def require_content_ref(payload: dict[str, Any]) -> str:
    value = payload.get("content_ref")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("payload response must include content_ref")
    return value


def datetime_to_string(value: datetime | str | None) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
