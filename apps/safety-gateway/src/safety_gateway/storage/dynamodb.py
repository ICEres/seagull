from __future__ import annotations

from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key
from seagull_policy import ReviewState, RiskLabel, SafetyAction

from safety_gateway.domain.models import SafetyAuditRecord, SafetyFlag


class DynamoDbSafetyAuditRepository:
    def __init__(self, table: Any) -> None:
        self._table = table

    def append(self, record: SafetyAuditRecord) -> None:
        self._table.put_item(Item=audit_record_to_item(record))

    def list_recent(
        self,
        *,
        actor_id: str | None = None,
        limit: int = 50,
    ) -> tuple[SafetyAuditRecord, ...]:
        if actor_id is not None:
            result = self._table.query(
                IndexName="actor-created-at-index",
                KeyConditionExpression=Key("actor_id").eq(actor_id),
                ScanIndexForward=False,
                Limit=limit,
            )
            items = result.get("Items", [])
        else:
            result = self._table.scan(Limit=limit)
            items = sorted(result.get("Items", []), key=lambda item: item.get("created_at", ""), reverse=True)

        return tuple(item_to_audit_record(item) for item in items[:limit])

    def count_recent(self, *, actor_id: str, action_type: str, since: datetime) -> int:
        result = self._table.query(
            IndexName="actor-created-at-index",
            KeyConditionExpression=Key("actor_id").eq(actor_id) & Key("created_at").gte(since.isoformat()),
        )
        return sum(
            1
            for item in result.get("Items", [])
            if item.get("action_type", "message.send") == action_type
        )


def audit_record_to_item(record: SafetyAuditRecord) -> dict[str, Any]:
    return without_none(
        {
            "audit_id": record.audit_id,
            "decision_id": record.decision_id,
            "actor_id": record.actor_id,
            "action_type": record.action_type,
            "action": record.action.value,
            "risk": record.risk.value,
            "target_ids": list(record.target_ids),
            "reasons": list(record.reasons),
            "policy_ids": list(record.policy_ids),
            "flags": [flag_to_item(flag) for flag in record.flags],
            "message_id": record.message_id,
            "thread_id": record.thread_id,
            "trace_id": record.trace_id,
            "review_state": record.review_state.value,
            "created_at": record.created_at.isoformat(),
        }
    )


def item_to_audit_record(item: dict[str, Any]) -> SafetyAuditRecord:
    return SafetyAuditRecord(
        audit_id=item["audit_id"],
        decision_id=item["decision_id"],
        actor_id=item["actor_id"],
        action_type=item.get("action_type", "message.send"),
        action=SafetyAction(item["action"]),
        risk=RiskLabel(item["risk"]),
        target_ids=tuple(item.get("target_ids", [])),
        reasons=tuple(item.get("reasons", [])),
        policy_ids=tuple(item.get("policy_ids", [])),
        flags=tuple(item_to_flag(flag) for flag in item.get("flags", [])),
        message_id=item.get("message_id"),
        thread_id=item.get("thread_id"),
        trace_id=item.get("trace_id"),
        review_state=ReviewState(item.get("review_state", ReviewState.NOT_REQUIRED.value)),
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def flag_to_item(flag: SafetyFlag) -> dict[str, str]:
    return {
        "label": flag.label,
        "risk": flag.risk.value,
        "reason": flag.reason,
        "policy_id": flag.policy_id,
    }


def item_to_flag(item: dict[str, str]) -> SafetyFlag:
    return SafetyFlag(
        label=item["label"],
        risk=RiskLabel(item["risk"]),
        reason=item["reason"],
        policy_id=item["policy_id"],
    )


def without_none(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}
