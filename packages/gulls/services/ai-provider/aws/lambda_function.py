from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any
from urllib.parse import unquote

import boto3

from ai_provider.api.local import (
    admin_audit_event_to_dict,
    budget_limit_to_dict,
    model_policy_to_dict,
    provider_config_to_dict,
    run_event_to_dict,
    run_to_dict,
    server_credit_balance_to_dict,
    server_credit_ledger_entry_to_dict,
    usage_record_to_dict,
    user_credit_balance_to_dict,
    user_credit_ledger_entry_to_dict,
)
from ai_provider.domain import AiProviderService, AiRunState, BudgetLimit, InvalidAiRunError, ModelPolicy
from ai_provider.providers import BedrockConverseProviderAdapter, FakeProviderAdapter, OpenAIProviderAdapter
from ai_provider.storage.dynamodb import DynamoDbAiProviderRepository
from seagull_common.lambda_runtime import (
    cors_headers as common_cors_headers,
    env_bool,
    env_int,
    jwt_claims,
    parse_body as common_parse_body,
    path_param as common_path_param,
    redacted_event,
    response as common_response,
    secret_env,
)
from seagull_common.logging import log
from seagull_common.validation import Validator


APP_NAME = os.environ.get("APP_NAME", "seagull-ai-provider")
PROVIDER_SECRET_PREFIX = os.environ.get("AI_PROVIDER_SECRET_PREFIX", APP_NAME)
ADMIN_SECRET = secret_env("AI_PROVIDER_ADMIN_SECRET")
ADMIN_GROUPS = tuple(
    group.strip().casefold()
    for group in os.environ.get("AI_PROVIDER_ADMIN_GROUPS", "seagull-admin,server-owner,admin").split(",")
    if group.strip()
)
PUBLIC_DEMO_ENABLED = env_bool("AI_PROVIDER_PUBLIC_DEMO_ENABLED", default=False)
PUBLIC_DEMO_PROVIDER = os.environ.get("AI_PROVIDER_PUBLIC_DEMO_PROVIDER", "openai").strip() or "openai"
PUBLIC_DEMO_MODEL = os.environ.get("AI_PROVIDER_PUBLIC_DEMO_MODEL", "").strip()
PUBLIC_DEMO_OWNER_USER_ID = os.environ.get("AI_PROVIDER_PUBLIC_DEMO_OWNER_USER_ID", "landing-demo").strip() or "landing-demo"
PUBLIC_DEMO_ACTOR_AGENT_ID = os.environ.get("AI_PROVIDER_PUBLIC_DEMO_ACTOR_AGENT_ID", "landing-demo-agent").strip() or "landing-demo-agent"
PUBLIC_DEMO_INPUT_CHAR_LIMIT = env_int("AI_PROVIDER_PUBLIC_DEMO_INPUT_CHAR_LIMIT", default=360, minimum=40)
PUBLIC_DEMO_MAX_OUTPUT_TOKENS = env_int("AI_PROVIDER_PUBLIC_DEMO_MAX_OUTPUT_TOKENS", default=64, minimum=8)
PUBLIC_DEMO_TOTAL_TOKEN_LIMIT = env_int("AI_PROVIDER_PUBLIC_DEMO_TOTAL_TOKEN_LIMIT", default=600, minimum=64)
PUBLIC_DEMO_USER_CREDIT_LIMIT = env_int("AI_PROVIDER_PUBLIC_DEMO_USER_CREDIT_LIMIT", default=600, minimum=64)
AI_RUN_QUEUE_URL = os.environ.get("AI_RUN_QUEUE_URL", "").strip()


