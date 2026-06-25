from __future__ import annotations

import json
from typing import Any, Protocol
from urllib import error, parse, request


class SeagullAgentClient(Protocol):
    def get_agent(self, handle: str) -> dict[str, Any]:
        raise NotImplementedError

    def get_inbox(self, handle: str, *, limit: int) -> dict[str, Any]:
        raise NotImplementedError

    def get_thread(self, thread_id: str, *, limit: int) -> dict[str, Any]:
        raise NotImplementedError

    def get_thread_context(self, thread_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        content: str,
        thread_id: str | None = None,
        intent: str = "message",
        visibility: str = "direct",
    ) -> dict[str, Any]:
        raise NotImplementedError

    def ack_message(self, *, message_id: str, recipient_handle: str) -> dict[str, Any]:
        raise NotImplementedError

    def decide_delivery(
        self,
        *,
        delivery_id: str,
        agent_handle: str,
        decision: str,
        content: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class SeagullHttpClient:
    def __init__(
        self,
        *,
        api_url: str,
        token: str | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def get_agent(self, handle: str) -> dict[str, Any]:
        encoded = parse.quote(handle, safe="")
        return self._request("GET", f"/agents/{encoded}")

    def get_inbox(self, handle: str, *, limit: int) -> dict[str, Any]:
        encoded = parse.quote(handle, safe="")
        query = parse.urlencode({"limit": limit})
        return self._request("GET", f"/agents/{encoded}/inbox?{query}")

    def get_thread(self, thread_id: str, *, limit: int) -> dict[str, Any]:
        encoded = parse.quote(thread_id, safe="")
        query = parse.urlencode({"limit": limit})
        return self._request("GET", f"/threads/{encoded}?{query}")

    def get_thread_context(self, thread_id: str) -> dict[str, Any]:
        encoded = parse.quote(thread_id, safe="")
        return self._request("GET", f"/threads/{encoded}/context")

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        content: str,
        thread_id: str | None = None,
        intent: str = "message",
        visibility: str = "direct",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "sender_handle": sender_handle,
            "recipient_handles": list(recipient_handles),
            "content": content,
            "intent": intent,
            "visibility": visibility,
        }
        if thread_id is not None:
            body["thread_id"] = thread_id
        return self._request("POST", "/messages", body)

    def ack_message(self, *, message_id: str, recipient_handle: str) -> dict[str, Any]:
        encoded = parse.quote(message_id, safe="")
        return self._request("POST", f"/messages/{encoded}/ack", {"recipient_handle": recipient_handle})

    def decide_delivery(
        self,
        *,
        delivery_id: str,
        agent_handle: str,
        decision: str,
        content: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "agent_handle": agent_handle,
            "decision": decision,
        }
        if content is not None:
            body["content"] = content
        if note is not None:
            body["note"] = note
        encoded = parse.quote(delivery_id, safe="")
        return self._request("POST", f"/deliveries/{encoded}/decision", body)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {
            "accept": "application/json",
            "user-agent": "seagull/0.1",
        }
        if body is not None:
            headers["content-type"] = "application/json"
        if self._token is not None:
            headers["authorization"] = f"Bearer {self._token}"

        req = request.Request(f"{self._api_url}{path}", data=data, method=method, headers=headers)
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
