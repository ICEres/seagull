from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from safety_gateway.domain import SafetyGatewayService
from safety_gateway.storage import InMemorySafetyAuditRepository


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


def load_lambda_module(*, admin_secret: str = "safety-secret") -> types.ModuleType:
    env = {
        "AUDIT_TABLE": "audit-events",
        "SAFETY_GATEWAY_ADMIN_SECRET": admin_secret,
    }

    module_name = "_safety_gateway_lambda_for_test"
    path = Path(__file__).resolve().parents[1] / "aws" / "lambda_function.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load safety gateway Lambda module")

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

    audit_repository = InMemorySafetyAuditRepository()
    module.audit_repository = audit_repository
    module.safety_service = SafetyGatewayService(audit_repository)
    return module


def event(
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    claims: dict[str, object] | None = None,
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


class SafetyGatewayLambdaAuthTest(TestCase):
    def test_health_is_public(self) -> None:
        lambda_module = load_lambda_module()

        response = lambda_module.handler(event("GET", "/health"), None)

        self.assertEqual(200, response["statusCode"])

    def test_evaluate_requires_authentication(self) -> None:
        lambda_module = load_lambda_module()

        response = lambda_module.handler(
            event("POST", "/evaluate", body={"actor_id": "agent_1", "content": "hello"}),
            None,
        )

        self.assertEqual(401, response["statusCode"])
        self.assertEqual("authentication is required", response_body(response)["message"])

    def test_evaluate_accepts_safety_secret(self) -> None:
        lambda_module = load_lambda_module()

        response = lambda_module.handler(
            event(
                "POST",
                "/evaluate",
                body={"actor_id": "agent_1", "content": "hello"},
                headers={"x-seagull-safety-secret": "safety-secret"},
            ),
            None,
        )

        self.assertEqual(200, response["statusCode"])
        self.assertEqual("allow", response_body(response)["decision"]["action"])

    def test_audit_accepts_admin_claim(self) -> None:
        lambda_module = load_lambda_module()
        lambda_module.handler(
            event(
                "POST",
                "/evaluate",
                body={"actor_id": "agent_1", "content": "hello"},
                headers={"x-seagull-safety-secret": "safety-secret"},
            ),
            None,
        )

        response = lambda_module.handler(
            event("GET", "/audit", claims={"cognito:groups": "seagull-admin"}),
            None,
        )

        self.assertEqual(200, response["statusCode"])
        self.assertEqual(1, len(response_body(response)["items"]))

    def test_auth_fails_closed_when_secret_is_not_configured(self) -> None:
        lambda_module = load_lambda_module(admin_secret="")

        response = lambda_module.handler(
            event("POST", "/evaluate", body={"actor_id": "agent_1", "content": "hello"}),
            None,
        )

        self.assertEqual(401, response["statusCode"])
        self.assertEqual("safety gateway auth is not configured", response_body(response)["message"])
