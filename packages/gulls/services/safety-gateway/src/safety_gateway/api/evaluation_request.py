from __future__ import annotations

from typing import Any

from seagull_policy import TrustLabel

from safety_gateway.domain import SafetyEvaluationRequest


def evaluation_request_from_body(body: dict[str, Any]) -> SafetyEvaluationRequest:
    return SafetyEvaluationRequest(
        actor_id=required_string(body, "actor_id"),
        action_type=optional_string(body, "action_type") or "message.send",
        content=optional_string(body, "content"),
        content_ref=optional_string(body, "content_ref"),
        target_ids=string_list(body.get("target_ids", ()), "target_ids"),
        intent=optional_string(body, "intent") or "message",
        visibility=optional_string(body, "visibility") or "direct",
        thread_id=optional_string(body, "thread_id"),
        message_id=optional_string(body, "message_id"),
        trace_id=optional_string(body, "trace_id"),
        trust_label=trust_label(body.get("trust_label")),
        thread_depth=optional_int(body, "thread_depth", default=0),
        repeated_reply_count=optional_int(body, "repeated_reply_count", default=0),
        metadata=string_map(body.get("metadata", {}), "metadata"),
    )


def required_string(body: dict[str, Any], field_name: str) -> str:
    value = optional_string(body, field_name)
    if value is None:
        raise ValueError(f"{field_name} is required")
    return value


def optional_string(body: dict[str, Any], field_name: str) -> str | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None


def string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must contain only strings")
    return tuple(item.strip() for item in value if item.strip())


def string_map(value: Any, field_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise ValueError(f"{field_name} must contain string keys and values")
    return {key: item for key, item in value.items()}


def optional_int(body: dict[str, Any], field_name: str, *, default: int) -> int:
    value = body.get(field_name)
    if value is None:
        return default
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def trust_label(value: Any) -> TrustLabel:
    if value is None:
        return TrustLabel.UNKNOWN
    if not isinstance(value, str):
        raise ValueError("trust_label must be a string")
    try:
        return TrustLabel(value)
    except ValueError as exc:
        raise ValueError(f"unsupported trust_label: {value}") from exc
