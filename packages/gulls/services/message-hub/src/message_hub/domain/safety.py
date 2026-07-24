from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from dataclasses import dataclass
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


GUEST_QUARANTINE_POLICY_ID = "guest.quarantine_first"


class _GuestSafetyStatus:
    """Duck-typed action whose ``.value`` feeds domain ``safety_status_for``."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value


class GuestQuarantinedDecision:
    """Deliverable decision that forces the guest quarantine-first hold.

    Duck-types ``seagull_policy.SafetyDecision`` the same way the deployed
    gateway adapter does: ``deliverable`` is True so the message persists,
    while ``action.value`` reads ``needs_review`` so the send path holds every
    delivery for human review. ``safety_action`` records what the composed
    evaluator actually decided (``allow``, ``block``, ...) for the workflow
    trace only — it must never be observable by the guest sender.
    """

    __slots__ = (
        "decision_id",
        "action",
        "risk",
        "reasons",
        "policy_ids",
        "deliverable",
        "safety_action",
    )

    def __init__(
        self,
        *,
        decision_id: str,
        risk: object,
        reasons: tuple[str, ...],
        policy_ids: tuple[str, ...],
        safety_action: str,
    ) -> None:
        self.decision_id = decision_id
        self.action = _GuestSafetyStatus("needs_review")
        self.risk = risk
        self.reasons = reasons
        self.policy_ids = policy_ids
        self.deliverable = True
        self.safety_action = safety_action


class GuestSafetyEvaluator:
    """Quarantine-first SafetyEvaluator wrapper for token-less guest sends.

    Composes the configured evaluator and forces EVERY guest send into the
    same held-for-review outcome:

    * ``allow`` / ``allow_with_warning`` become a needs-review hold, and
    * ``block`` / ``quarantine`` / ``rate_limit`` decisions — or a
      ``SafetyBlockedError`` raised by gateway-style evaluators (including
      their fail-closed transport errors) — are ALSO persisted and held.

    A hard block is therefore indistinguishable from review to the sender:
    guests cannot probe content policy through response differences, and a
    guest send never 403s on content. The composed evaluator's real action is
    kept on the returned decision's ``safety_action`` so the send path can
    record it in the delivery workflow trace for the human reviewer.
    """

    def __init__(self, inner: SafetyEvaluator | None) -> None:
        self._inner = inner
        self.last_decision: GuestQuarantinedDecision | None = None

    def evaluate_send(self, request: SafetyCheckRequest) -> GuestQuarantinedDecision:
        decision_id = "guest_quarantine"
        risk: object = None
        reasons: tuple[str, ...] = ()
        policy_ids: tuple[str, ...] = (GUEST_QUARANTINE_POLICY_ID,)
        safety_action = "allow"

        if self._inner is not None:
            try:
                inner_decision = self._inner.evaluate_send(request)
            except SafetyBlockedError as exc:
                safety_action = "block"
                reasons = (str(exc),)
            else:
                action = getattr(inner_decision.action, "value", None)
                safety_action = str(action) if action else str(inner_decision.action)
                decision_id = inner_decision.decision_id
                risk = getattr(inner_decision, "risk", None)
                reasons = tuple(inner_decision.reasons)
                policy_ids = (*tuple(inner_decision.policy_ids), GUEST_QUARANTINE_POLICY_ID)

        decision = GuestQuarantinedDecision(
            decision_id=decision_id,
            risk=risk,
            reasons=reasons,
            policy_ids=policy_ids,
            safety_action=safety_action,
        )
        self.last_decision = decision
        return decision


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
