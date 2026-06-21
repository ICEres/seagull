from __future__ import annotations

from typing import Protocol

from safety_gateway.domain.models import SafetyAuditRecord


class SafetyAuditRepository(Protocol):
    def append(self, record: SafetyAuditRecord) -> None:
        """Persist a safety decision audit record."""

    def list_recent(
        self,
        *,
        actor_id: str | None = None,
        limit: int = 50,
    ) -> tuple[SafetyAuditRecord, ...]:
        """Return recent audit records, newest first."""
