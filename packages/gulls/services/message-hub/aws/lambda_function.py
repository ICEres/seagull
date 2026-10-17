"""AWS Lambda adapter for the Seagull message hub.

Thin HTTP shim over ``LocalMessageHubApi`` + ``MessageHubService`` backed by
``DynamoDbMessageHubRepository``. All domain behavior (validation, safety
gating, task lifecycle, payload retention, token verification) lives in the
``message_hub`` package; this module only:

* parses API Gateway HTTP events and dispatches to api methods,
* wires the deployed AWS dependencies (DynamoDB tables, S3, SQS, Secrets
  Manager, the safety gateway) into the domain service — all lazily, so the
  module imports without environment variables or boto3,
* maps ``ApiError`` results back to the historical HTTP envelope.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request, urlopen

from message_hub.api import (
    HTML_MEDIA_TYPE,
    ApiError,
    LocalMessageHubApi,
    accept_prefers_html,
    render_agent_card_html,
)
from message_hub.domain import (
    DeliveryStatus,
    MessageHubError,
    MessageHubService,
    SafetyBlockedError,
    SendMessageResult,
    delivery_created_event,
)
from message_hub.domain.safety import SafetyCheckRequest
from message_hub.storage import (
    DynamoDbMessageHubRepository,
    RepositoryTableNotConfiguredError,
)
from seagull_common.coerce import without_none
from seagull_common.lambda_runtime import redacted_event
from seagull_common.logging import log

DEFAULT_APP_NAME = "seagull-message-hub"
DEFAULT_CONTEXT_MAX_INLINE_CHARS = 4000
DEFAULT_CONTEXT_MAX_RECENT_MESSAGES = 10
DEFAULT_CONTEXT_MAX_PAYLOAD_REFS = 20

# Required by the deployed terraform module; absence is a deploy bug surfaced
# on first use (never at import).
REQUIRED_TABLE_ENV_VARS = (
    "AGENTS_TABLE",
    "MESSAGES_TABLE",
    "THREADS_TABLE",
    "DELIVERIES_TABLE",
    "IDEMPOTENCY_TABLE",
    "THREAD_SUMMARIES_TABLE",
)
OPTIONAL_TABLE_ENV_VARS = {
    "routing_rules_table": "ROUTING_RULES_TABLE",
    "agent_tokens_table": "AGENT_TOKENS_TABLE",
    "tasks_table": "TASKS_TABLE",
    "tool_requests_table": "TOOL_REQUESTS_TABLE",
    "task_results_table": "TASK_RESULTS_TABLE",
    "payloads_table": "PAYLOADS_TABLE",
    # Feed: optional like the task tables, so an environment provisioned before
    # these tables existed keeps working until they are applied.
    "posts_table": "POSTS_TABLE",
    "follows_table": "FOLLOWS_TABLE",
    "rooms_table": "ROOMS_TABLE",
    "room_memberships_table": "ROOM_MEMBERSHIPS_TABLE",
    "feed_events_table": "FEED_EVENTS_TABLE",
    "notifications_table": "NOTIFICATIONS_TABLE",
}


class MessageHubConfigurationError(RuntimeError):
    """Raised when the Lambda environment is missing required settings."""


# ---------------------------------------------------------------------------
# Lazy configuration


def _cfg(config: dict[str, str] | None, name: str, default: str = "") -> str:
    if config is not None and name in config:
        return str(config[name] or "")
    return os.environ.get(name, default)


def secret_env(name: str, *, config: dict[str, str] | None = None) -> str:
    """Read a secret from env, or from Secrets Manager via ``<NAME>_ARN``."""
    direct = _cfg(config, name).strip()
    secret_arn = _cfg(config, f"{name}_ARN").strip()
    if direct or not secret_arn:
        return direct
    try:
        import boto3

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


# ---------------------------------------------------------------------------
# Safety gateway adapter


class _SafetyStatus:
    """Duck-typed action whose ``.value`` feeds domain ``safety_status_for``."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value


_STATUS_APPROVED = _SafetyStatus("approved")
_STATUS_APPROVED_WITH_WARNING = _SafetyStatus("approved_with_warning")
_STATUS_NEEDS_REVIEW = _SafetyStatus("needs_review")


class GatewaySafetyDecision:
    """Deliverable decision carrying the remote gateway's metadata.

    Duck-types ``seagull_policy.SafetyDecision`` for the fields the domain
    consumes (``deliverable``, ``decision_id``, ``action.value``, ``reasons``).
    Non-deliverable gateway actions never construct one — they raise
    ``SafetyBlockedError`` instead.
    """

    __slots__ = ("decision_id", "action", "risk", "reasons", "policy_ids", "deliverable")

    def __init__(
        self,
        *,
        decision_id: str,
        action: _SafetyStatus,
        risk: str | None,
        reasons: tuple[str, ...],
        policy_ids: tuple[str, ...],
    ) -> None:
        self.decision_id = decision_id
        self.action = action
        self.risk = risk
        self.reasons = reasons
        self.policy_ids = policy_ids
        self.deliverable = True


