"""AWS Lambda runtime helpers shared across gull services.

Env/secret readers, API Gateway event parsing, and response shaping. Nothing
here imports boto3 at module import time, so handler modules stay importable
in tests without AWS dependencies.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable
from urllib.parse import unquote

from seagull_common.logging import log


def secret_env(name: str) -> str:
    """Read a secret from the env directly, or from Secrets Manager via ``<NAME>_ARN``."""
    direct = os.environ.get(name, "").strip()
    secret_arn = os.environ.get(f"{name}_ARN", "").strip()
    if direct or not secret_arn:
        return direct
    try:
        import boto3

        result = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    except Exception as exc:
        log("warning", f"could not load secret {name}: {exc}")
        return ""
    secret = result.get("SecretString")
    if isinstance(secret, str):
        return secret.strip()
    encoded = result.get("SecretBinary")
    if isinstance(encoded, (bytes, bytearray)):
        return base64.b64decode(encoded).decode("utf-8").strip()
    if isinstance(encoded, str):
        return base64.b64decode(encoded).decode("utf-8").strip()
    return ""


def csv_env(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    value = os.environ.get(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().casefold()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def env_int(name: str, *, default: int, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def parse_body(event: dict[str, Any], *, error: Callable[[str], Exception]) -> dict[str, Any]:
    raw_body = event.get("body")
    if raw_body is None:
        return {}
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise error("body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise error("body must be a JSON object")
    return body


def response(status_code: int, body: dict[str, Any], *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json", **(headers or {})},
        "body": json.dumps(body, separators=(",", ":"), default=str),
    }


def cors_headers(
    *,
    allow_headers: str,
    allow_methods: str = "GET,POST,OPTIONS",
    allow_origin: str = "*",
    max_age: int | None = None,
) -> dict[str, str]:
    headers = {
        "access-control-allow-origin": allow_origin,
        "access-control-allow-methods": allow_methods,
        "access-control-allow-headers": allow_headers,
    }
    if max_age is not None:
        headers["access-control-max-age"] = str(max_age)
    return headers


def cors_response(*, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return {"statusCode": 204, "headers": headers or {}, "body": ""}


def redacted_event(event: dict[str, Any]) -> dict[str, Any]:
    """Loggable subset of an API Gateway event.

    Headers carry replayable credentials (bearer tokens, shared admin
    secrets) and the body carries private content; keep both out of logs.
    """
    return {
        "rawPath": event.get("rawPath"),
        "requestContext": event.get("requestContext"),
        "queryStringParameters": event.get("queryStringParameters"),
        "headers": "[redacted]",
        "body": "[redacted]" if event.get("body") is not None else None,
    }


def jwt_claims(event: dict[str, Any]) -> dict[str, Any] | None:
    authorizer = event.get("requestContext", {}).get("authorizer", {})
    jwt = authorizer.get("jwt", {}) if isinstance(authorizer, dict) else {}
    claims = jwt.get("claims", {}) if isinstance(jwt, dict) else {}
    return claims if isinstance(claims, dict) else None


def path_param(path: str, prefix: str, suffix: str, *, error: Callable[[str], Exception]) -> str:
    if not path.startswith(prefix) or not path.endswith(suffix):
        raise error("invalid path")
    value = path.removeprefix(prefix).removesuffix(suffix).strip("/")
    if not value:
        raise error("path parameter is required")
    return unquote(value)
