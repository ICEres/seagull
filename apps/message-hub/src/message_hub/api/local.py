from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from message_hub.domain import (
    ActionRequest,
    AgentDecisionResult,
    Agent,
    ContextBudget,
    ContextPack,
    ContextPayloadRef,
    Delivery,
    DuplicateAgentHandleError,
    ForbiddenDeliveryError,
    InboxItem,
    InvalidMessageError,
    Message,
    MessageRef,
    MessageHubService,
    NotFoundError,
    RoutingRule,
    SafetyBlockedError,
    SendMessageResult,
    ThreadContext,
    ThreadRecord,
    WorkflowTraceEntry,
)
from message_hub.storage import InMemoryMessageHubRepository


@dataclass(frozen=True, slots=True)
class ApiError(Exception):
    status_code: int
    error: str
    message: str


class LocalMessageHubApi:
    """Dependency-free local API adapter for the Phase 1 message loop."""

    def __init__(self, service: MessageHubService) -> None:
        self._service = service

    @classmethod
    def in_memory(cls) -> LocalMessageHubApi:
        return cls(MessageHubService(InMemoryMessageHubRepository()))

    def health(self) -> dict[str, Any]:
        return {"ok": True, "app": "message-hub", "storage": "memory"}

    def register_agent(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            agent = self._service.register_agent(
                required_string(body, "handle"),
                display_name=optional_string(body, "display_name"),
                capabilities=string_list(body.get("capabilities", ()), "capabilities"),
                response_rules=response_rules_object(body.get("response_rules")),
                trigger_mode=optional_string(body, "trigger_mode") or "manual",
                webhook_url=optional_string(body, "webhook_url"),
            )
        except DuplicateAgentHandleError as exc:
            raise ApiError(409, "conflict", str(exc)) from exc
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

        return {"created": True, "agent": agent_to_dict(agent)}

    def create_message(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._service.send_message(
                sender_handle=required_string(body, "sender_handle"),
                recipient_handles=string_list(body.get("recipient_handles", ()), "recipient_handles"),
                content=optional_string(body, "content") or optional_string(body, "content_inline"),
                content_ref=optional_string(body, "content_ref"),
                refs=refs_list(body.get("refs", ()), "refs"),
                intent=optional_string(body, "intent") or "message",
                visibility=optional_string(body, "visibility") or "direct",
                thread_id=optional_string(body, "thread_id"),
                idempotency_key=optional_string(body, "idempotency_key"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except SafetyBlockedError as exc:
            raise ApiError(403, "blocked", str(exc)) from exc

        return send_result_to_dict(result)

    def create_routing_rule(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            rule = self._service.add_routing_rule(
                name=required_string(body, "name"),
                route_to_handles=string_list(body.get("route_to_handles", ()), "route_to_handles"),
                mode=optional_string(body, "mode") or "copy",
                url_contains=string_list(body.get("url_contains", ()), "url_contains"),
                enabled=optional_bool(body, "enabled", default=True),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"created": True, "routing_rule": routing_rule_to_dict(rule)}

    def read_inbox(self, handle: str, *, limit: int = 20) -> dict[str, Any]:
        try:
            items = self._service.get_inbox(handle, limit=limit)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"items": [inbox_item_to_dict(item) for item in items]}

    def read_thread(self, thread_id: str, *, limit: int = 50) -> dict[str, Any]:
        try:
            messages = self._service.get_thread(thread_id, limit=limit)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "thread_id": thread_id,
            "messages": [message_to_dict(message) for message in messages],
        }

    def read_thread_context(self, thread_id: str, *, recent_limit: int = 10) -> dict[str, Any]:
        try:
            context = self._service.get_thread_context(thread_id, recent_limit=recent_limit)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return thread_context_to_dict(context)

    def read_context_pack(
        self,
        thread_id: str,
        *,
        requester_handle: str,
        max_inline_chars: int = 4000,
        max_recent_messages: int = 10,
        max_payload_refs: int = 20,
        token_budget_estimate: int | None = None,
    ) -> dict[str, Any]:
        try:
            context_pack = self._service.get_context_pack(
                thread_id,
                requester_handle=requester_handle,
                max_inline_chars=max_inline_chars,
                max_recent_messages=max_recent_messages,
                max_payload_refs=max_payload_refs,
                token_budget_estimate=token_budget_estimate,
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return context_pack_to_dict(context_pack)

    def ack_message(self, message_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            deliveries = self._service.ack_message(
                message_id,
                recipient_handle=optional_string(body, "recipient_handle"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"deliveries": [delivery_to_dict(delivery) for delivery in deliveries]}

    def submit_hook_result(self, delivery_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            delivery = self._service.apply_hook_result(
                delivery_id,
                hook=required_string(body, "hook"),
                runtime=required_string(body, "runtime"),
                actor=optional_string(body, "actor"),
                content=optional_string(body, "content") or optional_string(body, "current_content_inline"),
                content_ref=optional_string(body, "content_ref") or optional_string(body, "current_content_ref"),
                refs=refs_list(body.get("refs", ()), "refs"),
                action=optional_string(body, "action") or "continue",
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"delivery": delivery_to_dict(delivery)}

    def submit_delivery_decision(self, delivery_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._service.decide_delivery(
                delivery_id,
                agent_handle=required_string(body, "agent_handle"),
                decision=required_string(body, "decision"),
                content=optional_string(body, "content") or optional_string(body, "content_inline"),
                content_ref=optional_string(body, "content_ref"),
                refs=refs_list(body.get("refs", ()), "refs"),
                action_type=optional_string(body, "action_type"),
                action_target=optional_string(body, "action_target"),
                action_runtime=optional_string(body, "action_runtime") or "cloud",
                requires_approval=optional_bool(body, "requires_approval", default=True),
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return decision_result_to_dict(result)


def send_result_to_dict(result: SendMessageResult) -> dict[str, Any]:
    return {
        "message": message_to_dict(result.message),
        "thread": thread_to_dict(result.thread),
        "deliveries": [delivery_to_dict(delivery) for delivery in result.deliveries],
        "message_id": result.message.message_id,
        "thread_id": result.thread.thread_id,
    }


def agent_to_dict(agent: Agent) -> dict[str, Any]:
    return {
        "agent_id": agent.agent_id,
        "handle": agent.handle,
        "display_name": agent.display_name,
        "capabilities": list(agent.capabilities),
        "response_rules": agent.response_rules,
        "status": agent.status,
        "trigger_mode": agent.trigger_mode,
        "webhook_enabled": agent.trigger_mode == "webhook" and agent.webhook_url is not None,
        "created_at": datetime_to_string(agent.created_at),
        "updated_at": datetime_to_string(agent.updated_at),
    }


def message_to_dict(message: Message) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "thread_id": message.thread_id,
        "sender_agent_id": message.sender_agent_id,
        "recipient_agent_ids": list(message.recipient_agent_ids),
        "intent": message.intent,
        "visibility": message.visibility,
        "content_inline": message.content_inline,
        "content_ref": message.content_ref,
        "refs": [message_ref_to_dict(ref) for ref in message.refs],
        "schema_version": message.schema_version,
        "safety_status": message.safety_status,
        "created_at": datetime_to_string(message.created_at),
    }


def thread_to_dict(thread: ThreadRecord) -> dict[str, Any]:
    return {
        "thread_id": thread.thread_id,
        "root_message_id": thread.root_message_id,
        "participants": sorted(thread.participants),
        "message_count": thread.message_count,
        "last_message_id": thread.last_message_id,
        "last_message_at": datetime_to_string(thread.last_message_at),
        "title": thread.title,
        "summary_ref": thread.summary_ref,
        "created_at": datetime_to_string(thread.created_at),
        "updated_at": datetime_to_string(thread.updated_at),
    }


def delivery_to_dict(delivery: Delivery) -> dict[str, Any]:
    return {
        "delivery_id": delivery.delivery_id,
        "message_id": delivery.message_id,
        "thread_id": delivery.thread_id,
        "sender_agent_id": delivery.sender_agent_id,
        "recipient_agent_id": delivery.recipient_agent_id,
        "status": delivery.status.value,
        "retry_count": delivery.retry_count,
        "last_error": delivery.last_error,
        "current_content_inline": delivery.current_content_inline,
        "current_content_ref": delivery.current_content_ref,
        "refs": [message_ref_to_dict(ref) for ref in delivery.refs],
        "workflow_trace": [workflow_trace_to_dict(entry) for entry in delivery.workflow_trace],
        "current_stage": delivery.current_stage,
        "action_request": None if delivery.action_request is None else action_request_to_dict(delivery.action_request),
        "created_at": datetime_to_string(delivery.created_at),
        "updated_at": datetime_to_string(delivery.updated_at),
        "acked_at": datetime_to_string(delivery.acked_at),
    }


def inbox_item_to_dict(item: InboxItem) -> dict[str, Any]:
    return {
        "delivery": delivery_to_dict(item.delivery),
        "message": message_to_dict(item.message),
        "current_message": {
            "content_inline": item.delivery.current_content_inline or item.message.content_inline,
            "content_ref": item.delivery.current_content_ref or item.message.content_ref,
            "refs": [message_ref_to_dict(ref) for ref in item.delivery.refs or item.message.refs],
        },
    }


def routing_rule_to_dict(rule: RoutingRule) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "name": rule.name,
        "mode": rule.mode.value,
        "route_to_handles": list(rule.route_to_handles),
        "url_contains": list(rule.url_contains),
        "enabled": rule.enabled,
        "created_at": datetime_to_string(rule.created_at),
        "updated_at": datetime_to_string(rule.updated_at),
    }


def message_ref_to_dict(ref: MessageRef) -> dict[str, Any]:
    return {
        "type": ref.type,
        "url": ref.url,
        "find": ref.find,
        "remember_as": ref.remember_as,
    }


def workflow_trace_to_dict(entry: WorkflowTraceEntry) -> dict[str, Any]:
    return {
        "hook": entry.hook,
        "runtime": entry.runtime,
        "action": entry.action,
        "actor": entry.actor,
        "changed": list(entry.changed),
        "note": entry.note,
        "created_at": datetime_to_string(entry.created_at),
    }


def action_request_to_dict(action_request: ActionRequest) -> dict[str, Any]:
    return {
        "action_request_id": action_request.action_request_id,
        "type": action_request.type,
        "target": action_request.target,
        "runtime": action_request.runtime,
        "requires_approval": action_request.requires_approval,
        "status": action_request.status,
        "created_at": datetime_to_string(action_request.created_at),
    }


def decision_result_to_dict(result: AgentDecisionResult) -> dict[str, Any]:
    return {
        "delivery": delivery_to_dict(result.delivery),
        "reply": None if result.reply is None else send_result_to_dict(result.reply),
        "action_request": None if result.action_request is None else action_request_to_dict(result.action_request),
    }


def thread_context_to_dict(context: ThreadContext) -> dict[str, Any]:
    return {
        "thread": thread_to_dict(context.thread),
        "summary": None if context.summary is None else {
            "summary_id": context.summary.summary_id,
            "thread_id": context.summary.thread_id,
            "summary_text": context.summary.summary_text,
            "message_start_id": context.summary.message_start_id,
            "message_end_id": context.summary.message_end_id,
            "token_count_estimate": context.summary.token_count_estimate,
            "content_ref": context.summary.content_ref,
            "created_at": datetime_to_string(context.summary.created_at),
        },
        "recent_messages": [message_to_dict(message) for message in context.recent_messages],
    }


def context_pack_to_dict(context_pack: ContextPack) -> dict[str, Any]:
    return {
        "context_pack_id": context_pack.context_pack_id,
        "thread": thread_to_dict(context_pack.thread),
        "requester_handle": context_pack.requester_handle,
        "summary": None if context_pack.summary is None else {
            "summary_id": context_pack.summary.summary_id,
            "thread_id": context_pack.summary.thread_id,
            "summary_text": context_pack.summary.summary_text,
            "message_start_id": context_pack.summary.message_start_id,
            "message_end_id": context_pack.summary.message_end_id,
            "token_count_estimate": context_pack.summary.token_count_estimate,
            "content_ref": context_pack.summary.content_ref,
            "created_at": datetime_to_string(context_pack.summary.created_at),
        },
        "recent_messages": [message_to_dict(message) for message in context_pack.recent_messages],
        "selected_refs": [message_ref_to_dict(ref) for ref in context_pack.selected_refs],
        "payload_refs": [context_payload_ref_to_dict(ref) for ref in context_pack.payload_refs],
        "budget": context_budget_to_dict(context_pack.budget),
        "access_scope": context_pack.access_scope,
        "allowed_recipients": list(context_pack.allowed_recipients),
        "redacted_refs": list(context_pack.redacted_refs),
        "created_at": datetime_to_string(context_pack.created_at),
    }


def context_budget_to_dict(budget: ContextBudget) -> dict[str, Any]:
    return {
        "max_inline_chars": budget.max_inline_chars,
        "max_recent_messages": budget.max_recent_messages,
        "max_payload_refs": budget.max_payload_refs,
        "token_budget_estimate": budget.token_budget_estimate,
        "inline_chars_used": budget.inline_chars_used,
        "recent_messages_returned": budget.recent_messages_returned,
        "payload_refs_returned": budget.payload_refs_returned,
        "truncated": budget.truncated,
    }


def context_payload_ref_to_dict(ref: ContextPayloadRef) -> dict[str, str]:
    return {
        "content_ref": ref.content_ref,
        "source_type": ref.source_type,
        "source_id": ref.source_id,
    }


def required_string(body: dict[str, Any], field_name: str) -> str:
    value = optional_string(body, field_name)
    if value is None:
        raise ApiError(400, "bad_request", f"{field_name} is required")
    return value


def optional_string(body: dict[str, Any], field_name: str) -> str | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, "bad_request", f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None


def string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ApiError(400, "bad_request", f"{field_name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ApiError(400, "bad_request", f"{field_name} must contain only strings")
    return tuple(value)


def response_rules_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ApiError(400, "bad_request", "response_rules must be an object")
    allowed = {
        "schema_version",
        "persona",
        "style",
        "reply_posture",
        "max_reply_chars",
        "ask_human_triggers",
        "prohibited_behavior",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ApiError(400, "bad_request", f"unknown response_rules field(s): {', '.join(unknown)}")
    return dict(value)


def refs_list(value: Any, field_name: str) -> tuple[MessageRef, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ApiError(400, "bad_request", f"{field_name} must be a list")

    refs: list[MessageRef] = []
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(400, "bad_request", f"{field_name} must contain objects")
        ref_type = optional_string(item, "type")
        if ref_type is None:
            raise ApiError(400, "bad_request", "ref type is required")
        refs.append(
            MessageRef(
                type=ref_type,
                url=optional_string(item, "url"),
                find=optional_string(item, "find"),
                remember_as=optional_string(item, "remember_as"),
            )
        )
    return tuple(refs)


def optional_bool(body: dict[str, Any], field_name: str, *, default: bool) -> bool:
    value = body.get(field_name)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ApiError(400, "bad_request", f"{field_name} must be a boolean")
    return value


def datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
