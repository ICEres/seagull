from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import TestCase


class FakeKey:
    def __init__(self, name: str) -> None:
        self.name = name

    def eq(self, value: object) -> tuple[str, str, object]:
        return ("eq", self.name, value)


fake_dynamodb = types.ModuleType("boto3.dynamodb")
fake_conditions = types.ModuleType("boto3.dynamodb.conditions")
fake_conditions.Key = FakeKey
sys.modules.setdefault("boto3", types.ModuleType("boto3"))
sys.modules.setdefault("boto3.dynamodb", fake_dynamodb)
sys.modules.setdefault("boto3.dynamodb.conditions", fake_conditions)

from seagull_policy import ReviewState, RiskLabel, SafetyAction

from safety_gateway.domain.models import SafetyAuditRecord
from safety_gateway.storage.dynamodb import DynamoDbSafetyAuditRepository


class PaginatingFakeTable:
    """Minimal fake that returns one item per scan page, exercising pagination."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def put_item(self, *, Item: dict[str, Any]) -> None:
        self.items.append(Item)

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        start = int(kwargs.get("ExclusiveStartKey", {}).get("index", -1)) + 1 if "ExclusiveStartKey" in kwargs else 0
        if start >= len(self.items):
            return {"Items": []}
        page = [self.items[start]]
        response: dict[str, Any] = {"Items": page}
        if start + 1 < len(self.items):
            response["LastEvaluatedKey"] = {"index": start}
        return response


def _record(audit_id: str, created_at: datetime) -> SafetyAuditRecord:
    return SafetyAuditRecord(
        audit_id=audit_id,
        decision_id=f"decision_{audit_id}",
        actor_id="agent_1",
        action_type="message.send",
        action=SafetyAction.ALLOW,
        risk=RiskLabel.LOW,
        target_ids=(),
        reasons=(),
        policy_ids=(),
        flags=(),
        review_state=ReviewState.NOT_REQUIRED,
        created_at=created_at,
    )


class DynamoDbSafetyAuditRepositoryTest(TestCase):
    def test_list_recent_returns_globally_newest_across_scan_pages(self) -> None:
        table = PaginatingFakeTable()
        repo = DynamoDbSafetyAuditRepository(table)
        base = datetime(2026, 7, 1, tzinfo=timezone.utc)

        # Insert in scrambled time order so an arbitrary first scan page is not the newest.
        order = [3, 0, 9, 1, 7, 2, 8, 4, 6, 5]
        for i in order:
            repo.append(_record(f"audit_{i}", base + timedelta(minutes=i)))

        recent = repo.list_recent(limit=3)
        got = [record.audit_id for record in recent]
        # The three genuinely newest records, newest first — not an arbitrary page.
        self.assertEqual(["audit_9", "audit_8", "audit_7"], got)
