import base64
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


APP_NAME = os.environ.get("APP_NAME", "seagull-message-hub")
SAFETY_BLOCKED_TERMS = tuple(
    term.strip().lower()
    for term in os.environ.get("SAFETY_BLOCKED_TERMS", "unsafe:").split(",")
    if term.strip()
)
DEFAULT_CONTEXT_MAX_INLINE_CHARS = 4000
DEFAULT_CONTEXT_MAX_RECENT_MESSAGES = 10
DEFAULT_CONTEXT_MAX_PAYLOAD_REFS = 20
MAX_ENVELOPE_INLINE_CHARS = 4000
DEFAULT_CONTACT_RELATIONSHIP = "needs_approval"
CONTACT_EXPLANATION_SUMMARY_CHARS = 280
PRIVATE_CONTEXT_REF_MARKERS = (
    "mcp://",
    "file://",
    "localhost",
    "127.0.0.1",
    "::1",
    ".sock",
    "tool://",
    "raw_tool",
    "raw-tool",
    "tool_handle",
    "tool-handle",
    "mcp_server",
    "mcp-server",
    "credential",
    "credentials",
    "secret",
    "token",
    "api_key",
    "apikey",
    "password",
    "authorization",
    "bearer ",
)
PRIVATE_PROFILE_MARKERS = PRIVATE_CONTEXT_REF_MARKERS

AGENTS_TABLE = os.environ["AGENTS_TABLE"]
MESSAGES_TABLE = os.environ["MESSAGES_TABLE"]
THREADS_TABLE = os.environ["THREADS_TABLE"]
DELIVERIES_TABLE = os.environ["DELIVERIES_TABLE"]
IDEMPOTENCY_TABLE = os.environ["IDEMPOTENCY_TABLE"]
ROUTING_RULES_TABLE = os.environ.get("ROUTING_RULES_TABLE")
THREAD_SUMMARIES_TABLE = os.environ["THREAD_SUMMARIES_TABLE"]
TASKS_TABLE = os.environ.get("TASKS_TABLE")
TOOL_REQUESTS_TABLE = os.environ.get("TOOL_REQUESTS_TABLE")
TASK_RESULTS_TABLE = os.environ.get("TASK_RESULTS_TABLE")
AGENT_JOBS_QUEUE_URL = os.environ.get("AGENT_JOBS_QUEUE_URL")

dynamodb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")
agents_table = dynamodb.Table(AGENTS_TABLE)
messages_table = dynamodb.Table(MESSAGES_TABLE)
threads_table = dynamodb.Table(THREADS_TABLE)
deliveries_table = dynamodb.Table(DELIVERIES_TABLE)
idempotency_table = dynamodb.Table(IDEMPOTENCY_TABLE)
routing_rules_table = dynamodb.Table(ROUTING_RULES_TABLE) if ROUTING_RULES_TABLE else None
thread_summaries_table = dynamodb.Table(THREAD_SUMMARIES_TABLE)
tasks_table = dynamodb.Table(TASKS_TABLE) if TASKS_TABLE else None
tool_requests_table = dynamodb.Table(TOOL_REQUESTS_TABLE) if TOOL_REQUESTS_TABLE else None
task_results_table = dynamodb.Table(TASK_RESULTS_TABLE) if TASK_RESULTS_TABLE else None


class BadRequest(ValueError):
    pass


class NotFound(ValueError):
    pass


class Conflict(ValueError):
    pass


class Blocked(ValueError):
    pass


class Forbidden(ValueError):
    pass


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "/")

    try:
        if method == "GET" and path == "/health":
            return response(200, {"ok": True, "app": APP_NAME, "storage": "dynamodb", "time": now_iso()})

        if method == "POST" and path == "/agents":
            return register_agent(event)

        if method == "POST" and path == "/routing-rules":
            return create_routing_rule(event)

        if method == "GET" and path == "/routing-rules":
            return read_routing_rules()

        if method == "GET" and path.startswith("/agents/") and path.endswith("/inbox"):
            handle = path_param(path, "/agents/", "/inbox")
            return read_inbox(handle, event)

        if method == "GET" and path.startswith("/agents/") and path.endswith("/outbox"):
            handle = path_param(path, "/agents/", "/outbox")
            return read_outbox(handle, event)

        if method == "GET" and path.startswith("/agents/") and path.endswith("/sent"):
            handle = path_param(path, "/agents/", "/sent")
            return read_sent_messages(handle, event)

        if method == "GET" and path.startswith("/agents/"):
            handle = unquote(path.removeprefix("/agents/").strip("/"))
            return read_agent(handle)

        if method == "POST" and path == "/messages":
            return create_message(event)

        if method == "POST" and path == "/tasks":
            return create_task(event)

        if method == "POST" and path.startswith("/tasks/") and path.endswith("/accept"):
            task_id = path_param(path, "/tasks/", "/accept")
            return accept_task(task_id, event)

        if method == "POST" and path.startswith("/tasks/") and path.endswith("/status"):
            task_id = path_param(path, "/tasks/", "/status")
            return update_task_status(task_id, event)

        if method == "POST" and path.startswith("/tasks/") and path.endswith("/results"):
            task_id = path_param(path, "/tasks/", "/results")
            return return_task_result(task_id, event)

        if method == "POST" and path.startswith("/tasks/") and path.endswith("/tool-requests"):
            task_id = path_param(path, "/tasks/", "/tool-requests")
            return create_task_tool_request(task_id, event)

        if method == "POST" and path.startswith("/tool-requests/") and path.endswith("/complete"):
            tool_request_id = path_param(path, "/tool-requests/", "/complete")
            return complete_task_tool_request(tool_request_id, event)

        if method == "GET" and path.startswith("/tasks/"):
            task_id = unquote(path.removeprefix("/tasks/").strip("/"))
            return read_task(task_id)

        if method == "POST" and path.endswith("/hook-results"):
            delivery_id = delivery_path_param(path, "/hook-results")
            return submit_hook_result(delivery_id, event)

        if method == "POST" and path.endswith("/decision"):
            delivery_id = delivery_path_param(path, "/decision")
            return submit_delivery_decision(delivery_id, event)

        if method == "GET" and path.endswith("/contact-explanation"):
            delivery_id = delivery_path_param(path, "/contact-explanation")
            return read_contact_explanation(delivery_id)

        if method == "GET" and path.startswith("/threads/") and path.endswith("/context"):
            thread_id = path_param(path, "/threads/", "/context")
            return read_thread_context(thread_id, event)

        if method == "GET" and path.startswith("/threads/") and path.endswith("/context-pack"):
            thread_id = path_param(path, "/threads/", "/context-pack")
            return read_context_pack(thread_id, event)

        if method == "GET" and path.startswith("/threads/") and path.endswith("/tasks"):
            thread_id = path_param(path, "/threads/", "/tasks")
            return read_thread_tasks(thread_id, event)

        if method == "GET" and path.startswith("/threads/"):
            thread_id = unquote(path.removeprefix("/threads/").strip("/"))
            return read_thread(thread_id, event)

        if method == "POST" and path.startswith("/messages/") and path.endswith("/ack"):
            message_id = path_param(path, "/messages/", "/ack")
            return ack_message(message_id, event)

        return response(404, {"error": "not_found", "method": method, "path": path})
    except BadRequest as exc:
        return response(400, {"error": "bad_request", "message": str(exc)})
    except NotFound as exc:
        return response(404, {"error": "not_found", "message": str(exc)})
    except Conflict as exc:
        return response(409, {"error": "conflict", "message": str(exc)})
    except Blocked as exc:
        return response(403, {"error": "blocked", "message": str(exc)})
    except Forbidden as exc:
        return response(403, {"error": "forbidden", "message": str(exc)})
    except Exception as exc:
        print(json.dumps({"level": "error", "message": str(exc), "event": event}, default=str))
        return response(500, {"error": "internal_error"})