class SafetyGatewayEvaluator:
    """SafetyEvaluator that consults the deployed safety gateway over HTTPS.

    Reproduces the legacy ``evaluate_safety_gateway()`` semantics: same
    request payload, same admin-secret header, fail-closed on transport or
    protocol errors, ``human_review`` mapped to a held-for-review send, and
    ``block``/``quarantine``/``rate_limit`` rejected outright.
    """

    def __init__(
        self,
        *,
        gateway_url: str,
        admin_secret: str = "",
        timeout_seconds: float = 5.0,
        opener: Callable[..., Any] | None = None,
        thread_lookup: Callable[[str], Any] | None = None,
    ) -> None:
        self._gateway_url = (gateway_url or "").strip().rstrip("/")
        self._admin_secret = admin_secret
        self._timeout_seconds = timeout_seconds
        self._opener = opener
        self._thread_lookup = thread_lookup
        self._pending_review: dict[str, Any] | None = None

    @property
    def pending_review(self) -> dict[str, Any] | None:
        return self._pending_review

    def take_pending_review(self) -> dict[str, Any] | None:
        pending, self._pending_review = self._pending_review, None
        return pending

    def evaluate_send(self, request: SafetyCheckRequest) -> GatewaySafetyDecision:
        self._pending_review = None
        subject = "task" if request.intent == "task_request" else "message"
        decision = self._invoke_gateway(request)
        decision_id = self._required_field(decision, "decision_id")
        action = self._required_field(decision, "action")
        reasons = _clean_string_values(decision.get("reasons"))
        policy_ids = _clean_string_values(decision.get("policy_ids"))
        risk = decision.get("risk")
        risk = risk.strip() if isinstance(risk, str) and risk.strip() else None

        if action == "allow":
            status = _STATUS_APPROVED
        elif action == "allow_with_warning":
            status = _STATUS_APPROVED_WITH_WARNING
        elif action == "human_review":
            status = _STATUS_NEEDS_REVIEW
            self._pending_review = {
                "decision_id": decision_id,
                "reasons": reasons,
                "policy_ids": policy_ids,
                "risk": risk,
            }
        elif action in {"block", "quarantine", "rate_limit"}:
            raise SafetyBlockedError(
                f"{subject} blocked by safety gateway: {', '.join(reasons) or action}"
            )
        else:
            raise SafetyBlockedError(f"safety gateway returned unsupported action: {action}")

        return GatewaySafetyDecision(
            decision_id=decision_id,
            action=status,
            risk=risk,
            reasons=tuple(reasons),
            policy_ids=tuple(policy_ids),
        )

    def _invoke_gateway(self, request: SafetyCheckRequest) -> dict[str, Any]:
        if not self._gateway_url:
            raise SafetyBlockedError("safety gateway is not configured")

        payload = without_none(
            {
                "actor_id": request.sender.agent_id,
                "action_type": "task.request" if request.intent == "task_request" else "message.send",
                "content": request.content,
                "content_ref": request.content_ref,
                "target_ids": [agent.agent_id for agent in request.recipients],
                "intent": request.intent,
                "visibility": request.visibility,
                "thread_id": request.thread_id,
                "thread_depth": self._thread_depth(request.thread_id),
                "repeated_reply_count": 0,
            }
        )
        headers = {"content-type": "application/json"}
        if self._admin_secret:
            headers["x-seagull-safety-secret"] = self._admin_secret
        gateway_request = Request(
            f"{self._gateway_url}/evaluate",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        opener = self._opener or urlopen
        try:
            with opener(gateway_request, timeout=self._timeout_seconds) as result:
                status_code = int(result.status)
                raw = result.read().decode("utf-8")
        except HTTPError as exc:
            raise SafetyBlockedError(f"safety gateway rejected evaluation: HTTP {exc.code}") from exc
        except (OSError, TimeoutError, URLError) as exc:
            raise SafetyBlockedError(f"safety gateway is unavailable: {exc}") from exc

        if status_code < 200 or status_code >= 300:
            raise SafetyBlockedError(f"safety gateway rejected evaluation: HTTP {status_code}")

        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise SafetyBlockedError("safety gateway returned invalid JSON") from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("decision"), dict):
            raise SafetyBlockedError("safety gateway response is missing a decision")
        return parsed["decision"]

    def _thread_depth(self, thread_id: str | None) -> int:
        if not thread_id or self._thread_lookup is None:
            return 0
        try:
            thread = self._thread_lookup(thread_id)
        except Exception:
            return 0
        return int(getattr(thread, "message_count", 0) or 0) if thread is not None else 0

    @staticmethod
    def _required_field(decision: dict[str, Any], field_name: str) -> str:
        value = decision.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise SafetyBlockedError(f"safety gateway decision is missing {field_name}")
        return value.strip()


def _clean_string_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


# ---------------------------------------------------------------------------
# Domain service wiring


class GatedMessageHubService(MessageHubService):
    """MessageHubService with the deployed adapter's two deltas.

    * A ``human_review`` safety decision stores the message but holds every
      delivery for human review (status ``needs_review``, stage
      ``human.review``), recording the gateway decision in the workflow trace.
    * Delivery-created events are published for every recipient — not only
      webhook mode — because the agent worker decides per recipient (webhook
      POST vs WebSocket push). The publisher still skips non-delivered rows.
    """

    def __init__(
        self,
        repository: Any,
        *,
        safety_evaluator: Any,
        delivery_event_publisher: Callable[[dict[str, Any]], None] | None = None,
        review_hold: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        super().__init__(
            repository,
            safety_evaluator=safety_evaluator,
            delivery_event_publisher=delivery_event_publisher,
        )
        self._review_hold = review_hold

    def send_message(self, **kwargs: Any) -> SendMessageResult:
        result = super().send_message(**kwargs)
        hold = self._review_hold() if self._review_hold is not None else None
        if hold is None or not result.deliveries:
            return result

        note = f"held for human review by safety gateway decision {hold.get('decision_id')}"
        reasons = hold.get("reasons") or []
        if reasons:
            note = f"{note}: {', '.join(reasons)}"
        held = tuple(
            self.apply_hook_result(
                delivery.delivery_id,
                hook="delivery.before",
                runtime="cloud",
                actor="safety-gateway",
                action="review",
                note=note,
            )
            for delivery in result.deliveries
        )
        return SendMessageResult(message=result.message, thread=result.thread, deliveries=held)

    def _publish_delivery_created_events(self, *, deliveries, message, sender, recipients) -> None:
        if self._delivery_event_publisher is None:
            return
        if len(deliveries) != len(recipients):
            raise MessageHubError("delivery and recipient counts differ")
        for delivery, recipient in zip(deliveries, recipients):
            self._delivery_event_publisher(
                delivery_created_event(
                    delivery=delivery,
                    message=message,
                    sender=sender,
                    recipient=recipient,
                )
            )


class SqsDeliveryEventSink:
    """Sends wire-shaped delivery events to the agent jobs SQS queue."""

    def __init__(self, queue_url: str, *, sqs_client: Any = None) -> None:
        self._queue_url = queue_url
        self._sqs = sqs_client

    def __call__(self, event: dict[str, Any]) -> None:
        if self._sqs is None:
            import boto3

            self._sqs = boto3.client("sqs")
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(clean_item(event), separators=(",", ":"), sort_keys=True),
            MessageGroupId=event["data"]["thread_id"],
            MessageDeduplicationId=event["data"]["delivery_id"],
        )


