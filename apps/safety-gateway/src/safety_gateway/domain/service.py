from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from seagull_policy import ReviewState, RiskLabel, SafetyAction, SafetyDecision, TrustLabel
from safety_gateway._compat import dataclass

from safety_gateway.domain.models import (
    SafetyAuditRecord,
    SafetyEvaluationRequest,
    SafetyEvaluationResult,
    SafetyFlag,
    utc_now,
)
from safety_gateway.storage.repository import SafetyAuditRepository


IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class SafetyGatewayPolicy:
    blocked_actors: frozenset[str] = frozenset()
    blocked_terms: tuple[str, ...] = ("unsafe:",)
    prompt_injection_patterns: tuple[str, ...] = (
        "ignore previous instructions",
        "ignore all previous instructions",
        "reveal your system prompt",
        "print the system prompt",
        "developer message",
        "bypass safety",
        "disable safety",
    )
    spam_patterns: tuple[str, ...] = (
        "click here",
        "free money",
        "limited time offer",
        "buy now",
    )
    human_review_intents: tuple[str, ...] = (
        "connector_action",
        "credential_request",
        "external_action",
        "payment",
        "tool_call",
    )
    max_events_per_window: int = 20
    rate_limit_window_seconds: int = 60
    max_thread_depth: int = 12
    max_repeated_replies: int = 4


