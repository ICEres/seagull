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
    ForbiddenPayloadError,
    InboxItem,
    InvalidMessageError,
    Message,
    MessageRef,
    MessageHubService,
    NotFoundError,
    PayloadCompaction,
    PayloadUnavailableError,
    PayloadRecord,
    RoutingRule,
    SafetyBlockedError,
    SendMessageResult,
    TaskRecord,
    TaskResultRecord,
    TaskToolRequest,
    ThreadContext,
    ThreadRecord,
    WorkflowTraceEntry,
)
from message_hub.storage import InMemoryMessageHubRepository


PRIVATE_PROFILE_MARKERS = (
    "mcp://",
    "file://",
    "localhost",
    "127.0.0.1",
    "::1",
    ".sock",
    "tool://",
    "raw_tool",
    "raw-tool",
    "tool_handle",
    "tool-handle",
    "mcp_server",
    "mcp-server",
    "credential",
    "credentials",
    "secret",
    "token",
    "api_key",
    "apikey",
    "password",
    "authorization",
    "bearer ",
)


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

    def create_payload(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = self._service.create_payload(
                content=payload_content(body),
                media_type=optional_string(body, "media_type") or "text/plain; charset=utf-8",
                access_scope=optional_string(body, "access_scope") or "recipients",
                ttl_expires_at=optional_datetime(body, "ttl_expires_at"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

        return {
            "content_ref": payload.record.content_ref,
            "payload": payload_record_to_dict(payload.record),
        }

    def read_payload(
        self,
        content_ref: str,
        *,
        requester_handle: str | None = None,
    ) -> dict[str, Any]:
        try:
            record, content = self._service.read_payload_content(
                content_ref,
                requester_handle=requester_handle,
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenPayloadError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except PayloadUnavailableError as exc:
            raise ApiError(410, "payload_unavailable", str(exc)) from exc

        result: dict[str, Any] = {
            "content_ref": record.content_ref,
            "payload": payload_record_to_dict(record),
            "content_bytes": content,
        }
        try:
            result["content"] = content.decode("utf-8")
        except UnicodeDecodeError:
            pass
        return result

    def read_payload_metadata(self, content_ref: str) -> dict[str, Any]:
        try:
            payload = self._service.get_payload(content_ref)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        result: dict[str, Any] = {
            "content_ref": payload.record.content_ref,
            "payload": payload_record_to_dict(payload.record),
        }
        if payload.compaction is not None:
            result["compaction"] = payload_compaction_to_dict(payload.compaction)
        return result

    def update_payload_retention(self, content_ref: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = self._service.update_payload_retention(
                content_ref,
                retention_state=required_string(body, "retention_state"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except PayloadUnavailableError as exc:
            raise ApiError(410, "payload_unavailable", str(exc)) from exc

        return {
            "content_ref": payload.content_ref,
            "payload": payload_record_to_dict(payload),
        }

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

    def create_task(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            reject_private_task_fields(body)
            task = self._service.create_task(
                requester_handle=required_string(body, "requester_handle"),
                recipient_handle=required_string(body, "recipient_handle"),
                objective=required_string(body, "objective"),
                thread_id=optional_string(body, "thread_id"),
                context_refs=string_list(body.get("context_refs", ()), "context_refs"),
                context_pack_id=optional_string(body, "context_pack_id"),
                context_pack_ref=optional_string(body, "context_pack_ref"),
                input_ref=optional_string(body, "input_ref"),
                stream_id=optional_string(body, "stream_id"),
                allowed_tool_names=string_list(body.get("allowed_tool_names", ()), "allowed_tool_names"),
                allowed_use_terms=string_list(body.get("allowed_use_terms", ()), "allowed_use_terms"),
                idempotency_key=optional_string(body, "idempotency_key"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except SafetyBlockedError as exc:
            raise ApiError(403, "blocked", str(exc)) from exc

        return {"created": True, "task": task_to_dict(task), "task_id": task.task_id, "thread_id": task.thread_id}

    def read_task(self, task_id: str) -> dict[str, Any]:
        try:
            task = self._service.get_task(task_id)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"task": task_to_dict(task)}

    def read_thread_tasks(self, thread_id: str, *, limit: int = 50) -> dict[str, Any]:
        try:
            tasks = self._service.list_thread_tasks(thread_id, limit=limit)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"thread_id": thread_id, "tasks": [task_to_dict(task) for task in tasks]}

    def accept_task(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            task = self._service.accept_task(
                task_id,
                worker_handle=required_string(body, "worker_handle"),
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"task": task_to_dict(task), "task_id": task.task_id, "thread_id": task.thread_id, "state": task.state.value}

    def update_task(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            task = self._service.update_task_state(
                task_id,
                actor_handle=required_string(body, "actor_handle"),
                state=required_string(body, "state"),
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"task": task_to_dict(task), "task_id": task.task_id, "thread_id": task.thread_id, "state": task.state.value}

    def return_task_result(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._service.return_task_result(
                task_id,
                responder_handle=required_string(body, "responder_handle"),
                state=optional_string(body, "state") or "completed",
                content=optional_string(body, "content") or optional_string(body, "content_inline"),
                content_ref=optional_string(body, "content_ref"),
                artifact_refs=string_list(body.get("artifact_refs", ()), "artifact_refs"),
                tool_use_summary_refs=string_list(
                    body.get("tool_use_summary_refs", ()),
                    "tool_use_summary_refs",
                ),
                stream_id=optional_string(body, "stream_id"),
                error=optional_string(body, "error"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except SafetyBlockedError as exc:
            raise ApiError(403, "blocked", str(exc)) from exc

        return {
            "task_id": result.task_id,
            "thread_id": result.thread_id,
            "state": result.state.value,
            "result": task_result_to_dict(result),
        }

    def create_tool_request(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            reject_private_task_fields(body)
            tool_request = self._service.create_tool_request(
                task_id,
                requester_handle=required_string(body, "requester_handle"),
                worker_handle=required_string(body, "worker_handle"),
                tool_name=required_string(body, "tool_name"),
                purpose=required_string(body, "purpose"),
                input_ref=optional_string(body, "input_ref"),
                requires_approval=optional_bool(body, "requires_approval", default=True),
                approval_id=optional_string(body, "approval_id"),
                policy_decision_id=optional_string(body, "policy_decision_id"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except SafetyBlockedError as exc:
            raise ApiError(403, "blocked", str(exc)) from exc

        return {
            "tool_request": tool_request_to_dict(tool_request),
            "tool_request_id": tool_request.tool_request_id,
            "task_id": tool_request.task_id,
        }

    def complete_tool_request(self, tool_request_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            tool_request = self._service.complete_tool_request(
                tool_request_id,
                actor_handle=required_string(body, "actor_handle"),
                state=required_string(body, "state"),
                result_ref=optional_string(body, "result_ref"),
                artifact_refs=string_list(body.get("artifact_refs", ()), "artifact_refs"),
                tool_use_summary_ref=optional_string(body, "tool_use_summary_ref"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "tool_request": tool_request_to_dict(tool_request),
            "tool_request_id": tool_request.tool_request_id,
            "task_id": tool_request.task_id,
            "state": tool_request.status.value,
        }

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


def payload_record_to_dict(payload: PayloadRecord) -> dict[str, Any]:
    return {
        "content_ref": payload.content_ref,
        "media_type": payload.media_type,
        "byte_length": payload.byte_length,
        "hash": payload.hash,
        "compression": payload.compression,
        "compressed_byte_length": payload.compressed_byte_length,
        "compressed_hash": payload.compressed_hash,
        "ttl_expires_at": datetime_to_string(payload.ttl_expires_at),
        "retention_state": payload.retention_state,
        "access_scope": payload.access_scope,
        "fetch_policy_ref": payload.fetch_policy_ref,
        "chunk_manifest_ref": payload.chunk_manifest_ref,
        "storage_provider": payload.storage_provider,
        "storage_ref": payload.storage_ref,
        "created_at": datetime_to_string(payload.created_at),
    }


def payload_compaction_to_dict(compaction: PayloadCompaction) -> dict[str, Any]:
    return {
        "manifest_ref": compaction.manifest_ref,
        "summary": compaction.summary,
        "selected_chunk_refs": list(compaction.selected_chunk_refs),
        "selected_chunk_count": len(compaction.selected_chunks),
        "selected_chunk_byte_lengths": [len(chunk) for chunk in compaction.selected_chunks],
        "created_at": datetime_to_string(compaction.created_at),
    }


def agent_to_dict(agent: Agent) -> dict[str, Any]:
    return {
        "agent_id": agent.agent_id,
        "handle": agent.handle,
        "display_name": agent.display_name,
        "capabilities": public_capabilities(agent.capabilities),
        "response_rules": public_response_rules(agent.response_rules),
        "status": agent.status,
        "trigger_mode": agent.trigger_mode,
        "webhook_enabled": agent.trigger_mode == "webhook" and agent.webhook_url is not None,
        "created_at": datetime_to_string(agent.created_at),
        "updated_at": datetime_to_string(agent.updated_at),
    }


def public_capabilities(capabilities: tuple[str, ...]) -> list[str]:
    return [capability for capability in capabilities if not has_private_profile_marker(capability)]


def public_response_rules(response_rules: dict[str, Any] | None) -> dict[str, Any] | None:
    sanitized = sanitize_public_profile_value(response_rules)
    return sanitized if isinstance(sanitized, dict) else None


def sanitize_public_profile_value(value: Any) -> Any:
    if isinstance(value, str):
        return None if has_private_profile_marker(value) else value
    if isinstance(value, (list, tuple)):
        sanitized_items = []
        for item in value:
            sanitized = sanitize_public_profile_value(item)
            if sanitized is not None:
                sanitized_items.append(sanitized)
        return sanitized_items
    if isinstance(value, dict):
        sanitized_dict: dict[str, Any] = {}
        for key, item in value.items():
            if has_private_profile_marker(str(key)):
                continue
            sanitized = sanitize_public_profile_value(item)
            if sanitized is not None:
                sanitized_dict[str(key)] = sanitized
        return sanitized_dict
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return None


def has_private_profile_marker(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in PRIVATE_PROFILE_MARKERS)


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


def task_to_dict(task: TaskRecord) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "thread_id": task.thread_id,
        "requester_agent_id": task.requester_agent_id,
        "recipient_agent_id": task.recipient_agent_id,
        "objective": task.objective,
        "request_message_id": task.request_message_id,
        "context_refs": list(task.context_refs),
        "context_pack_id": task.context_pack_id,
        "context_pack_ref": task.context_pack_ref,
        "input_ref": task.input_ref,
        "stream_id": task.stream_id,
        "allowed_tool_names": list(task.allowed_tool_names),
        "allowed_use_terms": list(task.allowed_use_terms),
        "state": task.state.value,
        "policy_decision_id": task.policy_decision_id,
        "accepted_by_agent_id": task.accepted_by_agent_id,
        "result_message_id": task.result_message_id,
        "result_ref": task.result_ref,
        "artifact_refs": list(task.artifact_refs),
        "tool_request_ids": list(task.tool_request_ids),
        "created_at": datetime_to_string(task.created_at),
        "updated_at": datetime_to_string(task.updated_at),
    }


def tool_request_to_dict(tool_request: TaskToolRequest) -> dict[str, Any]:
    return {
        "tool_request_id": tool_request.tool_request_id,
        "task_id": tool_request.task_id,
        "thread_id": tool_request.thread_id,
        "requester_agent_id": tool_request.requester_agent_id,
        "worker_agent_id": tool_request.worker_agent_id,
        "tool_name": tool_request.tool_name,
        "purpose": tool_request.purpose,
        "input_ref": tool_request.input_ref,
        "requires_approval": tool_request.requires_approval,
        "status": tool_request.status.value,
        "approval_id": tool_request.approval_id,
        "policy_decision_id": tool_request.policy_decision_id,
        "accepted_by_agent_id": tool_request.accepted_by_agent_id,
        "result_ref": tool_request.result_ref,
        "artifact_refs": list(tool_request.artifact_refs),
        "tool_use_summary_ref": tool_request.tool_use_summary_ref,
        "created_at": datetime_to_string(tool_request.created_at),
        "updated_at": datetime_to_string(tool_request.updated_at),
    }


def task_result_to_dict(result: TaskResultRecord) -> dict[str, Any]:
    return {
        "result_id": result.result_id,
        "task_id": result.task_id,
        "thread_id": result.thread_id,
        "responder_agent_id": result.responder_agent_id,
        "state": result.state.value,
        "result_message_id": result.result_message_id,
        "stream_id": result.stream_id,
        "content_inline": result.content_inline,
        "content_ref": result.content_ref,
        "artifact_refs": list(result.artifact_refs),
        "tool_use_summary_refs": list(result.tool_use_summary_refs),
        "error": result.error,
        "created_at": datetime_to_string(result.created_at),
    }


PRIVATE_TASK_FIELDS = {
    "credential",
    "credentials",
    "mcp_server_url",
    "mcp_session",
    "private_prompt",
    "prompt",
    "raw_tool_handle",
    "secret",
    "secrets",
    "tool_credentials",
    "tool_runtime_config",
}


def reject_private_task_fields(body: dict[str, Any]) -> None:
    private_fields = sorted(set(body) & PRIVATE_TASK_FIELDS)
    if private_fields:
        raise ApiError(
            400,
            "bad_request",
            f"private task field(s) are not accepted: {', '.join(private_fields)}",
        )


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


def payload_content(body: dict[str, Any]) -> str | bytes:
    value = body.get("content")
    if value is None:
        value = body.get("content_inline")
    if value is None:
        value = body.get("content_bytes")
    if value is None:
        raise ApiError(400, "bad_request", "payload content is required")
    if not isinstance(value, (str, bytes)):
        raise ApiError(400, "bad_request", "payload content must be a string or bytes")
    return value


def optional_datetime(body: dict[str, Any], field_name: str) -> datetime | None:
    value = optional_string(body, field_name)
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ApiError(400, "bad_request", f"{field_name} must be an ISO datetime") from exc


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