class DeliveryEventPublisher:
    """Adapts domain delivery events to the wire payload the worker consumes.

    The domain event omits ``refs``/``current_*``/``current_stage``; the agent
    worker's webhook and socket payloads historically included them, so they
    are restored here from the freshly stored delivery row. Non-``delivered``
    rows (routing review holds) and sends pending a safety review hold are
    never enqueued — matching the previous adapter.
    """

    def __init__(
        self,
        sink: Callable[[dict[str, Any]], None],
        *,
        repository: Any,
        review_pending: Callable[[], bool] | None = None,
    ) -> None:
        self._sink = sink
        self._repository = repository
        self._review_pending = review_pending

    def __call__(self, event: dict[str, Any]) -> None:
        data = dict(event.get("data") or {})
        delivery = self._repository.get_delivery(str(data.get("delivery_id") or ""))
        if delivery is None or delivery.status != DeliveryStatus.DELIVERED:
            return
        if self._review_pending is not None and self._review_pending():
            return

        data["refs"] = [
            {"type": ref.type, "url": ref.url, "find": ref.find, "remember_as": ref.remember_as}
            for ref in delivery.refs
        ]
        data["current_content_inline"] = delivery.current_content_inline or data.get("content_inline")
        data["current_content_ref"] = delivery.current_content_ref or data.get("content_ref")
        data["current_stage"] = delivery.current_stage
        self._sink({**event, "data": data})


def build_service(
    *,
    repository: Any = None,
    safety_evaluator: Any = None,
    delivery_event_publisher: Callable[[dict[str, Any]], None] | None = None,
    config: dict[str, str] | None = None,
) -> MessageHubService:
    """Construct the domain service with lazily created AWS dependencies.

    ``delivery_event_publisher`` receives wire-shaped events (the SQS payload
    the agent worker consumes); when omitted, an SQS sink is used if
    ``AGENT_JOBS_QUEUE_URL`` is configured.
    """
    if repository is None:
        repository = _build_repository(config)

    if safety_evaluator is None:
        safety_evaluator = SafetyGatewayEvaluator(
            gateway_url=_cfg(config, "SAFETY_GATEWAY_URL"),
            admin_secret=secret_env("SAFETY_GATEWAY_ADMIN_SECRET", config=config),
            timeout_seconds=float(_cfg(config, "SAFETY_GATEWAY_TIMEOUT_SECONDS", "5")),
            thread_lookup=repository.get_thread,
        )

    sink = delivery_event_publisher
    if sink is None:
        queue_url = _cfg(config, "AGENT_JOBS_QUEUE_URL").strip()
        if queue_url:
            sink = SqsDeliveryEventSink(queue_url)

    publisher = None
    if sink is not None:
        publisher = DeliveryEventPublisher(
            sink,
            repository=repository,
            review_pending=lambda: getattr(safety_evaluator, "pending_review", None) is not None,
        )

    return GatedMessageHubService(
        repository,
        safety_evaluator=safety_evaluator,
        delivery_event_publisher=publisher,
        review_hold=getattr(safety_evaluator, "take_pending_review", None),
    )


def _build_repository(config: dict[str, str] | None) -> DynamoDbMessageHubRepository:
    missing = sorted(name for name in REQUIRED_TABLE_ENV_VARS if not _cfg(config, name).strip())
    if missing:
        raise MessageHubConfigurationError(
            "message hub configuration is incomplete; missing environment variables: "
            + ", ".join(missing)
        )

    import boto3

    dynamodb = boto3.resource("dynamodb")

    def table(name: str) -> Any:
        return dynamodb.Table(_cfg(config, name).strip())

    def optional_table(name: str) -> Any:
        value = _cfg(config, name).strip()
        return dynamodb.Table(value) if value else None

    payload_objects_bucket = _cfg(config, "PAYLOAD_OBJECTS_BUCKET").strip() or None
    return DynamoDbMessageHubRepository(
        agents_table=table("AGENTS_TABLE"),
        messages_table=table("MESSAGES_TABLE"),
        threads_table=table("THREADS_TABLE"),
        deliveries_table=table("DELIVERIES_TABLE"),
        idempotency_table=table("IDEMPOTENCY_TABLE"),
        thread_summaries_table=table("THREAD_SUMMARIES_TABLE"),
        **{kwarg: optional_table(env) for kwarg, env in OPTIONAL_TABLE_ENV_VARS.items()},
        payload_objects_bucket=payload_objects_bucket,
        s3_client=boto3.client("s3") if payload_objects_bucket else None,
    )


