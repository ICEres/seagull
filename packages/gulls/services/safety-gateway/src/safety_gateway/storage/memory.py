from __future__ import annotations

from datetime import datetime

from safety_gateway.domain.models import SafetyAuditRecord


class InMemorySafetyAuditRepository:
    def __init__(self) -> None:
        self._records: list[SafetyAuditRecord] = []

    def append(self, record: SafetyAuditRecord) -> None:
        self._records.append(record)

    def list_recent(
        self,
        *,
        actor_id: str | None = None,
        limit: int = 50,
    ) -> tuple[SafetyAuditRecord, ...]:
        records = reversed(self._records)
        if actor_id is not None:
            records = (record for record in records if record.actor_id == actor_id)
        return tuple(list(records)[:limit])

    def count_recent(self, *, actor_id: str, action_type: str, since: datetime) -> int:
        return sum(
            1
            for record in self._records
            if record.actor_id == actor_id
            and record.action_type == action_type
            and record.created_at >= since
        )
