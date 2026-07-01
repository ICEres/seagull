from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from message_hub._compat import dataclass
from message_hub.domain.models import Agent
from seagull_policy import RiskLabel, SafetyAction, SafetyDecision


class SafetyBlockedError(Exception):
    """Raised when local safety policy blocks a message before delivery."""


@dataclass(frozen=True, slots=True)
class SafetyCheckRequest:
    sender: Agent
    recipients: tuple[Agent, ...]
    content: str | None
    content_ref: str | None
    intent: str
    visibility: str
    thread_id: str | None = None


class SafetyEvaluator(Protocol):
    def evaluate_send(self, request: SafetyCheckRequest) -> SafetyDecision:
        """Return a safety decision for a send request."""


class LocalSafetyEvaluator:
    """Small Phase 1 safety gate for local development and tests."""

    def __init__(self, blocked_terms: Sequence[str] = ("unsafe:",)) -> None:
        self._blocked_terms = tuple(term.strip().lower() for term in blocked_terms if term.strip())

    def evaluate_send(self, request: SafetyCheckRequest) -> SafetyDecision:
        content = (request.content or "").lower()
        matched_terms = tuple(term for term in self._blocked_terms if term in content)
        if matched_terms:
            return SafetyDecision(
                decision_id="local_safety_block",
                action=SafetyAction.BLOCK,
                risk=RiskLabel.HIGH,
                reasons=tuple(f"blocked term: {term}" for term in matched_terms),
                policy_ids=("local.blocked_terms",),
            )

        return SafetyDecision(
            decision_id="local_safety_allow",
            action=SafetyAction.ALLOW,
            risk=RiskLabel.LOW,
            policy_ids=("local.default_allow",),
        )


def require_deliverable(decision: SafetyDecision) -> None:
    if not decision.deliverable:
        reasons = ", ".join(decision.reasons) or decision.action.value
        raise SafetyBlockedError(f"message blocked by safety policy: {reasons}")


def safety_status_for(decision: SafetyDecision) -> str:
    if decision.action == SafetyAction.ALLOW:
        return "approved"
    if decision.action == SafetyAction.ALLOW_WITH_WARNING:
        return "approved_with_warning"
    return decision.action.value
