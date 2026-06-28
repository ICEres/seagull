from __future__ import annotations

import json
from typing import Any, Protocol
from urllib import error, parse, request


class SeagullClient(Protocol):
    def list_agents(self, handles: tuple[str, ...]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_inbox(self, handle: str, *, limit: int) -> dict[str, Any]:
        raise NotImplementedError

    def get_thread_context(self, thread_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def get_context(
        self,
        *,
        thread_id: str,
        requester_handle: str,
        max_inline_chars: int | None = None,
        max_recent_messages: int | None = None,
        max_payload_refs: int | None = None,
        token_budget_estimate: int | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        content: str,
        content_ref: str | None = None,
        refs: tuple[dict[str, Any], ...] = (),
        thread_id: str | None = None,
        intent: str = "message",
        visibility: str = "direct",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def ack_message(self, *, message_id: str, recipient_handle: str) -> dict[str, Any]:
        raise NotImplementedError

    def create_task(
        self,
        *,
        requester_handle: str,
        recipient_handle: str,
        objective: str,
        context_refs: tuple[str, ...] = (),
        context_pack_id: str | None = None,
        context_pack_ref: str | None = None,
        input_ref: str | None = None,
        allowed_tool_names: tuple[str, ...] = (),
        allowed_use_terms: tuple[str, ...] = (),
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def accept_task(
        self,
        *,
        task_id: str,
        thread_id: str,
        worker_handle: str,
        requester_handle: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def update_task(
        self,
        *,
        task_id: str,
        thread_id: str,
        actor_handle: str,
        recipient_handle: str,
        state: str,
        note: str | None = None,
        progress: int | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def return_task_result(
        self,
        *,
        task_id: str,
        thread_id: str,
        responder_handle: str,
        requester_handle: str,
        state: str,
        content: str | None = None,
        content_ref: str | None = None,
        artifact_refs: tuple[str, ...] = (),
        tool_use_summary_refs: tuple[str, ...] = (),
        error: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def upload_artifact(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        name: str,
        content_ref: str,
        media_type: str | None = None,
        thread_id: str | None = None,
        task_id: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class SeagullHttpClient:
    def __init__(self, *, message_api_url: str, timeout_seconds: int = 10) -> None:
        self._message_api_url = message_api_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def list_agents(self, handles: tuple[str, ...]) -> list[dict[str, Any]]:
        agents = []
        for handle in handles:
            encoded = parse.quote(handle, safe="")
            try:
                agents.append(self._request("GET", f"/agents/{encoded}")["agent"])
            except SeagullClientError:
                agents.append({"handle": handle, "status": "unknown"})
        return agents

    def get_inbox(self, handle: str, *, limit: int) -> dict[str, Any]:
        encoded = parse.quote(handle, safe="")
        return self._request("GET", f"/agents/{encoded}/inbox?limit={limit}")

    def get_thread_context(self, thread_id: str) -> dict[str, Any]:
        encoded = parse.quote(thread_id, safe="")
        return self._request("GET", f"/threads/{encoded}/context")

    def get_context(
        self,
        *,
        thread_id: str,
        requester_handle: str,
        max_inline_chars: int | None = None,
        max_recent_messages: int | None = None,
        max_payload_refs: int | None = None,
        token_budget_estimate: int | None = None,
    ) -> dict[str, Any]:
        encoded_thread = parse.quote(thread_id, safe="")
        query = {
            "requester_handle": requester_handle,
            "max_inline_chars": max_inline_chars,
            "max_recent_messages": max_recent_messages,
            "max_payload_refs": max_payload_refs,
            "token_budget_estimate": token_budget_estimate,
        }
        return self._request("GET", f"/threads/{encoded_thread}/context-pack?{urlencode_without_none(query)}")

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        content: str,
        content_ref: str | None = None,
        refs: tuple[dict[str, Any], ...] = (),
        thread_id: str | None = None,
        intent: str = "message",
        visibility: str = "direct",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "sender_handle": sender_handle,
            "recipient_handles": list(recipient_handles),
            "content": content,
            "intent": intent,
            "visibility": visibility,
        }
        if content_ref is not None:
            body["content_ref"] = content_ref
        if refs:
            body["refs"] = list(refs)
        if thread_id is not None:
            body["thread_id"] = thread_id
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", "/messages", body)

    def ack_message(self, *, message_id: str, recipient_handle: str) -> dict[str, Any]:
        encoded = parse.quote(message_id, safe="")
        return self._request("POST", f"/messages/{encoded}/ack", {"recipient_handle": recipient_handle})

    def create_task(
        self,
        *,
        requester_handle: str,
        recipient_handle: str,
        objective: str,
        context_refs: tuple[str, ...] = (),
        context_pack_id: str | None = None,
        context_pack_ref: str | None = None,
        input_ref: str | None = None,
        allowed_tool_names: tuple[str, ...] = (),
        allowed_use_terms: tuple[str, ...] = (),
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body = without_none({
            "requester_handle": requester_handle,
            "recipient_handle": recipient_handle,
            "objective": objective,
            "context_refs": list(context_refs),
            "context_pack_id": context_pack_id,
            "context_pack_ref": context_pack_ref,
            "input_ref": input_ref,
            "allowed_tool_names": list(allowed_tool_names),
            "allowed_use_terms": list(allowed_use_terms),
            "idempotency_key": idempotency_key,
        })
        return self._request("POST", "/tasks", body)

    def accept_task(
        self,
        *,
        task_id: str,
        thread_id: str,
        worker_handle: str,
        requester_handle: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        encoded_task = parse.quote(task_id, safe="")
        return self._request(
            "POST",
            f"/tasks/{encoded_task}/accept",
            without_none({
                "thread_id": thread_id,
                "worker_handle": worker_handle,
                "requester_handle": requester_handle,
                "note": note,
            }),
        )

    def update_task(
        self,
        *,
        task_id: str,
        thread_id: str,
        actor_handle: str,
        recipient_handle: str,
        state: str,
        note: str | None = None,
        progress: int | None = None,
    ) -> dict[str, Any]:
        encoded_task = parse.quote(task_id, safe="")
        return self._request(
            "POST",
            f"/tasks/{encoded_task}/status",
            without_none({
                "thread_id": thread_id,
                "actor_handle": actor_handle,
                "recipient_handle": recipient_handle,
                "state": state,
                "note": note,
                "progress": progress,
            }),
        )

    def return_task_result(
        self,
        *,
        task_id: str,
        thread_id: str,
        responder_handle: str,
        requester_handle: str,
        state: str,
        content: str | None = None,
        content_ref: str | None = None,
        artifact_refs: tuple[str, ...] = (),
        tool_use_summary_refs: tuple[str, ...] = (),
        error: str | None = None,
    ) -> dict[str, Any]:
        encoded_task = parse.quote(task_id, safe="")
        body = without_none({
            "thread_id": thread_id,
            "responder_handle": responder_handle,
            "requester_handle": requester_handle,
            "state": state,
            "content": content,
            "content_ref": content_ref,
            "artifact_refs": list(artifact_refs),
            "tool_use_summary_refs": list(tool_use_summary_refs),
            "error": error,
        })
        return self._request("POST", f"/tasks/{encoded_task}/results", body)

    def upload_artifact(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        name: str,
        content_ref: str,
        media_type: str | None = None,
        thread_id: str | None = None,
        task_id: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        payload = without_none({
            "schema_version": "seagull.artifact_share.v1",
            "name": name,
            "content_ref": content_ref,
            "media_type": media_type,
            "task_id": task_id,
            "description": description,
        })
        result = self.send_message(
            sender_handle=sender_handle,
            recipient_handles=recipient_handles,
            content=compact_json(payload),
            content_ref=content_ref,
            thread_id=thread_id,
            intent="artifact_share",
        )
        return {**result, "artifact_ref": content_ref, "artifact": payload}

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        req = request.Request(
            f"{self._message_api_url}{path}",
            data=data,
            method=method,
            headers={"content-type": "application/json", "accept": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except error.HTTPError as exc:
            payload = exc.read().decode("utf-8")
            raise SeagullClientError(exc.code, payload) from exc
        except error.URLError as exc:
            raise SeagullClientError(502, str(exc)) from exc
        return json.loads(payload or "{}")


class SeagullClientError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def compact_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def urlencode_without_none(query: dict[str, Any]) -> str:
    return parse.urlencode({key: value for key, value in query.items() if value is not None})
