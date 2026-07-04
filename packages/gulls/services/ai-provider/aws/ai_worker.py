from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ai_provider.domain import AiRun, AiRunState
from lambda_function import service


MESSAGE_HUB_API_URL = os.environ.get("MESSAGE_HUB_API_URL", "").strip().rstrip("/")
MESSAGE_HUB_TIMEOUT_SECONDS = float(os.environ.get("MESSAGE_HUB_TIMEOUT_SECONDS", "10"))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures = []
    processed = 0
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            process_record(record)
            processed += 1
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "level": "error",
                        "message": str(exc),
                        "message_id": message_id,
                    },
                    default=str,
                )
            )
            if message_id is None:
                raise
            failures.append({"itemIdentifier": message_id})
    return {"processed": processed, "batchItemFailures": failures}


def process_record(record: dict[str, Any]) -> AiRun:
    payload = parse_record_body(record)
    run_id = required_string(payload, "run_id")
    request = required_object(payload, "request")
    run = service.execute_queued_run(run_id=run_id, **request)
    callback = payload.get("message_hub")
    if run.state == AiRunState.COMPLETED and callback is not None:
        publish_message_hub_result(run, required_object(payload, "message_hub"))
    return run


def parse_record_body(record: dict[str, Any]) -> dict[str, Any]:
    raw_body = record.get("body")
    if not isinstance(raw_body, str):
        raise ValueError("SQS record body must be a string")
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError("SQS record body must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("SQS record body must be a JSON object")
    return parsed


def publish_message_hub_result(run: AiRun, callback: dict[str, Any]) -> None:
    if not MESSAGE_HUB_API_URL:
        raise RuntimeError("MESSAGE_HUB_API_URL is not configured")
    if run.task_id is None:
        raise RuntimeError("message hub callback requires run.task_id")

    responder_handle = required_string(callback, "responder_handle")
    agent_token = required_string(callback, "agent_token")
    state = optional_string(callback, "state") or "completed"
    body = {
        "state": state,
        "artifact_refs": [f"seagull://ai-runs/{run.run_id}"],
    }
    if run.output_ref is not None:
        body["content_ref"] = run.output_ref
    elif run.output_text is not None:
        body["content"] = run.output_text

    request = Request(
        f"{MESSAGE_HUB_API_URL}/personal-agents/{quote(responder_handle, safe='')}/tasks/{quote(run.task_id, safe='')}/results",
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={
            "authorization": f"Bearer {agent_token}",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=MESSAGE_HUB_TIMEOUT_SECONDS) as response:
            status = int(response.status)
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"message hub task result failed: HTTP {exc.code} {detail}") from exc
    except (OSError, TimeoutError, URLError) as exc:
        raise RuntimeError(f"message hub task result failed: {exc}") from exc
    if status < 200 or status >= 300:
        raise RuntimeError(f"message hub task result failed: HTTP {status} {raw_body}")


def required_object(body: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = body.get(field_name)
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def required_string(body: dict[str, Any], field_name: str) -> str:
    value = optional_string(body, field_name)
    if value is None:
        raise ValueError(f"{field_name} is required")
    return value


def optional_string(body: dict[str, Any], field_name: str) -> str | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None
