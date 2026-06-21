import base64
import json
import os
from typing import Any

import boto3
from seagull_policy import TrustLabel

from safety_gateway.api.local import audit_record_to_dict, evaluation_result_to_dict
from safety_gateway.domain import SafetyEvaluationRequest, SafetyGatewayPolicy, SafetyGatewayService
from safety_gateway.storage.dynamodb import DynamoDbSafetyAuditRepository


def csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


APP_NAME = os.environ.get("APP_NAME", "seagull-safety-gateway")
AUDIT_TABLE = os.environ["AUDIT_TABLE"]


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


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "/")

    try:
        if method == "GET" and path == "/health":
            return response(200, {"ok": True, "app": APP_NAME, "storage": "dynamodb"})

        if method == "POST" and path == "/evaluate":
            body = parse_body(event)
            result = safety_service.evaluate(evaluation_request_from_body(body))
            return response(200, evaluation_result_to_dict(result))

        if method == "GET" and path == "/audit":
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
    except BadRequest as exc:
        return response(400, {"error": "bad_request", "message": str(exc)})
    except ValueError as exc:
        return response(400, {"error": "bad_request", "message": str(exc)})
    except Exception as exc:
        print(json.dumps({"level": "error", "message": str(exc), "event": event}, default=str))
        return response(500, {"error": "internal_error"})


def evaluation_request_from_body(body: dict[str, Any]) -> SafetyEvaluationRequest:
    return SafetyEvaluationRequest(
        actor_id=required_string(body, "actor_id"),
        action_type=optional_string(body, "action_type") or "message.send",
        content=optional_string(body, "content"),
        content_ref=optional_string(body, "content_ref"),
        target_ids=string_list(body.get("target_ids", ()), "target_ids"),
        intent=optional_string(body, "intent") or "message",
        visibility=optional_string(body, "visibility") or "direct",
        thread_id=optional_string(body, "thread_id"),
        message_id=optional_string(body, "message_id"),
        trace_id=optional_string(body, "trace_id"),
        trust_label=trust_label(body.get("trust_label")),
        thread_depth=optional_int(body, "thread_depth", default=0),
        repeated_reply_count=optional_int(body, "repeated_reply_count", default=0),
        metadata=string_map(body.get("metadata", {}), "metadata"),
    )


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
            "access-control-allow-origin": "*",
        },
        "body": json.dumps(body, separators=(",", ":"), default=str),
    }


def required_string(body: dict[str, Any], field_name: str) -> str:
    value = optional_string(body, field_name)
    if value is None:
        raise BadRequest(f"{field_name} is required")
    return value


def optional_string(body: dict[str, Any], field_name: str) -> str | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadRequest(f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None


def string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise BadRequest(f"{field_name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise BadRequest(f"{field_name} must contain only strings")
    return tuple(item.strip() for item in value if item.strip())


def string_map(value: Any, field_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BadRequest(f"{field_name} must be an object")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise BadRequest(f"{field_name} must contain string keys and values")
    return {key: item for key, item in value.items()}


def optional_int(body: dict[str, Any], field_name: str, *, default: int) -> int:
    value = body.get(field_name)
    if value is None:
        return default
    if not isinstance(value, int):
        raise BadRequest(f"{field_name} must be an integer")
    return value


def trust_label(value: Any) -> TrustLabel:
    if value is None:
        return TrustLabel.UNKNOWN
    if not isinstance(value, str):
        raise BadRequest("trust_label must be a string")
    try:
        return TrustLabel(value)
    except ValueError as exc:
        raise BadRequest(f"unsupported trust_label: {value}") from exc


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
