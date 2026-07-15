from __future__ import annotations

import base64
import hashlib
import http.client
import hmac
import ipaddress
import json
import os
import socket
import ssl
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit


def boto3_client(service_name: str) -> Any:
    import boto3

    return boto3.client(service_name)


def secret_env(name: str) -> str:
    direct = os.environ.get(name, "").strip()
    secret_arn = os.environ.get(f"{name}_ARN", "").strip()
    if direct or not secret_arn:
        return direct
    try:
        result = boto3_client("secretsmanager").get_secret_value(SecretId=secret_arn)
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


APP_NAME = os.environ.get("APP_NAME", "seagull-message-hub-agent-worker")
DELIVERIES_TABLE = os.environ.get("DELIVERIES_TABLE", "")
MESSAGES_TABLE = os.environ.get("MESSAGES_TABLE", "")
AGENTS_TABLE = os.environ.get("AGENTS_TABLE", "")
# WebSocket push (optional): the message-router's connections table and the
# API Gateway management endpoint (https form of the wss stage URL). When
# unset, socket push is a no-op and the worker behaves exactly as before.
CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "")
WEBSOCKET_CALLBACK_URL = os.environ.get("WEBSOCKET_CALLBACK_URL", "")
WEBHOOK_SIGNING_SECRET = secret_env("SEAGULL_WEBHOOK_SIGNING_SECRET")
INSECURE_WEBHOOK_SIGNING_SECRET = "dev-only-change-me"

_DYNAMODB = None
_MANAGEMENT_CLIENT = None


class RetryableDispatchError(Exception):
    """Raised when SQS should retry a webhook delivery."""


class VettedWebhookEndpoint:
    def __init__(
        self,
        *,
        url: str,
        host: str,
        address: str,
        port: int,
        request_target: str,
        host_header: str,
    ) -> None:
        self.url = url
        self.host = host
        self.address = address
        self.port = port
        self.request_target = request_target
        self.host_header = host_header


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
                connections_table=connections_table(),
                management_client=management_client(),
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
    connections_table: Any = None,
    management_client: Any = None,
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

    # WebSocket push first (best-effort wake-up to any live router
    # connections): a failing webhook below must not delay it, and a retried
    # record just re-pushes, which only costs the client an extra poll.
    # Socket pushes never touch trigger_status — that field means "webhook
    # sent" — and never fail the batch item; the client's fallback poll
    # covers misses.
    push_delivery_to_connections(
        event,
        delivery_id=delivery_id,
        recipient_agent_id=recipient_agent_id,
        connections_table=connections_table,
        management_client=management_client,
    )

    # Webhook dispatch only applies to webhook recipients — trigger_mode
    # "webhook", or a webhook_url on legacy records predating the field.
    # Manual-mode recipients are done after the socket push; marking them
    # failed below would corrupt trigger_status/retry_count for every
    # socket-only delivery.
    if recipient.get("trigger_mode", "manual") != "webhook" and not recipient.get("webhook_url"):
        return

    webhook_url = recipient.get("webhook_url")
    if not isinstance(webhook_url, str) or not webhook_url:
        mark_delivery_failure(tables.deliveries, delivery_id, "recipient has no webhook_url")
        return
    try:
        endpoint = validate_webhook_url(webhook_url, resolve_host=resolve_host)
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
        status_code = http_post(endpoint, body, headers)
    except Exception as exc:
        mark_delivery_failure(tables.deliveries, delivery_id, str(exc))
        raise RetryableDispatchError(f"webhook dispatch failed for {delivery_id}: {exc}") from exc

    if status_code < 200 or status_code >= 300:
        message = f"webhook returned HTTP {status_code}"
        mark_delivery_failure(tables.deliveries, delivery_id, message)
        raise RetryableDispatchError(f"webhook dispatch failed for {delivery_id}: {message}")

    mark_delivery_sent(tables.deliveries, delivery_id)


def push_delivery_to_connections(
    event: dict[str, Any],
    *,
    delivery_id: str,
    recipient_agent_id: str,
    connections_table: Any,
    management_client: Any,
) -> None:
    if connections_table is None or management_client is None:
        return

    try:
        result = connections_table.query(
            IndexName="agent-index",
            KeyConditionExpression="agent_id = :agent_id",
            ExpressionAttributeValues={":agent_id": recipient_agent_id},
        )
        items = result.get("Items") or []
    except Exception as exc:
        print(json.dumps({"level": "warning", "message": f"connections query failed: {exc}", "delivery_id": delivery_id}))
        return

    body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
    found = 0
    posted = 0
    stale = 0
    for item in items:
        connection_id = item.get("connection_id")
        if not isinstance(connection_id, str) or not connection_id:
            continue
        found += 1
        try:
            management_client.post_to_connection(ConnectionId=connection_id, Data=body)
            posted += 1
        except Exception as exc:
            if exception_code(exc) == "GoneException":
                stale += 1
                try:
                    connections_table.delete_item(Key={"connection_id": connection_id})
                except Exception as delete_exc:
                    print(json.dumps({"level": "warning", "message": f"stale connection cleanup failed: {delete_exc}"}))
            else:
                print(json.dumps({"level": "warning", "message": f"socket push failed: {exc}", "delivery_id": delivery_id}))

    print(json.dumps({
        "level": "info",
        "message": "socket push",
        "delivery_id": delivery_id,
        "connections_found": found,
        "posted": posted,
        "stale": stale,
    }))


def exception_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            return str(error.get("Code") or "")
    return ""


def connections_table() -> Any:
    if not CONNECTIONS_TABLE:
        return None
    return dynamodb().Table(CONNECTIONS_TABLE)


def management_client() -> Any:
    global _MANAGEMENT_CLIENT
    if not WEBSOCKET_CALLBACK_URL:
        return None
    if _MANAGEMENT_CLIENT is None:
        import boto3

        _MANAGEMENT_CLIENT = boto3.client("apigatewaymanagementapi", endpoint_url=WEBSOCKET_CALLBACK_URL)
    return _MANAGEMENT_CLIENT


def post_json(endpoint: VettedWebhookEndpoint | str, body: bytes, headers: dict[str, str]) -> int:
    vetted = validate_webhook_url(endpoint) if isinstance(endpoint, str) else endpoint
    connection = VettedHTTPSConnection(vetted, timeout=5, context=ssl.create_default_context())
    request_headers = {**headers, "Host": vetted.host_header}
    try:
        connection.request("POST", vetted.request_target, body=body, headers=request_headers)
        return int(connection.getresponse().status)
    finally:
        connection.close()


class VettedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        endpoint: VettedWebhookEndpoint,
        *,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(endpoint.host, endpoint.port, timeout=timeout, context=context)
        self._connect_address = endpoint.address
        self._ssl_context = context

    def connect(self) -> None:
        sock = socket.create_connection((self._connect_address, self.port), self.timeout, self.source_address)
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)


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
) -> VettedWebhookEndpoint:
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
    vetted_addresses = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("webhook_url host resolved to an invalid address") from exc
        if not ip.is_global:
            raise ValueError("webhook_url host resolves to a non-public address")
        vetted_addresses.append(str(ip))

    request_target = parsed.path or "/"
    if parsed.query:
        request_target = f"{request_target}?{parsed.query}"
    service_port = port or 443
    host_header = host if service_port == 443 else f"{host}:{service_port}"
    return VettedWebhookEndpoint(
        url=url,
        host=host,
        address=vetted_addresses[0],
        port=service_port,
        request_target=request_target,
        host_header=host_header,
    )


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
