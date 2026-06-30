from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

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


def load_lambda_module(*, auth_required: str | None = None) -> types.ModuleType:
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
) -> dict[str, object]:
    request: dict[str, object] = {
        "rawPath": path,
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