_RUNTIME: dict[str, Any] = {"api": None, "secrets": {}}


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def build_api(*, service: MessageHubService | None = None) -> LocalMessageHubApi:
    """Construct the api with guest-ingress settings from the environment.

    ``GUEST_STATUS_SIGNING_SECRET`` (direct or ``_ARN`` via the secret_env
    pattern) signs guest status-poll tokens; when it is unset the api falls
    back to a per-instance random secret, but token-less sends are refused
    with 503 before reaching the api (``require_guest_status_signing_secret``)
    so unverifiable status URLs are never handed out.
    """
    if service is None:
        service = build_service()
    return LocalMessageHubApi(
        service,
        guest_status_signing_secret=_cached_secret("GUEST_STATUS_SIGNING_SECRET") or None,
        guest_send_ip_hourly_limit=_int_env("GUEST_SEND_IP_HOURLY_LIMIT", 10),
        guest_send_recipient_hourly_limit=_int_env("GUEST_SEND_RECIPIENT_HOURLY_LIMIT", 30),
        guest_callback_domain_hourly_limit=_int_env("GUEST_CALLBACK_DOMAIN_HOURLY_LIMIT", 20),
        instance_domain=os.environ.get("PUBLIC_INSTANCE_DOMAIN", "").strip() or None,
    )


def get_api() -> LocalMessageHubApi:
    if _RUNTIME["api"] is None:
        _RUNTIME["api"] = build_api()
    return _RUNTIME["api"]


def configure_api(api: LocalMessageHubApi) -> None:
    """Install a pre-built api (tests inject an in-memory service here)."""
    _RUNTIME["api"] = api


def reset_runtime() -> None:
    _RUNTIME["api"] = None
    _RUNTIME["secrets"].clear()


def _cached_secret(name: str) -> str:
    if name not in _RUNTIME["secrets"]:
        _RUNTIME["secrets"][name] = secret_env(name)
    return _RUNTIME["secrets"][name]


# ---------------------------------------------------------------------------
# HTTP entrypoint


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "/")

    try:
        return dispatch(method, path, event)
    except ApiError as exc:
        return response(exc.status_code, {"error": exc.error, "message": exc.message})
    except RepositoryTableNotConfiguredError as exc:
        return response(400, {"error": "bad_request", "message": str(exc)})
    except SafetyBlockedError as exc:
        return response(403, {"error": "blocked", "message": str(exc)})
    except Exception as exc:
        log("error", str(exc), event=redacted_event(event))
        return response(500, {"error": "internal_error"})


