from __future__ import annotations

from datetime import datetime
from typing import Any

from seagull_policy import TrustLabel
from safety_gateway._compat import dataclass

from safety_gateway.domain import (
    SafetyAuditRecord,
    SafetyEvaluationRequest,
    SafetyEvaluationResult,
    SafetyFlag,
    SafetyGatewayService,
)
from safety_gateway.storage import InMemorySafetyAuditRepository


@dataclass(frozen=True, slots=True)
class ApiError(Exception):
    status_code: int
    error: str
    message: str


class LocalSafetyGatewayApi:
    """Dependency-free local API adapter for Phase 2 safety evaluation."""

    def __init__(self, service: SafetyGatewayService, audit_repository: InMemorySafetyAuditRepository) -> None:
        self._service = service
        self._audit_repository = audit_repository

    @classmethod
    def in_memory(cls) -> LocalSafetyGatewayApi:
        audit_repository = InMemorySafetyAuditRepository()
        return cls(SafetyGatewayService(audit_repository), audit_repository)

    def health(self) -> dict[str, Any]:
        return {"ok": True, "app": "safety-gateway", "storage": "memory"}

    def evaluate(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            request = SafetyEvaluationRequest(
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
            return evaluation_result_to_dict(self._service.evaluate(request))
        except ValueError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

    def list_audit_events(self, *, actor_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        return {
            "items": [
                audit_record_to_dict(record)
                for record in self._audit_repository.list_recent(actor_id=actor_id, limit=limit)
            ]
        }


def evaluation_result_to_dict(result: SafetyEvaluationResult) -> dict[str, Any]:
    return {
        "decision": {
            "decision_id": result.decision.decision_id,
            "action": result.decision.action.value,
            "risk": result.decision.risk.value,
            "review_state": result.decision.review_state.value,
            "deliverable": result.decision.deliverable,
            "reasons": list(result.decision.reasons),
            "policy_ids": list(result.decision.policy_ids),
            "created_at": datetime_to_string(result.decision.created_at),
        },
        "flags": [flag_to_dict(flag) for flag in result.flags],
        "audit": audit_record_to_dict(result.audit_record),
    }


def audit_record_to_dict(record: SafetyAuditRecord) -> dict[str, Any]:
    return {
        "audit_id": record.audit_id,
        "decision_id": record.decision_id,
        "actor_id": record.actor_id,
        "action_type": record.action_type,
        "action": record.action.value,
        "risk": record.risk.value,
        "review_state": record.review_state.value,
        "target_ids": list(record.target_ids),
        "reasons": list(record.reasons),
        "policy_ids": list(record.policy_ids),
        "flags": [flag_to_dict(flag) for flag in record.flags],
        "message_id": record.message_id,
        "thread_id": record.thread_id,
        "trace_id": record.trace_id,
        "created_at": datetime_to_string(record.created_at),
    }


def flag_to_dict(flag: SafetyFlag) -> dict[str, Any]:
    return {
        "label": flag.label,
        "risk": flag.risk.value,
        "reason": flag.reason,
        "policy_id": flag.policy_id,
    }


def required_string(body: dict[str, Any], field_name: str) -> str:
    value = optional_string(body, field_name)
    if value is None:
        raise ApiError(400, "bad_request", f"{field_name} is required")
    return value


def optional_string(body: dict[str, Any], field_name: str) -> str | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, "bad_request", f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None


def string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ApiError(400, "bad_request", f"{field_name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ApiError(400, "bad_request", f"{field_name} must contain only strings")
    return tuple(item.strip() for item in value if item.strip())


def string_map(value: Any, field_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ApiError(400, "bad_request", f"{field_name} must be an object")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise ApiError(400, "bad_request", f"{field_name} must contain string keys and values")
    return {key: item for key, item in value.items()}


def optional_int(body: dict[str, Any], field_name: str, *, default: int) -> int:
    value = body.get(field_name)
    if value is None:
        return default
    if not isinstance(value, int):
        raise ApiError(400, "bad_request", f"{field_name} must be an integer")
    return value


def trust_label(value: Any) -> TrustLabel:
    if value is None:
        return TrustLabel.UNKNOWN
    if not isinstance(value, str):
        raise ApiError(400, "bad_request", "trust_label must be a string")
    try:
        return TrustLabel(value)
    except ValueError as exc:
        raise ApiError(400, "bad_request", f"unsupported trust_label: {value}") from exc


def datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
