from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest import TestCase
from urllib import parse

from seagull_mcp.auth import (
    ALL_SCOPES,
    InMemoryConnectorTokenStore,
    TokenVerificationError,
    issue_connector_token,
    parse_connector_token,
    verify_bearer_token,
)
from seagull_mcp.client import SeagullHttpClient
from seagull_mcp.cognito import CognitoJwtVerifier, CognitoPrincipalResolver
from seagull_mcp.oauth_proxy import CognitoOAuthProxy
from seagull_mcp.server import McpConnectorApp
from seagull_mcp.server import allowed_origin_for


class FakeSeagullClient:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.acked_messages: list[dict[str, object]] = []
        self.created_tasks: list[dict[str, object]] = []
        self.accepted_tasks: list[dict[str, object]] = []
        self.updated_tasks: list[dict[str, object]] = []
        self.returned_results: list[dict[str, object]] = []
        self.uploaded_artifacts: list[dict[str, object]] = []
        self.context_requests: list[dict[str, object]] = []

    def list_agents(self, handles: tuple[str, ...]) -> list[dict[str, object]]:
        return [{"handle": handle, "status": "active"} for handle in handles]

    def get_inbox(self, handle: str, *, limit: int) -> dict[str, object]:
        return {
            "items": [
                {
                    "delivery": {
                        "delivery_id": "delivery_1",
                        "message_id": "message_1",
                        "thread_id": "thread_1",
                        "recipient_handle": handle,
                    },
                    "message": {
                        "message_id": "message_1",
                        "thread_id": "thread_1",
                        "content_inline": "hello",
                    },
                }
            ][:limit]
        }

    def get_thread_context(self, thread_id: str) -> dict[str, object]:
        return {"thread": {"thread_id": thread_id}, "recent_messages": []}

    def get_context(
        self,
        *,
        thread_id: str,
        requester_handle: str,
        max_inline_chars: int | None = None,
        max_recent_messages: int | None = None,
        max_payload_refs: int | None = None,
        token_budget_estimate: int | None = None,
    ) -> dict[str, object]:
        self.context_requests.append({
            "thread_id": thread_id,
            "requester_handle": requester_handle,
            "max_inline_chars": max_inline_chars,
            "max_recent_messages": max_recent_messages,
            "max_payload_refs": max_payload_refs,
            "token_budget_estimate": token_budget_estimate,
        })
        return {"context_pack_id": "context_pack_1", "thread": {"thread_id": thread_id}, "recent_messages": []}

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        content: str | None = None,
        content_ref: str | None = None,
        refs: tuple[dict[str, object], ...] = (),
        thread_id: str | None = None,
        intent: str = "message",
        visibility: str = "direct",
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        body = {
            "sender_handle": sender_handle,
            "recipient_handles": list(recipient_handles),
            "content": content,
            "content_ref": content_ref,
            "refs": list(refs),
            "thread_id": thread_id,
            "intent": intent,
            "visibility": visibility,
            "idempotency_key": idempotency_key,
        }
        self.sent_messages.append(body)
        return {"message_id": "message_sent", "thread_id": thread_id or "thread_new"}

    def ack_message(self, *, message_id: str, recipient_handle: str) -> dict[str, object]:
        body = {"message_id": message_id, "recipient_handle": recipient_handle}
        self.acked_messages.append(body)
        return {"deliveries": [{"message_id": message_id, "recipient_handle": recipient_handle, "status": "acked"}]}

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
    ) -> dict[str, object]:
        body = {
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
        }
        self.created_tasks.append(body)
        return {"task_id": "task_1", "thread_id": "thread_task", "message_id": "message_task"}

    def accept_task(
        self,
        *,
        task_id: str,
        thread_id: str,
        worker_handle: str,
        requester_handle: str,
        note: str | None = None,
    ) -> dict[str, object]:
        body = {
            "task_id": task_id,
            "thread_id": thread_id,
            "worker_handle": worker_handle,
            "requester_handle": requester_handle,
            "note": note,
        }
        self.accepted_tasks.append(body)
        return {"task_id": task_id, "thread_id": thread_id, "state": "accepted"}

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
    ) -> dict[str, object]:
        body = {
            "task_id": task_id,
            "thread_id": thread_id,
            "actor_handle": actor_handle,
            "recipient_handle": recipient_handle,
            "state": state,
            "note": note,
            "progress": progress,
        }
        self.updated_tasks.append(body)
        return {"task_id": task_id, "thread_id": thread_id, "state": state}

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
    ) -> dict[str, object]:
        body = {
            "task_id": task_id,
            "thread_id": thread_id,
            "responder_handle": responder_handle,
            "requester_handle": requester_handle,
            "state": state,
            "content": content,
            "content_ref": content_ref,
            "artifact_refs": list(artifact_refs),
            "tool_use_summary_refs": list(tool_use_summary_refs),
            "error": error,
        }
        self.returned_results.append(body)
        return {"task_id": task_id, "thread_id": thread_id, "state": state, "message_id": "message_result"}

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
    ) -> dict[str, object]:
        body = {
            "sender_handle": sender_handle,
            "recipient_handles": list(recipient_handles),
            "name": name,
            "content_ref": content_ref,
            "media_type": media_type,
            "thread_id": thread_id,
            "task_id": task_id,
            "description": description,
        }
        self.uploaded_artifacts.append(body)
        return {"artifact_ref": content_ref, "thread_id": thread_id}


