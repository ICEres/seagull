from __future__ import annotations

from typing import Any

from seagull_mcp.auth import PermissionDeniedError, Principal, normalize_handle
from seagull_mcp.client import SeagullClient


TOOL_REQUIRED_SCOPES = {
    "seagull.list_agents": "agents:read",
    "seagull.get_inbox": "messages:read",
    "seagull.get_thread_context": "messages:read",
    "seagull.get_context": "context:read",
    "seagull.send_message": "messages:write",
    "seagull.ack_message": "messages:ack",
    "seagull.open_inbox_ui": "messages:read",
    "seagull.create_task": "tasks:write",
    "seagull.accept_task": "tasks:write",
    "seagull.update_task": "tasks:write",
    "seagull.return_result": "tasks:write",
    "seagull.upload_artifact": "artifacts:write",
}


def tool_descriptors(scopes: frozenset[str] | None = None) -> list[dict[str, Any]]:
    descriptors = [
        {
            "name": "seagull.list_agents",
            "description": "List Seagull agents available to the authenticated connector.",
            "inputSchema": object_schema({}),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "seagull.get_inbox",
            "description": "Read recent inbox deliveries for one accessible Seagull agent.",
            "inputSchema": object_schema({
                "agent_handle": string_schema("Agent handle, for example @runner:gulls.ai."),
                "limit": integer_schema("Maximum inbox items to return.", minimum=1, maximum=50),
            }, required=("agent_handle",)),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "seagull.get_thread_context",
            "description": "Read compact context for a Seagull message thread as an accessible agent.",
            "inputSchema": object_schema({
                "agent_handle": string_schema("Accessible agent handle requesting context."),
                "thread_id": string_schema("Seagull thread ID."),
            }, required=("agent_handle", "thread_id")),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "seagull.get_context",
            "description": (
                "Read Seagull-managed context for an accessible agent. This returns Seagull context records, "
                "not another agent's private MCP session, files, browser, shell, or credentials."
            ),
            "inputSchema": object_schema({
                "agent_handle": string_schema("Accessible agent handle requesting context."),
                "thread_id": string_schema("Seagull thread ID to load compact context for."),
                "max_inline_chars": integer_schema("Maximum inline characters to include.", minimum=0, maximum=20000),
                "max_recent_messages": integer_schema("Maximum recent messages to include.", minimum=0, maximum=50),
                "max_payload_refs": integer_schema("Maximum payload or selected refs to include.", minimum=0, maximum=100),
                "token_budget_estimate": integer_schema("Optional estimated context token budget.", minimum=0, maximum=1000000),
            }, required=("agent_handle", "thread_id")),
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "seagull.send_message",
            "description": "Send a Seagull direct or thread reply message as an accessible agent.",
            "inputSchema": object_schema({
                "sender_handle": string_schema("Owned sender agent handle."),
                "recipient_handles": {
                    "type": "array",
                    "items": string_schema("Recipient agent handle."),
                    "minItems": 1,
                },
                "content": string_schema("Small message content to send inline."),
                "content_ref": string_schema("Optional Seagull payload reference for large content."),
                "thread_id": string_schema("Optional existing thread ID."),
                "intent": string_schema("Optional message intent."),
            }, required=("sender_handle", "recipient_handles")),
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "seagull.create_task",
            "description": (
                "Create a delegated task record through Seagull coordination APIs. This shares task refs; "
                "it does not grant access to the recipient agent's private tools or prompts."
            ),
            "inputSchema": object_schema({
                "requester_handle": string_schema("Owned requester agent handle."),
                "recipient_handle": string_schema("Recipient agent handle."),
                "objective": string_schema("Task objective or requested output."),
                "context_refs": array_schema("Context reference visible to the recipient."),
                "context_pack_id": string_schema("Optional Seagull context pack ID."),
                "context_pack_ref": string_schema("Optional external context pack reference."),
                "input_ref": string_schema("Optional large input reference."),
                "allowed_tool_names": array_schema("Optional coarse tool names allowed for this task."),
                "allowed_use_terms": array_schema("Optional allowed-use terms for shared context."),
                "idempotency_key": string_schema("Optional idempotency key for retry-safe task creation."),
            }, required=("requester_handle", "recipient_handle", "objective")),
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "seagull.accept_task",
            "description": (
                "Accept a delegated task as an accessible worker agent through Seagull. This records task state "
                "in Seagull instead of opening the worker's private MCP tools."
            ),
            "inputSchema": object_schema({
                "worker_handle": string_schema("Owned worker agent handle accepting the task."),
                "requester_handle": string_schema("Requester agent handle to notify."),
                "task_id": string_schema("Task ID returned by seagull.create_task."),
                "thread_id": string_schema("Task thread ID."),
                "note": string_schema("Optional acceptance note."),
            }, required=("worker_handle", "requester_handle", "task_id", "thread_id")),
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "seagull.update_task",
            "description": (
                "Publish a Seagull task status update as an accessible agent. This is durable coordination state, "
                "not a remote raw tool call."
            ),
            "inputSchema": object_schema({
                "actor_handle": string_schema("Owned agent handle publishing the update."),
                "recipient_handle": string_schema("Agent handle to notify."),
                "task_id": string_schema("Task ID."),
                "thread_id": string_schema("Task thread ID."),
                "state": string_schema("Task state, for example running, result_ready, completed, refused, or failed."),
                "note": string_schema("Optional status note."),
                "progress": integer_schema("Optional progress percentage.", minimum=0, maximum=100),
            }, required=("actor_handle", "recipient_handle", "task_id", "thread_id", "state")),
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "seagull.return_result",
            "description": (
                "Return a durable task result through Seagull as an accessible responder agent. Result content, "
                "refs, and artifacts are shared through Seagull records, not private MCP handles."
            ),
            "inputSchema": object_schema({
                "responder_handle": string_schema("Owned responder agent handle."),
                "requester_handle": string_schema("Requester agent handle to notify."),
                "task_id": string_schema("Task ID."),
                "thread_id": string_schema("Task thread ID."),
                "state": string_schema("Result state, default completed."),
                "content": string_schema("Optional result summary."),
                "content_ref": string_schema("Optional large result reference."),
                "artifact_refs": array_schema("Optional artifact references."),
                "tool_use_summary_refs": array_schema("Optional tool-use summary references."),
                "error": string_schema("Optional failure message."),
            }, required=("responder_handle", "requester_handle", "task_id", "thread_id")),
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "seagull.upload_artifact",
            "description": (
                "Share an artifact reference through Seagull as an accessible agent. The artifact is represented "
                "as a Seagull ref and must not expose private MCP server URLs, credentials, or raw local paths."
            ),
            "inputSchema": object_schema({
                "sender_handle": string_schema("Owned sender agent handle."),
                "recipient_handles": {
                    "type": "array",
                    "items": string_schema("Recipient agent handle."),
                    "minItems": 1,
                },
                "name": string_schema("Artifact display name."),
                "content_ref": string_schema("Seagull-safe artifact content reference."),
                "media_type": string_schema("Optional artifact media type."),
                "thread_id": string_schema("Optional task or message thread ID."),
                "task_id": string_schema("Optional related task ID."),
                "description": string_schema("Optional artifact description."),
            }, required=("sender_handle", "recipient_handles", "name", "content_ref")),
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "seagull.ack_message",
            "description": "Acknowledge that an accessible recipient agent handled a delivered message.",
            "inputSchema": object_schema({
                "message_id": string_schema("Message ID to acknowledge."),
                "recipient_handle": string_schema("Accessible recipient agent handle."),
            }, required=("message_id", "recipient_handle")),
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "seagull.open_inbox_ui",
            "description": "Open a simple Seagull inbox UI card for an accessible agent.",
            "inputSchema": object_schema({
                "agent_handle": string_schema("Agent handle to inspect."),
            }, required=("agent_handle",)),
            "annotations": {"readOnlyHint": True},
        },
    ]
    if scopes is None:
        return descriptors
    return [
        descriptor
        for descriptor in descriptors
        if TOOL_REQUIRED_SCOPES[descriptor["name"]] in scopes
    ]


