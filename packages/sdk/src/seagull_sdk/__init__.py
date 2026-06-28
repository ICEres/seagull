"""Dependency-free Seagull SDK helpers."""

from seagull_sdk.payloads import (
    DEFAULT_INLINE_CHAR_LIMIT,
    AutoPayloadMessageResult,
    PayloadMessageClient,
    send_message_with_auto_payload,
)

__all__ = [
    "AutoPayloadMessageResult",
    "DEFAULT_INLINE_CHAR_LIMIT",
    "PayloadMessageClient",
    "send_message_with_auto_payload",
]