class FakeVerifier:
    def __init__(self, claims_by_token: dict[str, dict[str, object]]) -> None:
        self._claims_by_token = claims_by_token

    def verify(self, token: str) -> dict[str, object]:
        if token not in self._claims_by_token:
            raise TokenVerificationError("bad token")
        return self._claims_by_token[token]


class FakeCognitoIdp:
    def __init__(self, attributes_by_username: dict[str, dict[str, str]]) -> None:
        self._attributes_by_username = attributes_by_username

    def admin_get_user(self, *, UserPoolId: str, Username: str) -> dict[str, object]:
        attributes = self._attributes_by_username[Username]
        return {
            "Username": Username,
            "UserAttributes": [
                {"Name": name, "Value": value}
                for name, value in attributes.items()
            ],
        }


class RecordingHttpClient(SeagullHttpClient):
    def __init__(self) -> None:
        super().__init__(message_api_url="https://message.example.com")
        self.requests: list[tuple[str, str, dict[str, object] | None]] = []

    def _request(self, method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
        self.requests.append((method, path, body))
        if path == "/payloads":
            return {"content_ref": "payload://payload_1", "payload": body or {}}
        if path.startswith("/payloads?"):
            return {"content_ref": "payload://payload_1", "payload": {"hash": "sha256:payload"}}
        if path == "/tasks":
            return {"task_id": "task_1", "thread_id": "thread_task", "task": body or {}}
        if path.endswith("/results"):
            task_id = path.split("/")[2]
            return {"task_id": task_id, "thread_id": body.get("thread_id", "thread_task") if body else "thread_task"}
        return {"message_id": "message_1", "thread_id": body.get("thread_id", "thread_1") if body else "thread_1"}


class McpConnectorTest(TestCase):
    def setUp(self) -> None:
        self.store = InMemoryConnectorTokenStore()
        self.client = FakeSeagullClient()
        self.issued = issue_connector_token(
            self.store,
            name="test connector",
            owner_user_id="user_alice",
            scopes=ALL_SCOPES,
            agent_handles=["@alice:gulls.ai"],
            now=datetime(2026, 6, 14, tzinfo=timezone.utc),
        )
        self.app = McpConnectorApp(
            token_store=self.store,
            seagull_client=self.client,
            resource_uri="https://mcp.gulls.ai/mcp",
            admin_secret="admin",
        )

    def test_connector_token_hashes_secret_and_verifies(self) -> None:
        token_id, secret = parse_connector_token(self.issued.token)
        record = self.store.get_token(token_id)

        self.assertIsNotNone(record)
        self.assertNotIn(secret, record.token_hash)

        principal = verify_bearer_token(self.store, self.issued.token)
        self.assertEqual("user_alice", principal.owner_user_id)
        self.assertEqual(frozenset({"@alice:gulls.ai"}), principal.agent_handles)

    def test_revoked_connector_token_fails(self) -> None:
        token_id, _ = parse_connector_token(self.issued.token)
        self.store.revoke_token(token_id, datetime(2026, 6, 14, tzinfo=timezone.utc))

        with self.assertRaises(TokenVerificationError):
            verify_bearer_token(self.store, self.issued.token)

    def test_missing_auth_gets_401_with_metadata_hint(self) -> None:
        response = self.app.handle(method="POST", path="/mcp", headers={}, body=json_rpc("initialize", {}))

        self.assertEqual(401, response.status_code)
        self.assertIn("WWW-Authenticate", response.headers or {})

    def test_cors_origin_uses_configured_allowlist(self) -> None:
        allowed_origins = ("https://chatgpt.com", "https://chat.openai.com")

        self.assertEqual(
            "https://chatgpt.com",
            allowed_origin_for(request_origin="https://chatgpt.com", allowed_origins=allowed_origins),
        )
        self.assertEqual(
            "https://chatgpt.com",
            allowed_origin_for(request_origin="https://evil.example", allowed_origins=allowed_origins),
        )

    def test_no_auth_dev_mode_connects_with_read_only_tool_list(self) -> None:
        app = McpConnectorApp(
            token_store=self.store,
            seagull_client=self.client,
            resource_uri="https://mcp.gulls.ai/mcp",
            no_auth_enabled=True,
            no_auth_agent_handles=("@alice:gulls.ai",),
            no_auth_scopes=("agents:read",),
        )

        init_response = app.handle(method="POST", path="/mcp", headers={}, body=json_rpc("initialize", {}))
        tools_response = app.handle(method="POST", path="/mcp", headers={}, body=json_rpc("tools/list", {}))

        self.assertEqual(200, init_response.status_code)
        self.assertIsInstance(tools_response.body, dict)
        tool_names = [tool["name"] for tool in tools_response.body["result"]["tools"]]
        self.assertEqual(["seagull.list_agents"], tool_names)

    def test_no_auth_dev_mode_blocks_write_tool_call(self) -> None:
        app = McpConnectorApp(
            token_store=self.store,
            seagull_client=self.client,
            resource_uri="https://mcp.gulls.ai/mcp",
            no_auth_enabled=True,
            no_auth_agent_handles=("@alice:gulls.ai",),
            no_auth_scopes=("agents:read",),
        )

        response = app.handle(
            method="POST",
            path="/mcp",
            headers={},
            body=json_rpc(
                "tools/call",
                {
                    "name": "seagull.send_message",
                    "arguments": {
                        "sender_handle": "@alice:gulls.ai",
                        "recipient_handles": ["@bob:gulls.ai"],
                        "content": "hi",
                    },
                },
            ),
        )

        self.assertEqual(200, response.status_code)
        self.assertIsInstance(response.body, dict)
        self.assertEqual(-32003, response.body["error"]["code"])
        self.assertEqual([], self.client.sent_messages)

    def test_initialize_and_tools_list(self) -> None:
        init_response = self.mcp("initialize", {})
        tools_response = self.mcp("tools/list", {})

        self.assertEqual("2025-06-18", init_response["result"]["protocolVersion"])
        tool_names = [tool["name"] for tool in tools_response["result"]["tools"]]
        self.assertIn("seagull.get_inbox", tool_names)
        self.assertIn("seagull.open_inbox_ui", tool_names)
        self.assertIn("seagull.create_task", tool_names)
        self.assertIn("seagull.return_result", tool_names)

    def test_get_inbox_requires_allowed_agent(self) -> None:
        response = self.mcp(
            "tools/call",
            {
                "name": "seagull.get_inbox",
                "arguments": {"agent_handle": "@bob:gulls.ai"},
            },
        )

        self.assertEqual(-32003, response["error"]["code"])

    def test_get_inbox_returns_structured_content_for_allowed_agent(self) -> None:
        response = self.mcp(
            "tools/call",
            {
                "name": "seagull.get_inbox",
                "arguments": {"agent_handle": "@alice:gulls.ai", "limit": 5},
            },
        )

        self.assertEqual("delivery_1", response["result"]["structuredContent"]["items"][0]["delivery"]["delivery_id"])

    def test_get_context_requires_context_scope(self) -> None:
        issued = issue_connector_token(
            self.store,
            name="messages only",
            owner_user_id="user_alice",
            scopes=["messages:read"],
            agent_handles=["@alice:gulls.ai"],
            now=datetime(2026, 6, 14, tzinfo=timezone.utc),
        )
        response = self.app.handle(
            method="POST",
            path="/mcp",
            headers={"authorization": f"Bearer {issued.token}"},
            body=json_rpc(
                "tools/call",
                {
                    "name": "seagull.get_context",
                    "arguments": {"agent_handle": "@alice:gulls.ai", "thread_id": "thread_1"},
                },
            ),
        )

        self.assertEqual(200, response.status_code)
        self.assertIsInstance(response.body, dict)
        self.assertEqual(-32003, response.body["error"]["code"])

    def test_get_context_passes_budget_to_seagull_client(self) -> None:
        response = self.mcp(
            "tools/call",
            {
                "name": "seagull.get_context",
                "arguments": {
                    "agent_handle": "@alice:gulls.ai",
                    "thread_id": "thread_1",
                    "max_inline_chars": 120,
                    "max_recent_messages": 3,
                    "max_payload_refs": 4,
                    "token_budget_estimate": 500,
                },
            },
        )

        self.assertEqual("context_pack_1", response["result"]["structuredContent"]["context_pack_id"])
        self.assertEqual(
            {
                "thread_id": "thread_1",
                "requester_handle": "@alice:gulls.ai",
                "max_inline_chars": 120,
                "max_recent_messages": 3,
                "max_payload_refs": 4,
                "token_budget_estimate": 500,
            },
            self.client.context_requests[0],
        )

    def test_create_task_requires_allowed_requester(self) -> None:
        response = self.mcp(
            "tools/call",
            {
                "name": "seagull.create_task",
                "arguments": {
                    "requester_handle": "@bob:gulls.ai",
                    "recipient_handle": "@alice:gulls.ai",
                    "objective": "review this plan",
                },
            },
        )

        self.assertEqual(-32003, response["error"]["code"])
        self.assertEqual([], self.client.created_tasks)

    def test_create_and_return_task_route_through_seagull_client(self) -> None:
        bob_issued = issue_connector_token(
            self.store,
            name="bob connector",
            owner_user_id="user_bob",
            scopes=ALL_SCOPES,
            agent_handles=["@bob:gulls.ai"],
            now=datetime(2026, 6, 14, tzinfo=timezone.utc),
        )
        created = self.mcp(
            "tools/call",
            {
                "name": "seagull.create_task",
                "arguments": {
                    "requester_handle": "@alice:gulls.ai",
                    "recipient_handle": "@bob:gulls.ai",
                    "objective": "review the protocol boundary",
                    "context_refs": ["thread://thread_1"],
                    "allowed_tool_names": ["repo_read"],
                },
            },
        )
        returned_response = self.app.handle(
            method="POST",
            path="/mcp",
            headers={"authorization": f"Bearer {bob_issued.token}"},
            body=json_rpc(
                "tools/call",
                {
                    "name": "seagull.return_result",
                    "arguments": {
                        "responder_handle": "@bob:gulls.ai",
                        "requester_handle": "@alice:gulls.ai",
                        "task_id": "task_1",
                        "thread_id": "thread_task",
                        "content": "done",
                        "artifact_refs": ["artifact://review_1"],
                    },
                },
            ),
        )

        self.assertEqual(200, returned_response.status_code)
        self.assertIsInstance(returned_response.body, dict)
        self.assertEqual("task_1", created["result"]["structuredContent"]["task_id"])
        self.assertEqual("@alice:gulls.ai", self.client.created_tasks[0]["requester_handle"])
        self.assertEqual(["repo_read"], self.client.created_tasks[0]["allowed_tool_names"])
        returned = returned_response.body
        self.assertEqual("task_1", returned["result"]["structuredContent"]["task_id"])
        self.assertEqual("@bob:gulls.ai", self.client.returned_results[0]["responder_handle"])
        self.assertEqual(["artifact://review_1"], self.client.returned_results[0]["artifact_refs"])

    def test_upload_artifact_requires_allowed_sender(self) -> None:
        response = self.mcp(
            "tools/call",
            {
                "name": "seagull.upload_artifact",
                "arguments": {
                    "sender_handle": "@bob:gulls.ai",
                    "recipient_handles": ["@alice:gulls.ai"],
                    "name": "review",
                    "content_ref": "artifact://review_1",
                },
            },
        )

        self.assertEqual(-32003, response["error"]["code"])
        self.assertEqual([], self.client.uploaded_artifacts)

    def test_http_client_uses_task_record_endpoints(self) -> None:
        client = RecordingHttpClient()

        created = client.create_task(
            requester_handle="@alice:gulls.ai",
            recipient_handle="@bob:gulls.ai",
            objective="review this",
            context_refs=("thread://thread_1",),
        )
        returned = client.return_task_result(
            task_id=created["task_id"],
            thread_id=created["thread_id"],
            responder_handle="@bob:gulls.ai",
            requester_handle="@alice:gulls.ai",
            state="completed",
            content="done",
            artifact_refs=("artifact://review_1",),
        )

        create_body = client.requests[0][2]
        result_body = client.requests[1][2]
        self.assertEqual("POST", client.requests[0][0])
        self.assertEqual("/tasks", client.requests[0][1])
        self.assertIsInstance(create_body, dict)
        self.assertEqual("@alice:gulls.ai", create_body["requester_handle"])
        self.assertEqual("@bob:gulls.ai", create_body["recipient_handle"])
        self.assertEqual(["thread://thread_1"], create_body["context_refs"])
        self.assertEqual("POST", client.requests[1][0])
        self.assertEqual("/tasks/task_1/results", client.requests[1][1])
        self.assertIsInstance(result_body, dict)
        self.assertEqual(returned["task_id"], "task_1")
        self.assertEqual("@bob:gulls.ai", result_body["responder_handle"])
        self.assertEqual(["artifact://review_1"], result_body["artifact_refs"])

    def test_http_client_reads_context_pack_with_budget_query(self) -> None:
        client = RecordingHttpClient()

        client.get_context(
            thread_id="thread_1",
            requester_handle="@alice:gulls.ai",
            max_inline_chars=100,
            max_recent_messages=3,
            max_payload_refs=5,
            token_budget_estimate=1000,
        )

        method, path, body = client.requests[0]
        self.assertEqual("GET", method)
        self.assertIsNone(body)
        self.assertTrue(path.startswith("/threads/thread_1/context-pack?"))
        query = parse.parse_qs(parse.urlsplit(path).query)
        self.assertEqual(["@alice:gulls.ai"], query["requester_handle"])
        self.assertEqual(["100"], query["max_inline_chars"])
        self.assertEqual(["3"], query["max_recent_messages"])
        self.assertEqual(["5"], query["max_payload_refs"])
        self.assertEqual(["1000"], query["token_budget_estimate"])

    def test_http_client_sends_ref_only_messages_and_payload_requests(self) -> None:
        client = RecordingHttpClient()

        payload = client.create_payload(
            content="large",
            media_type="text/markdown",
            access_scope="thread",
            ttl_expires_at="2026-06-28T00:00:00+00:00",
        )
        client.send_message(
            sender_handle="@alice:gulls.ai",
            recipient_handles=("@bob:gulls.ai",),
            content_ref=payload["content_ref"],
        )
        client.read_payload(payload["content_ref"], requester_handle="@bob:gulls.ai")

        self.assertEqual("POST", client.requests[0][0])
        self.assertEqual("/payloads", client.requests[0][1])
        self.assertEqual(
            {
                "content": "large",
                "media_type": "text/markdown",
                "access_scope": "thread",
                "ttl_expires_at": "2026-06-28T00:00:00+00:00",
            },
            client.requests[0][2],
        )
        self.assertEqual("POST", client.requests[1][0])
        self.assertEqual("/messages", client.requests[1][1])
        message_body = client.requests[1][2]
        self.assertIsInstance(message_body, dict)
        self.assertEqual("payload://payload_1", message_body["content_ref"])
        self.assertNotIn("content", message_body)
        self.assertEqual("GET", client.requests[2][0])
        self.assertEqual(
            "/payloads?content_ref=payload%3A%2F%2Fpayload_1&requester_handle=%40bob%3Agulls.ai",
            client.requests[2][1],
        )

    def test_send_message_requires_allowed_sender(self) -> None:
        response = self.mcp(
            "tools/call",
            {
                "name": "seagull.send_message",
                "arguments": {
                    "sender_handle": "@bob:gulls.ai",
                    "recipient_handles": ["@alice:gulls.ai"],
                    "content": "hi",
                },
            },
        )

        self.assertEqual(-32003, response["error"]["code"])
        self.assertEqual([], self.client.sent_messages)

    def test_send_message_calls_seagull_for_allowed_sender(self) -> None:
        response = self.mcp(
            "tools/call",
            {
                "name": "seagull.send_message",
                "arguments": {
                    "sender_handle": "@alice:gulls.ai",
                    "recipient_handles": ["@bob:gulls.ai"],
                    "content": "hi",
                    "thread_id": "thread_1",
                },
            },
        )

        self.assertEqual("message_sent", response["result"]["structuredContent"]["message_id"])
        self.assertEqual("@alice:gulls.ai", self.client.sent_messages[0]["sender_handle"])

    def test_send_message_accepts_content_ref_without_inline_content(self) -> None:
        response = self.mcp(
            "tools/call",
            {
                "name": "seagull.send_message",
                "arguments": {
                    "sender_handle": "@alice:gulls.ai",
                    "recipient_handles": ["@bob:gulls.ai"],
                    "content_ref": "payload://payload_1",
                    "thread_id": "thread_1",
                },
            },
        )

        self.assertEqual("message_sent", response["result"]["structuredContent"]["message_id"])
        self.assertIsNone(self.client.sent_messages[0]["content"])
        self.assertEqual("payload://payload_1", self.client.sent_messages[0]["content_ref"])

    def test_ack_message_calls_seagull_for_allowed_recipient(self) -> None:
        response = self.mcp(
            "tools/call",
            {
                "name": "seagull.ack_message",
                "arguments": {
                    "message_id": "message_1",
                    "recipient_handle": "@alice:gulls.ai",
                },
            },
        )

        self.assertEqual("acked", response["result"]["structuredContent"]["deliveries"][0]["status"])
        self.assertEqual("@alice:gulls.ai", self.client.acked_messages[0]["recipient_handle"])

    def test_limited_scope_blocks_send_message(self) -> None:
        issued = issue_connector_token(
            self.store,
            name="read only",
            owner_user_id="user_alice",
            scopes=["messages:read"],
            agent_handles=["@alice:gulls.ai"],
            now=datetime(2026, 6, 14, tzinfo=timezone.utc),
        )
        response = self.app.handle(
            method="POST",
            path="/mcp",
            headers={"authorization": f"Bearer {issued.token}"},
            body=json_rpc(
                "tools/call",
                {
                    "name": "seagull.send_message",
                    "arguments": {
                        "sender_handle": "@alice:gulls.ai",
                        "recipient_handles": ["@bob:gulls.ai"],
                        "content": "hi",
                    },
                },
            ),
        )

        self.assertEqual(200, response.status_code)
        self.assertIsInstance(response.body, dict)
        self.assertEqual(-32003, response.body["error"]["code"])

    def test_cognito_claim_validation_accepts_current_access_token(self) -> None:
        verifier = CognitoJwtVerifier(
            user_pool_id="pool_1",
            app_client_id="client_1",
            region="ap-southeast-2",
        )

        verifier.validate_claims(
            {
                "iss": "https://cognito-idp.ap-southeast-2.amazonaws.com/pool_1",
                "token_use": "access",
                "client_id": "client_1",
                "exp": 2000,
            },
            now_epoch=1000,
        )

    def test_cognito_claim_validation_rejects_bad_or_expired_tokens(self) -> None:
        verifier = CognitoJwtVerifier(
            user_pool_id="pool_1",
            app_client_id="client_1",
            region="ap-southeast-2",
        )
        valid_claims = {
            "iss": "https://cognito-idp.ap-southeast-2.amazonaws.com/pool_1",
            "token_use": "access",
            "client_id": "client_1",
            "exp": 2000,
        }

        for patch in (
            {"iss": "https://issuer.example.com"},
            {"token_use": "id"},
            {"client_id": "other_client"},
            {"exp": 999},
        ):
            claims = {**valid_claims, **patch}
            with self.assertRaises(TokenVerificationError):
                verifier.validate_claims(claims, now_epoch=1000)

    def test_cognito_oauth_user_can_only_act_as_mapped_agent(self) -> None:
        app = McpConnectorApp(
            token_store=self.store,
            seagull_client=self.client,
            resource_uri="https://mcp.gulls.ai/mcp",
            cognito_resolver=CognitoPrincipalResolver(
                verifier=FakeVerifier({
                    "alice-token": {
                        "username": "seagull-alice",
                        "jti": "token_alice",
                    },
                    "bob-token": {
                        "username": "seagull-bob",
                        "jti": "token_bob",
                    }
                }),
                user_pool_id="pool_1",
                identity_provider=FakeCognitoIdp({
                    "seagull-alice": {
                        "custom:sg_owner_id": "user_alice",
                        "custom:sg_handles": "@alice:gulls.ai",
                        "custom:sg_scopes": "agents:read,messages:read,messages:write,messages:ack",
                    },
                    "seagull-bob": {
                        "custom:sg_owner_id": "user_bob",
                        "custom:sg_handles": "@bob:gulls.ai",
                        "custom:sg_scopes": "agents:read,messages:read,messages:write,messages:ack",
                    }
                }),
            ),
        )

        allowed = app.handle(
            method="POST",
            path="/mcp",
            headers={"authorization": "Bearer alice-token"},
            body=json_rpc(
                "tools/call",
                {
                    "name": "seagull.send_message",
                    "arguments": {
                        "sender_handle": "@alice:gulls.ai",
                        "recipient_handles": ["@bob:gulls.ai"],
                        "content": "hello Bob",
                    },
                },
            ),
        )
        denied = app.handle(
            method="POST",
            path="/mcp",
            headers={"authorization": "Bearer alice-token"},
            body=json_rpc(
                "tools/call",
                {
                    "name": "seagull.send_message",
                    "arguments": {
                        "sender_handle": "@bob:gulls.ai",
                        "recipient_handles": ["@alice:gulls.ai"],
                        "content": "hello Alice",
                    },
                },
            ),
        )
        bob_denied = app.handle(
            method="POST",
            path="/mcp",
            headers={"authorization": "Bearer bob-token"},
            body=json_rpc(
                "tools/call",
                {
                    "name": "seagull.send_message",
                    "arguments": {
                        "sender_handle": "@alice:gulls.ai",
                        "recipient_handles": ["@bob:gulls.ai"],
                        "content": "I am Alice",
                    },
                },
            ),
        )

        self.assertEqual(200, allowed.status_code)
        self.assertIsInstance(allowed.body, dict)
        self.assertEqual("message_sent", allowed.body["result"]["structuredContent"]["message_id"])
        self.assertEqual(200, denied.status_code)
        self.assertIsInstance(denied.body, dict)
        self.assertEqual(-32003, denied.body["error"]["code"])
        self.assertEqual(200, bob_denied.status_code)
        self.assertIsInstance(bob_denied.body, dict)
        self.assertEqual(-32003, bob_denied.body["error"]["code"])

    def test_cognito_oauth_long_claims_control_tools_list(self) -> None:
        app = McpConnectorApp(
            token_store=self.store,
            seagull_client=self.client,
            resource_uri="https://mcp.gulls.ai/mcp",
            cognito_resolver=CognitoPrincipalResolver(
                verifier=FakeVerifier({
                    "alice-read-token": {
                        "username": "seagull-alice",
                        "jti": "token_alice_read",
                        "custom:seagull_owner_user_id": "user_alice",
                        "custom:seagull_agent_handles": "@alice:gulls.ai",
                        "custom:seagull_scopes": "agents:read",
                    }
                }),
                user_pool_id="pool_1",
                identity_provider=FakeCognitoIdp({"seagull-alice": {}}),
            ),
        )

        response = app.handle(
            method="POST",
            path="/mcp",
            headers={"authorization": "Bearer alice-read-token"},
            body=json_rpc("tools/list", {}),
        )

        self.assertEqual(200, response.status_code)
        self.assertIsInstance(response.body, dict)
        tool_names = [tool["name"] for tool in response.body["result"]["tools"]]
        self.assertEqual(["seagull.list_agents"], tool_names)

    def test_oauth_authorize_proxy_strips_unsupported_scopes(self) -> None:
        app = McpConnectorApp(
            token_store=self.store,
            seagull_client=self.client,
            resource_uri="https://mcp.gulls.ai/mcp",
            oauth_proxy=CognitoOAuthProxy(
                authorization_url="https://cognito.example.com/oauth2/authorize",
                token_url="https://cognito.example.com/oauth2/token",
                client_id="client_1",
            ),
        )

        response = app.handle(
            method="GET",
            path="/oauth/authorize",
            headers={},
            body=None,
            query={
                "client_id": "chatgpt_client",
                "response_type": "code",
                "redirect_uri": "https://chatgpt.com/connector/oauth/callback",
                "scope": "openid email profile offline_access messages:read",
                "state": "state_1",
                "code_challenge": "challenge_1",
                "code_challenge_method": "S256",
            },
        )

        self.assertEqual(302, response.status_code)
        location = (response.headers or {})["location"]
        query = parse.parse_qs(parse.urlsplit(location).query)
        self.assertEqual(["client_1"], query["client_id"])
        self.assertEqual(["openid email profile"], query["scope"])
        self.assertEqual(["state_1"], query["state"])
        self.assertEqual(["challenge_1"], query["code_challenge"])

    def test_admin_token_api_shows_token_once_and_lists_without_secret(self) -> None:
        response = self.app.handle(
            method="POST",
            path="/connector-tokens",
            headers={"x-seagull-admin-secret": "admin"},
            body=json.dumps(
                {
                    "name": "byo",
                    "owner_user_id": "user_bob",
                    "agent_handles": ["@bob:gulls.ai"],
                    "scopes": ["agents:read"],
                }
            ),
        )
        created = response.body

        self.assertEqual(201, response.status_code)
        self.assertIsInstance(created, dict)
        self.assertTrue(created["token"].startswith("sgc_"))
        self.assertNotIn("token_hash", created["record"])

        list_response = self.app.handle(
            method="GET",
            path="/connector-tokens",
            headers={"x-seagull-admin-secret": "admin"},
            body=None,
            query={"owner_user_id": "user_bob"},
        )

        self.assertEqual(200, list_response.status_code)
        self.assertNotIn(created["token"], json.dumps(list_response.body))

    def mcp(self, method: str, params: dict[str, object]) -> dict[str, object]:
        response = self.app.handle(
            method="POST",
            path="/mcp",
            headers={"authorization": f"Bearer {self.issued.token}"},
            body=json_rpc(method, params),
        )
        self.assertEqual(200, response.status_code)
        self.assertIsInstance(response.body, dict)
        return response.body


def json_rpc(method: str, params: dict[str, object]) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": "req_1", "method": method, "params": params})
