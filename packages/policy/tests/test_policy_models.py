from __future__ import annotations

from unittest import TestCase

from seagull_policy import (
    PolicyScope,
    ReviewState,
    RiskLabel,
    SafetyAction,
    SafetyDecision,
)


class PolicyModelsTest(TestCase):
    def test_allow_decision_is_deliverable(self) -> None:
        decision = SafetyDecision(
            decision_id="decision_1",
            action=SafetyAction.ALLOW,
            risk=RiskLabel.LOW,
        )

        self.assertTrue(decision.deliverable)

    def test_quarantine_decision_is_not_deliverable(self) -> None:
        decision = SafetyDecision(
            decision_id="decision_2",
            action=SafetyAction.QUARANTINE,
            risk=RiskLabel.HIGH,
            review_state=ReviewState.PENDING,
            policy_ids=("policy_1",),
            reasons=("unknown sender",),
        )

        self.assertFalse(decision.deliverable)
        self.assertEqual(PolicyScope.GLOBAL.value, "global")
