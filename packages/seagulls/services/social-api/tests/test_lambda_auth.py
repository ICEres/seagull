from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError

from social_api.domain import SocialApiService
from social_api.storage import InMemorySocialRepository


class FakeBoto3(types.ModuleType):
    def resource(self, service_name: str) -> "FakeDynamoDbResource":
        self.resource_name = service_name
        return FakeDynamoDbResource()


class FakeDynamoDbResource:
    def Table(self, table_name: str) -> object:
        return object()


class FakeKey:
    def __init__(self, name: str) -> None:
        self.name = name

    def eq(self, value: object) -> tuple[str, str, object]:
        return ("eq", self.name, value)


def load_lambda_module(*, auth_required: str | None = None, auth_bypass_secret: str | None = None) -> types.ModuleType:
    env = {
        "AGENT_ASSET_BINDINGS_TABLE": "agent-asset-bindings",
        "AGENT_CHAT_MESSAGES_TABLE": "agent-chat-messages",
        "AGENT_CHATS_TABLE": "agent-chats",
        "FEED_EVENTS_TABLE": "feed-events",
        "FOLLOWS_TABLE": "follows",
        "IDENTITIES_TABLE": "identities",
        "MODERATION_TABLE": "moderation",
        "NODES_TABLE": "nodes",
        "NOTIFICATIONS_TABLE": "notifications",
        "PAIR_TOKENS_TABLE": "pair-tokens",
        "PERSONAL_AGENT_ASSETS_TABLE": "personal-agent-assets",
        "POSTS_TABLE": "posts",
        "PROFILES_TABLE": "profiles",
        "ROOM_MEMBERSHIPS_TABLE": "room-memberships",
        "ROOMS_TABLE": "rooms",
    }
    if auth_required is not None:
        env["SOCIAL_AUTH_REQUIRED"] = auth_required
    if auth_bypass_secret is not None:
        env["SOCIAL_AUTH_BYPASS_SECRET"] = auth_bypass_secret

    module_name = "_social_api_lambda_for_test"
    path = Path(__file__).resolve().parents[1] / "aws" / "lambda_function.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load social API Lambda module")

    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(module_name, None)
    fake_dynamodb = types.ModuleType("boto3.dynamodb")
    fake_conditions = types.ModuleType("boto3.dynamodb.conditions")
    fake_conditions.Key = FakeKey
    fake_modules = {
        "boto3": FakeBoto3("boto3"),
        "boto3.dynamodb": fake_dynamodb,
        "boto3.dynamodb.conditions": fake_conditions,
    }
    with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, fake_modules):
        spec.loader.exec_module(module)

    module.service = SocialApiService(InMemorySocialRepository())
    return module