class SafetyGatewayService:
    def __init__(
        self,
        audit_repository: SafetyAuditRepository,
        *,
        policy: SafetyGatewayPolicy | None = None,
        id_factory: IdFactory | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._audit_repository = audit_repository
        self._policy = policy or SafetyGatewayPolicy()
        self._id_factory = id_factory or self._default_id_factory
        self._clock = clock
        self._rate_events: dict[tuple[str, str], list[datetime]] = defaultdict(list)

    def evaluate(self, request: SafetyEvaluationRequest) -> SafetyEvaluationResult:
        request = normalize_request(request)
        now = self._clock()
        flags = self._flags_for(request)
        rate_limited = self._record_and_check_rate_limit(request, now)

        action, risk, review_state, reasons, policy_ids = self._decide(request, flags, rate_limited)
        decision = SafetyDecision(
            decision_id=self._new_id("decision"),
            action=action,
            risk=risk,
            review_state=review_state,
            reasons=reasons,
            policy_ids=policy_ids,
            created_at=now,
        )
        audit_record = SafetyAuditRecord(
            audit_id=self._new_id("audit"),
            decision_id=decision.decision_id,
            actor_id=request.actor_id,
            action=decision.action,
            risk=decision.risk,
            target_ids=request.target_ids,
            reasons=decision.reasons,
            policy_ids=decision.policy_ids,
            flags=flags,
            message_id=request.message_id,
            thread_id=request.thread_id,
            trace_id=request.trace_id,
            review_state=decision.review_state,
            created_at=now,
        )
        self._audit_repository.append(audit_record)
        return SafetyEvaluationResult(decision=decision, audit_record=audit_record, flags=flags)

    def _decide(
        self,
        request: SafetyEvaluationRequest,
        flags: tuple[SafetyFlag, ...],
        rate_limited: bool,
    ) -> tuple[SafetyAction, RiskLabel, ReviewState, tuple[str, ...], tuple[str, ...]]:
        flag_labels = {flag.label for flag in flags}

        if request.trust_label == TrustLabel.BLOCKED or request.actor_id in self._policy.blocked_actors:
            return (
                SafetyAction.BLOCK,
                RiskLabel.CRITICAL,
                ReviewState.NOT_REQUIRED,
                ("blocked actor",),
                ("safety.actor_blocklist",),
            )

        if "blocked_term" in flag_labels:
            return decision_from_flags(SafetyAction.BLOCK, RiskLabel.HIGH, ReviewState.NOT_REQUIRED, flags)

        if rate_limited:
            return (
                SafetyAction.RATE_LIMIT,
                RiskLabel.MEDIUM,
                ReviewState.NOT_REQUIRED,
                ("rate limit exceeded",),
                ("safety.rate_limit",),
            )

        if "loop" in flag_labels:
            return decision_from_flags(SafetyAction.QUARANTINE, RiskLabel.HIGH, ReviewState.PENDING, flags)

        if "prompt_injection" in flag_labels:
            return decision_from_flags(SafetyAction.QUARANTINE, RiskLabel.HIGH, ReviewState.PENDING, flags)

        if request.intent in self._policy.human_review_intents or request.action_type in self._policy.human_review_intents:
            return (
                SafetyAction.HUMAN_REVIEW,
                RiskLabel.MEDIUM,
                ReviewState.PENDING,
                ("high-impact action requires human review",),
                ("safety.human_review_intent",),
            )

        if "spam" in flag_labels:
            return decision_from_flags(
                SafetyAction.ALLOW_WITH_WARNING,
                RiskLabel.MEDIUM,
                ReviewState.NOT_REQUIRED,
                flags,
            )

        return (
            SafetyAction.ALLOW,
            RiskLabel.LOW,
            ReviewState.NOT_REQUIRED,
            ("passed default safety policy",),
            ("safety.default_allow",),
        )

    def _flags_for(self, request: SafetyEvaluationRequest) -> tuple[SafetyFlag, ...]:
        flags: list[SafetyFlag] = []
        content = normalized_content(request.content)

        for term in normalized_terms(self._policy.blocked_terms):
            if term in content:
                flags.append(
                    SafetyFlag(
                        label="blocked_term",
                        risk=RiskLabel.HIGH,
                        reason=f"blocked term: {term}",
                        policy_id="safety.blocked_terms",
                    )
                )

        for pattern in normalized_terms(self._policy.prompt_injection_patterns):
            if pattern in content:
                flags.append(
                    SafetyFlag(
                        label="prompt_injection",
                        risk=RiskLabel.HIGH,
                        reason=f"prompt-injection pattern: {pattern}",
                        policy_id="safety.prompt_injection",
                    )
                )

        for pattern in normalized_terms(self._policy.spam_patterns):
            if pattern in content:
                flags.append(
                    SafetyFlag(
                        label="spam",
                        risk=RiskLabel.MEDIUM,
                        reason=f"spam pattern: {pattern}",
                        policy_id="safety.spam",
                    )
                )

        if request.thread_depth > self._policy.max_thread_depth:
            flags.append(
                SafetyFlag(
                    label="loop",
                    risk=RiskLabel.HIGH,
                    reason="thread depth exceeded",
                    policy_id="safety.loop_depth",
                )
            )

        if request.repeated_reply_count > self._policy.max_repeated_replies:
            flags.append(
                SafetyFlag(
                    label="loop",
                    risk=RiskLabel.HIGH,
                    reason="repeated reply count exceeded",
                    policy_id="safety.loop_replies",
                )
            )

        return tuple(flags)

    def _record_and_check_rate_limit(self, request: SafetyEvaluationRequest, now: datetime) -> bool:
        window = timedelta(seconds=self._policy.rate_limit_window_seconds)
        key = (request.actor_id, request.action_type)
        events = [
            event_time
            for event_time in self._rate_events[key]
            if now - event_time < window
        ]
        self._rate_events[key] = events
        limited = len(events) >= self._policy.max_events_per_window
        events.append(now)
        return limited

    def _new_id(self, prefix: str) -> str:
        return self._id_factory(prefix)

    @staticmethod
    def _default_id_factory(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"


def decision_from_flags(
    action: SafetyAction,
    risk: RiskLabel,
    review_state: ReviewState,
    flags: tuple[SafetyFlag, ...],
) -> tuple[SafetyAction, RiskLabel, ReviewState, tuple[str, ...], tuple[str, ...]]:
    return (
        action,
        risk,
        review_state,
        tuple(flag.reason for flag in flags),
        tuple(sorted({flag.policy_id for flag in flags})),
    )


def normalize_request(request: SafetyEvaluationRequest) -> SafetyEvaluationRequest:
    actor_id = request.actor_id.strip()
    action_type = request.action_type.strip() or "message.send"
    intent = request.intent.strip() or "message"
    visibility = request.visibility.strip() or "direct"
    target_ids = tuple(target_id.strip() for target_id in request.target_ids if target_id.strip())
    if not actor_id:
        raise ValueError("actor_id is required")
    if request.thread_depth < 0:
        raise ValueError("thread_depth must be greater than or equal to zero")
    if request.repeated_reply_count < 0:
        raise ValueError("repeated_reply_count must be greater than or equal to zero")

    return SafetyEvaluationRequest(
        actor_id=actor_id,
        action_type=action_type,
        content=request.content,
        content_ref=request.content_ref,
        target_ids=target_ids,
        intent=intent,
        visibility=visibility,
        thread_id=request.thread_id,
        message_id=request.message_id,
        trace_id=request.trace_id,
        trust_label=request.trust_label,
        thread_depth=request.thread_depth,
        repeated_reply_count=request.repeated_reply_count,
        metadata=request.metadata,
    )


def normalized_content(content: str | None) -> str:
    return (content or "").casefold()


def normalized_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term.strip().casefold() for term in terms if term.strip())
