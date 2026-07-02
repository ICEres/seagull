from __future__ import annotations

from datetime import datetime
from typing import Any

from safety_gateway._compat import dataclass
from safety_gateway.api.evaluation_request import evaluation_request_from_body

from safety_gateway.domain import (
    SafetyAuditRecord,
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
            request = evaluation_request_from_body(body)
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


def datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
