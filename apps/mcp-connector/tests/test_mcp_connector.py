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
from seagull_mcp.cognito import CognitoJwtVerifier, CognitoPrincipalResolver
from seagull_mcp.oauth_proxy import CognitoOAuthProxy
from seagull_mcp.server import McpConnectorApp


class FakeSeagullClient:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.acked_messages: list[dict[str, object]] = []

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

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        content: str,
        thread_id: str | None = None,
        intent: str = "message",
    ) -> dict[str, object]:
        body = {
            "sender_handle": sender_handle,
            "recipient_handles": list(recipient_handles),
            "content": content,
            "thread_id": thread_id,
            "intent": intent,
        }
        self.sent_messages.append(body)
        return {"message_id": "message_sent", "thread_id": thread_id or "thread_new"}

    def ack_message(self, *, message_id: str, recipient_handle: str) -> dict[str, object]:
        body = {"message_id": message_id, "recipient_handle": recipient_handle}
        self.acked_messages.append(body)
        return {"deliveries": [{"message_id": message_id, "recipient_handle": recipient_handle, "status": "acked"}]}


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
