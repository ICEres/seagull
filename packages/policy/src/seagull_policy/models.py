from __future__ import annotations

from dataclasses import field
from datetime import datetime, timezone
from enum import Enum

from seagull_policy._compat import dataclass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PolicyScope(str, Enum):
    GLOBAL = "global"
    SERVER = "server"
    ROOM = "room"
    AGENT = "agent"
    USER = "user"


class TrustLabel(str, Enum):
    UNKNOWN = "unknown"
    TRUSTED = "trusted"
    LIMITED = "limited"
    BLOCKED = "blocked"


class RiskLabel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewState(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SafetyAction(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    RATE_LIMIT = "rate_limit"
    QUARANTINE = "quarantine"
    HUMAN_REVIEW = "human_review"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class Policy:
    policy_id: str
    scope: PolicyScope
    name: str
    enabled: bool = True
    description: str | None = None


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    decision_id: str
    action: SafetyAction
    risk: RiskLabel
    review_state: ReviewState = ReviewState.NOT_REQUIRED
    reasons: tuple[str, ...] = ()
    policy_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    @property
    def deliverable(self) -> bool:
        return self.action in {
            SafetyAction.ALLOW,
            SafetyAction.ALLOW_WITH_WARNING,
        }


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    subject_id: str
    actor_id: str
    scope: PolicyScope
    granted: bool
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    rule_id: str
    scope: PolicyScope
    max_events: int
    window_seconds: int
    action: SafetyAction = SafetyAction.RATE_LIMIT


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    actor_id: str
    action: SafetyAction
    target_id: str | None = None
    risk: RiskLabel | None = None
    policy_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
