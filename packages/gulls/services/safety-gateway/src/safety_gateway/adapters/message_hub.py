from __future__ import annotations

from message_hub.domain.safety import SafetyCheckRequest

from safety_gateway.domain import SafetyEvaluationRequest, SafetyGatewayService


class MessageHubSafetyGatewayEvaluator:
    """Adapter that lets MessageHubService call the Phase 2 safety gateway."""

    def __init__(self, service: SafetyGatewayService) -> None:
        self._service = service

    def evaluate_send(self, request: SafetyCheckRequest):
        result = self._service.evaluate(
            SafetyEvaluationRequest(
                actor_id=request.sender.agent_id,
                action_type="message.send",
                content=request.content,
                content_ref=request.content_ref,
                target_ids=tuple(agent.agent_id for agent in request.recipients),
                intent=request.intent,
                visibility=request.visibility,
                thread_id=request.thread_id,
            )
        )
        return result.decision