def dispatch(method: str, path: str, event: dict[str, Any]) -> dict[str, Any]:
    if method == "GET" and path == "/health":
        app_name = os.environ.get("APP_NAME", DEFAULT_APP_NAME)
        return response(200, {"ok": True, "app": app_name, "storage": "dynamodb", "time": now_iso()})

    if method == "POST" and path == "/agents":
        return register_agent(event)

    if method == "POST" and path == "/agent-registrations":
        return response(201, get_api().agent_registration(parse_body(event)))

    if path == "/agent" or path.startswith("/agent/"):
        return route_agent_runtime(method, path, event)

    if method == "GET" and public_agent_profile_path(path):
        handle = unquote(path.removeprefix("/agents/").strip("/"))
        payload = get_api().read_agent(handle)
        if not public_agent_urls_enabled():
            # Kill switch: the profile route predates public agent URLs, so
            # it stays up, but negotiation and caching revert to legacy JSON.
            return response(200, payload)
        if accept_prefers_html(accept_header(event)):
            return html_response(200, render_agent_card_html(payload["agent"]))
        return cacheable_response(200, payload)

    if public_agent_messages_path(path):
        return route_public_agent_messages(method, path, event)

    if method == "GET" and path == "/.well-known/gulls":
        if not public_agent_urls_enabled():
            return response(404, {"error": "not_found", "method": method, "path": path})
        return cacheable_response(200, get_api().well_known_gulls(query_params(event).get("resource")))

    if method == "POST" and path == "/payloads":
        return response(201, get_api().create_payload(parse_body(event)))

    if method == "GET" and path == "/payloads":
        return read_payload(event)

    require_legacy_handle_routes_enabled(event)
    api = get_api()

    if method == "POST" and path == "/routing-rules":
        return response(201, api.create_routing_rule(parse_body(event)))

    if method == "GET" and path == "/routing-rules":
        return response(200, api.read_routing_rules())

    if method == "GET" and path.startswith("/agents/") and path.endswith("/inbox"):
        handle = path_param(path, "/agents/", "/inbox")
        api.require_agent_access(authorization_header(event), handle, required_scope="agent:inbox")
        return read_inbox(handle, event)

    # Agent Request queue, alongside the agent's inbox and outbox and gated the
    # same way, so a product surface reaches it without the legacy-route secret.
    if method == "GET" and path.startswith("/agents/") and path.endswith("/tasks"):
        handle = path_param(path, "/agents/", "/tasks")
        api.require_agent_access(authorization_header(event), handle, required_scope="agent:inbox")
        params = query_params(event)
        return response(
            200,
            api.read_agent_tasks(
                handle,
                role=(params.get("role") or "all").strip() or "all",
                limit=query_limit(event, default=50, maximum=100),
            ),
        )

    if method == "GET" and path.startswith("/agents/") and path.endswith("/outbox"):
        handle = path_param(path, "/agents/", "/outbox")
        api.require_agent_access(authorization_header(event), handle, required_scope="agent:read")
        agent = api.read_agent(handle)["agent"]
        items = api.read_outbox(handle, limit=query_limit(event, default=20, maximum=100))["items"]
        return response(200, {"agent": agent, "items": items})

    if method == "GET" and path.startswith("/agents/") and path.endswith("/sent"):
        handle = path_param(path, "/agents/", "/sent")
        api.require_agent_access(authorization_header(event), handle, required_scope="agent:read")
        agent = api.read_agent(handle)["agent"]
        messages = api.read_sent_messages(handle, limit=query_limit(event, default=20, maximum=100))
        return response(200, {"agent": agent, "messages": messages["messages"]})

    if method == "POST" and path == "/messages":
        return response(201, api.create_message(message_body(parse_body(event))))

    if path.startswith("/personal-agents/"):
        return route_personal_agent(method, path, event)

    if method == "POST" and path == "/tasks":
        return response(201, api.create_task(parse_body(event)))

    if method == "POST" and path.startswith("/tasks/") and path.endswith("/accept"):
        task_id = path_param(path, "/tasks/", "/accept")
        return response(200, api.accept_task(task_id, parse_body(event)))

    if method == "POST" and path.startswith("/tasks/") and path.endswith("/status"):
        task_id = path_param(path, "/tasks/", "/status")
        return response(200, api.update_task(task_id, parse_body(event)))

    if method == "POST" and path.startswith("/tasks/") and path.endswith("/results"):
        task_id = path_param(path, "/tasks/", "/results")
        return response(200, api.return_task_result(task_id, parse_body(event)))

    if method == "POST" and path.startswith("/tasks/") and path.endswith("/tool-requests"):
        task_id = path_param(path, "/tasks/", "/tool-requests")
        return response(201, api.create_tool_request(task_id, parse_body(event)))

    if method == "POST" and path.startswith("/tool-requests/") and path.endswith("/complete"):
        tool_request_id = path_param(path, "/tool-requests/", "/complete")
        return response(200, api.complete_tool_request(tool_request_id, parse_body(event)))

    # Agent-scoped request queue for the Agent Request surface. Checked before
    # the /tasks/{id} match below, which would otherwise swallow it.
    if method == "GET" and path.rstrip("/") == "/tasks":
        params = query_params(event)
        agent_handle = (params.get("agent_handle") or "").strip()
        if not agent_handle:
            return response(400, {"error": "bad_request", "message": "agent_handle is required"})
        return response(
            200,
            api.read_agent_tasks(
                agent_handle,
                role=(params.get("role") or "all").strip() or "all",
                limit=query_limit(event, default=50, maximum=100),
            ),
        )

    if method == "GET" and path.startswith("/tasks/"):
        task_id = unquote(path.removeprefix("/tasks/").strip("/"))
        return response(200, api.read_task(task_id))

    if method == "POST" and path.endswith("/hook-results"):
        delivery_id = delivery_path_param(path, "/hook-results")
        return response(200, api.submit_hook_result(delivery_id, parse_body(event)))

    if method == "POST" and path.endswith("/decision"):
        delivery_id = delivery_path_param(path, "/decision")
        return response(200, api.submit_delivery_decision(delivery_id, parse_body(event)))

    if method == "GET" and path.endswith("/contact-explanation"):
        delivery_id = delivery_path_param(path, "/contact-explanation")
        return response(200, api.read_contact_explanation(delivery_id))

    if method == "GET" and path.startswith("/threads/") and path.endswith("/context"):
        thread_id = path_param(path, "/threads/", "/context")
        return read_thread_context(thread_id, event)

    if method == "GET" and path.startswith("/threads/") and path.endswith("/context-pack"):
        thread_id = path_param(path, "/threads/", "/context-pack")
        return read_context_pack(thread_id, event)

    if method == "GET" and path.startswith("/threads/") and path.endswith("/tasks"):
        thread_id = path_param(path, "/threads/", "/tasks")
        limit = query_limit(event, default=50, maximum=100)
        return response(200, api.read_thread_tasks(thread_id, limit=limit))

    if method == "GET" and path.startswith("/threads/"):
        thread_id = unquote(path.removeprefix("/threads/").strip("/"))
        return response(200, api.read_thread(thread_id, limit=query_limit(event, default=50, maximum=100)))

    if method == "POST" and path.startswith("/messages/") and path.endswith("/ack"):
        message_id = path_param(path, "/messages/", "/ack")
        return ack_message(message_id, event)

    return response(404, {"error": "not_found", "method": method, "path": path})


# ---------------------------------------------------------------------------
# Route handlers needing composition beyond a single api call


def register_agent(event: dict[str, Any]) -> dict[str, Any]:
    body = parse_body(event)
    api = get_api()
    handle = body.get("handle")
    if isinstance(handle, str) and handle.strip().lower().startswith("@me_"):
        # Human proxies are server-owned identities. The ordinary legacy-route
        # switch is intentionally insufficient here: even when that flag is
        # enabled, callers must present the dedicated shared credential.
        require_legacy_route_secret(event)
        return response(201, api.register_human_proxy(body))
    try:
        return response(201, api.register_agent(body))
    except ApiError as exc:
        if exc.status_code != 409:
            raise
        # Historical get-or-create semantics: re-posting an existing handle
        # returns the current public profile instead of a conflict.
        agent = api.read_agent(str(body.get("handle") or ""))["agent"]
        return response(200, {"created": False, "agent": agent})


def read_payload(event: dict[str, Any]) -> dict[str, Any]:
    params = query_params(event)
    requester_handle = (params.get("requester_handle") or "").strip() or None
    result = get_api().read_payload(
        str(params.get("content_ref") or ""),
        requester_handle=requester_handle,
    )
    content_bytes = result.pop("content_bytes", b"")
    if "content" not in result:
        result["content_bytes_base64"] = base64.b64encode(content_bytes).decode("ascii")
    return response(200, result)


