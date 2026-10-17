from __future__ import annotations

import importlib.util
import io
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

from test_lambda_auth import event, load_lambda_module, response_body


HUB_LAMBDA_PATH = Path(__file__).resolve().parents[4] / "gulls" / "services" / "message-hub" / "aws" / "lambda_function.py"


class FakeSecretsManager:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
        return {"SecretString": self.values[SecretId]}


class FakeBoto3(types.ModuleType):
    def __init__(self, values: dict[str, str]) -> None:
        super().__init__("boto3")
        self.secrets = FakeSecretsManager(values)

    def client(self, service_name: str) -> FakeSecretsManager:
        if service_name != "secretsmanager":
            raise AssertionError(f"unexpected boto3 client: {service_name}")
        return self.secrets


def load_hub_lambda() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_message_hub_delivery_auth_lambda", HUB_LAMBDA_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Message Hub Lambda module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InMemoryHubTransport:
    """Pass urllib requests into the real Message Hub Lambda handler."""

    def __init__(self, hub_lambda: types.ModuleType, hub_secret_arn: str, boto3_module: FakeBoto3) -> None:
        self.hub_lambda = hub_lambda
        self.hub_secret_arn = hub_secret_arn
        self.boto3_module = boto3_module

    def __call__(self, request: object, timeout: float) -> object:
        del timeout
        url = request.full_url  # type: ignore[attr-defined]
        headers = {key.lower(): value for key, value in request.header_items()}  # type: ignore[attr-defined]
        body = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        hub_event = event("POST", "/messages", body=body, headers=headers)
        # Each Lambda has its own environment in production. Keep the Hub's
        # expected ARN stable while the Social side tests absent/wrong values.
        hub_env = {
            "MESSAGE_HUB_LEGACY_ROUTE_SECRET_ARN": self.hub_secret_arn,
            "MESSAGE_HUB_ALLOW_HANDLE_AGENT_ROUTES": "",
        }
        with patch.dict(os.environ, hub_env), patch.dict(sys.modules, {"boto3": self.boto3_module}):
            response = self.hub_lambda.handler(hub_event, None)
        status = int(response["statusCode"])
        raw = str(response["body"]).encode("utf-8")
        if status >= 400:
            with HTTPError(url, status, "message hub error", None, io.BytesIO(raw)) as error:
                raise error
        return io.BytesIO(raw)


class SocialChatDeliveryAuthTest(TestCase):
    CLAIMS = {"sub": "alice-sub", "email": "alice@example.com"}
    SECRET_ARN = "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:message-hub-route"

    def setUp(self) -> None:
        self.boto3 = FakeBoto3({self.SECRET_ARN: "shared-secret", "arn:wrong": "wrong-secret"})
        self.social_lambda = load_lambda_module()
        self.social_lambda.boto3 = self.boto3
        self.hub_lambda = load_hub_lambda()
        self.hub_lambda.reset_runtime()
        self.hub_lambda.configure_api(self.hub_lambda.LocalMessageHubApi.in_memory())
        self.hub_service = self.hub_lambda.get_api()._service  # noqa: SLF001 - test transport setup
        for handle in ("@alice:seagull.local", "@assistant:seagull.local"):
            self.hub_service.register_agent(handle)
        self.social_lambda.urlopen = InMemoryHubTransport(self.hub_lambda, self.SECRET_ARN, self.boto3)
        self.social_lambda.service = SocialApiService(InMemorySocialRepository())

    def create_chat(self) -> str:
        for handle in ("@alice:seagull.local", "@assistant:seagull.local"):
            response = self.social_lambda.handler(
                event("POST", "/profiles", body={"handle": handle}, claims=self.CLAIMS), None
            )
            self.assertEqual(200, response["statusCode"])
        response = self.social_lambda.handler(
            event(
                "POST",
                "/agent-chats",
                body={"agent_handle": "@assistant:seagull.local", "sender_handle": "@alice:seagull.local"},
                claims=self.CLAIMS,
            ),
            None,
        )
        self.assertEqual(200, response["statusCode"])
        return str(response_body(response)["chat"]["chat_id"])

    def send(self, chat_id: str) -> dict[str, object]:
        with patch.dict(sys.modules, {"boto3": self.boto3}):
            response = self.social_lambda.handler(
                event(
                    "POST",
                    f"/agent-chats/{chat_id}/messages",
                    body={"content": "hello"},
                    claims=self.CLAIMS,
                ),
                None,
            )
        self.assertEqual(200, response["statusCode"])
        return response_body(response)["message"]

    def test_absent_secret_persists_401_delivery_failure(self) -> None:
        chat_id = self.create_chat()
        with patch.dict(os.environ, {"MESSAGE_API_URL": "https://hub.test"}, clear=True):
            message = self.send(chat_id)
        self.assertEqual("delivery_failed", message["delivery_status"])
        self.assertIn("401", str(message["delivery_error"]))
        stored = self.social_lambda.service._repository.get_agent_chat_message(  # noqa: SLF001
            message["chat_message_id"]
        )
        self.assertEqual("delivery_failed", stored.delivery_status)

    def test_wrong_secret_persists_401_delivery_failure(self) -> None:
        chat_id = self.create_chat()
        with patch.dict(
            os.environ,
            {
                "MESSAGE_API_URL": "https://hub.test",
                "MESSAGE_HUB_LEGACY_ROUTE_SECRET_ARN": "arn:wrong",
            },
            clear=True,
        ):
            message = self.send(chat_id)
        self.assertEqual("delivery_failed", message["delivery_status"])
        self.assertIn("401", str(message["delivery_error"]))

    def test_matching_arn_secret_delivers_message_with_hub_ids(self) -> None:
        chat_id = self.create_chat()
        with patch.dict(
            os.environ,
            {
                "MESSAGE_API_URL": "https://hub.test",
                "MESSAGE_HUB_LEGACY_ROUTE_SECRET_ARN": self.SECRET_ARN,
            },
            clear=True,
        ):
            message = self.send(chat_id)
        self.assertEqual("delivered", message["delivery_status"])
        self.assertTrue(message["hub_message_id"])
        self.assertTrue(message["hub_thread_id"])
        hub_messages = self.hub_service._repository.list_thread_messages(  # noqa: SLF001
            message["hub_thread_id"]
        )
        self.assertEqual(["hello"], [item.content_inline for item in hub_messages])