def register_agent(event: dict[str, Any]) -> dict[str, Any]:
    body = parse_body(event)
    handle = normalize_handle(required(body, "handle"))
    now = now_iso()

    existing_agent = get_agent_by_handle(handle)
    if existing_agent is not None:
        return response(200, {"created": False, "agent": public_agent(existing_agent)})

    agent = {
        "agent_id": agent_id_for_handle(handle),
        "handle": handle,
        "display_name": optional_string(body, "display_name"),
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    capabilities = string_list(body.get("capabilities", []), "capabilities")
    if capabilities:
        agent["capabilities"] = set(capabilities)
    response_rules = response_rules_object(body.get("response_rules"))
    if response_rules is not None:
        agent["response_rules"] = response_rules
    trigger_mode, webhook_url = trigger_config(body)
    agent["trigger_mode"] = trigger_mode
    if webhook_url is not None:
        agent["webhook_url"] = webhook_url

    try:
        agents_table.put_item(
            Item=without_none(agent),
            ConditionExpression="attribute_not_exists(agent_id)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        existing_agent = get_agent_by_handle(handle)
        if existing_agent is None:
            raise Conflict(f"agent already exists: {handle}") from exc
        return response(200, {"created": False, "agent": public_agent(existing_agent)})

    return response(201, {"created": True, "agent": public_agent(agent)})


def read_agent(handle: str) -> dict[str, Any]:
    agent = require_agent_by_handle(handle)
    return response(200, {"agent": public_agent(agent)})


def create_routing_rule(event: dict[str, Any]) -> dict[str, Any]:
    if routing_rules_table is None:
        raise BadRequest("routing rules are not configured")

    body = parse_body(event)
    mode = (optional_string(body, "mode") or "copy").lower()
    if mode not in {"direct", "copy", "handoff", "review", "block"}:
        raise BadRequest("mode must be direct, copy, handoff, review, or block")

    route_to_handles = [normalize_handle(handle) for handle in string_list(body.get("route_to_handles", []), "route_to_handles")]
    if mode != "block" and not route_to_handles:
        raise BadRequest("route_to_handles is required unless mode is block")
    for handle in route_to_handles:
        require_agent_by_handle(handle)

    url_contains = [
        value.strip().lower()
        for value in string_list(body.get("url_contains", []), "url_contains")
        if value.strip()
    ]
    if not url_contains:
        raise BadRequest("url_contains requires at least one value")

    now = now_iso()
    rule = {
        "rule_id": f"routing_rule_{uuid.uuid4().hex}",
        "name": required(body, "name"),
        "mode": mode,
        "route_to_handles": route_to_handles,
        "url_contains": url_contains,
        "enabled": optional_bool(body, "enabled", default=True),
        "created_at": now,
        "updated_at": now,
    }
    routing_rules_table.put_item(Item=without_none(rule), ConditionExpression="attribute_not_exists(rule_id)")
    return response(201, {"created": True, "routing_rule": clean_item(rule)})


def read_routing_rules() -> dict[str, Any]:
    if routing_rules_table is None:
        raise BadRequest("routing rules are not configured")
    result = routing_rules_table.scan()
    rules = result.get("Items", [])
    rules.sort(key=lambda rule: (rule.get("created_at", ""), rule.get("rule_id", "")))
    return response(200, {"items": clean_item(rules)})


def create_message(event: dict[str, Any]) -> dict[str, Any]:
    body = parse_body(event)
    sender_handle = normalize_handle(body.get("sender_handle") or body.get("sender") or "")
    sender = require_agent_by_handle(sender_handle)

    recipient_handles = message_recipient_handles(body)
    recipients = [require_agent_by_handle(handle) for handle in recipient_handles]
    visibility = optional_string(body, "visibility") or "direct"
    refs = refs_list(body.get("refs", []), "refs")
    content_inline = optional_string(body, "content") or optional_string(body, "content_inline")
    content_ref = optional_string(body, "content_ref")
    recipients, routing_trace, needs_review = apply_routing_rules(
        recipients=recipients,
        content_inline=content_inline,
        content_ref=content_ref,
        refs=refs,
    )
    if visibility != "public" and not recipients:
        raise BadRequest("direct or limited messages require at least one recipient")

    if content_inline is None and content_ref is None and not refs:
        raise BadRequest("content, content_ref, or refs is required")

    idempotency_key = optional_string(body, "idempotency_key")
    if idempotency_key:
        existing_message_id = get_idempotent_message_id(sender["agent_id"], idempotency_key)
        if existing_message_id is not None:
            return response(200, send_result(existing_message_id, idempotent=True))

    safety_status = local_safety_status(content_inline)
    stored_content_inline, stored_content_ref = envelope_content_for_storage(
        content_inline,
        content_ref,
        "message content",
    )

    thread_id = optional_string(body, "thread_id")
    now = now_iso()
    if thread_id:
        existing_thread = get_thread_record(thread_id)
        if existing_thread is None:
            raise NotFound(f"thread not found: {thread_id}")
    else:
        thread_id = f"thread_{uuid.uuid4().hex}"
        existing_thread = None

    message_id = f"message_{uuid.uuid4().hex}"
    recipient_agent_ids = [agent["agent_id"] for agent in recipients]
    message = {
        "message_id": message_id,
        "thread_id": thread_id,
        "sender_agent_id": sender["agent_id"],
        "sender_handle": sender["handle"],
        "intent": optional_string(body, "intent") or "message",
        "visibility": visibility,
        "content_inline": stored_content_inline,
        "content_ref": stored_content_ref,
        "refs": refs,
        "schema_version": "seagull.message.v1",
        "safety_status": safety_status,
        "created_at": now,
    }
    if recipient_agent_ids:
        message["recipient_agent_ids"] = set(recipient_agent_ids)
        message["recipient_handles"] = set(agent["handle"] for agent in recipients)

    if existing_thread is None:
        thread = {
            "thread_id": thread_id,
            "root_message_id": message_id,
            "participants": set([sender["agent_id"], *recipient_agent_ids]),
            "message_count": 1,
            "last_message_id": message_id,
            "last_message_at": now,
            "created_at": now,
            "updated_at": now,
        }
    else:
        thread = existing_thread

    deliveries = [
        {
            "delivery_id": f"delivery_{message_id}_{recipient['agent_id']}",
            "message_id": message_id,
            "thread_id": thread_id,
            "sender_agent_id": sender["agent_id"],
            "sender_handle": sender["handle"],
            "recipient_agent_id": recipient["agent_id"],
            "recipient_handle": recipient["handle"],
            "status": "needs_review" if needs_review else "delivered",
            "retry_count": 0,
            "current_content_inline": stored_content_inline,
            "current_content_ref": stored_content_ref,
            "refs": refs,
            "workflow_trace": routing_trace,
            "current_stage": "human.review" if needs_review else "agent.wait",
            "created_at": now,
            "updated_at": now,
        }
        for recipient in recipients
    ]

    messages_table.put_item(Item=without_none(message), ConditionExpression="attribute_not_exists(message_id)")
    if existing_thread is None:
        threads_table.put_item(Item=thread, ConditionExpression="attribute_not_exists(thread_id)")
    else:
        update_existing_thread(thread_id, message_id, now, [sender["agent_id"], *recipient_agent_ids])

    for delivery in deliveries:
        deliveries_table.put_item(Item=delivery, ConditionExpression="attribute_not_exists(delivery_id)")

    enqueue_delivery_events(deliveries, message, sender, recipients)

    if idempotency_key:
        idempotency_table.put_item(
            Item={
                "sender_agent_id": sender["agent_id"],
                "idempotency_key": idempotency_key,
                "message_id": message_id,
                "created_at": now,
                "expires_at": int(time.time()) + 604800,
            }
        )

    return response(
        201,
        {
            "message": clean_item(message),
            "thread": clean_item(get_thread_record(thread_id) or thread),
            "deliveries": clean_item(deliveries),
            "message_id": message_id,
            "thread_id": thread_id,
        },
    )


def create_task(event: dict[str, Any]) -> dict[str, Any]:
    require_task_tables()
    body = parse_body(event)
    reject_private_task_fields(body)
    requester = require_agent_by_handle(required(body, "requester_handle"))
    recipient = require_agent_by_handle(required(body, "recipient_handle"))
    objective = required(body, "objective")
    require_small_inline(objective, "objective")
    idempotency_key = optional_string(body, "idempotency_key")
    if idempotency_key:
        existing_task_id = get_idempotent_task_id(requester["agent_id"], idempotency_key)
        if existing_task_id is not None:
            existing_task = tasks_table.get_item(Key={"task_id": existing_task_id}).get("Item")
            if existing_task is not None:
                return response(200, {"created": False, "task": clean_item(existing_task), "task_id": existing_task_id, "thread_id": existing_task["thread_id"]})

    task_id = f"task_{uuid.uuid4().hex}"
    message_response = create_message(
        {
            "body": json.dumps(
                without_none(
                    {
                        "sender_handle": requester["handle"],
                        "recipient_handles": [recipient["handle"]],
                        "thread_id": optional_string(body, "thread_id"),
                        "intent": "task_request",
                        "visibility": "direct",
                        "refs": [task_ref(task_id, "task request")],
                    }
                )
            )
        }
    )
    message_body = json.loads(message_response["body"])
    now = now_iso()
    task = {
        "task_id": task_id,
        "thread_id": message_body["thread_id"],
        "requester_agent_id": requester["agent_id"],
        "recipient_agent_id": recipient["agent_id"],
        "objective": objective,
        "request_message_id": message_body["message_id"],
        "context_refs": string_list(body.get("context_refs", []), "context_refs"),
        "context_pack_id": optional_string(body, "context_pack_id"),
        "context_pack_ref": optional_string(body, "context_pack_ref"),
        "input_ref": optional_string(body, "input_ref"),
        "stream_id": optional_string(body, "stream_id"),
        "allowed_tool_names": string_list(body.get("allowed_tool_names", []), "allowed_tool_names"),
        "allowed_use_terms": string_list(body.get("allowed_use_terms", []), "allowed_use_terms"),
        "state": "requested",
        "policy_decision_id": "local_safety_allow",
        "artifact_refs": [],
        "tool_request_ids": [],
        "created_at": now,
        "updated_at": now,
    }
    tasks_table.put_item(Item=without_none(task), ConditionExpression="attribute_not_exists(task_id)")
    if idempotency_key:
        idempotency_table.put_item(
            Item={
                "sender_agent_id": requester["agent_id"],
                "idempotency_key": f"task:{idempotency_key}",
                "task_id": task_id,
                "created_at": now,
                "expires_at": int(time.time()) + 604800,
            }
        )
    return response(201, {"created": True, "task": clean_item(task), "task_id": task_id, "thread_id": task["thread_id"]})


def read_task(task_id: str) -> dict[str, Any]:
    task = require_task(task_id)
    return response(200, {"task": clean_item(task)})


def read_thread_tasks(thread_id: str, event: dict[str, Any]) -> dict[str, Any]:
    require_task_tables()
    if get_thread_record(thread_id) is None:
        raise NotFound(f"thread not found: {thread_id}")
    result = tasks_table.query(
        IndexName="thread-created-at-index",
        KeyConditionExpression=Key("thread_id").eq(thread_id),
        ScanIndexForward=True,
        Limit=query_limit(event, default=50, maximum=100),
    )
    return response(200, {"thread_id": thread_id, "tasks": clean_item(result.get("Items", []))})


def accept_task(task_id: str, event: dict[str, Any]) -> dict[str, Any]:
    require_task_tables()
    body = parse_body(event)
    task = require_task(task_id)
    worker = require_agent_by_handle(required(body, "worker_handle"))
    if worker["agent_id"] != task["recipient_agent_id"]:
        raise Forbidden("only the recipient agent can accept this task")
    now = now_iso()
    task["state"] = "accepted"
    task["accepted_by_agent_id"] = worker["agent_id"]
    task["updated_at"] = now
    tasks_table.put_item(Item=without_none(task))
    send_task_notification(
        task,
        sender=worker,
        recipient_agent_id=task["requester_agent_id"],
        intent="status_update",
        label="task accepted",
        note=optional_string(body, "note"),
    )
    return response(200, {"task": clean_item(task), "task_id": task_id, "thread_id": task["thread_id"], "state": task["state"]})


def update_task_status(task_id: str, event: dict[str, Any]) -> dict[str, Any]:
    require_task_tables()
    body = parse_body(event)
    task = require_task(task_id)
    actor = require_agent_by_handle(required(body, "actor_handle"))
    require_task_actor(task, actor)
    state = normalize_task_state(required(body, "state"))
    now = now_iso()
    task["state"] = state
    task["updated_at"] = now
    tasks_table.put_item(Item=without_none(task))
    recipient_agent_id = task["requester_agent_id"] if actor["agent_id"] != task["requester_agent_id"] else task["recipient_agent_id"]
    send_task_notification(
        task,
        sender=actor,
        recipient_agent_id=recipient_agent_id,
        intent="status_update",
        label=f"task {state}",
        note=optional_string(body, "note"),
    )
    return response(200, {"task": clean_item(task), "task_id": task_id, "thread_id": task["thread_id"], "state": state})


def return_task_result(task_id: str, event: dict[str, Any]) -> dict[str, Any]:
    require_task_tables()
    body = parse_body(event)
    task = require_task(task_id)
    responder = require_agent_by_handle(required(body, "responder_handle"))
    require_task_actor(task, responder)
    if responder["agent_id"] == task["requester_agent_id"]:
        raise Forbidden("requester cannot return its own task result")
    state = normalize_task_state(optional_string(body, "state") or "completed")
    content_inline = optional_string(body, "content") or optional_string(body, "content_inline")
    content_ref = optional_string(body, "content_ref")
    artifact_refs = string_list(body.get("artifact_refs", []), "artifact_refs")
    tool_use_summary_refs = string_list(body.get("tool_use_summary_refs", []), "tool_use_summary_refs")
    stored_content_inline, stored_content_ref = envelope_content_for_storage(
        content_inline,
        content_ref,
        "task result content",
    )
    stream_id = optional_string(body, "stream_id") or task.get("stream_id")
    if task.get("stream_id") and stream_id != task["stream_id"]:
        raise BadRequest("task result stream_id must match task stream_id")
    error = optional_string(body, "error")
    if stored_content_inline is None and stored_content_ref is None and not artifact_refs and error is None:
        raise BadRequest("task result requires content, content_ref, artifact_refs, or error")

    result_id = f"task_result_{uuid.uuid4().hex}"
    result_ref = f"seagull://tasks/{task_id}/results/{result_id}"
    requester = require_agent(task["requester_agent_id"])
    message_response = create_message(
        {
            "body": json.dumps(
                without_none(
                    {
                        "sender_handle": responder["handle"],
                        "recipient_handles": [requester["handle"]],
                        "thread_id": task["thread_id"],
                        "intent": "task_result",
                        "visibility": "direct",
                        "content_ref": stored_content_ref,
                        "refs": [{"type": "task_result", "url": result_ref, "remember_as": "task result"}],
                    }
                )
            )
        }
    )
    message_body = json.loads(message_response["body"])
    now = now_iso()
    result = {
        "result_id": result_id,
        "task_id": task_id,
        "thread_id": task["thread_id"],
        "responder_agent_id": responder["agent_id"],
        "state": state,
        "result_message_id": message_body["message_id"],
        "stream_id": stream_id,
        "content_inline": stored_content_inline,
        "content_ref": stored_content_ref,
        "artifact_refs": artifact_refs,
        "tool_use_summary_refs": tool_use_summary_refs,
        "error": error,
        "created_at": now,
    }
    task_results_table.put_item(Item=without_none(result), ConditionExpression="attribute_not_exists(result_id)")
    task["state"] = state
    task["result_message_id"] = message_body["message_id"]
    task["result_ref"] = result_ref
    if stream_id:
        task["stream_id"] = stream_id
    task["artifact_refs"] = list(dict.fromkeys([*task.get("artifact_refs", []), *artifact_refs]))
    task["updated_at"] = now
    tasks_table.put_item(Item=without_none(task))
    return response(200, {"task_id": task_id, "thread_id": task["thread_id"], "state": state, "result": clean_item(result)})


def create_task_tool_request(task_id: str, event: dict[str, Any]) -> dict[str, Any]:
    require_task_tables()
    body = parse_body(event)
    reject_private_task_fields(body)
    task = require_task(task_id)
    requester = require_agent_by_handle(required(body, "requester_handle"))
    worker = require_agent_by_handle(required(body, "worker_handle"))
    if requester["agent_id"] != task["requester_agent_id"]:
        raise Forbidden("only the task requester can request delegated tool use")
    if worker["agent_id"] != task["recipient_agent_id"]:
        raise Forbidden("tool request worker must be the task recipient")
    now = now_iso()
    tool_request_id = f"tool_request_{uuid.uuid4().hex}"
    tool_request = {
        "tool_request_id": tool_request_id,
        "task_id": task_id,
        "thread_id": task["thread_id"],
        "requester_agent_id": requester["agent_id"],
        "worker_agent_id": worker["agent_id"],
        "tool_name": required(body, "tool_name"),
        "purpose": required(body, "purpose"),
        "input_ref": optional_string(body, "input_ref"),
        "requires_approval": optional_bool(body, "requires_approval", default=True),
        "approval_id": optional_string(body, "approval_id"),
        "policy_decision_id": optional_string(body, "policy_decision_id"),
        "created_at": now,
        "updated_at": now,
    }
    tool_request["status"] = "needs_approval" if tool_request["requires_approval"] else "requested"
    tool_requests_table.put_item(Item=without_none(tool_request), ConditionExpression="attribute_not_exists(tool_request_id)")
    task["tool_request_ids"] = [*task.get("tool_request_ids", []), tool_request_id]
    task["updated_at"] = now
    tasks_table.put_item(Item=without_none(task))
    send_task_notification(
        task,
        sender=requester,
        recipient_agent_id=worker["agent_id"],
        intent="tool_request",
        label="tool request",
        ref={"type": "tool_request", "url": f"seagull://tasks/{task_id}/tool-requests/{tool_request_id}", "remember_as": "tool request"},
    )
    return response(201, {"tool_request": clean_item(tool_request), "tool_request_id": tool_request_id, "task_id": task_id})


def complete_task_tool_request(tool_request_id: str, event: dict[str, Any]) -> dict[str, Any]:
    require_task_tables()
    body = parse_body(event)
    tool_request = require_tool_request(tool_request_id)
    actor = require_agent_by_handle(required(body, "actor_handle"))
    if actor["agent_id"] != tool_request["worker_agent_id"]:
        raise Forbidden("only the worker agent can complete this tool request")
    state = normalize_task_state(required(body, "state"))
    now = now_iso()
    tool_request["status"] = state
    if state in {"accepted", "running", "result_ready", "completed"}:
        tool_request["accepted_by_agent_id"] = actor["agent_id"]
    tool_request["result_ref"] = optional_string(body, "result_ref")
    tool_request["artifact_refs"] = string_list(body.get("artifact_refs", []), "artifact_refs")
    tool_request["tool_use_summary_ref"] = optional_string(body, "tool_use_summary_ref")
    tool_request["updated_at"] = now
    tool_requests_table.put_item(Item=without_none(tool_request))
    return response(200, {"tool_request": clean_item(tool_request), "tool_request_id": tool_request_id, "task_id": tool_request["task_id"], "state": state})


def read_inbox(handle: str, event: dict[str, Any]) -> dict[str, Any]:
    agent = require_agent_by_handle(handle)
    result = deliveries_table.query(
        IndexName="recipient-created-at-index",
        KeyConditionExpression=Key("recipient_agent_id").eq(agent["agent_id"]),
        ScanIndexForward=False,
        Limit=query_limit(event, default=20, maximum=100),
    )
    return response(200, {"agent": public_agent(agent), "items": delivery_items(result.get("Items", []))})


def read_outbox(handle: str, event: dict[str, Any]) -> dict[str, Any]:
    agent = require_agent_by_handle(handle)
    result = deliveries_table.query(
        IndexName="sender-created-at-index",
        KeyConditionExpression=Key("sender_agent_id").eq(agent["agent_id"]),
        ScanIndexForward=False,
        Limit=query_limit(event, default=20, maximum=100),
    )
    return response(200, {"agent": public_agent(agent), "items": delivery_items(result.get("Items", []))})


def read_sent_messages(handle: str, event: dict[str, Any]) -> dict[str, Any]:
    agent = require_agent_by_handle(handle)
    result = messages_table.query(
        IndexName="sender-created-at-index",
        KeyConditionExpression=Key("sender_agent_id").eq(agent["agent_id"]),
        ScanIndexForward=False,
        Limit=query_limit(event, default=20, maximum=100),
    )
    return response(200, {"agent": public_agent(agent), "messages": clean_item(result.get("Items", []))})


def read_thread(thread_id: str, event: dict[str, Any]) -> dict[str, Any]:
    thread = get_thread_record(thread_id)
    if thread is None:
        raise NotFound(f"thread not found: {thread_id}")

    result = messages_table.query(
        IndexName="thread-created-at-index",
        KeyConditionExpression=Key("thread_id").eq(thread_id),
        ScanIndexForward=True,
        Limit=query_limit(event, default=50, maximum=100),
    )
    return response(200, {"thread": clean_item(thread), "messages": clean_item(result.get("Items", []))})


def read_thread_context(thread_id: str, event: dict[str, Any]) -> dict[str, Any]:
    thread = get_thread_record(thread_id)
    if thread is None:
        raise NotFound(f"thread not found: {thread_id}")

    message_result = messages_table.query(
        IndexName="thread-created-at-index",
        KeyConditionExpression=Key("thread_id").eq(thread_id),
        ScanIndexForward=False,
        Limit=query_limit(event, default=10, maximum=20),
    )
    recent_messages = list(reversed(message_result.get("Items", [])))
    summary = latest_thread_summary(thread_id) or generated_summary(recent_messages)
    return response(
        200,
        {
            "thread": clean_item(thread),
            "context_mode": "summary_plus_recent",
            "summary": clean_item(summary),
            "recent_messages": clean_item(recent_messages),
        },
    )


def read_context_pack(thread_id: str, event: dict[str, Any]) -> dict[str, Any]:
    thread = get_thread_record(thread_id)
    if thread is None:
        raise NotFound(f"thread not found: {thread_id}")

    params = query_params(event)
    requester_handle = normalize_handle(required(params, "requester_handle"))
    requester = require_agent_by_handle(requester_handle)
    participants = set(thread.get("participants", []))
    if requester["agent_id"] not in participants:
        raise Forbidden("agent cannot read context for this thread")

    max_inline_chars = query_int(
        event,
        "max_inline_chars",
        default=DEFAULT_CONTEXT_MAX_INLINE_CHARS,
        minimum=0,
        maximum=20000,
    )
    max_recent_messages = query_int(
        event,
        "max_recent_messages",
        default=DEFAULT_CONTEXT_MAX_RECENT_MESSAGES,
        minimum=0,
        maximum=50,
    )
    max_payload_refs = query_int(
        event,
        "max_payload_refs",
        default=DEFAULT_CONTEXT_MAX_PAYLOAD_REFS,
        minimum=0,
        maximum=100,
    )
    token_budget_estimate = optional_query_int(
        event,
        "token_budget_estimate",
        minimum=0,
        maximum=1_000_000,
    )

    if max_recent_messages == 0:
        messages = []
    else:
        message_result = messages_table.query(
            IndexName="thread-created-at-index",
            KeyConditionExpression=Key("thread_id").eq(thread_id),
            ScanIndexForward=False,
            Limit=max_recent_messages,
        )
        messages = list(reversed(message_result.get("Items", [])))
    inline_chars_used = 0
    truncated = False
    budgeted_messages = []
    selected_refs = []
    payload_refs = []
    redacted_refs = []

    for message in messages:
        budgeted_message = dict(message)
        content_inline = budgeted_message.get("content_inline")
        if isinstance(content_inline, str) and content_inline:
            remaining_chars = max(max_inline_chars - inline_chars_used, 0)
            if len(content_inline) <= remaining_chars:
                inline_chars_used += len(content_inline)
            elif remaining_chars > 0:
                budgeted_message["content_inline"] = content_inline[:remaining_chars]
                inline_chars_used += remaining_chars
                truncated = True
                redacted_refs.append(f"message://{message['message_id']}/content_inline")
            else:
                budgeted_message.pop("content_inline", None)
                truncated = True
                redacted_refs.append(f"message://{message['message_id']}/content_inline")

        content_ref = budgeted_message.get("content_ref")
        if isinstance(content_ref, str) and content_ref:
            if private_context_value(content_ref):
                budgeted_message.pop("content_ref", None)
                redacted_refs.append(f"message://{message['message_id']}/content_ref")
            elif len(payload_refs) < max_payload_refs:
                payload_refs.append(
                    {
                        "content_ref": content_ref,
                        "source_type": "message",
                        "source_id": budgeted_message["message_id"],
                    }
                )

        for ref in message.get("refs", []):
            if private_context_ref(ref):
                redacted_refs.append(f"message://{message['message_id']}/ref")
                continue
            if len(selected_refs) < max_payload_refs:
                selected_refs.append(ref)

        budgeted_message["refs"] = []
        budgeted_messages.append(budgeted_message)

    summary = latest_thread_summary(thread_id)
    context_summary = dict(summary) if summary else None
    if context_summary and isinstance(context_summary.get("content_ref"), str):
        summary_content_ref = context_summary["content_ref"]
        if private_context_value(summary_content_ref):
            context_summary.pop("content_ref", None)
            redacted_refs.append(f"summary://{context_summary.get('summary_id', 'latest')}/content_ref")
        elif len(payload_refs) < max_payload_refs:
            payload_refs.append(
                {
                    "content_ref": summary_content_ref,
                    "source_type": "thread_summary",
                    "source_id": context_summary.get("summary_id", "latest"),
                }
            )

    allowed_recipients = sorted(
        agent["handle"]
        for agent_id in participants
        for agent in (agents_table.get_item(Key={"agent_id": agent_id}).get("Item"),)
        if agent is not None
    )
    return response(
        200,
        {
            "context_pack_id": f"context_pack_{thread_id}_{requester['agent_id']}",
            "thread": clean_item(thread),
            "requester_handle": requester["handle"],
            "summary": clean_item(context_summary),
            "recent_messages": clean_item(budgeted_messages),
            "selected_refs": clean_item(selected_refs),
            "payload_refs": clean_item(payload_refs),
            "budget": {
                "max_inline_chars": max_inline_chars,
                "max_recent_messages": max_recent_messages,
                "max_payload_refs": max_payload_refs,
                "token_budget_estimate": token_budget_estimate,
                "inline_chars_used": inline_chars_used,
                "recent_messages_returned": len(budgeted_messages),
                "payload_refs_returned": len(payload_refs),
                "truncated": truncated,
            },
            "access_scope": "recipients",
            "allowed_recipients": allowed_recipients,
            "redacted_refs": redacted_refs,
            "created_at": now_iso(),
        },
    )


def ack_message(message_id: str, event: dict[str, Any]) -> dict[str, Any]:
    body = parse_body(event, default={})
    recipient_handle = optional_string(body, "recipient_handle") or optional_string(body, "recipient")
    if recipient_handle is None:
        recipient_handle = query_params(event).get("recipient_handle") or query_params(event).get("recipient")

    key_expression = Key("message_id").eq(message_id)

    if recipient_handle:
        recipient = require_agent_by_handle(recipient_handle)
        key_expression = key_expression & Key("recipient_agent_id").eq(recipient["agent_id"])

    result = deliveries_table.query(
        IndexName="message-recipient-index",
        KeyConditionExpression=key_expression,
    )
    deliveries = result.get("Items", [])
    if not deliveries:
        raise NotFound(f"delivery not found for message: {message_id}")

    now = now_iso()
    updated = []
    for delivery in deliveries:
        update_result = deliveries_table.update_item(
            Key={"delivery_id": delivery["delivery_id"]},
            UpdateExpression="SET #status = :status, acked_at = :acked_at, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "acked",
                ":acked_at": now,
                ":updated_at": now,
            },
            ReturnValues="ALL_NEW",
        )
        updated.append(update_result["Attributes"])

    return response(200, {"message_id": message_id, "deliveries": clean_item(updated)})


def submit_hook_result(delivery_id: str, event: dict[str, Any]) -> dict[str, Any]:
    body = parse_body(event)
    delivery = require_delivery(delivery_id)
    hook = normalize_hook(required(body, "hook"))
    runtime = normalize_runtime(required(body, "runtime"))
    action = normalize_hook_action(optional_string(body, "action") or "continue")
    refs = refs_list(body.get("refs", []), "refs")
    now = now_iso()

    changed = []
    content_inline = optional_string(body, "content") or optional_string(body, "current_content_inline")
    content_ref = optional_string(body, "content_ref") or optional_string(body, "current_content_ref")
    if content_inline is not None:
        stored_content_inline, stored_content_ref = envelope_content_for_storage(
            content_inline,
            content_ref,
            "delivery content",
        )
        delivery["current_content_inline"] = stored_content_inline
        changed.append("current_content_inline")
        if stored_content_ref is not None:
            delivery["current_content_ref"] = stored_content_ref
            changed.append("current_content_ref")
    if content_ref is not None:
        delivery["current_content_ref"] = content_ref
        if content_inline is None:
            delivery.pop("current_content_inline", None)
            changed.append("current_content_inline")
        if "current_content_ref" not in changed:
            changed.append("current_content_ref")
    if refs:
        delivery["refs"] = list(delivery.get("refs", [])) + refs
        changed.append("refs")

    delivery["status"] = delivery.get("status", "delivered")
    delivery["current_stage"] = next_stage_after_hook(hook, delivery.get("current_stage", "agent.wait"))
    note = optional_string(body, "note")
    if action == "block":
        delivery["status"] = "failed"
        delivery["last_error"] = note or "blocked by hook result"
        delivery["current_stage"] = "blocked"
    elif action == "review":
        delivery["status"] = "needs_review"
        delivery["current_stage"] = "human.review"
    elif action == "fail":
        delivery["status"] = "failed"
        delivery["last_error"] = note or "hook result failed"
        delivery["current_stage"] = "failed"

    delivery["workflow_trace"] = list(delivery.get("workflow_trace", [])) + [
        {
            "hook": hook,
            "runtime": runtime,
            "action": action,
            "actor": optional_string(body, "actor"),
            "changed": changed,
            "note": note,
            "created_at": now,
        }
    ]
    delivery["updated_at"] = now
    deliveries_table.put_item(Item=without_none(delivery))
    return response(200, {"delivery": clean_item(delivery)})


def submit_delivery_decision(delivery_id: str, event: dict[str, Any]) -> dict[str, Any]:
    body = parse_body(event)
    delivery = require_delivery(delivery_id)
    agent = require_agent_by_handle(required(body, "agent_handle"))
    if delivery.get("recipient_agent_id") != agent["agent_id"]:
        raise Forbidden("agent cannot decide another recipient's delivery")

    decision = normalize_agent_decision(required(body, "decision"))
    now = now_iso()
    trace = {
        "hook": "agent.decision",
        "runtime": "agent_client",
        "action": decision,
        "actor": agent["handle"],
        "note": optional_string(body, "note"),
        "created_at": now,
    }

    if decision == "reply":
        content_inline = optional_string(body, "content") or optional_string(body, "content_inline")
        content_ref = optional_string(body, "content_ref")
        refs = refs_list(body.get("refs", []), "refs")
        if content_inline is None and content_ref is None and not refs:
            raise BadRequest("reply decision requires content, content_ref, or refs")

        sender = require_agent(delivery["sender_agent_id"])
        reply_response = create_message(
            {
                "body": json.dumps(
                    {
                        "sender_handle": agent["handle"],
                        "recipient_handles": [sender["handle"]],
                        "content": content_inline,
                        "content_ref": content_ref,
                        "refs": refs,
                        "intent": "reply",
                        "visibility": "direct",
                        "thread_id": delivery["thread_id"],
                    }
                )
            }
        )
        reply_body = json.loads(reply_response["body"])
        delivery["status"] = "replied"
        delivery["current_stage"] = "done"
        delivery["acked_at"] = now
        delivery["updated_at"] = now
        delivery["workflow_trace"] = list(delivery.get("workflow_trace", [])) + [trace]
        deliveries_table.put_item(Item=without_none(delivery))
        return response(200, {"delivery": clean_item(delivery), "reply": reply_body, "action_request": None})

    if decision == "action":
        action_request = {
            "action_request_id": f"action_{uuid.uuid4().hex}",
            "type": required(body, "action_type"),
            "target": optional_string(body, "action_target"),
            "runtime": normalize_runtime(optional_string(body, "action_runtime") or "cloud"),
            "requires_approval": optional_bool(body, "requires_approval", default=True),
            "status": "pending",
            "created_at": now,
        }
        delivery["status"] = "pending_action"
        delivery["current_stage"] = "action.before"
        delivery["action_request"] = action_request
        delivery["updated_at"] = now
        delivery["workflow_trace"] = list(delivery.get("workflow_trace", [])) + [trace]
        deliveries_table.put_item(Item=without_none(delivery))
        return response(200, {"delivery": clean_item(delivery), "reply": None, "action_request": action_request})

    delivery["status"] = "ignored" if decision == "ignore" else "needs_review"
    delivery["current_stage"] = "done" if decision == "ignore" else "human.review"
    if decision == "ignore":
        delivery["acked_at"] = now
    delivery["updated_at"] = now
    delivery["workflow_trace"] = list(delivery.get("workflow_trace", [])) + [trace]
    deliveries_table.put_item(Item=without_none(delivery))
    return response(200, {"delivery": clean_item(delivery), "reply": None, "action_request": None})


def read_contact_explanation(delivery_id: str) -> dict[str, Any]:
    delivery = require_delivery(delivery_id)
    message = messages_table.get_item(Key={"message_id": delivery["message_id"]}).get("Item")
    if message is None:
        raise NotFound(f"message not found: {delivery['message_id']}")
    thread = get_thread_record(delivery["thread_id"])
    if thread is None:
        raise NotFound(f"thread not found: {delivery['thread_id']}")

    requester = require_agent(delivery["sender_agent_id"])
    recipient = require_agent(delivery["recipient_agent_id"])
    relationship = DEFAULT_CONTACT_RELATIONSHIP
    summary = latest_thread_summary(delivery["thread_id"])
    tasks = contact_tasks_for_message(delivery["thread_id"], message["message_id"])
    explanation = {
        "explanation_id": f"contact_explanation_{delivery['delivery_id']}",
        "delivery_id": delivery["delivery_id"],
        "message_id": message["message_id"],
        "thread_id": delivery["thread_id"],
        "requester_agent_id": requester["agent_id"],
        "requester_handle": requester["handle"],
        "recipient_agent_id": recipient["agent_id"],
        "recipient_handle": recipient["handle"],
        "answering_asset_handle": recipient["handle"],
        "relationship": relationship,
        "reason": contact_reason(message, delivery, requester, recipient),
        "allowed_reason": contact_allowed_reason(message, delivery, relationship),
        "shared_context_summary": contact_shared_context_summary(message, delivery, summary),
        "shared_context_refs": contact_shared_context_refs(message, delivery, tasks),
        "pending_action": contact_pending_action(delivery, tasks),
        "current_stage": delivery.get("current_stage", "agent.wait"),
        "policy_refs": contact_policy_refs(message, delivery, relationship, tasks),
        "audit_event_refs": contact_audit_refs(delivery, thread),
        "created_at": delivery.get("updated_at") or delivery.get("created_at"),
    }
    return response(200, {"explanation": clean_item(explanation)})


def contact_tasks_for_message(thread_id: str, message_id: str) -> list[dict[str, Any]]:
    if tasks_table is None:
        return []
    result = tasks_table.query(
        IndexName="thread-created-at-index",
        KeyConditionExpression=Key("thread_id").eq(thread_id),
        ScanIndexForward=True,
        Limit=100,
    )
    return [task for task in result.get("Items", []) if task.get("request_message_id") == message_id]


def contact_reason(
    message: dict[str, Any],
    delivery: dict[str, Any],
    requester: dict[str, Any],
    recipient: dict[str, Any],
) -> str:
    intent = str(message.get("intent") or "message").replace("_", " ")
    route_entries = [
        entry
        for entry in delivery.get("workflow_trace", [])
        if entry.get("hook") == "route.resolve"
    ]
    if message.get("intent") == "task_request":
        return f"{requester['handle']} requested delegated task work from {recipient['handle']}."
    if message.get("intent") == "reply":
        return f"{requester['handle']} replied to {recipient['handle']} in this thread."
    if route_entries:
        route_labels = ", ".join(str(entry.get("note") or entry.get("action")) for entry in route_entries)
        return f"{requester['handle']} sent a {intent}; routing delivered it to {recipient['handle']} via {route_labels}."
    return f"{requester['handle']} sent a {intent} to {recipient['handle']}."


def contact_allowed_reason(
    message: dict[str, Any],
    delivery: dict[str, Any],
    relationship: str,
) -> str:
    status = str(delivery.get("status") or "delivered")
    reasons = [
        f"message safety status is {message.get('safety_status', 'unknown')}",
        f"relationship is {relationship}",
    ]
    if status == "needs_review":
        reasons.append("delivery is held for human review")
    elif status == "pending_action" and delivery.get("action_request"):
        action_request = delivery["action_request"]
        reasons.append(
            "requested action requires approval"
            if action_request.get("requires_approval", True)
            else "requested action is preapproved"
        )
    else:
        reasons.append(f"delivery state is {status}")
    return f"Seagull allowed the contact because {'; '.join(reasons)}."


def contact_shared_context_summary(
    message: dict[str, Any],
    delivery: dict[str, Any],
    summary: dict[str, Any] | None,
) -> str:
    if summary and summary.get("summary_text"):
        return truncate_contact_text(str(summary["summary_text"]))
    content = delivery.get("current_content_inline") or message.get("content_inline")
    if isinstance(content, str) and content:
        return truncate_contact_text(content)
    content_ref = delivery.get("current_content_ref") or message.get("content_ref")
    if isinstance(content_ref, str) and content_ref:
        return f"Context was shared by reference: {content_ref}."

    refs = delivery.get("refs") or message.get("refs") or []
    labels = [
        ref.get("remember_as") or ref.get("find") or ref.get("type")
        for ref in refs
        if isinstance(ref, dict)
    ]
    if labels:
        return truncate_contact_text(f"Context was shared as refs: {', '.join(labels)}.")
    return "No inline context was shared."


def contact_shared_context_refs(
    message: dict[str, Any],
    delivery: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> list[str]:
    values = [message.get("content_ref"), delivery.get("current_content_ref")]
    for ref in [*message.get("refs", []), *delivery.get("refs", [])]:
        if isinstance(ref, dict):
            values.append(ref.get("url"))
    for task in tasks:
        values.extend(task.get("context_refs", []))
        values.extend([task.get("context_pack_ref"), task.get("input_ref"), task.get("result_ref")])
        values.extend(task.get("artifact_refs", []))
    return unique_contact_strings(values)


def contact_pending_action(delivery: dict[str, Any], tasks: list[dict[str, Any]]) -> str | None:
    action_request = delivery.get("action_request")
    if isinstance(action_request, dict):
        approval = "requires approval" if action_request.get("requires_approval", True) else "preapproved"
        target = f" for {action_request['target']}" if action_request.get("target") else ""
        return f"{action_request.get('type')}{target} ({approval})"
    if delivery.get("status") == "needs_review":
        return "human review"
    for task in tasks:
        state = task.get("state")
        if state not in {"completed", "refused", "failed"}:
            return f"task {task.get('task_id')} is {state}"
    if delivery.get("status") == "pending_action":
        return str(delivery.get("current_stage") or "action.before")
    return None


def contact_policy_refs(
    message: dict[str, Any],
    delivery: dict[str, Any],
    relationship: str,
    tasks: list[dict[str, Any]],
) -> list[str]:
    values = [
        f"message_safety:{message.get('safety_status', 'unknown')}",
        f"relationship:{relationship}",
    ]
    if delivery.get("status") == "needs_review":
        values.append("delivery_gate:human_review")
    action_request = delivery.get("action_request")
    if isinstance(action_request, dict):
        approval = str(bool(action_request.get("requires_approval", True))).lower()
        values.append(f"action_approval_required:{approval}")
    for task in tasks:
        if task.get("policy_decision_id"):
            values.append(f"policy_decision:{task['policy_decision_id']}")
    return unique_contact_strings(values)


def contact_audit_refs(delivery: dict[str, Any], thread: dict[str, Any]) -> list[str]:
    values = [
        f"delivery:{delivery['delivery_id']}:{delivery.get('status', 'delivered')}",
        f"message:{delivery['message_id']}",
        f"thread:{thread['thread_id']}:message_count:{thread.get('message_count', 0)}",
    ]
    values.extend(
        f"workflow_trace:{index}:{entry.get('hook')}:{entry.get('action')}"
        for index, entry in enumerate(delivery.get("workflow_trace", []), start=1)
        if isinstance(entry, dict)
    )
    action_request = delivery.get("action_request")
    if isinstance(action_request, dict):
        values.append(
            f"action_request:{action_request.get('action_request_id')}:{action_request.get('status', 'pending')}"
        )
    return unique_contact_strings(values)


def truncate_contact_text(value: str) -> str:
    if len(value) <= CONTACT_EXPLANATION_SUMMARY_CHARS:
        return value
    return f"{value[:CONTACT_EXPLANATION_SUMMARY_CHARS].rstrip()}..."


def unique_contact_strings(values: list[Any]) -> list[str]:
    normalized = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        normalized.append(stripped)
        seen.add(stripped)
    return normalized


def send_result(message_id: str, *, idempotent: bool) -> dict[str, Any]:
    message = messages_table.get_item(Key={"message_id": message_id}).get("Item")
    if message is None:
        raise NotFound(f"message not found: {message_id}")
    thread = get_thread_record(message["thread_id"])
    deliveries = deliveries_table.query(
        IndexName="message-recipient-index",
        KeyConditionExpression=Key("message_id").eq(message_id),
    ).get("Items", [])
    return {
        "idempotent": idempotent,
        "message": clean_item(message),
        "thread": clean_item(thread),
        "deliveries": clean_item(deliveries),
        "message_id": message_id,
        "thread_id": message["thread_id"],
    }


def local_safety_status(content: str | None) -> str:
    normalized_content = (content or "").lower()
    blocked_terms = [term for term in SAFETY_BLOCKED_TERMS if term in normalized_content]
    if blocked_terms:
        raise Blocked(f"message blocked by local safety policy: {', '.join(blocked_terms)}")
    return "approved"


def delivery_items(deliveries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for delivery in deliveries:
        message = messages_table.get_item(Key={"message_id": delivery["message_id"]}).get("Item")
        items.append(
            {
                "delivery": clean_item(delivery),
                "message": clean_item(message),
                "current_message": {
                    "content_inline": delivery.get("current_content_inline") or (message or {}).get("content_inline"),
                    "content_ref": delivery.get("current_content_ref") or (message or {}).get("content_ref"),
                    "refs": delivery.get("refs") or (message or {}).get("refs") or [],
                },
            }
        )
    return items


def apply_routing_rules(
    *,
    recipients: list[dict[str, Any]],
    content_inline: str | None,
    content_ref: str | None,
    refs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    routed = list(recipients)
    trace = []
    needs_review = False

    for rule in list_routing_rule_items():
        if not rule.get("enabled", True) or not routing_rule_matches(
            rule,
            content_inline=content_inline,
            content_ref=content_ref,
            refs=refs,
        ):
            continue

        mode = rule.get("mode", "copy")
        if mode == "block":
            raise BadRequest(f"message blocked by routing rule: {rule.get('name')}")

        rule_recipients = [require_agent_by_handle(handle) for handle in rule.get("route_to_handles", [])]
        if mode in {"direct", "handoff"}:
            routed = list(rule_recipients)
        elif mode in {"copy", "review"}:
            routed = merge_recipients(routed, rule_recipients)
            needs_review = needs_review or mode == "review"

        trace.append(
            {
                "hook": "route.resolve",
                "runtime": "cloud",
                "action": mode,
                "actor": rule.get("rule_id"),
                "changed": ["recipient_agent_ids"],
                "note": rule.get("name"),
                "created_at": now_iso(),
            }
        )

    return routed, trace, needs_review


def list_routing_rule_items() -> list[dict[str, Any]]:
    if routing_rules_table is None:
        return []
    result = routing_rules_table.scan()
    return list(result.get("Items", []))


def routing_rule_matches(
    rule: dict[str, Any],
    *,
    content_inline: str | None,
    content_ref: str | None,
    refs: list[dict[str, Any]],
) -> bool:
    haystacks = [content_inline or "", content_ref or ""]
    haystacks.extend(str(ref.get("url") or "") for ref in refs)
    normalized_haystacks = [haystack.lower() for haystack in haystacks]
    return any(
        needle in haystack
        for needle in rule.get("url_contains", [])
        for haystack in normalized_haystacks
    )


def merge_recipients(existing: list[dict[str, Any]], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(existing)
    seen = {agent["agent_id"] for agent in merged}
    for agent in additions:
        if agent["agent_id"] in seen:
            continue
        merged.append(agent)
        seen.add(agent["agent_id"])
    return merged


def get_agent_by_handle(handle: str) -> dict[str, Any] | None:
    normalized = normalize_handle(handle)
    result = agents_table.query(
        IndexName="handle-index",
        KeyConditionExpression=Key("handle").eq(normalized),
        Limit=1,
    )
    items = result.get("Items", [])
    if not items:
        return None
    return items[0]


def require_agent_by_handle(handle: str) -> dict[str, Any]:
    agent = get_agent_by_handle(handle)
    if agent is None:
        raise NotFound(f"agent not found: {normalize_handle(handle)}")
    return agent


def require_agent(agent_id: str) -> dict[str, Any]:
    agent = agents_table.get_item(Key={"agent_id": agent_id}).get("Item")
    if agent is None:
        raise NotFound(f"agent not found: {agent_id}")
    return agent


def require_delivery(delivery_id: str) -> dict[str, Any]:
    delivery = deliveries_table.get_item(Key={"delivery_id": delivery_id}).get("Item")
    if delivery is None:
        raise NotFound(f"delivery not found: {delivery_id}")
    return delivery


def require_task_tables() -> None:
    if tasks_table is None or tool_requests_table is None or task_results_table is None:
        raise BadRequest("task tables are not configured")


def require_task(task_id: str) -> dict[str, Any]:
    require_task_tables()
    task = tasks_table.get_item(Key={"task_id": task_id}).get("Item")
    if task is None:
        raise NotFound(f"task not found: {task_id}")
    return task


def require_tool_request(tool_request_id: str) -> dict[str, Any]:
    require_task_tables()
    tool_request = tool_requests_table.get_item(Key={"tool_request_id": tool_request_id}).get("Item")
    if tool_request is None:
        raise NotFound(f"tool request not found: {tool_request_id}")
    return tool_request


def require_task_actor(task: dict[str, Any], actor: dict[str, Any]) -> None:
    allowed_agent_ids = {
        task["requester_agent_id"],
        task["recipient_agent_id"],
    }
    accepted_by_agent_id = task.get("accepted_by_agent_id")
    if accepted_by_agent_id:
        allowed_agent_ids.add(accepted_by_agent_id)
    if actor["agent_id"] not in allowed_agent_ids:
        raise Forbidden("agent cannot update this task")


def send_task_notification(
    task: dict[str, Any],
    *,
    sender: dict[str, Any],
    recipient_agent_id: str,
    intent: str,
    label: str,
    note: str | None = None,
    ref: dict[str, Any] | None = None,
) -> None:
    recipient = require_agent(recipient_agent_id)
    refs = [ref or task_ref(task["task_id"], label)]
    if note:
        refs.append({"type": "note", "find": note})
    create_message(
        {
            "body": json.dumps(
                {
                    "sender_handle": sender["handle"],
                    "recipient_handles": [recipient["handle"]],
                    "thread_id": task["thread_id"],
                    "intent": intent,
                    "visibility": "direct",
                    "refs": refs,
                }
            )
        }
    )


def get_thread_record(thread_id: str) -> dict[str, Any] | None:
    return threads_table.get_item(Key={"thread_id": thread_id}).get("Item")


def update_existing_thread(
    thread_id: str,
    message_id: str,
    updated_at: str,
    participant_ids: list[str],
) -> None:
    update_expression = (
        "SET last_message_id = :message_id, last_message_at = :updated_at, updated_at = :updated_at "
        "ADD message_count :one"
    )
    expression_values: dict[str, Any] = {
        ":one": 1,
        ":message_id": message_id,
        ":updated_at": updated_at,
    }
    if participant_ids:
        update_expression = (
            "SET last_message_id = :message_id, last_message_at = :updated_at, updated_at = :updated_at "
            "ADD participants :participants, message_count :one"
        )
        expression_values[":participants"] = set(participant_ids)

    threads_table.update_item(
        Key={"thread_id": thread_id},
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_values,
    )


def get_idempotent_message_id(sender_agent_id: str, idempotency_key: str) -> str | None:
    result = idempotency_table.get_item(
        Key={"sender_agent_id": sender_agent_id, "idempotency_key": idempotency_key}
    )
    item = result.get("Item")
    if item is None:
        return None
    expires_at = item.get("expires_at")
    if expires_at is not None and int(expires_at) <= int(time.time()):
        return None
    return item.get("message_id")


def get_idempotent_task_id(requester_agent_id: str, idempotency_key: str) -> str | None:
    result = idempotency_table.get_item(
        Key={"sender_agent_id": requester_agent_id, "idempotency_key": f"task:{idempotency_key}"}
    )
    item = result.get("Item")
    if item is None:
        return None
    expires_at = item.get("expires_at")
    if expires_at is not None and int(expires_at) <= int(time.time()):
        return None
    return item.get("task_id")


def latest_thread_summary(thread_id: str) -> dict[str, Any] | None:
    result = thread_summaries_table.query(
        KeyConditionExpression=Key("thread_id").eq(thread_id),
        ScanIndexForward=False,
        Limit=1,
    )
    items = result.get("Items", [])
    if not items:
        return None
    return items[0]


def generated_summary(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not messages:
        return None
    senders: list[str] = []
    for message in messages:
        sender = message.get("sender_handle") or message.get("sender_agent_id")
        if sender and sender not in senders:
            senders.append(sender)
    return {
        "summary_text": f"{len(messages)} recent message(s) involving {', '.join(senders)}.",
        "generated": True,
    }


def public_agent(agent: dict[str, Any]) -> dict[str, Any]:
    trigger_mode = agent.get("trigger_mode") or "manual"
    return clean_item(
        {
            "agent_id": agent.get("agent_id"),
            "handle": agent.get("handle"),
            "display_name": agent.get("display_name"),
            "capabilities": public_capabilities(agent.get("capabilities", [])),
            "response_rules": public_response_rules(agent.get("response_rules")),
            "status": agent.get("status"),
            "trigger_mode": trigger_mode,
            "webhook_enabled": trigger_mode == "webhook" and bool(agent.get("webhook_url")),
            "created_at": agent.get("created_at"),
            "updated_at": agent.get("updated_at"),
        }
    )


def public_capabilities(capabilities: Any) -> list[str]:
    if isinstance(capabilities, str):
        values = [capabilities]
    elif isinstance(capabilities, set):
        values = sorted(item for item in capabilities if isinstance(item, str))
    elif isinstance(capabilities, (list, tuple)):
        values = [item for item in capabilities if isinstance(item, str)]
    else:
        values = []
    return [capability for capability in values if not has_private_profile_marker(capability)]


def public_response_rules(response_rules: Any) -> dict[str, Any] | None:
    sanitized = sanitize_public_profile_value(response_rules)
    return sanitized if isinstance(sanitized, dict) else None


def sanitize_public_profile_value(value: Any) -> Any:
    if isinstance(value, str):
        return None if has_private_profile_marker(value) else value
    if isinstance(value, (list, tuple, set)):
        sanitized_items = []
        for item in value:
            sanitized = sanitize_public_profile_value(item)
            if sanitized is not None:
                sanitized_items.append(sanitized)
        return sanitized_items
    if isinstance(value, dict):
        sanitized_dict: dict[str, Any] = {}
        for key, item in value.items():
            if has_private_profile_marker(str(key)):
                continue
            sanitized = sanitize_public_profile_value(item)
            if sanitized is not None:
                sanitized_dict[str(key)] = sanitized
        return sanitized_dict
    if value is None or isinstance(value, (bool, int, float, Decimal)):
        return value
    return None


def has_private_profile_marker(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in PRIVATE_PROFILE_MARKERS)


def trigger_config(body: dict[str, Any]) -> tuple[str, str | None]:
    trigger_mode = (optional_string(body, "trigger_mode") or "manual").lower()
    webhook_url = optional_string(body, "webhook_url")
    if trigger_mode not in {"manual", "webhook"}:
        raise BadRequest("trigger_mode must be manual or webhook")
    if trigger_mode == "webhook" and webhook_url is None:
        raise BadRequest("webhook_url is required when trigger_mode is webhook")
    if trigger_mode == "manual" and webhook_url is not None:
        raise BadRequest("webhook_url requires trigger_mode webhook")
    if webhook_url is not None and not (webhook_url.startswith("http://") or webhook_url.startswith("https://")):
        raise BadRequest("webhook_url must start with http:// or https://")
    return trigger_mode, webhook_url


def enqueue_delivery_events(
    deliveries: list[dict[str, Any]],
    message: dict[str, Any],
    sender: dict[str, Any],
    recipients: list[dict[str, Any]],
) -> None:
    if not AGENT_JOBS_QUEUE_URL:
        return

    for delivery, recipient in zip(deliveries, recipients, strict=True):
        if recipient.get("trigger_mode", "manual") != "webhook":
            continue

        event = delivery_created_event(delivery=delivery, message=message, sender=sender, recipient=recipient)
        sqs.send_message(
            QueueUrl=AGENT_JOBS_QUEUE_URL,
            MessageBody=json.dumps(clean_item(event), separators=(",", ":"), sort_keys=True),
            MessageGroupId=message["thread_id"],
            MessageDeduplicationId=delivery["delivery_id"],
        )


def delivery_created_event(
    *,
    delivery: dict[str, Any],
    message: dict[str, Any],
    sender: dict[str, Any],
    recipient: dict[str, Any],
) -> dict[str, Any]:
    event_id = f"event_{delivery['delivery_id']}"
    return {
        "specversion": "1.0",
        "type": "seagull.delivery.created.v1",
        "source": "seagull.message-hub",
        "id": event_id,
        "event_id": event_id,
        "time": delivery["created_at"],
        "subject": delivery["delivery_id"],
        "datacontenttype": "application/json",
        "data": {
            "event_id": event_id,
            "delivery_id": delivery["delivery_id"],
            "message_id": message["message_id"],
            "thread_id": message["thread_id"],
            "sender_agent_id": sender["agent_id"],
            "sender_handle": sender["handle"],
            "recipient_agent_id": recipient["agent_id"],
            "recipient_handle": recipient["handle"],
            "intent": message["intent"],
            "visibility": message["visibility"],
            "content_inline": message.get("content_inline"),
            "content_ref": message.get("content_ref"),
            "refs": message.get("refs", []),
            "current_content_inline": delivery.get("current_content_inline") or message.get("content_inline"),
            "current_content_ref": delivery.get("current_content_ref") or message.get("content_ref"),
            "current_stage": delivery.get("current_stage"),
            "created_at": message["created_at"],
        },
    }


def message_recipient_handles(body: dict[str, Any]) -> list[str]:
    raw_handles = body.get("recipient_handles")
    if raw_handles is None and body.get("recipient_handle") is not None:
        raw_handles = [body["recipient_handle"]]
    if raw_handles is None and body.get("recipient") is not None:
        raw_handles = [body["recipient"]]

    handles = string_list(raw_handles or [], "recipient_handles")
    normalized = []
    seen = set()
    for handle in handles:
        normalized_handle = normalize_handle(handle)
        if normalized_handle not in seen:
            normalized.append(normalized_handle)
            seen.add(normalized_handle)
    return normalized


TASK_STATES = {
    "requested",
    "accepted",
    "running",
    "needs_approval",
    "result_ready",
    "completed",
    "refused",
    "failed",
}

PRIVATE_TASK_FIELDS = {
    "credential",
    "credentials",
    "mcp_server_url",
    "mcp_session",
    "private_prompt",
    "prompt",
    "raw_tool_handle",
    "secret",
    "secrets",
    "tool_credentials",
    "tool_runtime_config",
}


def normalize_task_state(state: str) -> str:
    normalized = state.strip().lower()
    if normalized not in TASK_STATES:
        raise BadRequest(f"task state must be one of: {', '.join(sorted(TASK_STATES))}")
    return normalized


def task_ref(task_id: str, label: str) -> dict[str, str]:
    return {"type": "task", "url": f"seagull://tasks/{task_id}", "remember_as": label}


def reject_private_task_fields(body: dict[str, Any]) -> None:
    private_fields = sorted(set(body) & PRIVATE_TASK_FIELDS)
    if private_fields:
        raise BadRequest(f"private task field(s) are not accepted: {', '.join(private_fields)}")


def path_param(path: str, prefix: str, suffix: str) -> str:
    value = path.removeprefix(prefix).removesuffix(suffix).strip("/")
    return unquote(value)


def delivery_path_param(path: str, suffix: str) -> str:
    if path.startswith("/agent/deliveries/"):
        return path_param(path, "/agent/deliveries/", suffix)
    if path.startswith("/deliveries/"):
        return path_param(path, "/deliveries/", suffix)
    raise BadRequest("delivery route must start with /deliveries or /agent/deliveries")


def parse_body(event: dict[str, Any], *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_body = event.get("body")
    if not raw_body:
        return default if default is not None else {}
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    body = json.loads(raw_body)
    if not isinstance(body, dict):
        raise BadRequest("JSON body must be an object")
    return body


def query_params(event: dict[str, Any]) -> dict[str, str]:
    return event.get("queryStringParameters") or {}


def required(body: dict[str, Any], key: str) -> str:
    value = optional_string(body, key)
    if value is None:
        raise BadRequest(f"{key} is required")
    return value


def optional_string(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadRequest(f"{key} must be a string")
    value = value.strip()
    return value or None


def require_small_inline(value: str, field_name: str) -> None:
    if len(value) > MAX_ENVELOPE_INLINE_CHARS:
        raise BadRequest(f"{field_name} exceeds {MAX_ENVELOPE_INLINE_CHARS} characters; use refs or content_ref")


def envelope_content_for_storage(
    content_inline: str | None,
    content_ref: str | None,
    field_name: str,
) -> tuple[str | None, str | None]:
    if content_inline is not None and len(content_inline) > MAX_ENVELOPE_INLINE_CHARS:
        if content_ref is None:
            raise BadRequest(f"{field_name} exceeds {MAX_ENVELOPE_INLINE_CHARS} characters; provide content_ref")
        return None, content_ref
    return content_inline, content_ref


def string_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise BadRequest(f"{name} must be a list of strings")

    values = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BadRequest(f"{name} must be a list of non-empty strings")
        values.append(item.strip())
    return values


def response_rules_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BadRequest("response_rules must be an object")
    allowed = {
        "schema_version",
        "persona",
        "style",
        "reply_posture",
        "max_reply_chars",
        "ask_human_triggers",
        "prohibited_behavior",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BadRequest(f"unknown response_rules field(s): {', '.join(unknown)}")
    return dict(value)


def refs_list(value: Any, name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BadRequest(f"{name} must be a list")

    refs = []
    for item in value:
        if not isinstance(item, dict):
            raise BadRequest(f"{name} must contain objects")
        ref_type = optional_string(item, "type")
        if ref_type is None:
            raise BadRequest("ref type is required")
        refs.append(
            without_none(
                {
                    "type": ref_type,
                    "url": optional_string(item, "url"),
                    "find": optional_string(item, "find"),
                    "remember_as": optional_string(item, "remember_as"),
                }
            )
        )
    return refs


def optional_bool(body: dict[str, Any], key: str, *, default: bool) -> bool:
    value = body.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise BadRequest(f"{key} must be a boolean")
    return value


def normalize_hook(hook: str) -> str:
    normalized = hook.strip().lower()
    if normalized not in {
        "send.before",
        "route.resolve",
        "delivery.before",
        "receive.before",
        "action.before",
        "reply.before",
        "after",
        "agent.decision",
    }:
        raise BadRequest("unsupported lifecycle hook")
    return normalized


def normalize_runtime(runtime: str) -> str:
    normalized = runtime.strip().lower()
    if normalized not in {"cloud", "cloud_node", "lan_node", "agent_client"}:
        raise BadRequest("runtime must be cloud, cloud_node, lan_node, or agent_client")
    return normalized


def normalize_hook_action(action: str) -> str:
    normalized = action.strip().lower()
    if normalized not in {"continue", "block", "review", "fail"}:
        raise BadRequest("hook action must be continue, block, review, or fail")
    return normalized


def normalize_agent_decision(decision: str) -> str:
    normalized = decision.strip().lower()
    if normalized not in {"reply", "action", "ignore", "ask_human"}:
        raise BadRequest("agent decision must be reply, action, ignore, or ask_human")
    return normalized


def next_stage_after_hook(hook: str, fallback: str) -> str:
    return {
        "send.before": "route.resolve",
        "route.resolve": "delivery.before",
        "delivery.before": "receive.before",
        "receive.before": "agent.wait",
        "action.before": "action.ready",
        "reply.before": "publish",
        "after": "done",
    }.get(hook, fallback)


def normalize_handle(handle: str) -> str:
    normalized = handle.strip().lower()
    if not normalized:
        raise BadRequest("agent handle is required")
    if not normalized.startswith("@"):
        raise BadRequest("agent handle must start with @")
    return normalized


def agent_id_for_handle(handle: str) -> str:
    digest = hashlib.sha256(handle.encode("utf-8")).hexdigest()[:32]
    return f"agent_{digest}"


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
        raise BadRequest(f"{key} must be an integer") from None
    return max(minimum, min(value, maximum))


def private_context_ref(ref: dict[str, Any]) -> bool:
    haystacks = (
        str(ref.get("type") or ""),
        str(ref.get("url") or ""),
        str(ref.get("find") or ""),
        str(ref.get("remember_as") or ""),
    )
    return private_context_value(*haystacks)


def private_context_value(*values: str) -> bool:
    normalized = " ".join(values).lower()
    return any(marker in normalized for marker in PRIVATE_CONTEXT_REF_MARKERS)


def without_none(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
        },
        "body": json.dumps(clean_item(body), default=json_default),
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clean_item(value: Any) -> Any:
    if isinstance(value, list):
        return [clean_item(item) for item in value]
    if isinstance(value, tuple):
        return [clean_item(item) for item in value]
    if isinstance(value, set):
        return sorted(clean_item(item) for item in value)
    if isinstance(value, dict):
        return {key: clean_item(item) for key, item in value.items() if item is not None}
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