def read_inbox(handle: str, event: dict[str, Any]) -> dict[str, Any]:
    api = get_api()
    agent = api.read_agent(handle)["agent"]
    items = api.read_inbox(handle, limit=query_limit(event, default=20, maximum=100))["items"]
    return response(200, {"agent": agent, "items": items})


def read_thread_context(thread_id: str, event: dict[str, Any]) -> dict[str, Any]:
    params = query_params(event)
    requester_handle = (params.get("requester_handle") or "").strip()
    if not requester_handle:
        raise ApiError(400, "bad_request", "requester_handle is required")
    result = get_api().read_thread_context_for(
        thread_id,
        requester_handle=requester_handle,
        recent_limit=query_limit(event, default=10, maximum=20),
    )
    return response(200, result)


def read_context_pack(thread_id: str, event: dict[str, Any]) -> dict[str, Any]:
    params = query_params(event)
    requester_handle = (params.get("requester_handle") or "").strip()
    if not requester_handle:
        raise ApiError(400, "bad_request", "requester_handle is required")
    result = get_api().read_context_pack(
        thread_id,
        requester_handle=requester_handle,
        max_inline_chars=query_int(
            event, "max_inline_chars", default=DEFAULT_CONTEXT_MAX_INLINE_CHARS, minimum=0, maximum=20000
        ),
        max_recent_messages=query_int(
            event, "max_recent_messages", default=DEFAULT_CONTEXT_MAX_RECENT_MESSAGES, minimum=0, maximum=50
        ),
        max_payload_refs=query_int(
            event, "max_payload_refs", default=DEFAULT_CONTEXT_MAX_PAYLOAD_REFS, minimum=0, maximum=100
        ),
        token_budget_estimate=optional_query_int(
            event, "token_budget_estimate", minimum=0, maximum=1_000_000
        ),
    )
    return response(200, result)


def ack_message(message_id: str, event: dict[str, Any]) -> dict[str, Any]:
    body = parse_body(event, default={})
    recipient_handle = body.get("recipient_handle") or body.get("recipient")
    if recipient_handle is None:
        params = query_params(event)
        recipient_handle = params.get("recipient_handle") or params.get("recipient")
    result = get_api().ack_message(message_id, {"recipient_handle": recipient_handle})
    return response(200, {"message_id": message_id, **result})


def route_agent_runtime(method: str, path: str, event: dict[str, Any]) -> dict[str, Any]:
    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    api = get_api()
    authorization = authorization_header(event)

    if method == "GET" and parts == ["agent", "me"]:
        return response(200, api.agent_me(authorization))

    if method == "GET" and parts == ["agent", "inbox"]:
        limit = query_limit(event, default=20, maximum=100)
        return response(200, api.agent_inbox(authorization, limit=limit))

    if method == "POST" and parts == ["agent", "inbox-posture"]:
        return response(200, api.agent_set_inbox_posture(authorization, parse_body(event)))

    if method == "POST" and parts == ["agent", "guest-invites"]:
        # Invite tokens are verified with the guest status signing secret;
        # without it a minted invite could never be honored.
        require_guest_status_signing_secret()
        return response(201, api.agent_mint_guest_invite(authorization, parse_body(event)))

    if method == "POST" and parts == ["agent", "posts"]:
        return response(201, api.agent_post(authorization, message_body(parse_body(event))))

    if method == "POST" and len(parts) == 4 and parts[:2] == ["agent", "deliveries"] and parts[3] == "decision":
        return response(200, api.agent_decide_delivery(authorization, parts[2], parse_body(event)))

    if method == "POST" and len(parts) == 4 and parts[:2] == ["agent", "deliveries"] and parts[3] == "ack":
        return response(200, api.agent_ack_delivery(authorization, parts[2]))

    if method == "GET" and parts == ["agent", "tasks"]:
        params = query_params(event)
        return response(
            200,
            api.agent_list_tasks(
                authorization,
                role=(params.get("role") or "all").strip() or "all",
                limit=query_limit(event, default=50, maximum=100),
            ),
        )

    if method == "POST" and parts == ["agent", "tasks"]:
        return response(201, api.agent_request_task(authorization, parse_body(event)))

    if method == "POST" and len(parts) == 4 and parts[:2] == ["agent", "tasks"] and parts[3] == "accept":
        return response(200, api.agent_accept_task(authorization, parts[2], parse_body(event)))

    if method == "POST" and len(parts) == 4 and parts[:2] == ["agent", "tasks"] and parts[3] == "results":
        return response(200, api.agent_return_result(authorization, parts[2], parse_body(event)))

    raise ApiError(404, "not_found", f"agent runtime route not found: {method} {path}")


def route_public_agent_messages(method: str, path: str, event: dict[str, Any]) -> dict[str, Any]:
    """Public agent URL routes: message an agent's card URL, read send status.

    Requests carrying an sga_ bearer token act as that token's agent; a
    token-less POST is GUEST ingress (posture-gated, rate-limited,
    quarantine-first) and a GET with a ``token`` query parameter is the
    signed guest status poll — neither needs Authorization.
    ``PUBLIC_AGENT_URLS_ENABLED`` is the deploy-time kill switch: when set to
    ``false``/``0`` these routes 404 exactly like unrouted paths (existing
    routes are unaffected).
    """
    if not public_agent_urls_enabled():
        return response(404, {"error": "not_found", "method": method, "path": path})

    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    api = get_api()

    if method == "POST" and len(parts) == 3:
        return public_agent_send_route(parts[1], event)

    if method == "GET" and len(parts) == 4:
        params = query_params(event)
        if "token" in params:
            # A token parameter — even an empty one — selects the guest flow,
            # where anything invalid reads as 404 (never 401/403).
            return response(200, api.public_agent_guest_message_status(parts[1], parts[3], params.get("token")))
        return response(200, api.public_agent_message_status(authorization_header(event), parts[1], parts[3]))

    return response(404, {"error": "not_found", "method": method, "path": path})


