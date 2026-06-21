from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from seagull_policy import ReviewState, RiskLabel, SafetyAction, SafetyDecision, TrustLabel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


EMPTY_METADATA: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class SafetyEvaluationRequest:
    actor_id: str
    action_type: str = "message.send"
    content: str | None = None
    content_ref: str | None = None
    target_ids: tuple[str, ...] = ()
    intent: str = "message"
    visibility: str = "direct"
    thread_id: str | None = None
    message_id: str | None = None
    trace_id: str | None = None
    trust_label: TrustLabel = TrustLabel.UNKNOWN
    thread_depth: int = 0
    repeated_reply_count: int = 0
    metadata: Mapping[str, str] = field(default=EMPTY_METADATA)


@dataclass(frozen=True, slots=True)
class SafetyFlag:
    label: str
    risk: RiskLabel
    reason: str
    policy_id: str


@dataclass(frozen=True, slots=True)
class SafetyAuditRecord:
    audit_id: str
    decision_id: str
    actor_id: str
    action: SafetyAction
    risk: RiskLabel
    target_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    policy_ids: tuple[str, ...] = ()
    flags: tuple[SafetyFlag, ...] = ()
    message_id: str | None = None
    thread_id: str | None = None
    trace_id: str | None = None
    review_state: ReviewState = ReviewState.NOT_REQUIRED
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class SafetyEvaluationResult:
    decision: SafetyDecision
    audit_record: SafetyAuditRecord
    flags: tuple[SafetyFlag, ...] = ()
