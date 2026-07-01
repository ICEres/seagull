from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, Sequence

from seagull_sdk._compat import dataclass


DEFAULT_INLINE_CHAR_LIMIT = 4000
DEFAULT_PAYLOAD_MEDIA_TYPE = "text/plain; charset=utf-8"
DEFAULT_PAYLOAD_ACCESS_SCOPE = "recipients"


class PayloadMessageClient(Protocol):
    def create_payload(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a payload and return a response containing content_ref."""

    def create_message(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a message using inline content or content_ref."""


class SendMessageClientAdapter:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create_payload(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._client.create_payload(
            content=body["content"],
            media_type=body.get("media_type", DEFAULT_PAYLOAD_MEDIA_TYPE),
            access_scope=body.get("access_scope", DEFAULT_PAYLOAD_ACCESS_SCOPE),
            ttl_expires_at=body.get("ttl_expires_at"),
        )

    def create_message(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._client.send_message(
            sender_handle=body["sender_handle"],
            recipient_handles=tuple(body["recipient_handles"]),
            content=body.get("content"),
            content_ref=body.get("content_ref"),
            refs=tuple(body.get("refs", ())),
            thread_id=body.get("thread_id"),
            intent=body.get("intent", "message"),
            visibility=body.get("visibility", "direct"),
            idempotency_key=body.get("idempotency_key"),
        )


@dataclass(frozen=True, slots=True)
class AutoPayloadMessageResult:
    response: dict[str, Any]
    payload: dict[str, Any] | None = None

    @property
    def content_ref(self) -> str | None:
        if self.payload is not None:
            return require_content_ref(self.payload)
        message = self.response.get("message")
        if isinstance(message, dict):
            value = message.get("content_ref")
            if isinstance(value, str) and value.strip():
                return value
        return None

    @property
    def payload_manifest(self) -> dict[str, Any] | None:
        if self.payload is None:
            return None
        value = self.payload.get("payload")
        if not isinstance(value, dict):
            raise ValueError("payload response must include payload metadata")
        return value


def send_message_with_auto_payload(
    client: PayloadMessageClient,
    *,
    sender_handle: str,
    recipient_handles: Sequence[str],
    content: str | None = None,
    content_ref: str | None = None,
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
    normalized_content_ref = normalize_optional_string(content_ref)
    if content is None and normalized_content_ref is None:
        raise ValueError("content or content_ref is required")

    body = without_none({
        "sender_handle": sender_handle,
        "recipient_handles": list(recipient_handles),
        "content_ref": normalized_content_ref,
        "refs": list(refs),
        "intent": intent,
        "visibility": visibility,
        "thread_id": thread_id,
        "idempotency_key": idempotency_key,
    })

    if normalized_content_ref is not None:
        return AutoPayloadMessageResult(response=client.create_message(body))

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


def normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
