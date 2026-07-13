from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
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


# Terminal run states that must be reported back to the requesting task. Without
# reporting the non-completed ones, a failed/denied/quarantined run leaves the
# task hanging in its working state forever.
REPORTABLE_STATES = frozenset(
    {
        AiRunState.COMPLETED,
        AiRunState.FAILED,
        AiRunState.DENIED,
        AiRunState.QUARANTINED,
    }
)


def process_record(record: dict[str, Any]) -> AiRun:
    payload = parse_record_body(record)
    run_id = required_string(payload, "run_id")
    request = required_object(payload, "request")
    run = service.execute_queued_run(run_id=run_id, **request)
    callback = payload.get("message_hub")
    if run.state in REPORTABLE_STATES and callback is not None:
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

    agent_token = required_string(callback, "agent_token")
    body = task_result_body(run, callback)

    request = Request(
        f"{MESSAGE_HUB_API_URL}/agent/tasks/{run.task_id}/results",
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


def task_result_body(run: AiRun, callback: dict[str, Any]) -> dict[str, Any]:
    artifact_refs = [f"seagull://ai-runs/{run.run_id}"]
    if run.state == AiRunState.COMPLETED:
        body: dict[str, Any] = {
            "state": optional_string(callback, "state") or "completed",
            "artifact_refs": artifact_refs,
        }
        if run.output_ref is not None:
            body["content_ref"] = run.output_ref
        elif run.output_text is not None:
            body["content"] = run.output_text
        return body

    # Non-completed terminal runs still notify the requester so the task does not
    # hang. Denials/quarantines are refusals; a provider failure is a failure.
    task_state = "refused" if run.state in (AiRunState.DENIED, AiRunState.QUARANTINED) else "failed"
    reason = (
        run.denial_reason
        or run.safety_reason
        or run.credit_reason
        or run.budget_reason
        or run.finish_reason
        or run.state.value
    )
    return {
        "state": task_state,
        "artifact_refs": artifact_refs,
        "error": f"ai run {run.state.value}: {reason}",
    }


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
