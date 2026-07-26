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


class SocialApiLambdaAuthTest(TestCase):
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