def event(
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    claims: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
) -> dict[str, object]:
    request: dict[str, object] = {
        "rawPath": path,
        "headers": headers or {},
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
            },
        },
    }
    if body is not None:
        request["body"] = json.dumps(body)
    if claims is not None:
        request["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}  # type: ignore[index]
    if query is not None:
        request["queryStringParameters"] = query
    return request


def response_body(response: dict[str, object]) -> dict[str, object]:
    return json.loads(response["body"])


class FakeMessageHubPoster:
    """Records message-hub POSTs; optionally fails the first /messages call."""

    def __init__(self, *, fail_first_send_with: int | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._fail_first_send_with = fail_first_send_with

    def __call__(self, base_url: str, path: str, body: dict[str, object]) -> dict[str, object]:
        self.calls.append((path, body))
        if path == "/agents":
            return {"created": True, "agent": {"handle": body.get("handle")}}
        if path != "/messages":
            raise AssertionError(f"unexpected message hub path: {path}")
        if self._fail_first_send_with is not None:
            code = self._fail_first_send_with
            self._fail_first_send_with = None
            raise HTTPError(f"{base_url}{path}", code, "hub error", None, None)
        return {
            "thread_id": "thread_1",
            "message": {"message_id": "message_1", "thread_id": "thread_1"},
        }


class FakeAiProviderRunClient:
    """Stands in for the AI provider: one completed run with output."""

    def create_run(self, request: dict[str, object]) -> dict[str, object]:
        return {"run_id": "run_1", "state": "completed", "output_text": "reply from the agent"}


class FakeLambdaPayload:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = json.dumps(value).encode("utf-8")
        self.closed = False

    def read(self) -> bytes:
        return self.value

    def close(self) -> None:
        self.closed = True


class FakeLambdaClient:
    def __init__(self, payload: dict[str, object], *, function_error: str | None = None) -> None:
        self.payload = FakeLambdaPayload(payload)
        self.function_error = function_error
        self.calls: list[dict[str, object]] = []

    def invoke(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        result: dict[str, object] = {"Payload": self.payload}
        if self.function_error is not None:
            result["FunctionError"] = self.function_error
        return result


class FakeBotocoreConfig(types.ModuleType):
    class Config:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs


class SocialApiLambdaChatDeliveryTest(TestCase):
    CLAIMS = {"sub": "alice-sub", "email": "alice@example.com"}
    HUB_ENV = {"MESSAGE_API_URL": "https://hub.test"}

    def load_module_with_hub(self, poster: FakeMessageHubPoster) -> types.ModuleType:
        lambda_module = load_lambda_module()
        lambda_module.service = SocialApiService(
            InMemorySocialRepository(),
            agent_registry=lambda_module.MessageHubAgentRegistry(),
        )
        lambda_module.post_message_hub_json = poster
        return lambda_module

    def create_chat(self, lambda_module: types.ModuleType) -> str:
        for handle in ("@alice:seagull.local", "@assistant:seagull.local"):
            response = lambda_module.handler(
                event("POST", "/profiles", body={"handle": handle}, claims=self.CLAIMS),
                None,
            )
            self.assertEqual(200, response["statusCode"])
        chat_response = lambda_module.handler(
            event(
                "POST",
                "/agent-chats",
                body={
                    "agent_handle": "@assistant:seagull.local",
                    "sender_handle": "@alice:seagull.local",
                },
                claims=self.CLAIMS,
            ),
            None,
        )
        self.assertEqual(200, chat_response["statusCode"])
        return response_body(chat_response)["chat"]["chat_id"]

    def send_chat_message(self, lambda_module: types.ModuleType, chat_id: str) -> dict[str, object]:
        response = lambda_module.handler(
            event(
                "POST",
                f"/agent-chats/{chat_id}/messages",
                body={"content": "Plan the MVP."},
                claims=self.CLAIMS,
            ),
            None,
        )
        self.assertEqual(200, response["statusCode"])
        return response_body(response)["message"]

    def test_profile_creation_registers_handles_and_send_does_not_reregister(self) -> None:
        poster = FakeMessageHubPoster()
        lambda_module = self.load_module_with_hub(poster)

        with patch.dict(os.environ, self.HUB_ENV):
            chat_id = self.create_chat(lambda_module)

            self.assertEqual(
                ["@alice:seagull.local", "@assistant:seagull.local"],
                [body["handle"] for path, body in poster.calls if path == "/agents"],
            )

            poster.calls.clear()
            message = self.send_chat_message(lambda_module, chat_id)

        self.assertEqual(["/messages"], [path for path, _ in poster.calls])
        self.assertEqual("delivered", message["delivery_status"])
        self.assertEqual("message_1", message["hub_message_id"])
        self.assertEqual("thread_1", message["hub_thread_id"])

    def test_send_backfills_unregistered_legacy_agents_once_and_retries(self) -> None:
        poster = FakeMessageHubPoster(fail_first_send_with=404)
        lambda_module = self.load_module_with_hub(poster)

        with patch.dict(os.environ, self.HUB_ENV):
            chat_id = self.create_chat(lambda_module)
            poster.calls.clear()
            message = self.send_chat_message(lambda_module, chat_id)

        self.assertEqual(
            ["/messages", "/agents", "/agents", "/messages"],
            [path for path, _ in poster.calls],
        )
        self.assertEqual(
            ["@alice:seagull.local", "@assistant:seagull.local"],
            [body["handle"] for path, body in poster.calls if path == "/agents"],
        )
        self.assertEqual("delivered", message["delivery_status"])

    def test_send_non_404_hub_error_records_delivery_failed_without_backfill(self) -> None:
        poster = FakeMessageHubPoster(fail_first_send_with=500)
        lambda_module = self.load_module_with_hub(poster)

        with patch.dict(os.environ, self.HUB_ENV):
            chat_id = self.create_chat(lambda_module)
            poster.calls.clear()
            message = self.send_chat_message(lambda_module, chat_id)

        self.assertEqual(["/messages"], [path for path, _ in poster.calls])
        self.assertEqual("delivery_failed", message["delivery_status"])
        self.assertIn("500", message["delivery_error"])

    def enable_ai_replies(self, lambda_module: types.ModuleType) -> None:
        lambda_module.AI_PROVIDER_API_URL = "https://ai.test"
        lambda_module.AI_PROVIDER_ADMIN_SECRET = "admin-secret"
        lambda_module.AI_REPLY_PROVIDER = "anthropic"
        lambda_module.AI_REPLY_MODEL = "claude-test"
        lambda_module.AiProviderRunClient = FakeAiProviderRunClient

    def test_the_agent_reply_is_delivered_back_through_the_hub(self) -> None:
        """Both sides of the conversation reach gulls, in one thread.

        Delivering only the human's message would leave gulls holding half of
        every conversation -- which is exactly what a chat read cutover would
        then surface.
        """
        poster = FakeMessageHubPoster()
        lambda_module = self.load_module_with_hub(poster)
        self.enable_ai_replies(lambda_module)

        with patch.dict(os.environ, self.HUB_ENV):
            chat_id = self.create_chat(lambda_module)
            poster.calls.clear()
            response = lambda_module.handler(
                event(
                    "POST",
                    f"/agent-chats/{chat_id}/messages",
                    body={"content": "Plan the MVP."},
                    claims=self.CLAIMS,
                ),
                None,
            )

        self.assertEqual(200, response["statusCode"])
        self.assertEqual(["/messages", "/messages"], [path for path, _ in poster.calls])

        inbound, outbound = (body for _, body in poster.calls)
        self.assertEqual("@alice:seagull.local", inbound["sender_handle"])
        self.assertEqual(["@assistant:seagull.local"], inbound["recipient_handles"])
        # Reversed, and in the thread the first delivery stamped on the session.
        self.assertEqual("@assistant:seagull.local", outbound["sender_handle"])
        self.assertEqual(["@alice:seagull.local"], outbound["recipient_handles"])
        self.assertEqual("reply from the agent", outbound["content"])
        self.assertEqual("thread_1", outbound["thread_id"])

        reply = response_body(response)["reply"]
        self.assertEqual("delivered", reply["delivery_status"])
        self.assertEqual("message_1", reply["hub_message_id"])
        self.assertEqual("thread_1", reply["hub_thread_id"])


class SocialApiLambdaAuthTest(TestCase):
    def test_agent_network_inbox_is_scoped_to_owned_gull(self) -> None:
        lambda_module = load_lambda_module()
        claims = {"sub": "alice-sub", "email": "alice@example.com"}
        lambda_module.handler(
            event("POST", "/profiles", body={"handle": "@alice:seagull.local"}, claims=claims),
            None,
        )
        lambda_module.owner_hub_read = lambda handle, owner, path: {
            "agent": {"handle": handle},
            "items": [],
            "next_cursor": None,
        }

        allowed = lambda_module.handler(
            event(
                "GET",
                "/agent-network/inbox",
                claims=claims,
                query={"agent_handle": "@alice:seagull.local"},
            ),
            None,
        )
        self.assertEqual(200, allowed["statusCode"])

        denied = lambda_module.handler(
            event(
                "GET",
                "/agent-network/inbox",
                claims={"sub": "bob-sub", "email": "bob@example.com"},
                query={"agent_handle": "@alice:seagull.local"},
            ),
            None,
        )
        self.assertEqual(403, denied["statusCode"])

    def test_agent_network_send_validates_owned_sender_and_keeps_cloud_mode(self) -> None:
        lambda_module = load_lambda_module()
        claims = {"sub": "alice-sub", "email": "alice@example.com"}
        lambda_module.handler(
            event("POST", "/profiles", body={"handle": "@alice:seagull.local"}, claims=claims),
            None,
        )
        calls: list[dict[str, object]] = []

        def fake_hub(*args: object, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs.get("body", {}))
            return {"message_id": "message_1", "thread_id": "thread_1", "deliveries": []}

        lambda_module.message_hub_json = fake_hub
        sent = lambda_module.handler(
            event(
                "POST",
                "/agent-network/messages",
                claims=claims,
                body={
                    "sender_handle": "@alice:seagull.local",
                    "recipient_handles": ["@other:seagull.local"],
                    "content": "Hello",
                    "idempotency_key": "mobile-1",
                },
            ),
            None,
        )
        self.assertEqual(201, sent["statusCode"])
        self.assertEqual("@alice:seagull.local", calls[0]["sender_handle"])
        self.assertEqual("cloud", calls[0]["runtime_mode"])
        self.assertEqual("mobile-1", calls[0]["idempotency_key"])

        denied = lambda_module.handler(
            event(
                "POST",
                "/agent-network/messages",
                claims=claims,
                body={
                    "sender_handle": "@other:seagull.local",
                    "recipient_handles": ["@alice:seagull.local"],
                    "content": "Impersonate",
                },
            ),
            None,
        )
        self.assertEqual(404, denied["statusCode"])

    def test_message_hub_bridge_preserves_safe_http_status(self) -> None:
        lambda_module = load_lambda_module()

        def failing_urlopen(request: object, timeout: float) -> object:
            raise HTTPError("https://hub.test/agent/threads/missing", 404, "not found", None, None)

        lambda_module.urlopen = failing_urlopen
        with self.assertRaises(lambda_module.MessageHubRequestError) as raised:
            lambda_module.message_hub_json("https://hub.test", "/agent/threads/missing")
        self.assertEqual(404, raised.exception.status_code)
        self.assertNotIn("not found", str(raised.exception))

    def test_agent_network_sent_is_owner_scoped_and_enriches_public_handles(self) -> None:
        lambda_module = load_lambda_module()
        claims = {"sub": "alice-sub", "email": "alice@example.com"}
        lambda_module.handler(
            event("POST", "/profiles", body={"handle": "@alice:seagull.local"}, claims=claims),
            None,
        )

        class AgentTable:
            def get_item(self, *, Key: dict[str, str]) -> dict[str, object]:
                if Key["agent_id"] == "hub_alice":
                    return {"Item": {"agent_id": "hub_alice", "handle": "@alice:seagull.local", "display_name": "Alice"}}
                return {"Item": {"agent_id": "hub_other", "handle": "@other:seagull.local", "display_name": "Other"}}

        lambda_module.dynamodb.Table = lambda name: AgentTable()
        lambda_module.owner_hub_read = lambda handle, owner, path: {
            "messages": [{
                "message_id": "m1",
                "sender_agent_id": "hub_alice",
                "recipient_agent_ids": ["hub_other"],
            }],
        }
        with patch.dict(os.environ, {"GULLS_AGENTS_TABLE": "hub-agents"}):
            sent = lambda_module.handler(
                event("GET", "/agent-network/sent", claims=claims, query={"agent_handle": "@alice:seagull.local"}),
                None,
            )
        self.assertEqual(200, sent["statusCode"])
        body = response_body(sent)
        self.assertEqual("@alice:seagull.local", body["messages"][0]["sender_handle"])
        self.assertEqual(["@other:seagull.local"], body["messages"][0]["recipient_handles"])
        self.assertFalse(body["truncated"])

        denied = lambda_module.handler(
            event(
                "GET",
                "/agent-network/sent",
                claims={"sub": "bob-sub", "email": "bob@example.com"},
                query={"agent_handle": "@alice:seagull.local"},
            ),
            None,
        )
        self.assertEqual(403, denied["statusCode"])

    def test_agent_projection_failure_preserves_other_public_metadata(self) -> None:
        lambda_module = load_lambda_module()

        class AgentTable:
            def get_item(self, *, Key: dict[str, str]) -> dict[str, object]:
                if Key["agent_id"] == "hub_failed":
                    raise RuntimeError("temporary projection failure")
                return {
                    "Item": {
                        "agent_id": "hub_good",
                        "handle": "@good:seagull.local",
                        "display_name": "Good",
                        "owner_user_id": "private-owner",
                        "secret": "private-secret",
                    }
                }

        lambda_module.dynamodb.Table = lambda name: AgentTable()
        payload = {
            "messages": [{
                "message_id": "m1",
                "sender_agent_id": "hub_good",
                "recipient_agent_ids": ["hub_failed"],
            }],
        }
        with patch.dict(os.environ, {"GULLS_AGENTS_TABLE": "hub-agents"}):
            enriched = lambda_module.enrich_owner_hub_payload(payload)

        message = enriched["messages"][0]
        self.assertEqual("@good:seagull.local", message["sender_handle"])
        self.assertEqual("Good", message["sender_display_name"])
        self.assertEqual(["hub_good"], [agent["agent_id"] for agent in enriched["agents"]])
        self.assertNotIn("owner_user_id", enriched["agents"][0])
        self.assertNotIn("secret", enriched["agents"][0])

    def test_missing_auth_env_defaults_to_required(self) -> None:
        lambda_module = load_lambda_module()

        response = lambda_module.handler(
            event(
                "POST",
                "/profiles",
                body={"owner_user_id": "user_victim", "handle": "@attacker:seagull.local"},
            ),
            None,
        )

        self.assertTrue(lambda_module.SOCIAL_AUTH_REQUIRED)
        self.assertEqual(401, response["statusCode"])
        self.assertEqual("authentication is required", response_body(response)["message"])

    def test_my_ai_usage_proxies_current_identity_to_provider(self) -> None:
        lambda_module = load_lambda_module()
        claims = {"sub": "alice-sub", "email": "alice@example.com"}
        identity = lambda_module.service.identify_human(
            provider="cognito",
            subject="alice-sub",
            email="alice@example.com",
        )
        summary = {
            "owner_user_id": identity.user_id,
            "balance": {"owner_user_id": identity.user_id, "available_credits": 20000},
            "usage": [],
            "entries": [],
        }
        lambda_module.AI_PROVIDER_API_URL = "https://ai-provider.test"
        lambda_module.AI_PROVIDER_ADMIN_SECRET = "provider-secret"

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(summary).encode("utf-8")

        requests: list[object] = []

        def fake_urlopen(request: object, timeout: float) -> FakeResponse:
            requests.append(request)
            return FakeResponse()

        lambda_module.urlopen = fake_urlopen
        response = lambda_module.handler(
            event("GET", "/me/ai-usage", claims=claims, query={"owner_user_id": "spoofed"}),
            None,
        )
        self.assertEqual(200, response["statusCode"])
        self.assertEqual(summary, response_body(response))
        self.assertEqual(1, len(requests))
        self.assertIn(f"/owners/{identity.user_id}/ai-usage-summary", requests[0].full_url)
        self.assertEqual(
            "provider-secret",
            next(value for key, value in requests[0].headers.items() if key.casefold() == "x-seagull-admin-secret"),
        )

        unauthenticated = lambda_module.handler(event("GET", "/me/ai-usage"), None)
        self.assertEqual(401, unauthenticated["statusCode"])

        lambda_module.urlopen = lambda request, timeout: (_ for _ in ()).throw(RuntimeError("provider down"))
        unavailable = lambda_module.handler(event("GET", "/me/ai-usage", claims=claims), None)
        self.assertEqual(503, unavailable["statusCode"])

    def test_my_ai_usage_uses_lambda_provider_transport_and_maps_failures(self) -> None:
        lambda_module = load_lambda_module()
        claims = {"sub": "alice-sub", "email": "alice@example.com"}
        identity = lambda_module.service.identify_human(
            provider="cognito",
            subject="alice-sub",
            email="alice@example.com",
        )
        lambda_module.AI_PROVIDER_FUNCTION_ARN = "arn:aws:lambda:ap-southeast-2:123:function:ai-provider"
        lambda_module.AI_PROVIDER_API_URL = ""
        lambda_module.AI_PROVIDER_ADMIN_SECRET = "provider-secret"
        summary = {
            "owner_user_id": identity.user_id,
            "balance": {"owner_user_id": identity.user_id, "available_credits": 20_000},
            "usage": [],
            "entries": [],
        }

        success_client = FakeLambdaClient(
            {"statusCode": 200, "body": json.dumps(summary)},
        )
        fake_botocore = types.ModuleType("botocore")
        fake_botocore_config = FakeBotocoreConfig("botocore.config")

        def invoke_with_client(client: FakeLambdaClient) -> dict[str, object]:
            lambda_module.boto3.client = lambda service_name, **kwargs: client
            with patch.dict(
                sys.modules,
                {"botocore": fake_botocore, "botocore.config": fake_botocore_config},
            ):
                return lambda_module.handler(event("GET", "/me/ai-usage", claims=claims), None)

        success = invoke_with_client(success_client)
        self.assertEqual(200, success["statusCode"])
        self.assertEqual(summary, response_body(success))
        self.assertEqual(1, len(success_client.calls))
        invoked = json.loads(success_client.calls[0]["Payload"])
        self.assertEqual("GET", invoked["requestContext"]["http"]["method"])
        self.assertEqual(
            f"/owners/{identity.user_id}/ai-usage-summary",
            invoked["rawPath"],
        )
        self.assertEqual("provider-secret", invoked["headers"]["x-seagull-admin-secret"])

        for payload, function_error in (
            ({"statusCode": 500, "body": "{}"}, None),
            ({"statusCode": 200, "body": "{}"}, "Unhandled"),
        ):
            with self.subTest(payload=payload, function_error=function_error):
                failed_client = FakeLambdaClient(payload, function_error=function_error)
                failed = invoke_with_client(failed_client)
                self.assertEqual(503, failed["statusCode"])

    def test_prompt_routes_are_owner_scoped_and_preserve_saved_prompt_on_bad_put(self) -> None:
        lambda_module = load_lambda_module()
        alice_claims = {"sub": "alice-sub", "email": "alice@example.com"}
        bob_claims = {"sub": "bob-sub", "email": "bob@example.com"}
        encoded_path = "/profiles/%40prompt-gull%3Aseagull.local/prompt"

        created = lambda_module.handler(
            event(
                "POST",
                "/profiles",
                body={"handle": "@prompt-gull:seagull.local"},
                claims=alice_claims,
            ),
            None,
        )
        self.assertEqual(200, created["statusCode"])

        saved = lambda_module.handler(
            event("PUT", encoded_path, body={"instructions": "Reply calmly."}, claims=alice_claims),
            None,
        )
        self.assertEqual(200, saved["statusCode"])
        self.assertEqual("Reply calmly.", response_body(saved)["prompt"]["instructions"])

        read = lambda_module.handler(event("GET", encoded_path, claims=alice_claims), None)
        self.assertEqual(200, read["statusCode"])
        self.assertEqual("Reply calmly.", response_body(read)["prompt"]["instructions"])

        for malformed_body in ({}, {"instructions": None}):
            with self.subTest(malformed_body=malformed_body):
                malformed = lambda_module.handler(
                    event("PUT", encoded_path, body=malformed_body, claims=alice_claims),
                    None,
                )
                self.assertEqual(400, malformed["statusCode"])
                still_saved = lambda_module.handler(event("GET", encoded_path, claims=alice_claims), None)
                self.assertEqual("Reply calmly.", response_body(still_saved)["prompt"]["instructions"])

        spoofed_query = lambda_module.handler(
            event("GET", encoded_path, claims=alice_claims, query={"owner_user_id": "user_other"}),
            None,
        )
        self.assertEqual(403, spoofed_query["statusCode"])
        spoofed_body = lambda_module.handler(
            event(
                "PUT",
                encoded_path,
                body={"owner_user_id": "user_other", "instructions": "Spoofed."},
                claims=alice_claims,
            ),
            None,
        )
        self.assertEqual(403, spoofed_body["statusCode"])

        for method, body in (("GET", None), ("PUT", {"instructions": "Other owner."})):
            with self.subTest(method=method):
                denied = lambda_module.handler(
                    event(method, encoded_path, body=body, claims=bob_claims),
                    None,
                )
                self.assertEqual(403, denied["statusCode"])

        unauthenticated = lambda_module.handler(event("GET", encoded_path), None)
        self.assertEqual(401, unauthenticated["statusCode"])

        reset = lambda_module.handler(event("PUT", encoded_path, body={"instructions": ""}, claims=alice_claims), None)
        self.assertEqual(200, reset["statusCode"])
        self.assertIsNone(response_body(reset)["prompt"])
        reset_read = lambda_module.handler(event("GET", encoded_path, claims=alice_claims), None)
        self.assertIsNone(response_body(reset_read)["prompt"])

    def test_ai_reply_enabled_accepts_direct_lambda_transport(self) -> None:
        lambda_module = load_lambda_module()
        lambda_module.AI_PROVIDER_FUNCTION_ARN = "arn:aws:lambda:ap-southeast-2:123:function:ai-provider"
        lambda_module.AI_PROVIDER_API_URL = ""
        lambda_module.AI_PROVIDER_ADMIN_SECRET = "admin-secret"
        lambda_module.AI_REPLY_PROVIDER = "bedrock"
        lambda_module.AI_REPLY_MODEL = "amazon.nova-micro-v1:0"

        self.assertTrue(lambda_module.ai_reply_enabled())

    def test_direct_ai_provider_invocation_builds_gateway_event_and_closes_payload(self) -> None:
        lambda_module = load_lambda_module()
        lambda_module.AI_PROVIDER_FUNCTION_ARN = "arn:aws:lambda:ap-southeast-2:123:function:ai-provider"
        lambda_module.AI_PROVIDER_API_URL = ""
        lambda_module.AI_PROVIDER_ADMIN_SECRET = "admin-secret"
        lambda_module.AI_REPLY_PROVIDER = "bedrock"
        lambda_module.AI_REPLY_MODEL = "amazon.nova-micro-v1:0"
        fake_client = FakeLambdaClient(
            {"statusCode": 200, "body": json.dumps({"run": {"run_id": "run_1"}})}
        )
        client_options: dict[str, object] = {}

        def fake_boto3_client(service_name: str, **kwargs: object) -> FakeLambdaClient:
            client_options.update(kwargs)
            return fake_client

        lambda_module.boto3.client = fake_boto3_client
        fake_botocore = types.ModuleType("botocore")
        fake_botocore_config = FakeBotocoreConfig("botocore.config")

        with patch.dict(
            sys.modules,
            {"botocore": fake_botocore, "botocore.config": fake_botocore_config},
        ):
            run = lambda_module.AiProviderRunClient().create_run({"owner_user_id": "user_1"})

        self.assertEqual({"run_id": "run_1"}, run)
        self.assertTrue(fake_client.payload.closed)
        config = client_options["config"]
        self.assertEqual(3.0, config.kwargs["connect_timeout"])
        self.assertEqual(20.0, config.kwargs["read_timeout"])
        self.assertEqual({"max_attempts": 0}, config.kwargs["retries"])
        self.assertEqual(1, len(fake_client.calls))
        call = fake_client.calls[0]
        self.assertEqual(lambda_module.AI_PROVIDER_FUNCTION_ARN, call["FunctionName"])
        self.assertEqual("RequestResponse", call["InvocationType"])
        invoke_event = json.loads(call["Payload"])
        self.assertEqual("POST", invoke_event["requestContext"]["http"]["method"])
        self.assertEqual("/ai-runs", invoke_event["rawPath"])
        self.assertEqual("admin-secret", invoke_event["headers"]["x-seagull-admin-secret"])
        request_body = json.loads(invoke_event["body"])
        self.assertEqual("bedrock", request_body["provider"])
        self.assertEqual("amazon.nova-micro-v1:0", request_body["model"])

    def test_direct_ai_provider_errors_do_not_expose_admin_secret(self) -> None:
        lambda_module = load_lambda_module()
        lambda_module.AI_PROVIDER_FUNCTION_ARN = "arn:aws:lambda:ap-southeast-2:123:function:ai-provider"
        lambda_module.AI_PROVIDER_ADMIN_SECRET = "super-secret"
        lambda_module.AI_REPLY_PROVIDER = "bedrock"
        lambda_module.AI_REPLY_MODEL = "amazon.nova-micro-v1:0"
        fake_botocore = types.ModuleType("botocore")
        fake_botocore_config = FakeBotocoreConfig("botocore.config")

        with patch.dict(
            sys.modules,
            {"botocore": fake_botocore, "botocore.config": fake_botocore_config},
        ):
            for payload, function_error in (
                ({"statusCode": 403, "body": "forbidden super-secret"}, None),
                ({"statusCode": 200, "body": "{}"}, None),
                ({"statusCode": 200, "body": "{}"}, "Unhandled"),
            ):
                fake_client = FakeLambdaClient(payload, function_error=function_error)
                lambda_module.boto3.client = lambda service_name, client=fake_client, **kwargs: client
                with self.assertRaises(RuntimeError) as raised:
                    lambda_module.AiProviderRunClient().create_run({"owner_user_id": "user_1"})
                self.assertNotIn("super-secret", str(raised.exception))
                self.assertTrue(fake_client.payload.closed)

            class RaisingLambdaClient:
                def invoke(self, **kwargs: object) -> dict[str, object]:
                    raise RuntimeError("transport failure super-secret")

            lambda_module.boto3.client = lambda service_name, **kwargs: RaisingLambdaClient()
            with self.assertRaises(RuntimeError) as raised:
                lambda_module.AiProviderRunClient().create_run({"owner_user_id": "user_1"})
            self.assertNotIn("super-secret", str(raised.exception))

    def test_authenticated_profile_create_uses_jwt_identity(self) -> None:
        lambda_module = load_lambda_module()

        response = lambda_module.handler(
            event(
                "POST",
                "/profiles",
                body={"handle": "@researcher:seagull.local"},
                claims={"sub": "alice-sub", "email": "alice@example.com"},
            ),
            None,
        )

        payload = response_body(response)
        self.assertEqual(200, response["statusCode"])
        self.assertEqual("@researcher:seagull.local", payload["profile"]["handle"])
        self.assertTrue(payload["profile"]["owner_user_id"].startswith("user_"))

    def test_identity_create_requires_authenticated_identity_by_default(self) -> None:
        lambda_module = load_lambda_module()

        response = lambda_module.handler(
            event(
                "POST",
                "/identities",
                body={"provider": "local", "subject": "attacker"},
            ),
            None,
        )

        self.assertEqual(401, response["statusCode"])
        self.assertEqual("authentication is required", response_body(response)["message"])

    def test_identity_create_uses_jwt_claims(self) -> None:
        lambda_module = load_lambda_module()

        response = lambda_module.handler(
            event(
                "POST",
                "/identities",
                body={"provider": "local", "subject": "attacker"},
                claims={"sub": "alice-sub", "email": "alice@example.com"},
            ),
            None,
        )

        payload = response_body(response)
        self.assertEqual(200, response["statusCode"])
        self.assertEqual("cognito", payload["identity"]["provider"])
        self.assertEqual("alice-sub", payload["identity"]["subject"])

    def test_auth_disabled_still_requires_bypass_secret_for_owner_routes(self) -> None:
        lambda_module = load_lambda_module(auth_required="false", auth_bypass_secret="dev-secret")

        response = lambda_module.handler(
            event(
                "POST",
                "/profiles",
                body={"owner_user_id": "user_victim", "handle": "@attacker:seagull.local"},
            ),
            None,
        )

        self.assertEqual(401, response["statusCode"])
        self.assertEqual("auth bypass secret is required", response_body(response)["message"])

    def test_auth_disabled_accepts_bypass_secret_for_owner_routes(self) -> None:
        lambda_module = load_lambda_module(auth_required="false", auth_bypass_secret="dev-secret")
        identity_response = lambda_module.handler(
            event(
                "POST",
                "/identities",
                body={"provider": "local", "subject": "dev"},
                headers={"x-seagull-auth-bypass-secret": "dev-secret"},
            ),
            None,
        )
        owner_user_id = response_body(identity_response)["identity"]["user_id"]

        response = lambda_module.handler(
            event(
                "POST",
                "/profiles",
                body={"owner_user_id": owner_user_id, "handle": "@dev:seagull.local"},
                headers={"x-seagull-auth-bypass-secret": "dev-secret"},
            ),
            None,
        )

        payload = response_body(response)
        self.assertEqual(200, response["statusCode"])
        self.assertEqual(owner_user_id, payload["profile"]["owner_user_id"])


class EnvFlagTest(TestCase):
    """Every gulls cutover flag ships off.

    An unset or unparseable value must read as False rather than enabling a
    cutover by accident, so this pins the parse rather than trusting it.
    """

    def setUp(self) -> None:
        self.module = load_lambda_module()

    def test_only_explicit_truthy_values_enable_a_flag(self) -> None:
        for value in ("1", "true", "TRUE", " yes ", "Yes"):
            with patch.dict(os.environ, {"SOME_FLAG": value}, clear=False):
                self.assertTrue(self.module._env_flag("SOME_FLAG"), f"{value!r} should enable")

    def test_anything_else_leaves_a_flag_off(self) -> None:
        for value in ("", "0", "false", "no", "maybe", "  "):
            with patch.dict(os.environ, {"SOME_FLAG": value}, clear=False):
                self.assertFalse(self.module._env_flag("SOME_FLAG"), f"{value!r} should not enable")

    def test_an_unset_flag_is_off(self) -> None:
        os.environ.pop("DEFINITELY_UNSET_FLAG", None)

        self.assertFalse(self.module._env_flag("DEFINITELY_UNSET_FLAG"))

    def test_require_agent_registry_is_off_unless_asked_for(self) -> None:
        """The deployment decision PR #4 described but left unreachable."""
        self.assertFalse(self.module._env_flag("REQUIRE_AGENT_REGISTRY"))

        with patch.dict(os.environ, {"REQUIRE_AGENT_REGISTRY": "true"}, clear=False):
            self.assertTrue(self.module._env_flag("REQUIRE_AGENT_REGISTRY"))
