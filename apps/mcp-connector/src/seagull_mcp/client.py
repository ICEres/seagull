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

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        content: str,
        thread_id: str | None = None,
        intent: str = "message",
    ) -> dict[str, Any]:
        raise NotImplementedError

    def ack_message(self, *, message_id: str, recipient_handle: str) -> dict[str, Any]:
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

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        content: str,
        thread_id: str | None = None,
        intent: str = "message",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "sender_handle": sender_handle,
            "recipient_handles": list(recipient_handles),
            "content": content,
            "intent": intent,
        }
        if thread_id is not None:
            body["thread_id"] = thread_id
        return self._request("POST", "/messages", body)

    def ack_message(self, *, message_id: str, recipient_handle: str) -> dict[str, Any]:
        encoded = parse.quote(message_id, safe="")
        return self._request("POST", f"/messages/{encoded}/ack", {"recipient_handle": recipient_handle})

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