dynamodb = boto3.resource("dynamodb")
repository = DynamoDbAiProviderRepository(
    runs_table=dynamodb.Table(os.environ["AI_RUNS_TABLE"]),
    run_events_table=dynamodb.Table(os.environ["AI_RUN_EVENTS_TABLE"]),
    usage_table=dynamodb.Table(os.environ["AI_USAGE_LEDGER_TABLE"]),
    user_credit_ledger_table=dynamodb.Table(os.environ["AI_USER_CREDIT_LEDGER_TABLE"]),
    server_credit_ledger_table=dynamodb.Table(os.environ["AI_SERVER_CREDIT_LEDGER_TABLE"]),
    provider_configs_table=dynamodb.Table(os.environ["AI_PROVIDER_CONFIGS_TABLE"]),
    admin_audit_events_table=dynamodb.Table(os.environ["AI_ADMIN_AUDIT_EVENTS_TABLE"]),
    model_policies_table=dynamodb.Table(os.environ["AI_MODEL_POLICIES_TABLE"]),
    budget_limits_table=dynamodb.Table(os.environ["AI_BUDGET_LIMITS_TABLE"]),
)


def provider_api_key(provider: str) -> str:
    config = repository_provider_config(provider)
    if config is not None and config.secret_ref:
        return secret_ref_value(config.secret_ref)
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY", "").strip()
    return ""


def repository_provider_config(provider: str) -> Any:
    config = repository.get_provider_config(provider)
    if config is not None:
        return config
    normalized_provider = provider.casefold()
    for candidate in repository.list_provider_configs():
        if candidate.provider.casefold() == normalized_provider:
            return candidate
    return None


def secret_ref_value(secret_ref: str) -> str:
    ref = secret_ref.strip()
    if not ref:
        return ""
    if ref.lower().startswith("env:"):
        return os.environ.get(ref[4:].strip(), "").strip()
    if ref in os.environ:
        return os.environ.get(ref, "").strip()
    try:
        result = secretsmanager_client().get_secret_value(SecretId=ref)
    except Exception as exc:
        log("warning", f"could not load provider secret {ref}: {exc}")
        return ""
    return secret_string(result).strip()


def save_provider_api_key(provider: str, api_key: str) -> str:
    secret = api_key.strip()
    if not secret:
        raise BadRequest("api_key cannot be empty")
    secret_name = provider_secret_name(provider)
    client = secretsmanager_client()
    try:
        client.create_secret(Name=secret_name, SecretString=secret)
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code != "ResourceExistsException":
            raise
        client.put_secret_value(SecretId=secret_name, SecretString=secret)
    return secret_name


def provider_secret_name(provider: str) -> str:
    safe_provider = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in provider.strip().casefold()
    ).strip("-")
    return f"{PROVIDER_SECRET_PREFIX}/providers/{safe_provider or 'provider'}/api-key"


def secretsmanager_client() -> Any:
    return boto3.client("secretsmanager")


def secret_string(result: dict[str, Any]) -> str:
    secret = result.get("SecretString")
    if isinstance(secret, str):
        return secret
    encoded = result.get("SecretBinary")
    if isinstance(encoded, (bytes, bytearray)):
        return base64.b64decode(encoded).decode("utf-8")
    if isinstance(encoded, str):
        return base64.b64decode(encoded).decode("utf-8")
    return ""


