from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from ai_provider.domain import AiProviderService
from ai_provider.providers import FakeProviderAdapter
from ai_provider.storage import InMemoryAiProviderRepository


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


def load_lambda_module() -> types.ModuleType:
    env = {
        "AI_ADMIN_AUDIT_EVENTS_TABLE": "admin-audit",
        "AI_BUDGET_LIMITS_TABLE": "budget-limits",
        "AI_MODEL_POLICIES_TABLE": "model-policies",
        "AI_PROVIDER_ADMIN_SECRET": "admin-secret",
        "AI_PROVIDER_CONFIGS_TABLE": "provider-configs",
        "AI_RUN_EVENTS_TABLE": "run-events",
        "AI_RUNS_TABLE": "runs",
        "AI_SERVER_CREDIT_LEDGER_TABLE": "server-credit-ledger",
        "AI_USAGE_LEDGER_TABLE": "usage-ledger",
        "AI_USER_CREDIT_LEDGER_TABLE": "user-credit-ledger",
    }
    module_name = "_ai_provider_lambda_for_test"
    path = Path(__file__).resolve().parents[1] / "aws" / "lambda_function.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ai-provider Lambda module")

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
    with patch.dict(os.environ, env, clear=False), patch.dict(sys.modules, fake_modules):
        spec.loader.exec_module(module)

    repository = InMemoryAiProviderRepository()
    service = AiProviderService(repository, {"fake": FakeProviderAdapter()})
    service.grant_server_credits(admin_actor_id="admin_1", credit_amount=10_000, reason="test server credits")
    service.grant_user_credits(admin_actor_id="admin_1", owner_user_id="user_1", credit_amount=1000, reason="test credits")
    module.service = service
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


def run_body(owner_user_id: str = "user_1") -> dict[str, object]:
    return {
        "provider": "fake",
        "model": "fake-small",
        "actor_agent_id": "agent_1",
        "owner_user_id": owner_user_id,
        "input_messages": [{"role": "user", "content": "Summarize this thread."}],
        "max_output_tokens": 32,
    }


def body(response: dict[str, object]) -> dict[str, object]:
    return json.loads(response["body"])


class AiProviderLambdaAuthTest(TestCase):
    def setUp(self) -> None:
        self.lambda_module = load_lambda_module()

    def test_create_run_rejects_missing_authentication(self) -> None:
        response = self.lambda_module.handler(event("POST", "/ai-runs", body=run_body()), None)

        self.assertEqual(401, response["statusCode"])
        self.assertEqual("authentication is required", body(response)["message"])

    def test_create_run_rejects_owner_mismatch(self) -> None:
        response = self.lambda_module.handler(
            event(
                "POST",
                "/ai-runs",
                body=run_body(owner_user_id="user_2"),
                claims={"custom:seagull_user_id": "user_1"},
            ),
            None,
        )

        self.assertEqual(401, response["statusCode"])
        self.assertEqual("owner_user_id does not match authenticated user", body(response)["message"])

    def test_create_run_accepts_matching_owner_claim(self) -> None:
        response = self.lambda_module.handler(
            event("POST", "/ai-runs", body=run_body(), claims={"custom:seagull_user_id": "user_1"}),
            None,
        )

        self.assertEqual(200, response["statusCode"])
        self.assertEqual("user_1", body(response)["run"]["owner_user_id"])

    def test_owner_usage_requires_matching_owner_claim(self) -> None:
        self.lambda_module.handler(
            event("POST", "/ai-runs", body=run_body(), claims={"custom:seagull_user_id": "user_1"}),
            None,
        )

        allowed = self.lambda_module.handler(
            event("GET", "/owners/user_1/ai-usage", claims={"custom:seagull_user_id": "user_1"}),
            None,
        )
        denied = self.lambda_module.handler(
            event("GET", "/owners/user_1/ai-usage", claims={"custom:seagull_user_id": "user_2"}),
            None,
        )

        self.assertEqual(200, allowed["statusCode"])
        self.assertEqual(1, len(body(allowed)["usage"]))
        self.assertEqual(401, denied["statusCode"])

    def test_agent_usage_is_admin_only(self) -> None:
        self.lambda_module.handler(
            event("POST", "/ai-runs", body=run_body(), claims={"custom:seagull_user_id": "user_1"}),
            None,
        )

        user_response = self.lambda_module.handler(
            event("GET", "/agents/agent_1/ai-usage", claims={"custom:seagull_user_id": "user_1"}),
            None,
        )
        admin_response = self.lambda_module.handler(
            event("GET", "/agents/agent_1/ai-usage", headers={"x-seagull-admin-secret": "admin-secret"}),
            None,
        )

        self.assertEqual(401, user_response["statusCode"])
        self.assertEqual(200, admin_response["statusCode"])
        self.assertEqual(1, len(body(admin_response)["usage"]))

    def test_admin_claim_can_read_admin_endpoint_without_shared_secret(self) -> None:
        response = self.lambda_module.handler(
            event("GET", "/admin/ai-credits/server-balance", claims={"cognito:groups": "seagull-admin"}),
            None,
        )

        self.assertEqual(200, response["statusCode"])
        self.assertEqual(9000, body(response)["balance"]["available_credits"])
