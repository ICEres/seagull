"""Public agent cards: the one sanitized public representation of an agent.

Every agent handle maps to a public URL resource (``/agents/{handle}``), and
``agent_card`` is the single place that decides what that resource exposes.
Both the local api (``LocalMessageHubApi.read_agent``) and the deployed
Lambda adapter serve public profiles through this module, so there is exactly
one sanitizer: private wiring (webhook URLs, token material, tool/MCP
endpoints, credentials) can never leak from a second, drifting copy.

The module also owns the public-URL companions of the card:

* path builders for the card, message-status, and thread resources, and
* ``sender_visible_status``, the coarse delivery-status view a message sender
  is allowed to observe.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from message_hub.domain.models import Agent, DeliveryStatus

# Substrings that mark a profile value as private wiring rather than public
# capability metadata. Matched case-insensitively anywhere in the value.
PRIVATE_PROFILE_MARKERS = (
    "mcp://",
    "file://",
    "localhost",
    "127.0.0.1",
    "::1",
    ".sock",
    "tool://",
    "raw_tool",
    "raw-tool",
    "tool_handle",
    "tool-handle",
    "mcp_server",
    "mcp-server",
    "credential",
    "credentials",
    "secret",
    "token",
    "api_key",
    "apikey",
    "password",
    "authorization",
    "bearer ",
)


def agent_card(agent: Agent) -> dict[str, Any]:
    """Build the sanitized public card for an agent.

    This is byte-identical to the historical ``GET /agents/{handle}`` profile:
    it never includes ``webhook_url``, token data, or raw ``response_rules``
    internals — capabilities and response rules pass through the private
    marker filter, and the webhook is reduced to an enabled flag.
    """
    return {
        "agent_id": agent.agent_id,
        "handle": agent.handle,
        "display_name": agent.display_name,
        "capabilities": public_capabilities(agent.capabilities),
        "response_rules": public_response_rules(agent.response_rules),
        "status": agent.status,
        "trigger_mode": agent.trigger_mode,
        "webhook_enabled": agent.trigger_mode == "webhook" and agent.webhook_url is not None,
        "created_at": _datetime_to_string(agent.created_at),
        "updated_at": _datetime_to_string(agent.updated_at),
    }


def public_capabilities(capabilities: tuple[str, ...]) -> list[str]:
    return [capability for capability in capabilities if not has_private_profile_marker(capability)]


def public_response_rules(response_rules: dict[str, Any] | None) -> dict[str, Any] | None:
    sanitized = sanitize_public_profile_value(response_rules)
    return sanitized if isinstance(sanitized, dict) else None


def sanitize_public_profile_value(value: Any) -> Any:
    if isinstance(value, str):
        return None if has_private_profile_marker(value) else value
    if isinstance(value, (list, tuple)):
        sanitized_items = []
        for item in value:
            sanitized = sanitize_public_profile_value(item)
            if sanitized is not None:
                sanitized_items.append(sanitized)
        return sanitized_items
    if isinstance(value, dict):
        sanitized_dict: dict[str, Any] = {}
        for key, item in value.items():
            if has_private_profile_marker(str(key)):
                continue
            sanitized = sanitize_public_profile_value(item)
            if sanitized is not None:
                sanitized_dict[str(key)] = sanitized
        return sanitized_dict
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return None


def has_private_profile_marker(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in PRIVATE_PROFILE_MARKERS)


# ---------------------------------------------------------------------------
# Public URL paths


def agent_public_path(handle: str) -> str:
    """Path of an agent's public card, with the canonical handle URL-encoded."""
    return f"/agents/{quote(handle, safe='')}"


def message_status_path(handle: str, delivery_id: str) -> str:
    """Sender-visible status path for a message posted to an agent's URL."""
    return f"{agent_public_path(handle)}/messages/{quote(delivery_id, safe='')}"


def thread_path(thread_id: str) -> str:
    return f"/threads/{quote(thread_id, safe='')}"


# ---------------------------------------------------------------------------
# Sender-visible delivery status

# Coarse view of a delivery's lifecycle for the message SENDER. Recipient
# decisions must not leak: ``ignored`` (and other post-delivery outcomes the
# recipient did not choose to surface) all read as ``delivered``; a reply is
# observable anyway, so ``replied`` stays distinct. Review holds collapse to
# ``quarantined`` without exposing which gate held them.
SENDER_VISIBLE_DELIVERY_STATUS: dict[str, str] = {
    DeliveryStatus.QUEUED.value: "accepted",
    DeliveryStatus.NEEDS_REVIEW.value: "quarantined",
    DeliveryStatus.PENDING_ACTION.value: "quarantined",
    DeliveryStatus.DELIVERED.value: "delivered",
    DeliveryStatus.READ.value: "delivered",
    DeliveryStatus.ACKED.value: "delivered",
    DeliveryStatus.IGNORED.value: "delivered",
    DeliveryStatus.REPLIED.value: "replied",
    DeliveryStatus.FAILED.value: "blocked",
}


def sender_visible_status(status: DeliveryStatus | str) -> str:
    value = status.value if isinstance(status, DeliveryStatus) else str(status)
    try:
        return SENDER_VISIBLE_DELIVERY_STATUS[value]
    except KeyError:
        raise ValueError(f"delivery status has no sender-visible mapping: {value}") from None


def _datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