service = AiProviderService(
    repository,
    {
        "fake": FakeProviderAdapter(),
        "openai": OpenAIProviderAdapter(api_key_resolver=provider_api_key),
        "bedrock": BedrockConverseProviderAdapter(),
    },
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

        if method == "POST" and path == "/demo/landing/ai-run":
            return handle_landing_demo_run(event)

        if method == "POST" and path == "/ai-runs":
            body = parse_body(event)
            owner_user_id = required_string(body, "owner_user_id")
            require_owner_or_admin(event, owner_user_id)
            run_kwargs = ai_run_request_kwargs(body, owner_user_id=owner_user_id)
            if async_run_requested(body):
                if not AI_RUN_QUEUE_URL:
                    raise BadRequest("AI run queue is not configured")
                run = service.create_queued_run(**run_kwargs)
                queued = run.state == AiRunState.QUEUED
                if queued:
                    enqueue_ai_run(run.run_id, run.owner_user_id, run_kwargs, message_hub_callback(body))
                return response(202 if queued else 200, {"run": run_to_dict(run), "queued": queued})

            run = service.create_run(**run_kwargs)
            return response(200, {"run": run_to_dict(run)})

        if method == "GET" and path.startswith("/ai-runs/") and path.endswith("/events"):
            require_authenticated_request(event)
            run_id = path_param(path, "/ai-runs/", "/events")
            run = service.get_run(run_id)
            require_owner_or_admin(event, run.owner_user_id)
            return response(
                200,
                {
                    "run_id": run_id,
                    "events": [run_event_to_dict(event) for event in service.list_run_events(run_id)],
                },
            )

        if method == "GET" and path.startswith("/ai-runs/"):
            require_authenticated_request(event)
            run_id = unquote(path.removeprefix("/ai-runs/").strip("/"))
            run = service.get_run(run_id)
            require_owner_or_admin(event, run.owner_user_id)
            return response(200, {"run": run_to_dict(run)})

        if method == "GET" and path.startswith("/owners/") and path.endswith("/ai-usage"):
            owner_user_id = path_param(path, "/owners/", "/ai-usage")
            require_owner_or_admin(event, owner_user_id)
            return response(
                200,
                {
                    "owner_user_id": owner_user_id,
                    "usage": [usage_record_to_dict(record) for record in service.list_usage_by_owner(owner_user_id)],
                },
            )

        if method == "GET" and path.startswith("/owners/") and path.endswith("/ai-usage-summary"):
            owner_user_id = path_param(path, "/owners/", "/ai-usage-summary")
            require_owner_or_admin(event, owner_user_id)
            return response(
                200,
                {
                    "owner_user_id": owner_user_id,
                    "balance": user_credit_balance_to_dict(service.get_user_credit_balance(owner_user_id)),
                    "usage": [
                        usage_record_to_dict(record)
                        for record in service.list_usage_by_owner(owner_user_id)
                    ],
                    "entries": [
                        user_credit_ledger_entry_to_dict(entry)
                        for entry in service.list_user_credit_ledger(owner_user_id)
                    ],
                },
            )

        if method == "GET" and path.startswith("/agents/") and path.endswith("/ai-usage"):
            require_admin(event)
            agent_id = path_param(path, "/agents/", "/ai-usage")
            return response(
                200,
                {
                    "agent_id": agent_id,
                    "usage": [usage_record_to_dict(record) for record in service.list_usage_by_agent(agent_id)],
                },
            )

        if path.startswith("/admin/"):
            require_admin(event)

        if method == "POST" and path == "/admin/ai-credits/server-grants":
            body = parse_body(event)
            entry = service.grant_server_credits(
                admin_actor_id=required_string(body, "admin_actor_id"),
                credit_amount=required_int(body, "credit_amount"),
                reason=optional_string(body, "reason") or "server credit grant",
            )
            return response(200, {"entry": server_credit_ledger_entry_to_dict(entry)})

        if method == "GET" and path == "/admin/ai-credits/server-balance":
            return response(200, {"balance": server_credit_balance_to_dict(service.get_server_credit_balance())})

        if method == "GET" and path == "/admin/ai-credits/server-ledger":
            return response(
                200,
                {"entries": [server_credit_ledger_entry_to_dict(entry) for entry in service.list_server_credit_ledger()]},
            )

        if method == "POST" and path.startswith("/owners/") and path.endswith("/ai-credits/grants"):
            require_admin(event)
            body = parse_body(event)
            owner_user_id = path_param(path, "/owners/", "/ai-credits/grants")
            entry = service.grant_user_credits(
                admin_actor_id=required_string(body, "admin_actor_id"),
                owner_user_id=owner_user_id,
                credit_amount=required_int(body, "credit_amount"),
                reason=optional_string(body, "reason") or "manual credit grant",
            )
            return response(200, {"entry": user_credit_ledger_entry_to_dict(entry)})

        if method == "GET" and path.startswith("/owners/") and path.endswith("/ai-credits/balance"):
            owner_user_id = path_param(path, "/owners/", "/ai-credits/balance")
            require_owner_or_admin(event, owner_user_id)
            return response(200, {"balance": user_credit_balance_to_dict(service.get_user_credit_balance(owner_user_id))})

        if method == "GET" and path.startswith("/owners/") and path.endswith("/ai-credits/ledger"):
            owner_user_id = path_param(path, "/owners/", "/ai-credits/ledger")
            require_owner_or_admin(event, owner_user_id)
            return response(
                200,
                {
                    "owner_user_id": owner_user_id,
                    "entries": [user_credit_ledger_entry_to_dict(entry) for entry in service.list_user_credit_ledger(owner_user_id)],
                },
            )

        if method == "POST" and path.startswith("/admin/ai-providers/"):
            body = parse_body(event)
            provider = unquote(path.removeprefix("/admin/ai-providers/").strip("/"))
            if not provider:
                raise BadRequest("provider is required")
            existing_config = service_provider_config(provider)
            secret_ref = optional_string(body, "secret_ref")
            api_key = optional_string(body, "api_key")
            if api_key:
                secret_ref = save_provider_api_key(provider, api_key)
            elif secret_ref is None and existing_config is not None and existing_config.secret_ref:
                secret_ref = existing_config.secret_ref
            config = service.save_provider_config(
                admin_actor_id=required_string(body, "admin_actor_id"),
                provider=provider,
                enabled=optional_bool(body, "enabled", default=True),
                allowed_models=string_list(body.get("allowed_models", ()), "allowed_models"),
                secret_ref=secret_ref,
                region=optional_string(body, "region"),
                reason=optional_string(body, "reason") or "provider config update",
            )
            return response(200, {"provider_config": provider_config_to_dict(config)})

        if method == "GET" and path == "/admin/ai-providers":
            return response(
                200,
                {"provider_configs": [provider_config_to_dict(config) for config in service.list_provider_configs()]},
            )

        if method == "GET" and path == "/admin/ai-audit-events":
            return response(
                200,
                {"events": [admin_audit_event_to_dict(event) for event in service.list_admin_audit_events()]},
            )

        if method == "POST" and path == "/admin/model-policies":
            require_admin(event)
            body = parse_body(event)
            policy = ModelPolicy(
                policy_id=required_string(body, "policy_id"),
                scope_key=required_string(body, "scope_key"),
                allowed_providers=string_list(body.get("allowed_providers", ()), "allowed_providers"),
                allowed_models=string_list(body.get("allowed_models", ()), "allowed_models"),
                max_output_tokens=optional_nullable_int(body, "max_output_tokens"),
                enabled=optional_bool(body, "enabled", default=True),
            )
            service.put_model_policy(policy)
            return response(200, {"policy": model_policy_to_dict(policy)})

        if method == "POST" and path == "/admin/budget-limits":
            require_admin(event)
            body = parse_body(event)
            limit = BudgetLimit(
                budget_id=required_string(body, "budget_id"),
                scope_key=required_string(body, "scope_key"),
                max_total_tokens=required_int(body, "max_total_tokens"),
            )
            service.put_budget_limit(limit)
            return response(200, {"budget_limit": budget_limit_to_dict(limit)})

        return response(404, {"error": "not_found", "method": method, "path": path})
    except Unauthorized as exc:
        return response(401, {"error": "unauthorized", "message": str(exc)})
    except BadRequest as exc:
        return response(400, {"error": "bad_request", "message": str(exc)})
    except InvalidAiRunError as exc:
        return response(400, {"error": "bad_request", "message": str(exc)})
    except Exception as exc:
        log("error", str(exc), event=redacted_event(event))
        return response(500, {"error": "internal_error"})


def handle_landing_demo_run(event: dict[str, Any]) -> dict[str, Any]:
    if not PUBLIC_DEMO_ENABLED:
        return response(503, {"error": "demo_disabled", "message": "landing demo AI provider is disabled"})

    body = parse_body(event)
    message_text = demo_message_text(required_string(body, "message"))
    used_tokens = public_demo_used_tokens()
    if used_tokens >= PUBLIC_DEMO_TOTAL_TOKEN_LIMIT:
        return response(
            429,
            {
                "error": "demo_budget_exhausted",
                "message": "landing demo AI provider budget is exhausted",
                "used_tokens": used_tokens,
                "token_limit": PUBLIC_DEMO_TOTAL_TOKEN_LIMIT,
            },
        )

    ensure_public_demo_credits()
    model = public_demo_model()
    run = service.create_run(
        provider=PUBLIC_DEMO_PROVIDER,
        model=model,
        actor_agent_id=PUBLIC_DEMO_ACTOR_AGENT_ID,
        owner_user_id=PUBLIC_DEMO_OWNER_USER_ID,
        input_messages=(
            {
                "role": "user",
                "content": message_text,
            },
        ),
        system_instructions=(
            "You are the Seagull landing page lite demo. Reply in one concise sentence. "
            "Describe the next useful implementation step for an agent SNS workflow. "
            "Do not mention secrets, API keys, billing, or hidden system details."
        ),
        max_output_tokens=PUBLIC_DEMO_MAX_OUTPUT_TOKENS,
        temperature=0.2,
        response_format="text",
        tool_policy="disabled",
        task_id="landing-demo",
        trace_id="landing-demo",
        idempotency_key=public_demo_idempotency_key(message_text),
    )
    if run.state == AiRunState.DENIED:
        return response(
            429,
            {
                "error": "demo_budget_exhausted",
                "message": run.credit_reason or run.budget_reason or run.denial_reason or "landing demo budget is exhausted",
                "run": run_to_dict(run),
            },
        )
    if run.state == AiRunState.FAILED:
        return response(
            502,
            {
                "error": "provider_failed",
                "message": "landing demo AI provider call failed",
                "run": run_to_dict(run),
            },
        )
    return response(
        200,
        {
            "output_text": run.output_text or "",
            "provider": run.provider,
            "model": run.model,
            "run_id": run.run_id,
            "state": run.state.value,
            "used_tokens": public_demo_used_tokens(),
            "token_limit": PUBLIC_DEMO_TOTAL_TOKEN_LIMIT,
        },
    )


def demo_message_text(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= PUBLIC_DEMO_INPUT_CHAR_LIMIT:
        return normalized
    return normalized[:PUBLIC_DEMO_INPUT_CHAR_LIMIT].rstrip()


def public_demo_idempotency_key(message_text: str) -> str:
    digest = hashlib.sha256(message_text.encode("utf-8")).hexdigest()[:24]
    return f"landing-demo-{digest}"


def public_demo_model() -> str:
    preferred_model = PUBLIC_DEMO_MODEL or ("gpt-5.4-mini" if PUBLIC_DEMO_PROVIDER == "openai" else "fake-small")
    config = service_provider_config(PUBLIC_DEMO_PROVIDER)
    if config is not None and config.allowed_models:
        if preferred_model in config.allowed_models:
            return preferred_model
        return config.allowed_models[0]
    return preferred_model


def service_provider_config(provider: str) -> Any:
    config = service.get_provider_config(provider)
    if config is not None:
        return config
    normalized_provider = provider.casefold()
    for candidate in service.list_provider_configs():
        if candidate.provider.casefold() == normalized_provider:
            return candidate
    return None


def public_demo_used_tokens() -> int:
    return sum(record.total_tokens for record in service.list_usage_by_owner(PUBLIC_DEMO_OWNER_USER_ID))


def ensure_public_demo_credits() -> None:
    ledger = service.list_user_credit_ledger(PUBLIC_DEMO_OWNER_USER_ID)
    if ledger:
        return
    server_balance = service.get_server_credit_balance().available_credits
    if server_balance < PUBLIC_DEMO_USER_CREDIT_LIMIT:
        service.grant_server_credits(
            admin_actor_id="landing-demo",
            credit_amount=PUBLIC_DEMO_USER_CREDIT_LIMIT - server_balance,
            reason="landing demo server credit bootstrap",
        )
    service.grant_user_credits(
        admin_actor_id="landing-demo",
        owner_user_id=PUBLIC_DEMO_OWNER_USER_ID,
        credit_amount=PUBLIC_DEMO_USER_CREDIT_LIMIT,
        reason="landing demo credit bootstrap",
    )


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    return common_parse_body(event, error=BadRequest)


def ai_run_request_kwargs(body: dict[str, Any], *, owner_user_id: str) -> dict[str, Any]:
    return {
        "provider": required_string(body, "provider"),
        "model": required_string(body, "model"),
        "actor_agent_id": required_string(body, "actor_agent_id"),
        "owner_user_id": owner_user_id,
        "input_messages": provider_messages(body.get("input_messages", ())),
        "system_instructions": optional_string(body, "system_instructions"),
        "system_instructions_ref": optional_string(body, "system_instructions_ref"),
        "context_refs": string_list(body.get("context_refs", ()), "context_refs"),
        "content_ref": optional_string(body, "content_ref"),
        "max_output_tokens": optional_int(body, "max_output_tokens", default=512),
        "temperature": optional_float(body, "temperature", default=0.2),
        "response_format": optional_string(body, "response_format") or "text",
        "tool_policy": optional_string(body, "tool_policy") or "disabled",
        "task_id": optional_string(body, "task_id"),
        "message_id": optional_string(body, "message_id"),
        "trace_id": optional_string(body, "trace_id"),
        "idempotency_key": optional_string(body, "idempotency_key"),
    }


def async_run_requested(body: dict[str, Any]) -> bool:
    if optional_bool(body, "async", default=False):
        return True
    return (optional_string(body, "execution_mode") or "").casefold() == "async"


def enqueue_ai_run(
    run_id: str,
    owner_user_id: str,
    run_kwargs: dict[str, Any],
    callback: dict[str, Any] | None,
) -> None:
    payload = {
        "run_id": run_id,
        "request": serializable_run_request(run_kwargs),
    }
    if callback is not None:
        payload["message_hub"] = callback
    boto3.client("sqs").send_message(
        QueueUrl=AI_RUN_QUEUE_URL,
        MessageBody=json.dumps(payload, separators=(",", ":")),
        MessageGroupId=owner_user_id,
        MessageDeduplicationId=run_id,
    )


def serializable_run_request(run_kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": run_kwargs["provider"],
        "model": run_kwargs["model"],
        "actor_agent_id": run_kwargs["actor_agent_id"],
        "owner_user_id": run_kwargs["owner_user_id"],
        "input_messages": list(run_kwargs["input_messages"]),
        "system_instructions": run_kwargs["system_instructions"],
        "system_instructions_ref": run_kwargs["system_instructions_ref"],
        "context_refs": list(run_kwargs["context_refs"]),
        "content_ref": run_kwargs["content_ref"],
        "max_output_tokens": run_kwargs["max_output_tokens"],
        "temperature": run_kwargs["temperature"],
        "response_format": run_kwargs["response_format"],
        "tool_policy": run_kwargs["tool_policy"],
        "task_id": run_kwargs["task_id"],
        "message_id": run_kwargs["message_id"],
        "trace_id": run_kwargs["trace_id"],
        "idempotency_key": run_kwargs["idempotency_key"],
    }


def message_hub_callback(body: dict[str, Any]) -> dict[str, Any] | None:
    callback = body.get("message_hub")
    if callback is None:
        return None
    if not isinstance(callback, dict):
        raise BadRequest("message_hub must be an object")
    responder_handle = optional_string(callback, "responder_handle")
    agent_token = optional_string(callback, "agent_token")
    if responder_handle is None or agent_token is None:
        raise BadRequest("message_hub.responder_handle and message_hub.agent_token are required")
    return {
        "responder_handle": responder_handle,
        "agent_token": agent_token,
        "state": optional_string(callback, "state") or "completed",
    }


CORS_HEADERS = common_cors_headers(allow_headers="authorization,content-type,x-seagull-admin-secret")


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return common_response(status_code, body, headers=CORS_HEADERS)


def cors_response() -> dict[str, Any]:
    return response(204, {})


def require_admin(event: dict[str, Any]) -> None:
    if admin_claims(jwt_claims(event)):
        return
    if not ADMIN_SECRET:
        raise Unauthorized("admin API is not configured")
    if not is_admin_request(event):
        raise Unauthorized("admin secret is required")


def is_admin_request(event: dict[str, Any]) -> bool:
    if not ADMIN_SECRET:
        return False
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    provided = headers.get("x-seagull-admin-secret")
    return isinstance(provided, str) and hmac.compare_digest(provided, ADMIN_SECRET)


def require_authenticated_request(event: dict[str, Any]) -> None:
    if is_admin_request(event):
        return
    if not jwt_claims(event):
        raise Unauthorized("authentication is required")


def require_owner_or_admin(event: dict[str, Any], owner_user_id: str) -> None:
    if is_admin_request(event):
        return
    claims = jwt_claims(event)
    if not claims:
        raise Unauthorized("authentication is required")
    claim_owner_user_id = owner_user_id_from_claims(claims)
    if claim_owner_user_id is None:
        raise Unauthorized("authenticated token is missing owner_user_id claim")
    if not hmac.compare_digest(claim_owner_user_id, owner_user_id):
        raise Unauthorized("owner_user_id does not match authenticated user")


def owner_user_id_from_claims(claims: dict[str, Any]) -> str | None:
    for name in ("custom:seagull_user_id", "custom:owner_user_id", "seagull_user_id", "owner_user_id"):
        value = optional_claim(claims, name)
        if value is not None:
            return value
    return optional_claim(claims, "sub")


def optional_claim(claims: dict[str, Any], name: str) -> str | None:
    value = claims.get(name)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def admin_claims(claims: dict[str, Any] | None) -> bool:
    if not claims:
        return False
    admin_flag = optional_claim(claims, "custom:seagull_admin") or optional_claim(claims, "seagull_admin")
    if admin_flag is not None and admin_flag.casefold() in {"1", "true", "yes"}:
        return True
    groups = claim_values(claims.get("cognito:groups"))
    roles = claim_values(claims.get("custom:role")) + claim_values(claims.get("role"))
    allowed = set(ADMIN_GROUPS)
    return any(value.casefold() in allowed for value in groups + roles)


def claim_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.replace(",", " ").split() if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def provider_messages(value: Any) -> tuple[dict[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise BadRequest("input_messages must be a list")
    messages: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise BadRequest("input_messages must contain objects")
        message = {
            "role": required_string(item, "role"),
            "content": required_string(item, "content"),
        }
        content_ref = optional_string(item, "content_ref")
        if content_ref is not None:
            message["content_ref"] = content_ref
        messages.append(message)
    return tuple(messages)


_validator = Validator(BadRequest)
required_string = _validator.required_string
optional_string = _validator.optional_string
string_list = _validator.string_list
required_int = _validator.required_int
optional_int = _validator.optional_int_with_default
optional_nullable_int = _validator.optional_int
optional_float = _validator.optional_float
optional_bool = _validator.optional_bool


def path_param(path: str, prefix: str, suffix: str) -> str:
    return common_path_param(path, prefix, suffix, error=BadRequest)