class SeagullMcpTools:
    def __init__(self, client: SeagullClient) -> None:
        self._client = client

    def call(self, name: str, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        if name == "seagull.list_agents":
            return self._list_agents(principal)
        if name == "seagull.get_inbox":
            return self._get_inbox(arguments, principal)
        if name == "seagull.get_thread_context":
            return self._get_thread_context(arguments, principal)
        if name == "seagull.get_context":
            return self._get_context(arguments, principal)
        if name == "seagull.send_message":
            return self._send_message(arguments, principal)
        if name == "seagull.create_task":
            return self._create_task(arguments, principal)
        if name == "seagull.accept_task":
            return self._accept_task(arguments, principal)
        if name == "seagull.update_task":
            return self._update_task(arguments, principal)
        if name == "seagull.return_result":
            return self._return_result(arguments, principal)
        if name == "seagull.upload_artifact":
            return self._upload_artifact(arguments, principal)
        if name == "seagull.ack_message":
            return self._ack_message(arguments, principal)
        if name == "seagull.open_inbox_ui":
            return self._open_inbox_ui(arguments, principal)
        raise ValueError(f"unknown tool: {name}")

    def _list_agents(self, principal: Principal) -> dict[str, Any]:
        principal.require_scope("agents:read")
        agents = self._client.list_agents(tuple(sorted(principal.agent_handles)))
        return tool_result({"agents": agents}, f"{len(agents)} Seagull agent(s) available.")

    def _get_inbox(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("messages:read")
        handle = required_string(arguments, "agent_handle")
        principal.require_agent(handle)
        limit = bounded_int(arguments.get("limit", 20), "limit", minimum=1, maximum=50)
        result = self._client.get_inbox(normalize_handle(handle), limit=limit)
        count = len(result.get("items", []))
        return tool_result(result, f"{count} inbox item(s).")

    def _get_thread_context(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("messages:read")
        handle = required_string(arguments, "agent_handle")
        principal.require_agent(handle)
        thread_id = required_string(arguments, "thread_id")
        result = self._client.get_thread_context(thread_id)
        return tool_result(result, f"Loaded thread context for {thread_id}.")

    def _get_context(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("context:read")
        handle = required_string(arguments, "agent_handle")
        principal.require_agent(handle)
        thread_id = required_string(arguments, "thread_id")
        result = self._client.get_context(
            thread_id=thread_id,
            requester_handle=normalize_handle(handle),
            max_inline_chars=optional_bounded_int(
                arguments.get("max_inline_chars"),
                "max_inline_chars",
                minimum=0,
                maximum=20000,
            ),
            max_recent_messages=optional_bounded_int(
                arguments.get("max_recent_messages"),
                "max_recent_messages",
                minimum=0,
                maximum=50,
            ),
            max_payload_refs=optional_bounded_int(
                arguments.get("max_payload_refs"),
                "max_payload_refs",
                minimum=0,
                maximum=100,
            ),
            token_budget_estimate=optional_bounded_int(
                arguments.get("token_budget_estimate"),
                "token_budget_estimate",
                minimum=0,
                maximum=1000000,
            ),
        )
        context_pack_id = result.get("context_pack_id") or thread_id
        return tool_result(result, f"Loaded Seagull context pack {context_pack_id}.")

    def _send_message(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("messages:write")
        sender_handle = required_string(arguments, "sender_handle")
        principal.require_agent(sender_handle)
        recipients = string_list(arguments.get("recipient_handles"), "recipient_handles")
        content = optional_string(arguments, "content")
        content_ref = optional_string(arguments, "content_ref")
        if content is None and content_ref is None:
            raise ValueError("content or content_ref is required")
        result = self._client.send_message(
            sender_handle=normalize_handle(sender_handle),
            recipient_handles=tuple(normalize_handle(handle) for handle in recipients),
            content=None if content_ref is not None else content,
            content_ref=content_ref,
            thread_id=optional_string(arguments, "thread_id"),
            intent=optional_string(arguments, "intent") or "message",
        )
        return tool_result(result, f"Sent Seagull message {result.get('message_id')}.")

    def _create_task(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("tasks:write")
        requester_handle = required_string(arguments, "requester_handle")
        principal.require_agent(requester_handle)
        recipient_handle = required_string(arguments, "recipient_handle")
        objective = required_string(arguments, "objective")
        result = self._client.create_task(
            requester_handle=normalize_handle(requester_handle),
            recipient_handle=normalize_handle(recipient_handle),
            objective=objective,
            context_refs=optional_string_list(arguments.get("context_refs"), "context_refs"),
            context_pack_id=optional_string(arguments, "context_pack_id"),
            context_pack_ref=optional_string(arguments, "context_pack_ref"),
            input_ref=optional_string(arguments, "input_ref"),
            allowed_tool_names=optional_string_list(arguments.get("allowed_tool_names"), "allowed_tool_names"),
            allowed_use_terms=optional_string_list(arguments.get("allowed_use_terms"), "allowed_use_terms"),
            idempotency_key=optional_string(arguments, "idempotency_key"),
        )
        return tool_result(result, f"Created Seagull task {result.get('task_id')}.")

    def _accept_task(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("tasks:write")
        worker_handle = required_string(arguments, "worker_handle")
        principal.require_agent(worker_handle)
        result = self._client.accept_task(
            task_id=required_string(arguments, "task_id"),
            thread_id=required_string(arguments, "thread_id"),
            worker_handle=normalize_handle(worker_handle),
            requester_handle=normalize_handle(required_string(arguments, "requester_handle")),
            note=optional_string(arguments, "note"),
        )
        return tool_result(result, f"Accepted Seagull task {result.get('task_id')}.")

    def _update_task(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("tasks:write")
        actor_handle = required_string(arguments, "actor_handle")
        principal.require_agent(actor_handle)
        result = self._client.update_task(
            task_id=required_string(arguments, "task_id"),
            thread_id=required_string(arguments, "thread_id"),
            actor_handle=normalize_handle(actor_handle),
            recipient_handle=normalize_handle(required_string(arguments, "recipient_handle")),
            state=required_string(arguments, "state"),
            note=optional_string(arguments, "note"),
            progress=optional_bounded_int(arguments.get("progress"), "progress", minimum=0, maximum=100),
        )
        return tool_result(result, f"Updated Seagull task {result.get('task_id')}.")

    def _return_result(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("tasks:write")
        responder_handle = required_string(arguments, "responder_handle")
        principal.require_agent(responder_handle)
        result = self._client.return_task_result(
            task_id=required_string(arguments, "task_id"),
            thread_id=required_string(arguments, "thread_id"),
            responder_handle=normalize_handle(responder_handle),
            requester_handle=normalize_handle(required_string(arguments, "requester_handle")),
            state=optional_string(arguments, "state") or "completed",
            content=optional_string(arguments, "content"),
            content_ref=optional_string(arguments, "content_ref"),
            artifact_refs=optional_string_list(arguments.get("artifact_refs"), "artifact_refs"),
            tool_use_summary_refs=optional_string_list(
                arguments.get("tool_use_summary_refs"),
                "tool_use_summary_refs",
            ),
            error=optional_string(arguments, "error"),
        )
        return tool_result(result, f"Returned Seagull task result for {result.get('task_id')}.")

    def _upload_artifact(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("artifacts:write")
        sender_handle = required_string(arguments, "sender_handle")
        principal.require_agent(sender_handle)
        result = self._client.upload_artifact(
            sender_handle=normalize_handle(sender_handle),
            recipient_handles=tuple(
                normalize_handle(handle)
                for handle in string_list(arguments.get("recipient_handles"), "recipient_handles")
            ),
            name=required_string(arguments, "name"),
            content_ref=required_string(arguments, "content_ref"),
            media_type=optional_string(arguments, "media_type"),
            thread_id=optional_string(arguments, "thread_id"),
            task_id=optional_string(arguments, "task_id"),
            description=optional_string(arguments, "description"),
        )
        return tool_result(result, f"Shared Seagull artifact {result.get('artifact_ref')}.")

    def _ack_message(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("messages:ack")
        recipient_handle = required_string(arguments, "recipient_handle")
        principal.require_agent(recipient_handle)
        message_id = required_string(arguments, "message_id")
        result = self._client.ack_message(message_id=message_id, recipient_handle=normalize_handle(recipient_handle))
        return tool_result(result, f"Acknowledged Seagull message {message_id}.")

    def _open_inbox_ui(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("messages:read")
        handle = required_string(arguments, "agent_handle")
        principal.require_agent(handle)
        normalized = normalize_handle(handle)
        return {
            "structuredContent": {"agent_handle": normalized, "resource_uri": "ui://seagull/inbox.html"},
            "content": [{"type": "text", "text": f"Open Seagull inbox for {normalized}."}],
            "_meta": {
                "ui/resourceUri": "ui://seagull/inbox.html",
                "seagull/agent_handle": normalized,
            },
        }


def tool_result(structured_content: dict[str, Any], text: str) -> dict[str, Any]:
    return {
        "structuredContent": structured_content,
        "content": [{"type": "text", "text": text}],
    }


def object_schema(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def string_schema(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def integer_schema(description: str, *, minimum: int, maximum: int) -> dict[str, Any]:
    return {"type": "integer", "description": description, "minimum": minimum, "maximum": maximum}


def array_schema(item_description: str) -> dict[str, Any]:
    return {
        "type": "array",
        "items": string_schema(item_description),
    }


def required_string(arguments: dict[str, Any], field_name: str) -> str:
    value = optional_string(arguments, field_name)
    if value is None:
        raise ValueError(f"{field_name} is required")
    return value


def optional_string(arguments: dict[str, Any], field_name: str) -> str | None:
    value = arguments.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None


def string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field_name} must contain only non-empty strings")
    return tuple(item.strip() for item in value)


def optional_string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    return string_list(value, field_name)


def bounded_int(value: Any, field_name: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return min(max(value, minimum), maximum)


def optional_bounded_int(value: Any, field_name: str, *, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    return bounded_int(value, field_name, minimum=minimum, maximum=maximum)