def public_agent_send_route(name: str, event: dict[str, Any]) -> dict[str, Any]:
    """POST /agents/{name}/messages for both sender classes, with the ops log.

    Every public send emits exactly one structured JSON log line (route,
    recipient handle — it is public — posture, sender_class, outcome,
    delivery_id) whether it succeeds or maps to an ApiError.
    """
    authorization = authorization_header(event)
    sender_class = "guest" if authorization is None else "registered"
    api = get_api()

    try:
        if authorization is None:
            # Guest ingress requires the status-URL signing secret: without it
            # the 202 envelope could not carry a verifiable status_url.
            require_guest_status_signing_secret()
            result = api.public_agent_send(
                None,
                name,
                parse_body(event),
                source_ip=guest_source_ip(event),
                invite_token=query_params(event).get("invite"),
            )
            replayed = False
        else:
            result = api.public_agent_send(
                authorization,
                name,
                parse_body(event),
                idempotency_key=idempotency_key_header(event),
            )
            replayed = bool(result.pop("replayed", False))
    except ApiError as exc:
        log_public_agent_send(
            api,
            name=name,
            sender_class=sender_class,
            outcome=exc.error,
            delivery_id=None,
        )
        raise

    log_public_agent_send(
        api,
        name=name,
        sender_class=sender_class,
        outcome="replayed" if replayed else "accepted",
        delivery_id=str(result.get("delivery_id") or ""),
    )
    return response(200 if replayed else 202, result)


def log_public_agent_send(
    api: LocalMessageHubApi,
    *,
    name: str,
    sender_class: str,
    outcome: str,
    delivery_id: str | None,
) -> None:
    posture = None
    recipient = None
    try:
        card = api.read_agent(name)["agent"]
        posture = card.get("inbox_posture")
        recipient = card.get("handle")
    except ApiError:
        pass
    # Recipient handles are public (they are the URL), so log them raw; guest
    # sender identities and message content are never logged.
    print(
        json.dumps(
            {
                "event": "public_agent_send",
                "route": "POST /agents/{name}/messages",
                "recipient": recipient or name,
                "posture": posture,
                "sender_class": sender_class,
                "outcome": outcome,
                "delivery_id": delivery_id,
            },
            sort_keys=True,
        )
    )


def require_guest_status_signing_secret() -> None:
    if not _cached_secret("GUEST_STATUS_SIGNING_SECRET"):
        raise ApiError(
            503,
            "config_error",
            "guest sends are not configured: set GUEST_STATUS_SIGNING_SECRET "
            "(or GUEST_STATUS_SIGNING_SECRET_ARN)",
        )


def guest_source_ip(event: dict[str, Any]) -> str:
    value = event.get("requestContext", {}).get("http", {}).get("sourceIp")
    normalized = str(value).strip() if value is not None else ""
    return normalized or "unknown"


def route_personal_agent(method: str, path: str, event: dict[str, Any]) -> dict[str, Any]:
    agent_handle, parts = personal_agent_path_parts(path)
    api = get_api()
    authorization = authorization_header(event)

    if method == "GET" and parts == ["inbox"]:
        api.require_agent_access(authorization, agent_handle, required_scope="agent:inbox")
        return read_inbox(agent_handle, event)

    if method == "POST" and parts == ["send"]:
        api.require_agent_access(authorization, agent_handle, required_scope="agent:post")
        return response(201, api.personal_agent_send(agent_handle, message_body(parse_body(event))))

    if method == "POST" and len(parts) == 3 and parts[0] == "deliveries":
        api.require_agent_access(authorization, agent_handle, required_scope="agent:post")
        delivery_id = unquote(parts[1])
        action = parts[2]
        body = parse_body(event)
        if action == "reply":
            return response(200, api.personal_agent_reply(agent_handle, delivery_id, body))
        if action == "ignore":
            return response(200, api.personal_agent_ignore(agent_handle, delivery_id, body))
        if action == "ask-owner":
            return response(200, api.personal_agent_ask_owner(agent_handle, delivery_id, body))
        raise ApiError(404, "not_found", f"personal-agent delivery action not found: {action}")

    if method == "POST" and parts == ["tasks"]:
        api.require_agent_access(authorization, agent_handle, required_scope="agent:post")
        return response(201, api.personal_agent_request_task(agent_handle, parse_body(event)))

    if method == "POST" and len(parts) == 3 and parts[0] == "tasks" and parts[2] == "accept":
        api.require_agent_access(authorization, agent_handle, required_scope="agent:post")
        return response(200, api.personal_agent_accept_task(agent_handle, unquote(parts[1]), parse_body(event)))

    if method == "POST" and len(parts) == 3 and parts[0] == "tasks" and parts[2] == "results":
        api.require_agent_access(authorization, agent_handle, required_scope="agent:post")
        return response(200, api.personal_agent_return_result(agent_handle, unquote(parts[1]), parse_body(event)))

    raise ApiError(404, "not_found", f"personal-agent route not found: {method} {path}")


# ---------------------------------------------------------------------------
# Auth helpers


def require_legacy_handle_routes_enabled(event: dict[str, Any]) -> None:
    allow = os.environ.get("MESSAGE_HUB_ALLOW_HANDLE_AGENT_ROUTES", "").lower()
    if allow in {"1", "true", "yes"}:
        return
    require_legacy_route_secret(event)


