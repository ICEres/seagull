from __future__ import annotations

import base64
import hmac
import json
import os
from typing import Any

import boto3

from safety_gateway.api.evaluation_request import evaluation_request_from_body
from safety_gateway.api.local import audit_record_to_dict, evaluation_result_to_dict
from safety_gateway.domain import SafetyGatewayPolicy, SafetyGatewayService
from safety_gateway.storage.dynamodb import DynamoDbSafetyAuditRepository


def secret_env(name: str) -> str:
    direct = os.environ.get(name, "").strip()
    secret_arn = os.environ.get(f"{name}_ARN", "").strip()
    if direct or not secret_arn:
        return direct
    try:
        result = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    except Exception as exc:
        print(json.dumps({"level": "warning", "message": f"could not load secret {name}: {exc}"}))
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


def csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


APP_NAME = os.environ.get("APP_NAME", "seagull-safety-gateway")
AUDIT_TABLE = os.environ["AUDIT_TABLE"]
ADMIN_SECRET = secret_env("SAFETY_GATEWAY_ADMIN_SECRET")
ADMIN_GROUPS = tuple(
    group.strip().casefold()
    for group in os.environ.get("SAFETY_GATEWAY_ADMIN_GROUPS", "seagull-admin,server-owner,admin").split(",")
    if group.strip()
)


dynamodb = boto3.resource("dynamodb")
audit_repository = DynamoDbSafetyAuditRepository(dynamodb.Table(AUDIT_TABLE))
safety_service = SafetyGatewayService(
    audit_repository,
    policy=SafetyGatewayPolicy(
        blocked_terms=csv_env("SAFETY_BLOCKED_TERMS", ("unsafe:",)),
        max_events_per_window=int(os.environ.get("SAFETY_MAX_EVENTS_PER_WINDOW", "20")),
        rate_limit_window_seconds=int(os.environ.get("SAFETY_RATE_LIMIT_WINDOW_SECONDS", "60")),
        max_thread_depth=int(os.environ.get("SAFETY_MAX_THREAD_DEPTH", "12")),
        max_repeated_replies=int(os.environ.get("SAFETY_MAX_REPEATED_REPLIES", "4")),
    ),
)


class BadRequest(ValueError):
    pass


class Unauthorized(ValueError):
    pass


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "/")

    try:
        if method == "OPTIONS":
            return cors_response()

        if method == "GET" and path == "/health":
            return response(200, {"ok": True, "app": APP_NAME, "storage": "dynamodb"})

        if method == "POST" and path == "/evaluate":
            require_authenticated_request(event)
            body = parse_body(event)
            result = safety_service.evaluate(evaluation_request_from_body(body))
            return response(200, evaluation_result_to_dict(result))

        if method == "GET" and path == "/audit":
            require_authenticated_request(event)
            query = event.get("queryStringParameters") or {}
            actor_id = optional_query_string(query, "actor_id")
            limit = optional_query_int(query, "limit", default=50)
            return response(
                200,
                {
                    "items": [
                        audit_record_to_dict(record)
                        for record in audit_repository.list_recent(actor_id=actor_id, limit=limit)
                    ]
                },
            )

        return response(404, {"error": "not_found", "method": method, "path": path})
    except Unauthorized as exc:
        return response(401, {"error": "unauthorized", "message": str(exc)})
    except BadRequest as exc:
        return response(400, {"error": "bad_request", "message": str(exc)})
    except ValueError as exc:
        return response(400, {"error": "bad_request", "message": str(exc)})
    except Exception as exc:
        print(json.dumps({"level": "error", "message": str(exc), "event": event}, default=str))
        return response(500, {"error": "internal_error"})


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body")
    if raw_body is None:
        return {}
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise BadRequest("body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    return body


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            **cors_headers(),
        },
        "body": json.dumps(body, separators=(",", ":"), default=str),
    }


def cors_response() -> dict[str, Any]:
    return {
        "statusCode": 204,
        "headers": cors_headers(),
        "body": "",
    }


def cors_headers() -> dict[str, str]:
    return {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET,POST,OPTIONS",
        "access-control-allow-headers": "authorization,content-type,x-seagull-safety-secret",
        "access-control-max-age": "300",
    }


def require_authenticated_request(event: dict[str, Any]) -> None:
    if is_admin_request(event) or admin_claims(jwt_claims(event)):
        return
    if not ADMIN_SECRET:
        raise Unauthorized("safety gateway auth is not configured")
    raise Unauthorized("authentication is required")


def is_admin_request(event: dict[str, Any]) -> bool:
    if not ADMIN_SECRET:
        return False
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    provided = headers.get("x-seagull-safety-secret")
    return isinstance(provided, str) and hmac.compare_digest(provided, ADMIN_SECRET)


def admin_claims(claims: dict[str, Any] | None) -> bool:
    if not claims:
        return False
    groups = claims.get("cognito:groups")
    if isinstance(groups, str):
        claim_groups = {group.strip().casefold() for group in groups.split(",") if group.strip()}
    elif isinstance(groups, list):
        claim_groups = {str(group).strip().casefold() for group in groups if str(group).strip()}
    else:
        claim_groups = set()
    return bool(claim_groups.intersection(ADMIN_GROUPS))


def jwt_claims(event: dict[str, Any]) -> dict[str, Any] | None:
    authorizer = event.get("requestContext", {}).get("authorizer", {})
    jwt = authorizer.get("jwt", {}) if isinstance(authorizer, dict) else {}
    claims = jwt.get("claims", {}) if isinstance(jwt, dict) else {}
    return claims if isinstance(claims, dict) else None


def optional_query_string(query: dict[str, Any], field_name: str) -> str | None:
    value = query.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadRequest(f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None


def optional_query_int(query: dict[str, Any], field_name: str, *, default: int) -> int:
    value = query.get(field_name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise BadRequest(f"{field_name} must be an integer") from exc
    return max(1, min(parsed, 100))
