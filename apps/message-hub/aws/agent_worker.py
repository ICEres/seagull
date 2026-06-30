from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import socket
from datetime import datetime, timezone
from typing import Any, Callable
from urllib import error, request
from urllib.parse import urlsplit


APP_NAME = os.environ.get("APP_NAME", "seagull-message-hub-agent-worker")
DELIVERIES_TABLE = os.environ.get("DELIVERIES_TABLE", "")
MESSAGES_TABLE = os.environ.get("MESSAGES_TABLE", "")
AGENTS_TABLE = os.environ.get("AGENTS_TABLE", "")
WEBHOOK_SIGNING_SECRET = os.environ.get("SEAGULL_WEBHOOK_SIGNING_SECRET", "")
INSECURE_WEBHOOK_SIGNING_SECRET = "dev-only-change-me"

_DYNAMODB = None


class RetryableDispatchError(Exception):
    """Raised when SQS should retry a webhook delivery."""


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures = []
    tables = dynamodb_tables()

    for record in event.get("Records", []):
        try:
            payload = json.loads(record.get("body") or "{}")
            handle_delivery_event(
                payload,
                tables=tables,
                http_post=post_json,
                signing_secret=WEBHOOK_SIGNING_SECRET,
            )
        except RetryableDispatchError as exc:
            print(json.dumps({"level": "warning", "message": str(exc), "record": record.get("messageId")}))
            failures.append({"itemIdentifier": record.get("messageId")})
        except Exception as exc:
            print(json.dumps({"level": "error", "message": str(exc), "record": record.get("messageId")}))
            failures.append({"itemIdentifier": record.get("messageId")})

    return {"batchItemFailures": failures}


def handle_delivery_event(
    event: dict[str, Any],
    *,
    tables: Any,
    http_post: Any,
    signing_secret: str,
    resolve_host: Callable[[str, int | None], list[str]] | None = None,
) -> None:
    data = event.get("data") or {}
    delivery_id = data.get("delivery_id")
    if not isinstance(delivery_id, str) or not delivery_id:
        return

    delivery = get_item(tables.deliveries, {"delivery_id": delivery_id})
    if delivery is None:
        return
    if delivery.get("status") == "acked":
        return
    if delivery.get("trigger_status") == "sent":
        return

    message_id = delivery.get("message_id") or data.get("message_id")
    recipient_agent_id = delivery.get("recipient_agent_id") or data.get("recipient_agent_id")
    if not isinstance(message_id, str) or not isinstance(recipient_agent_id, str):
        mark_delivery_failure(tables.deliveries, delivery_id, "delivery is missing message or recipient")
        return

    message = get_item(tables.messages, {"message_id": message_id})
    recipient = get_item(tables.agents, {"agent_id": recipient_agent_id})
    if message is None or recipient is None:
        mark_delivery_failure(tables.deliveries, delivery_id, "message or recipient no longer exists")
        return

    webhook_url = recipient.get("webhook_url")
    if not isinstance(webhook_url, str) or not webhook_url:
        mark_delivery_failure(tables.deliveries, delivery_id, "recipient has no webhook_url")
        return
    try:
        validate_webhook_url(webhook_url, resolve_host=resolve_host)
    except ValueError as exc:
        mark_delivery_failure(tables.deliveries, delivery_id, str(exc))
        return
    try:
        signing_secret = require_webhook_signing_secret(signing_secret)
    except ValueError as exc:
        mark_delivery_failure(tables.deliveries, delivery_id, str(exc))
        return

    body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"{APP_NAME}/1.0",
        "X-Seagull-Event-Type": str(event.get("type") or "seagull.delivery.created.v1"),
        "X-Seagull-Signature": sign_webhook_body(body, signing_secret),
    }

    try:
        status_code = http_post(webhook_url, body, headers)
    except Exception as exc:
        mark_delivery_failure(tables.deliveries, delivery_id, str(exc))
        raise RetryableDispatchError(f"webhook dispatch failed for {delivery_id}: {exc}") from exc

    if status_code < 200 or status_code >= 300:
        message = f"webhook returned HTTP {status_code}"
        mark_delivery_failure(tables.deliveries, delivery_id, message)
        raise RetryableDispatchError(f"webhook dispatch failed for {delivery_id}: {message}")

    mark_delivery_sent(tables.deliveries, delivery_id)


def post_json(url: str, body: bytes, headers: dict[str, str]) -> int:
    validate_webhook_url(url)
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=5) as response:
            return int(response.status)
    except error.HTTPError as exc:
        return int(exc.code)


def mark_delivery_sent(table: Any, delivery_id: str) -> None:
    now = now_iso()
    table.update_item(
        Key={"delivery_id": delivery_id},
        UpdateExpression=(
            "SET trigger_status = :status, last_triggered_at = :triggered_at, updated_at = :updated_at "
            "REMOVE last_error"
        ),
        ExpressionAttributeValues={
            ":status": "sent",
            ":triggered_at": now,
            ":updated_at": now,
        },
    )


def mark_delivery_failure(table: Any, delivery_id: str, error_message: str) -> None:
    table.update_item(
        Key={"delivery_id": delivery_id},
        UpdateExpression=(
            "SET trigger_status = :status, last_error = :error, updated_at = :updated_at "
            "ADD retry_count :one"
        ),
        ExpressionAttributeValues={
            ":status": "failed",
            ":error": error_message[:500],
            ":updated_at": now_iso(),
            ":one": 1,
        },
    )


def get_item(table: Any, key: dict[str, str]) -> dict[str, Any] | None:
    return table.get_item(Key=key).get("Item")


def sign_webhook_body(body: bytes, secret: str) -> str:
    signing_secret = require_webhook_signing_secret(secret)
    digest = hmac.new(signing_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def require_webhook_signing_secret(secret: str) -> str:
    signing_secret = secret.strip()
    if not signing_secret:
        raise ValueError("webhook signing secret is not configured")
    if hmac.compare_digest(signing_secret, INSECURE_WEBHOOK_SIGNING_SECRET):
        raise ValueError("webhook signing secret uses the insecure development placeholder")
    return signing_secret


def validate_webhook_url(
    url: str,
    *,
    resolve_host: Callable[[str, int | None], list[str]] | None = None,
) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("webhook_url must use https")
    if parsed.username or parsed.password:
        raise ValueError("webhook_url must not include credentials")
    if not parsed.hostname:
        raise ValueError("webhook_url host is required")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("webhook_url port is invalid") from exc

    host = parsed.hostname
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        resolver = resolve_host or resolve_host_ips
        addresses = resolver(host, port)

    if not addresses:
        raise ValueError("webhook_url host did not resolve")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("webhook_url host resolved to an invalid address") from exc
        if not ip.is_global:
            raise ValueError("webhook_url host resolves to a non-public address")


def resolve_host_ips(host: str, port: int | None) -> list[str]:
    service_port = port or 443
    results = socket.getaddrinfo(host, service_port, type=socket.SOCK_STREAM)
    return sorted({result[4][0] for result in results})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def dynamodb_tables() -> Any:
    class Tables:
        deliveries = dynamodb().Table(DELIVERIES_TABLE)
        messages = dynamodb().Table(MESSAGES_TABLE)
        agents = dynamodb().Table(AGENTS_TABLE)

    return Tables()


def dynamodb() -> Any:
    global _DYNAMODB
    if _DYNAMODB is None:
        import boto3

        _DYNAMODB = boto3.resource("dynamodb")
    return _DYNAMODB