def require_legacy_route_secret(event: dict[str, Any]) -> None:
    legacy_secret = _cached_secret("MESSAGE_HUB_LEGACY_ROUTE_SECRET")
    if legacy_secret:
        headers = event.get("headers") or {}
        provided = (
            headers.get("x-seagull-legacy-secret")
            or headers.get("X-Seagull-Legacy-Secret")
            or headers.get("x-seagull-admin-secret")
            or headers.get("X-Seagull-Admin-Secret")
        )
        if provided and hmac.compare_digest(provided, legacy_secret):
            return
    raise ApiError(
        401,
        "unauthorized",
        "legacy handle-based message hub routes are disabled; use /agent runtime routes",
    )


def authorization_header(event: dict[str, Any]) -> str | None:
    headers = event.get("headers") or {}
    return headers.get("authorization") or headers.get("Authorization")


def accept_header(event: dict[str, Any]) -> str | None:
    headers = event.get("headers") or {}
    return headers.get("accept") or headers.get("Accept")


def idempotency_key_header(event: dict[str, Any]) -> str | None:
    headers = event.get("headers") or {}
    return headers.get("idempotency-key") or headers.get("Idempotency-Key")


def public_agent_urls_enabled() -> bool:
    # Kill switch for the public agent URL routes (Lambda only; the local api
    # has no flag). Default enabled; only explicit "false"/"0" disables.
    return os.environ.get("PUBLIC_AGENT_URLS_ENABLED", "").strip().lower() not in {"false", "0"}


# ---------------------------------------------------------------------------
# Request parsing helpers


def message_body(body: dict[str, Any]) -> dict[str, Any]:
    """Map legacy sender/recipient aliases onto the api's field names."""
    normalized = dict(body)
    if normalized.get("sender_handle") is None and normalized.get("sender") is not None:
        normalized["sender_handle"] = normalized["sender"]
    if normalized.get("recipient_handles") is None:
        for alias in ("recipient_handle", "recipient"):
            if normalized.get(alias) is not None:
                normalized["recipient_handles"] = [normalized[alias]]
                break
    return normalized


def public_agent_profile_path(path: str) -> bool:
    parts = [part for part in path.strip("/").split("/") if part]
    return len(parts) == 2 and parts[0] == "agents"


def public_agent_messages_path(path: str) -> bool:
    # /agents/{name}/messages and /agents/{name}/messages/{delivery_id}
    parts = [part for part in path.strip("/").split("/") if part]
    return len(parts) in {3, 4} and parts[0] == "agents" and parts[2] == "messages"


def path_param(path: str, prefix: str, suffix: str) -> str:
    value = path.removeprefix(prefix).removesuffix(suffix).strip("/")
    return unquote(value)


def delivery_path_param(path: str, suffix: str) -> str:
    if path.startswith("/agent/deliveries/"):
        return path_param(path, "/agent/deliveries/", suffix)
    if path.startswith("/deliveries/"):
        return path_param(path, "/deliveries/", suffix)
    raise ApiError(400, "bad_request", "delivery route must start with /deliveries or /agent/deliveries")


def personal_agent_path_parts(path: str) -> tuple[str, list[str]]:
    value = path.removeprefix("/personal-agents/").strip("/")
    parts = [part for part in value.split("/") if part]
    if len(parts) < 2:
        raise ApiError(404, "not_found", f"personal-agent route not found: {path}")
    return unquote(parts[0]), parts[1:]


def parse_body(event: dict[str, Any], *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_body = event.get("body")
    if not raw_body:
        return default if default is not None else {}
    if event.get("isBase64Encoded"):
        try:
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ApiError(400, "bad_request", "request body is not valid base64 or utf-8") from exc
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ApiError(400, "bad_request", "request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise ApiError(400, "bad_request", "JSON body must be an object")
    return body


def query_params(event: dict[str, Any]) -> dict[str, str]:
    return event.get("queryStringParameters") or {}


def query_limit(event: dict[str, Any], *, default: int, maximum: int) -> int:
    raw_limit = query_params(event).get("limit", default)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(limit, maximum))


def query_int(event: dict[str, Any], key: str, *, default: int, minimum: int, maximum: int) -> int:
    raw_value = query_params(event).get(key, default)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def optional_query_int(event: dict[str, Any], key: str, *, minimum: int, maximum: int) -> int | None:
    raw_value = query_params(event).get(key)
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        raise ApiError(400, "bad_request", f"{key} must be an integer") from None
    return max(minimum, min(value, maximum))


# ---------------------------------------------------------------------------
# Response helpers


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
        },
        "body": json.dumps(clean_item(body), default=json_default),
    }


def cacheable_response(status_code: int, body: dict[str, Any], *, max_age: int = 60) -> dict[str, Any]:
    """JSON response for public, auth-free resources (cards, discovery).

    The short TTL is what the apex CloudFront behavior honors; everything
    else keeps ``response``'s no-store.
    """
    result = response(status_code, body)
    result["headers"]["cache-control"] = f"public, max-age={max_age}"
    return result


def html_response(status_code: int, html_body: str, *, max_age: int = 60) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": HTML_MEDIA_TYPE,
            "cache-control": f"public, max-age={max_age}",
        },
        "body": html_body,
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clean_item(value: Any) -> Any:
    """Match the historical wire format: drop null fields, sort sets."""
    if isinstance(value, (list, tuple)):
        return [clean_item(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(clean_item(item) for item in value)
    if isinstance(value, dict):
        return {key: clean_item(item) for key, item in value.items() if item is not None}
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
