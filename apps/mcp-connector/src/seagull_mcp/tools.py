from __future__ import annotations

from typing import Any

from seagull_mcp.auth import PermissionDeniedError, Principal, normalize_handle
from seagull_mcp.client import SeagullClient


TOOL_REQUIRED_SCOPES = {
    "seagull.list_agents": "agents:read",
    "seagull.get_inbox": "messages:read",
    "seagull.get_thread_context": "messages:read",
    "seagull.send_message": "messages:write",
    "seagull.ack_message": "messages:ack",
    "seagull.open_inbox_ui": "messages:read",
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
            "name": "seagull.send_message",
            "description": "Send a Seagull direct or thread reply message as an accessible agent.",
            "inputSchema": object_schema({
                "sender_handle": string_schema("Owned sender agent handle."),
                "recipient_handles": {
                    "type": "array",
                    "items": string_schema("Recipient agent handle."),
                    "minItems": 1,
                },
                "content": string_schema("Message content to send."),
                "thread_id": string_schema("Optional existing thread ID."),
                "intent": string_schema("Optional message intent."),
            }, required=("sender_handle", "recipient_handles", "content")),
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
        if name == "seagull.send_message":
            return self._send_message(arguments, principal)
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

    def _send_message(self, arguments: dict[str, Any], principal: Principal) -> dict[str, Any]:
        principal.require_scope("messages:write")
        sender_handle = required_string(arguments, "sender_handle")
        principal.require_agent(sender_handle)
        recipients = string_list(arguments.get("recipient_handles"), "recipient_handles")
        content = required_string(arguments, "content")
        result = self._client.send_message(
            sender_handle=normalize_handle(sender_handle),
            recipient_handles=tuple(normalize_handle(handle) for handle in recipients),
            content=content,
            thread_id=optional_string(arguments, "thread_id"),
            intent=optional_string(arguments, "intent") or "message",
        )
        return tool_result(result, f"Sent Seagull message {result.get('message_id')}.")

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


def bounded_int(value: Any, field_name: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return min(max(value, minimum), maximum)
