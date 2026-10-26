"""DynamoDB-backed MessageHubRepository.

Implements the repository protocol against the deployed table schemas
(infra/terraform/modules/message-hub). Item attribute names, set-vs-list
choices, timestamp format (millisecond ISO 8601 with a ``Z`` suffix), and the
idempotency-key layout deliberately match what ``aws/lambda_function.py``
has historically written, so this repository reads existing production data
and existing readers can parse what it writes. Parsing tolerates extra
attributes (e.g. the denormalized ``sender_handle`` fields older writers
added) and both list- and set-typed string collections.

Payload content lives in S3 (``payloads/<id>.gz`` in the payload objects
bucket); the DynamoDB item stores metadata plus a ``storage_ref``.

Tables for the task-work subsystems (quotes, escrows, capacity policies,
credit ledger, reputation events, tool grants) may not be provisioned yet;
constructing the repository without them is allowed and only the methods
that need them raise ``RepositoryTableNotConfiguredError``.

Known inherited trade-off: ``list_messages_by_content_ref`` and
``list_payloads``/``list_routing_rules`` use table scans, matching the
previous Lambda implementation. A content_ref GSI is tracked separately.
"""

from __future__ import annotations

import time
import uuid
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from seagull_common.coerce import without_none

from message_hub.domain.models import (
    ActionRequest,
    Agent,
    AgentTokenRecord,
    Delivery,
    DeliveryStatus,
    FeedEventRecord,
    FollowRecord,
    Message,
    MessageRef,
    NotificationRecord,
    PostRecord,
    RoomMembershipRecord,
    RoomRecord,
    PayloadCompaction,
    PayloadRecord,
    RoutingRule,
    RoutingRuleMode,
    StoredPayload,
    TaskCapacityRole,
    TaskCapacitySharingPolicyRecord,
    TaskCapacityTier,
    TaskCreditLedgerEntry,
    TaskCreditLedgerEntryType,
    TaskEscrowRecord,
    TaskQuoteRecord,
    TaskRecord,
    TaskResultRecord,
    TaskState,
    TaskToolRequest,
    TaskWorkerReputationEventRecord,
    TaskWorkerReputationEventType,
    ThreadRecord,
    ThreadSummary,
    ToolGrant,
)
from message_hub.storage.pagination import CursorPage, cursor_after, decode_cursor
from message_hub.storage.repository import (
    AtomicCommitConflict,
    IdempotencyRecoveryConflict,
    SendTooLargeError,
)

MESSAGE_IDEMPOTENCY_TTL_SECONDS = 604800
TASK_IDEMPOTENCY_KEY_PREFIX = "task:"
MAX_DYNAMODB_ITEM_BYTES = 400 * 1024
MAX_DYNAMODB_TRANSACTION_BYTES = 4 * 1024 * 1024
# Reserved sender_agent_id partition in the idempotency table for guest-send
# rate counters; real agent ids are always ``agent_<hex>`` so this can never
# collide with an idempotency row.
GUEST_RATE_SENDER_KEY = "__guest_rate__"


class RepositoryTableNotConfiguredError(RuntimeError):
    """A repository method needs a table that was not provisioned/wired."""

    def __init__(self, table_name: str) -> None:
        super().__init__(f"repository table is not configured: {table_name}")
        self.table_name = table_name


# ---------------------------------------------------------------------------
# Serialization helpers


def to_iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _opt_iso(value: datetime | None) -> str | None:
    return None if value is None else to_iso(value)


def _opt_parse_iso(value: Any) -> datetime | None:
    return None if value in (None, "") else parse_iso(value)


def _int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _strings(value: Any) -> tuple[str, ...]:
    """Parse a DynamoDB string collection stored as either a list or a set."""
    if value is None:
        return ()
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(str(item) for item in value))
    return tuple(str(item) for item in value)


def _string_set(values: Any) -> set[str] | None:
    """DynamoDB string set for writes; None (omitted) when empty."""
    collected = {str(item) for item in values or ()}
    return collected or None


def _clean(value: Any) -> Any:
    """Convert Decimals/sets from DynamoDB into plain Python values."""
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_clean(item) for item in value)
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


def _enum_value(value: Any) -> Any:
    """Stored form of an enum-or-string field.

    ``str()`` on a str-Enum yields "Visibility.PUBLIC", not "public", so read
    ``.value`` explicitly rather than relying on stringification.
    """
    return value.value if hasattr(value, "value") else value


def _refs_to_items(refs: tuple[MessageRef, ...]) -> list[dict[str, Any]]:
    return [
        without_none(
            {
                "type": ref.type,
                "url": ref.url,
                "find": ref.find,
                "remember_as": ref.remember_as,
            }
        )
        for ref in refs
    ]


def _refs_from_items(value: Any) -> tuple[MessageRef, ...]:
    refs = []
    for item in value or ():
        refs.append(
            MessageRef(
                type=str(item.get("type") or ""),
                url=item.get("url"),
                find=item.get("find"),
                remember_as=item.get("remember_as"),
            )
        )
    return tuple(refs)


def _trace_to_items(trace: tuple[Any, ...]) -> list[dict[str, Any]]:
    items = []
    for entry in trace:
        items.append(
            without_none(
                {
                    "hook": entry.hook,
                    "runtime": entry.runtime,
                    "action": entry.action,
                    "actor": entry.actor,
                    "changed": list(entry.changed),
                    "note": entry.note,
                    "created_at": to_iso(entry.created_at),
                }
            )
        )
    return items


def _trace_from_items(value: Any) -> tuple[Any, ...]:
    from message_hub.domain.models import WorkflowTraceEntry

    entries = []
    for item in value or ():
        entries.append(
            WorkflowTraceEntry(
                hook=str(item.get("hook") or ""),
                runtime=str(item.get("runtime") or ""),
                action=str(item.get("action") or "continue"),
                actor=item.get("actor"),
                changed=_strings(item.get("changed")),
                note=item.get("note"),
                created_at=_opt_parse_iso(item.get("created_at"))
                or datetime.now(timezone.utc),
            )
        )
    return tuple(entries)


def _action_request_to_item(request: ActionRequest | None) -> dict[str, Any] | None:
    if request is None:
        return None
    return without_none(
        {
            "action_request_id": request.action_request_id,
            "type": request.type,
            "target": request.target,
            "runtime": request.runtime,
            "requires_approval": request.requires_approval,
            "status": request.status,
            "created_at": to_iso(request.created_at),
        }
    )


def _action_request_from_item(value: Any) -> ActionRequest | None:
    if not value:
        return None
    return ActionRequest(
        action_request_id=str(value.get("action_request_id") or ""),
        type=str(value.get("type") or ""),
        target=value.get("target"),
        runtime=str(value.get("runtime") or "cloud"),
        requires_approval=bool(value.get("requires_approval", True)),
        status=str(value.get("status") or "pending"),
        created_at=_opt_parse_iso(value.get("created_at"))
        or datetime.now(timezone.utc),
    )


def agent_to_item(agent: Agent) -> dict[str, Any]:
    return without_none(
        {
            "agent_id": agent.agent_id,
            "handle": agent.handle,
            "display_name": agent.display_name,
            "capabilities": _string_set(agent.capabilities),
            "response_rules": agent.response_rules,
            "status": agent.status,
            "inbox_posture": agent.inbox_posture,
            "trigger_mode": agent.trigger_mode,
            "webhook_url": agent.webhook_url,
            "created_at": to_iso(agent.created_at),
            "updated_at": to_iso(agent.updated_at),
        }
    )


def agent_from_item(item: dict[str, Any]) -> Agent:
    response_rules = item.get("response_rules")
    return Agent(
        agent_id=str(item["agent_id"]),
        handle=str(item["handle"]),
        display_name=item.get("display_name"),
        capabilities=_strings(item.get("capabilities")),
        response_rules=_clean(response_rules) if response_rules is not None else None,
        status=str(item.get("status") or "active"),
        # Additive attribute: rows written before M2 have no inbox_posture and
        # read back as the default.
        inbox_posture=str(item.get("inbox_posture") or "contacts_only"),
        trigger_mode=str(item.get("trigger_mode") or "manual"),
        webhook_url=item.get("webhook_url"),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_opt_parse_iso(item.get("updated_at")) or datetime.now(timezone.utc),
    )


def token_to_item(token: AgentTokenRecord) -> dict[str, Any]:
    return without_none(
        {
            "token_id": token.token_id,
            "token_hash": token.token_hash,
            "agent_id": token.agent_id,
            "agent_handle": token.agent_handle,
            "scopes": list(token.scopes),
            "name": token.name,
            "owner_user_id": token.owner_user_id,
            "node_id": token.node_id,
            "created_at": to_iso(token.created_at),
            "expires_at": _opt_iso(token.expires_at),
            "last_used_at": _opt_iso(token.last_used_at),
            "revoked_at": _opt_iso(token.revoked_at),
        }
    )


def token_from_item(item: dict[str, Any]) -> AgentTokenRecord:
    return AgentTokenRecord(
        token_id=str(item["token_id"]),
        token_hash=str(item["token_hash"]),
        agent_id=str(item["agent_id"]),
        agent_handle=str(item["agent_handle"]),
        scopes=_strings(item.get("scopes")),
        name=item.get("name"),
        owner_user_id=item.get("owner_user_id"),
        node_id=item.get("node_id"),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
        expires_at=_opt_parse_iso(item.get("expires_at")),
        last_used_at=_opt_parse_iso(item.get("last_used_at")),
        revoked_at=_opt_parse_iso(item.get("revoked_at")),
    )


def message_to_item(message: Message) -> dict[str, Any]:
    return without_none(
        {
            "message_id": message.message_id,
            "thread_id": message.thread_id,
            "sender_agent_id": message.sender_agent_id,
            "recipient_agent_ids": _string_set(message.recipient_agent_ids),
            "intent": message.intent,
            "visibility": message.visibility,
            "content_inline": message.content_inline,
            "content_ref": message.content_ref,
            "refs": _refs_to_items(message.refs) or None,
            "schema_version": message.schema_version,
            "safety_status": message.safety_status,
            "runtime_mode": message.runtime_mode,
            "created_at": to_iso(message.created_at),
        }
    )


def message_from_item(item: dict[str, Any]) -> Message:
    return Message(
        message_id=str(item["message_id"]),
        thread_id=str(item["thread_id"]),
        sender_agent_id=str(item["sender_agent_id"]),
        recipient_agent_ids=_strings(item.get("recipient_agent_ids")),
        intent=str(item.get("intent") or "message"),
        visibility=str(item.get("visibility") or "direct"),
        content_inline=item.get("content_inline"),
        content_ref=item.get("content_ref"),
        refs=_refs_from_items(item.get("refs")),
        schema_version=str(item.get("schema_version") or "seagull.message.v1"),
        safety_status=str(item.get("safety_status") or "approved"),
        runtime_mode=item.get("runtime_mode"),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
    )


def thread_to_item(thread: ThreadRecord) -> dict[str, Any]:
    return without_none(
        {
            "thread_id": thread.thread_id,
            "root_message_id": thread.root_message_id,
            "participants": _string_set(thread.participants),
            "message_count": thread.message_count,
            "last_message_id": thread.last_message_id,
            "last_message_at": to_iso(thread.last_message_at),
            "title": thread.title,
            "summary_ref": thread.summary_ref,
            "created_at": to_iso(thread.created_at),
            "updated_at": to_iso(thread.updated_at),
            "revision": thread.revision,
        }
    )


def thread_from_item(item: dict[str, Any]) -> ThreadRecord:
    return ThreadRecord(
        thread_id=str(item["thread_id"]),
        root_message_id=str(item.get("root_message_id") or ""),
        participants=frozenset(_strings(item.get("participants"))),
        message_count=_int(item.get("message_count")),
        last_message_id=str(item.get("last_message_id") or ""),
        last_message_at=_opt_parse_iso(item.get("last_message_at"))
        or datetime.now(timezone.utc),
        title=item.get("title"),
        summary_ref=item.get("summary_ref"),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_opt_parse_iso(item.get("updated_at")) or datetime.now(timezone.utc),
        revision=_int(item.get("revision")),
    )


def delivery_to_item(delivery: Delivery) -> dict[str, Any]:
    return without_none(
        {
            "delivery_id": delivery.delivery_id,
            "message_id": delivery.message_id,
            "thread_id": delivery.thread_id,
            "sender_agent_id": delivery.sender_agent_id,
            "recipient_agent_id": delivery.recipient_agent_id,
            "status": delivery.status.value,
            "retry_count": delivery.retry_count,
            "last_error": delivery.last_error,
            "current_content_inline": delivery.current_content_inline,
            "current_content_ref": delivery.current_content_ref,
            "refs": _refs_to_items(delivery.refs) or None,
            "workflow_trace": _trace_to_items(delivery.workflow_trace) or None,
            "current_stage": delivery.current_stage,
            "action_request": _action_request_to_item(delivery.action_request),
            "created_at": to_iso(delivery.created_at),
            "updated_at": to_iso(delivery.updated_at),
            "acked_at": _opt_iso(delivery.acked_at),
        }
    )


def delivery_from_item(item: dict[str, Any]) -> Delivery:
    return Delivery(
        delivery_id=str(item["delivery_id"]),
        message_id=str(item["message_id"]),
        thread_id=str(item["thread_id"]),
        sender_agent_id=str(item.get("sender_agent_id") or ""),
        recipient_agent_id=str(item["recipient_agent_id"]),
        status=DeliveryStatus(str(item.get("status") or "queued")),
        retry_count=_int(item.get("retry_count")),
        last_error=item.get("last_error"),
        current_content_inline=item.get("current_content_inline"),
        current_content_ref=item.get("current_content_ref"),
        refs=_refs_from_items(item.get("refs")),
        workflow_trace=_trace_from_items(item.get("workflow_trace")),
        current_stage=str(item.get("current_stage") or "agent.wait"),
        action_request=_action_request_from_item(item.get("action_request")),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_opt_parse_iso(item.get("updated_at")) or datetime.now(timezone.utc),
        acked_at=_opt_parse_iso(item.get("acked_at")),
    )


def routing_rule_to_item(rule: RoutingRule) -> dict[str, Any]:
    return without_none(
        {
            "rule_id": rule.rule_id,
            "name": rule.name,
            "mode": rule.mode.value,
            "route_to_handles": list(rule.route_to_handles),
            "url_contains": list(rule.url_contains),
            "enabled": rule.enabled,
            "created_at": to_iso(rule.created_at),
            "updated_at": to_iso(rule.updated_at),
        }
    )


def routing_rule_from_item(item: dict[str, Any]) -> RoutingRule:
    return RoutingRule(
        rule_id=str(item["rule_id"]),
        name=str(item.get("name") or ""),
        mode=RoutingRuleMode(str(item.get("mode") or "direct")),
        route_to_handles=_strings(item.get("route_to_handles")),
        url_contains=_strings(item.get("url_contains")),
        enabled=bool(item.get("enabled", True)),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_opt_parse_iso(item.get("updated_at")) or datetime.now(timezone.utc),
    )


def thread_summary_to_item(summary: ThreadSummary) -> dict[str, Any]:
    return without_none(
        {
            "thread_id": summary.thread_id,
            "created_at": to_iso(summary.created_at),
            "summary_id": summary.summary_id,
            "summary_text": summary.summary_text,
            "message_start_id": summary.message_start_id,
            "message_end_id": summary.message_end_id,
            "token_count_estimate": summary.token_count_estimate,
            "content_ref": summary.content_ref,
        }
    )


def thread_summary_from_item(item: dict[str, Any]) -> ThreadSummary:
    return ThreadSummary(
        thread_id=str(item["thread_id"]),
        summary_id=str(item.get("summary_id") or ""),
        summary_text=str(item.get("summary_text") or ""),
        message_start_id=item.get("message_start_id"),
        message_end_id=item.get("message_end_id"),
        token_count_estimate=_opt_int(item.get("token_count_estimate")),
        content_ref=item.get("content_ref"),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
    )


def payload_record_to_item(record: PayloadRecord) -> dict[str, Any]:
    return without_none(
        {
            "content_ref": record.content_ref,
            "media_type": record.media_type,
            "byte_length": record.byte_length,
            "hash": record.hash,
            "compression": record.compression,
            "compressed_byte_length": record.compressed_byte_length,
            "compressed_hash": record.compressed_hash,
            "ttl_expires_at": _opt_iso(record.ttl_expires_at),
            "ttl_expires_at_epoch": (
                int(record.ttl_expires_at.timestamp())
                if record.ttl_expires_at is not None
                else None
            ),
            "retention_state": record.retention_state,
            "access_scope": record.access_scope,
            "fetch_policy_ref": record.fetch_policy_ref,
            "chunk_manifest_ref": record.chunk_manifest_ref,
            "storage_provider": record.storage_provider,
            "storage_ref": record.storage_ref,
            "created_at": to_iso(record.created_at),
        }
    )


def payload_record_from_item(item: dict[str, Any]) -> PayloadRecord:
    return PayloadRecord(
        content_ref=str(item["content_ref"]),
        media_type=str(item.get("media_type") or "text/plain; charset=utf-8"),
        byte_length=_int(item.get("byte_length")),
        hash=str(item.get("hash") or ""),
        compression=str(item.get("compression") or "gzip"),
        compressed_byte_length=_int(item.get("compressed_byte_length")),
        compressed_hash=item.get("compressed_hash"),
        ttl_expires_at=_opt_parse_iso(item.get("ttl_expires_at")),
        retention_state=str(item.get("retention_state") or "ready"),
        access_scope=str(item.get("access_scope") or "recipients"),
        fetch_policy_ref=item.get("fetch_policy_ref"),
        chunk_manifest_ref=item.get("chunk_manifest_ref"),
        storage_provider=str(item.get("storage_provider") or "aws_s3"),
        storage_ref=item.get("storage_ref"),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
    )


def task_to_item(task: TaskRecord) -> dict[str, Any]:
    return without_none(
        {
            "task_id": task.task_id,
            "thread_id": task.thread_id,
            "requester_agent_id": task.requester_agent_id,
            "recipient_agent_id": task.recipient_agent_id,
            "objective": task.objective,
            "request_message_id": task.request_message_id,
            "context_refs": list(task.context_refs),
            "context_pack_id": task.context_pack_id,
            "context_pack_ref": task.context_pack_ref,
            "input_ref": task.input_ref,
            "stream_id": task.stream_id,
            "allowed_tool_names": list(task.allowed_tool_names),
            "allowed_use_terms": list(task.allowed_use_terms),
            "tool_grant_ids": list(task.tool_grant_ids),
            "quote_ids": list(task.quote_ids),
            "escrow_ids": list(task.escrow_ids),
            "capacity_policy_ids": list(task.capacity_policy_ids),
            "state": task.state.value,
            "policy_decision_id": task.policy_decision_id,
            "accepted_by_agent_id": task.accepted_by_agent_id,
            "result_message_id": task.result_message_id,
            "result_ref": task.result_ref,
            "artifact_refs": list(task.artifact_refs),
            "tool_request_ids": list(task.tool_request_ids),
            "created_at": to_iso(task.created_at),
            "updated_at": to_iso(task.updated_at),
        }
    )


def task_from_item(item: dict[str, Any]) -> TaskRecord:
    return TaskRecord(
        task_id=str(item["task_id"]),
        thread_id=str(item["thread_id"]),
        requester_agent_id=str(item["requester_agent_id"]),
        recipient_agent_id=str(item["recipient_agent_id"]),
        objective=str(item.get("objective") or ""),
        request_message_id=str(item.get("request_message_id") or ""),
        context_refs=_strings(item.get("context_refs")),
        context_pack_id=item.get("context_pack_id"),
        context_pack_ref=item.get("context_pack_ref"),
        input_ref=item.get("input_ref"),
        stream_id=item.get("stream_id"),
        allowed_tool_names=_strings(item.get("allowed_tool_names")),
        allowed_use_terms=_strings(item.get("allowed_use_terms")),
        tool_grant_ids=_strings(item.get("tool_grant_ids")),
        quote_ids=_strings(item.get("quote_ids")),
        escrow_ids=_strings(item.get("escrow_ids")),
        capacity_policy_ids=_strings(item.get("capacity_policy_ids")),
        state=TaskState(str(item.get("state") or "requested")),
        policy_decision_id=item.get("policy_decision_id"),
        accepted_by_agent_id=item.get("accepted_by_agent_id"),
        result_message_id=item.get("result_message_id"),
        result_ref=item.get("result_ref"),
        artifact_refs=_strings(item.get("artifact_refs")),
        tool_request_ids=_strings(item.get("tool_request_ids")),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_opt_parse_iso(item.get("updated_at")) or datetime.now(timezone.utc),
    )


def quote_to_item(quote: TaskQuoteRecord) -> dict[str, Any]:
    return without_none(
        {
            "quote_id": quote.quote_id,
            "task_id": quote.task_id,
            "thread_id": quote.thread_id,
            "requester_agent_id": quote.requester_agent_id,
            "worker_agent_id": quote.worker_agent_id,
            "task_reason": quote.task_reason,
            "expected_credit_cost": quote.expected_credit_cost,
            "shared_context_refs": list(quote.shared_context_refs),
            "requires_approval": quote.requires_approval,
            "approval_reason": quote.approval_reason,
            "approved_by_agent_id": quote.approved_by_agent_id,
            "approval_id": quote.approval_id,
            "policy_decision_id": quote.policy_decision_id,
            "limits_ref": quote.limits_ref,
            "abuse_policy_ref": quote.abuse_policy_ref,
            "audit_refs": list(quote.audit_refs),
            "created_at": to_iso(quote.created_at),
            "updated_at": to_iso(quote.updated_at),
        }
    )


def quote_from_item(item: dict[str, Any]) -> TaskQuoteRecord:
    return TaskQuoteRecord(
        quote_id=str(item["quote_id"]),
        task_id=str(item["task_id"]),
        thread_id=str(item.get("thread_id") or ""),
        requester_agent_id=str(item.get("requester_agent_id") or ""),
        worker_agent_id=str(item.get("worker_agent_id") or ""),
        task_reason=str(item.get("task_reason") or ""),
        expected_credit_cost=_int(item.get("expected_credit_cost")),
        shared_context_refs=_strings(item.get("shared_context_refs")),
        requires_approval=bool(item.get("requires_approval", True)),
        approval_reason=item.get("approval_reason"),
        approved_by_agent_id=item.get("approved_by_agent_id"),
        approval_id=item.get("approval_id"),
        policy_decision_id=item.get("policy_decision_id"),
        limits_ref=item.get("limits_ref"),
        abuse_policy_ref=item.get("abuse_policy_ref"),
        audit_refs=_strings(item.get("audit_refs")),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_opt_parse_iso(item.get("updated_at")) or datetime.now(timezone.utc),
    )


def escrow_to_item(escrow: TaskEscrowRecord) -> dict[str, Any]:
    return without_none(
        {
            "escrow_id": escrow.escrow_id,
            "task_id": escrow.task_id,
            "quote_id": escrow.quote_id,
            "thread_id": escrow.thread_id,
            "requester_agent_id": escrow.requester_agent_id,
            "worker_agent_id": escrow.worker_agent_id,
            "credit_amount": escrow.credit_amount,
            "state": escrow.state.value,
            "approval_id": escrow.approval_id,
            "policy_decision_id": escrow.policy_decision_id,
            "limits_ref": escrow.limits_ref,
            "abuse_policy_ref": escrow.abuse_policy_ref,
            "audit_refs": list(escrow.audit_refs),
            "created_at": to_iso(escrow.created_at),
            "updated_at": to_iso(escrow.updated_at),
            "released_at": _opt_iso(escrow.released_at),
        }
    )


def escrow_from_item(item: dict[str, Any]) -> TaskEscrowRecord:
    return TaskEscrowRecord(
        escrow_id=str(item["escrow_id"]),
        task_id=str(item["task_id"]),
        quote_id=str(item.get("quote_id") or ""),
        thread_id=str(item.get("thread_id") or ""),
        requester_agent_id=str(item.get("requester_agent_id") or ""),
        worker_agent_id=str(item.get("worker_agent_id") or ""),
        credit_amount=_int(item.get("credit_amount")),
        state=TaskState(str(item.get("state") or "escrowed")),
        approval_id=item.get("approval_id"),
        policy_decision_id=item.get("policy_decision_id"),
        limits_ref=item.get("limits_ref"),
        abuse_policy_ref=item.get("abuse_policy_ref"),
        audit_refs=_strings(item.get("audit_refs")),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_opt_parse_iso(item.get("updated_at")) or datetime.now(timezone.utc),
        released_at=_opt_parse_iso(item.get("released_at")),
    )


def capacity_policy_to_item(policy: TaskCapacitySharingPolicyRecord) -> dict[str, Any]:
    return without_none(
        {
            "policy_id": policy.policy_id,
            "task_id": policy.task_id,
            "thread_id": policy.thread_id,
            "requester_agent_id": policy.requester_agent_id,
            "worker_agent_id": policy.worker_agent_id,
            "requester_role": policy.requester_role.value,
            "worker_role": policy.worker_role.value,
            "requester_capacity_tier": policy.requester_capacity_tier.value,
            "worker_capacity_tier": policy.worker_capacity_tier.value,
            "max_credit_cost": policy.max_credit_cost,
            "max_auto_escrow_credits": policy.max_auto_escrow_credits,
            "allow_private_context": policy.allow_private_context,
            "private_context_requires_approval": policy.private_context_requires_approval,
            "paid_work_requires_approval": policy.paid_work_requires_approval,
            "high_cost_requires_approval": policy.high_cost_requires_approval,
            "abuse_policy_ref": policy.abuse_policy_ref,
            "limits_ref": policy.limits_ref,
            "policy_decision_id": policy.policy_decision_id,
            "audit_refs": list(policy.audit_refs),
            "created_at": to_iso(policy.created_at),
        }
    )


def capacity_policy_from_item(item: dict[str, Any]) -> TaskCapacitySharingPolicyRecord:
    return TaskCapacitySharingPolicyRecord(
        policy_id=str(item["policy_id"]),
        task_id=str(item["task_id"]),
        thread_id=str(item.get("thread_id") or ""),
        requester_agent_id=str(item.get("requester_agent_id") or ""),
        worker_agent_id=str(item.get("worker_agent_id") or ""),
        requester_role=TaskCapacityRole(str(item.get("requester_role") or "requester")),
        worker_role=TaskCapacityRole(str(item.get("worker_role") or "worker")),
        requester_capacity_tier=TaskCapacityTier(
            str(item.get("requester_capacity_tier") or "low")
        ),
        worker_capacity_tier=TaskCapacityTier(
            str(item.get("worker_capacity_tier") or "high")
        ),
        max_credit_cost=_int(item.get("max_credit_cost")),
        max_auto_escrow_credits=_int(item.get("max_auto_escrow_credits")),
        allow_private_context=bool(item.get("allow_private_context", False)),
        private_context_requires_approval=bool(
            item.get("private_context_requires_approval", True)
        ),
        paid_work_requires_approval=bool(item.get("paid_work_requires_approval", True)),
        high_cost_requires_approval=bool(item.get("high_cost_requires_approval", True)),
        abuse_policy_ref=item.get("abuse_policy_ref"),
        limits_ref=item.get("limits_ref"),
        policy_decision_id=item.get("policy_decision_id"),
        audit_refs=_strings(item.get("audit_refs")),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
    )


def ledger_entry_to_item(entry: TaskCreditLedgerEntry) -> dict[str, Any]:
    return without_none(
        {
            "entry_id": entry.entry_id,
            "account_agent_id": entry.account_agent_id,
            "entry_type": entry.entry_type.value,
            "credit_amount": entry.credit_amount,
            "available_delta": entry.available_delta,
            "escrow_delta": entry.escrow_delta,
            "task_id": entry.task_id,
            "thread_id": entry.thread_id,
            "quote_id": entry.quote_id,
            "escrow_id": entry.escrow_id,
            "counterparty_agent_id": entry.counterparty_agent_id,
            "reason": entry.reason,
            "settlement_scope": entry.settlement_scope,
            "policy_decision_id": entry.policy_decision_id,
            "limits_ref": entry.limits_ref,
            "abuse_policy_ref": entry.abuse_policy_ref,
            "audit_refs": list(entry.audit_refs),
            "created_at": to_iso(entry.created_at),
        }
    )


def ledger_entry_from_item(item: dict[str, Any]) -> TaskCreditLedgerEntry:
    return TaskCreditLedgerEntry(
        entry_id=str(item["entry_id"]),
        account_agent_id=str(item["account_agent_id"]),
        entry_type=TaskCreditLedgerEntryType(str(item.get("entry_type") or "credit_grant")),
        credit_amount=_int(item.get("credit_amount")),
        available_delta=_int(item.get("available_delta")),
        escrow_delta=_int(item.get("escrow_delta")),
        task_id=item.get("task_id"),
        thread_id=item.get("thread_id"),
        quote_id=item.get("quote_id"),
        escrow_id=item.get("escrow_id"),
        counterparty_agent_id=item.get("counterparty_agent_id"),
        reason=item.get("reason"),
        settlement_scope=str(item.get("settlement_scope") or "internal_product_credit"),
        policy_decision_id=item.get("policy_decision_id"),
        limits_ref=item.get("limits_ref"),
        abuse_policy_ref=item.get("abuse_policy_ref"),
        audit_refs=_strings(item.get("audit_refs")),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
    )


def reputation_event_to_item(event: TaskWorkerReputationEventRecord) -> dict[str, Any]:
    return without_none(
        {
            "event_id": event.event_id,
            "worker_agent_id": event.worker_agent_id,
            "event_type": event.event_type.value,
            "task_id": event.task_id,
            "thread_id": event.thread_id,
            "reporter_agent_id": event.reporter_agent_id,
            "reason": event.reason,
            "policy_decision_id": event.policy_decision_id,
            "limits_ref": event.limits_ref,
            "abuse_policy_ref": event.abuse_policy_ref,
            "audit_refs": list(event.audit_refs),
            "created_at": to_iso(event.created_at),
        }
    )


def reputation_event_from_item(item: dict[str, Any]) -> TaskWorkerReputationEventRecord:
    return TaskWorkerReputationEventRecord(
        event_id=str(item["event_id"]),
        worker_agent_id=str(item["worker_agent_id"]),
        event_type=TaskWorkerReputationEventType(
            str(item.get("event_type") or "task_completed")
        ),
        task_id=str(item.get("task_id") or ""),
        thread_id=str(item.get("thread_id") or ""),
        reporter_agent_id=item.get("reporter_agent_id"),
        reason=item.get("reason"),
        policy_decision_id=item.get("policy_decision_id"),
        limits_ref=item.get("limits_ref"),
        abuse_policy_ref=item.get("abuse_policy_ref"),
        audit_refs=_strings(item.get("audit_refs")),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
    )


def tool_grant_to_item(grant: ToolGrant) -> dict[str, Any]:
    return without_none(
        {
            "grant_id": grant.grant_id,
            "task_id": grant.task_id,
            "thread_id": grant.thread_id,
            "issuer_agent_id": grant.issuer_agent_id,
            "subject_agent_id": grant.subject_agent_id,
            "audience": grant.audience,
            "scopes": list(grant.scopes),
            "purpose": grant.purpose,
            "ttl_expires_at": _opt_iso(grant.ttl_expires_at),
            "max_calls": grant.max_calls,
            "used_count": grant.used_count,
            "budget_ref": grant.budget_ref,
            "allowed_resource_selectors": list(grant.allowed_resource_selectors),
            "read_only": grant.read_only,
            "approval_id": grant.approval_id,
            "policy_decision_id": grant.policy_decision_id,
            "revoked_at": _opt_iso(grant.revoked_at),
            "created_at": to_iso(grant.created_at),
            "updated_at": to_iso(grant.updated_at),
        }
    )


def tool_grant_from_item(item: dict[str, Any]) -> ToolGrant:
    return ToolGrant(
        grant_id=str(item["grant_id"]),
        task_id=str(item["task_id"]),
        thread_id=str(item.get("thread_id") or ""),
        issuer_agent_id=str(item.get("issuer_agent_id") or ""),
        subject_agent_id=str(item.get("subject_agent_id") or ""),
        audience=str(item.get("audience") or ""),
        scopes=_strings(item.get("scopes")),
        purpose=str(item.get("purpose") or ""),
        ttl_expires_at=_opt_parse_iso(item.get("ttl_expires_at")),
        max_calls=_opt_int(item.get("max_calls")),
        used_count=_int(item.get("used_count")),
        budget_ref=item.get("budget_ref"),
        allowed_resource_selectors=_strings(item.get("allowed_resource_selectors")),
        read_only=bool(item.get("read_only", True)),
        approval_id=item.get("approval_id"),
        policy_decision_id=item.get("policy_decision_id"),
        revoked_at=_opt_parse_iso(item.get("revoked_at")),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_opt_parse_iso(item.get("updated_at")) or datetime.now(timezone.utc),
    )


def tool_request_to_item(tool_request: TaskToolRequest) -> dict[str, Any]:
    return without_none(
        {
            "tool_request_id": tool_request.tool_request_id,
            "task_id": tool_request.task_id,
            "thread_id": tool_request.thread_id,
            "requester_agent_id": tool_request.requester_agent_id,
            "worker_agent_id": tool_request.worker_agent_id,
            "tool_name": tool_request.tool_name,
            "purpose": tool_request.purpose,
            "input_ref": tool_request.input_ref,
            "requires_approval": tool_request.requires_approval,
            "status": tool_request.status.value,
            "approval_id": tool_request.approval_id,
            "policy_decision_id": tool_request.policy_decision_id,
            "accepted_by_agent_id": tool_request.accepted_by_agent_id,
            "tool_grant_id": tool_request.tool_grant_id,
            "result_ref": tool_request.result_ref,
            "artifact_refs": list(tool_request.artifact_refs),
            "tool_use_summary_ref": tool_request.tool_use_summary_ref,
            "created_at": to_iso(tool_request.created_at),
            "updated_at": to_iso(tool_request.updated_at),
        }
    )


def tool_request_from_item(item: dict[str, Any]) -> TaskToolRequest:
    return TaskToolRequest(
        tool_request_id=str(item["tool_request_id"]),
        task_id=str(item["task_id"]),
        thread_id=str(item.get("thread_id") or ""),
        requester_agent_id=str(item.get("requester_agent_id") or ""),
        worker_agent_id=str(item.get("worker_agent_id") or ""),
        tool_name=str(item.get("tool_name") or ""),
        purpose=str(item.get("purpose") or ""),
        input_ref=item.get("input_ref"),
        requires_approval=bool(item.get("requires_approval", True)),
        status=TaskState(str(item.get("status") or "needs_approval")),
        approval_id=item.get("approval_id"),
        policy_decision_id=item.get("policy_decision_id"),
        accepted_by_agent_id=item.get("accepted_by_agent_id"),
        tool_grant_id=item.get("tool_grant_id"),
        result_ref=item.get("result_ref"),
        artifact_refs=_strings(item.get("artifact_refs")),
        tool_use_summary_ref=item.get("tool_use_summary_ref"),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_opt_parse_iso(item.get("updated_at")) or datetime.now(timezone.utc),
    )


def task_result_to_item(result: TaskResultRecord) -> dict[str, Any]:
    return without_none(
        {
            "result_id": result.result_id,
            "task_id": result.task_id,
            "thread_id": result.thread_id,
            "responder_agent_id": result.responder_agent_id,
            "state": result.state.value,
            "result_message_id": result.result_message_id,
            "stream_id": result.stream_id,
            "content_inline": result.content_inline,
            "content_ref": result.content_ref,
            "artifact_refs": list(result.artifact_refs),
            "tool_use_summary_refs": list(result.tool_use_summary_refs),
            "error": result.error,
            "created_at": to_iso(result.created_at),
        }
    )


def task_result_from_item(item: dict[str, Any]) -> TaskResultRecord:
    return TaskResultRecord(
        result_id=str(item["result_id"]),
        task_id=str(item["task_id"]),
        thread_id=str(item.get("thread_id") or ""),
        responder_agent_id=str(item.get("responder_agent_id") or ""),
        state=TaskState(str(item.get("state") or "result_ready")),
        result_message_id=str(item.get("result_message_id") or ""),
        stream_id=item.get("stream_id"),
        content_inline=item.get("content_inline"),
        content_ref=item.get("content_ref"),
        artifact_refs=_strings(item.get("artifact_refs")),
        tool_use_summary_refs=_strings(item.get("tool_use_summary_refs")),
        error=item.get("error"),
        created_at=_opt_parse_iso(item.get("created_at")) or datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Repository


class DynamoDbMessageHubRepository:
    """MessageHubRepository backed by the deployed DynamoDB tables + S3."""

    def __init__(
        self,
        *,
        agents_table: Any,
        messages_table: Any,
        threads_table: Any,
        deliveries_table: Any,
        idempotency_table: Any,
        thread_summaries_table: Any,
        payloads_table: Any = None,
        routing_rules_table: Any = None,
        agent_tokens_table: Any = None,
        tasks_table: Any = None,
        tool_requests_table: Any = None,
        task_results_table: Any = None,
        task_quotes_table: Any = None,
        task_escrows_table: Any = None,
        task_capacity_policies_table: Any = None,
        task_credit_ledger_table: Any = None,
        task_reputation_events_table: Any = None,
        tool_grants_table: Any = None,
        posts_table: Any = None,
        follows_table: Any = None,
        rooms_table: Any = None,
        room_memberships_table: Any = None,
        feed_events_table: Any = None,
        notifications_table: Any = None,
        payload_objects_bucket: str | None = None,
        s3_client: Any = None,
    ) -> None:
        self._agents = agents_table
        self._messages = messages_table
        self._threads = threads_table
        self._deliveries = deliveries_table
        self._idempotency = idempotency_table
        self._thread_summaries = thread_summaries_table
        self._payloads = payloads_table
        self._routing_rules = routing_rules_table
        self._agent_tokens = agent_tokens_table
        self._tasks = tasks_table
        self._tool_requests = tool_requests_table
        self._task_results = task_results_table
        self._task_quotes = task_quotes_table
        self._task_escrows = task_escrows_table
        self._task_capacity_policies = task_capacity_policies_table
        self._task_credit_ledger = task_credit_ledger_table
        self._task_reputation_events = task_reputation_events_table
        self._tool_grants = tool_grants_table
        self._posts = posts_table
        self._follows = follows_table
        self._rooms = rooms_table
        self._room_memberships = room_memberships_table
        self._feed_events = feed_events_table
        self._notifications = notifications_table
        self._payload_objects_bucket = payload_objects_bucket
        self._s3 = s3_client

    @staticmethod
    def _require(table: Any, name: str) -> Any:
        if table is None:
            raise RepositoryTableNotConfiguredError(name)
        return table

    @staticmethod
    def _partition_condition(key_name: str, key_value: str) -> Any:
        """Build a DynamoDB Key equality expression.

        Keeping the tiny fallback makes repository pagination unit-testable
        with a query double in environments that do not install boto3. Real
        DynamoDB tables always use boto3's condition object.
        """
        try:
            from boto3.dynamodb.conditions import Key
        except ImportError:  # pragma: no cover - only dependency-light tests
            class FallbackCondition:
                _values = (key_value,)

            return FallbackCondition()
        return Key(key_name).eq(key_value)

    @staticmethod
    def _query_all(
        table: Any,
        *,
        index_name: str | None,
        key_name: str,
        key_value: str,
        newest_first: bool,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key(key_name).eq(key_value),
            "ScanIndexForward": not newest_first,
        }
        if index_name is not None:
            kwargs["IndexName"] = index_name
        if limit is not None:
            kwargs["Limit"] = limit
        items: list[dict[str, Any]] = []
        while True:
            result = table.query(**kwargs)
            items.extend(result.get("Items", []))
            last_key = result.get("LastEvaluatedKey")
            if last_key is None or (limit is not None and len(items) >= limit):
                break
            kwargs["ExclusiveStartKey"] = last_key
        if limit is not None:
            items = items[:limit]
        return items

    @classmethod
    def _query_recent(
        cls,
        table: Any,
        *,
        index_name: str | None,
        key_name: str,
        key_value: str,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        """Return items in chronological order, truncated to the newest ``limit``."""
        if limit is None:
            return cls._query_all(
                table,
                index_name=index_name,
                key_name=key_name,
                key_value=key_value,
                newest_first=False,
                limit=None,
            )
        items = cls._query_all(
            table,
            index_name=index_name,
            key_name=key_name,
            key_value=key_value,
            newest_first=True,
            limit=limit,
        )
        items.reverse()
        return items

    @staticmethod
    def _scan_all(table: Any, **kwargs: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while True:
            result = table.scan(**kwargs)
            items.extend(result.get("Items", []))
            last_key = result.get("LastEvaluatedKey")
            if last_key is None:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    # -- agents

    def add_agent(self, agent: Agent) -> None:
        self._agents.put_item(Item=agent_to_item(agent))

    def get_agent(self, agent_id: str) -> Agent | None:
        item = self._agents.get_item(Key={"agent_id": agent_id}).get("Item")
        return None if item is None else agent_from_item(item)

    def get_agent_by_handle(self, handle: str) -> Agent | None:
        items = self._query_all(
            self._agents,
            index_name="handle-index",
            key_name="handle",
            key_value=handle,
            newest_first=False,
            limit=1,
        )
        return agent_from_item(items[0]) if items else None

    def update_agent(self, agent: Agent) -> None:
        self._agents.put_item(Item=agent_to_item(agent))

    def increment_guest_send_count(
        self,
        scope_key: str,
        window_start_epoch: int,
        *,
        ttl_epoch: int,
    ) -> int:
        # Reuses the idempotency table (reserved partition + TTL attribute) so
        # rate counters need no new table; ADD is atomic per window row.
        result = self._idempotency.update_item(
            Key={
                "sender_agent_id": GUEST_RATE_SENDER_KEY,
                "idempotency_key": f"{scope_key}:{int(window_start_epoch)}",
            },
            UpdateExpression="SET expires_at = :expires_at ADD send_count :one",
            ExpressionAttributeValues={":expires_at": int(ttl_epoch), ":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(result["Attributes"]["send_count"])

    # -- agent tokens

    def put_agent_token(self, token: AgentTokenRecord) -> None:
        table = self._require(self._agent_tokens, "agent_tokens")
        table.put_item(Item=token_to_item(token))

    def get_agent_token(self, token_id: str) -> AgentTokenRecord | None:
        table = self._require(self._agent_tokens, "agent_tokens")
        item = table.get_item(Key={"token_id": token_id}).get("Item")
        return None if item is None else token_from_item(item)

    def update_agent_token(self, token: AgentTokenRecord) -> None:
        self.put_agent_token(token)

    def list_agent_tokens_by_agent(self, agent_id: str) -> tuple[AgentTokenRecord, ...]:
        table = self._require(self._agent_tokens, "agent_tokens")
        items = self._query_all(
            table,
            index_name="agent-created-at-index",
            key_name="agent_id",
            key_value=agent_id,
            newest_first=True,
            limit=None,
        )
        return tuple(token_from_item(item) for item in items)

    # -- messages

    def put_message(self, message: Message) -> None:
        self._messages.put_item(Item=message_to_item(message))

    def commit_message_send(
        self,
        *,
        message: Message,
        thread: ThreadRecord,
        deliveries: tuple[Delivery, ...],
        sender_agent_id: str,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
        source_delivery_id: str | None = None,
        expected_source_delivery_status: str | None = None,
        expected_source_delivery_updated_at: datetime | None = None,
        source_delivery: Delivery | None = None,
    ) -> bool:
        actions: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self._messages.name,
                    "Item": message_to_item(message),
                    "ConditionExpression": "attribute_not_exists(message_id)",
                }
            }
        ]
        thread_put: dict[str, Any] = {
            "TableName": self._threads.name,
            "Item": thread_to_item(thread),
        }
        if thread.revision == 0:
            thread_put["ConditionExpression"] = "attribute_not_exists(thread_id)"
        elif thread.revision == 1:
            thread_put["ConditionExpression"] = "attribute_not_exists(revision) OR revision = :expected_revision"
            thread_put["ExpressionAttributeValues"] = {":expected_revision": 0}
        else:
            thread_put["ConditionExpression"] = "revision = :expected_revision"
            thread_put["ExpressionAttributeValues"] = {":expected_revision": thread.revision - 1}
        actions.append({"Put": thread_put})
        for delivery in deliveries:
            actions.append(
                {
                    "Put": {
                        "TableName": self._deliveries.name,
                        "Item": delivery_to_item(delivery),
                        "ConditionExpression": "attribute_not_exists(delivery_id)",
                    }
                }
            )
        if source_delivery is not None:
            if source_delivery_id is not None and source_delivery.delivery_id != source_delivery_id:
                raise AtomicCommitConflict("source delivery id mismatch")
            source_put: dict[str, Any] = {
                "TableName": self._deliveries.name,
                "Item": delivery_to_item(source_delivery),
            }
            if expected_source_delivery_status is not None or expected_source_delivery_updated_at is not None:
                conditions: list[str] = []
                expression_names: dict[str, str] = {}
                expression_values: dict[str, Any] = {}
                if expected_source_delivery_status is not None:
                    conditions.append("#status = :expected_status")
                    expression_names["#status"] = "status"
                    expression_values[":expected_status"] = expected_source_delivery_status
                if expected_source_delivery_updated_at is not None:
                    conditions.append("#updated_at = :expected_updated_at")
                    expression_names["#updated_at"] = "updated_at"
                    expression_values[":expected_updated_at"] = to_iso(expected_source_delivery_updated_at)
                source_put["ConditionExpression"] = " AND ".join(conditions)
                source_put["ExpressionAttributeNames"] = expression_names
                source_put["ExpressionAttributeValues"] = expression_values
            actions.append({"Put": source_put})
        if idempotency_key is not None:
            actions.append(
                {
                    "Put": {
                        "TableName": self._idempotency.name,
                        "Item": self._idempotency_item(
                            sender_agent_id,
                            idempotency_key,
                            message_id=message.message_id,
                            delivery_ids=tuple(delivery.delivery_id for delivery in deliveries),
                            request_fingerprint=request_fingerprint,
                            durable=source_delivery is not None,
                        ),
                        "ConditionExpression": "attribute_not_exists(sender_agent_id) OR expires_at <= :now",
                        "ExpressionAttributeValues": {":now": int(time.time())},
                    }
                }
            )
        self._transact_write(actions)
        return True

    def get_message(self, message_id: str) -> Message | None:
        item = self._messages.get_item(Key={"message_id": message_id}, ConsistentRead=True).get("Item")
        return None if item is None else message_from_item(item)

    def list_thread_messages(
        self, thread_id: str, *, limit: int | None = None
    ) -> tuple[Message, ...]:
        items = self._query_recent(
            self._messages,
            index_name="thread-created-at-index",
            key_name="thread_id",
            key_value=thread_id,
            limit=limit,
        )
        return tuple(message_from_item(item) for item in items)

    def list_thread_messages_page(
        self, thread_id: str, *, limit: int, cursor: str | None = None
    ) -> CursorPage[Message]:
        if limit < 1:
            raise ValueError("limit must be positive")
        position = decode_cursor(cursor, kind="thread", scope=thread_id)
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": self._partition_condition("thread_id", thread_id),
            "IndexName": "thread-created-at-index",
            "ScanIndexForward": False,
            "Limit": limit + 1,
        }
        if position is not None:
            kwargs["ExclusiveStartKey"] = {
                "message_id": position.record_id,
                "thread_id": thread_id,
                "created_at": position.created_at,
            }
        result = self._messages.query(**kwargs)
        raw_items = result.get("Items", [])
        has_more = len(raw_items) > limit or result.get("LastEvaluatedKey") is not None
        page_items = raw_items[:limit]
        messages = [message_from_item(item) for item in page_items]
        messages.sort(key=lambda message: (to_iso(message.created_at), message.message_id))
        next_cursor = None
        if has_more and messages:
            last = page_items[-1]
            next_cursor = cursor_after(
                kind="thread",
                scope=thread_id,
                created_at=str(last["created_at"]),
                record_id=str(last["message_id"]),
            )
        return CursorPage(tuple(messages), next_cursor)

    def list_messages_by_sender(
        self, sender_agent_id: str, *, limit: int | None = None
    ) -> tuple[Message, ...]:
        items = self._query_all(
            self._messages,
            index_name="sender-created-at-index",
            key_name="sender_agent_id",
            key_value=sender_agent_id,
            newest_first=True,
            limit=limit,
        )
        return tuple(message_from_item(item) for item in items)

    def list_messages_by_content_ref(self, content_ref: str) -> tuple[Message, ...]:
        from boto3.dynamodb.conditions import Attr

        items = self._scan_all(
            self._messages, FilterExpression=Attr("content_ref").eq(content_ref)
        )
        messages = [message_from_item(item) for item in items]
        messages.sort(key=lambda message: (to_iso(message.created_at), message.message_id))
        return tuple(messages)

    # -- payloads

    def _payload_object_key(self, content_ref: str) -> str:
        payload_id = content_ref.removeprefix("payload://")
        return f"payloads/{payload_id}.gz"

    def _discard_payload_content(self, record: PayloadRecord) -> str | None:
        """Drop retained object bytes for a payload whose content is being cleared."""
        table = self._require(self._payloads, "payloads")
        item = table.get_item(Key={"content_ref": record.content_ref}).get("Item")
        if item is None:
            return record.storage_ref
        stored_ref = str(item.get("storage_ref") or "")
        if not stored_ref.startswith("s3://"):
            return record.storage_ref
        if self._s3 is not None:
            _, _, remainder = stored_ref.partition("s3://")
            bucket, _, key = remainder.partition("/")
            self._s3.delete_object(Bucket=bucket, Key=key)
        return None if record.storage_ref == stored_ref else record.storage_ref

    def _write_payload_content(self, payload: StoredPayload) -> str | None:
        if payload.compressed_content is None:
            return self._discard_payload_content(payload.record)
        if self._s3 is None or not self._payload_objects_bucket:
            raise RepositoryTableNotConfiguredError("payload_objects_bucket")
        object_key = self._payload_object_key(payload.record.content_ref)
        self._s3.put_object(
            Bucket=self._payload_objects_bucket,
            Key=object_key,
            Body=payload.compressed_content,
            ContentType="application/gzip",
            Metadata={
                "content-ref": payload.record.content_ref,
                "media-type": payload.record.media_type,
            },
        )
        return f"s3://{self._payload_objects_bucket}/{object_key}"

    def _read_payload_content(self, storage_ref: str | None) -> bytes | None:
        if not storage_ref or not storage_ref.startswith("s3://"):
            return None
        if self._s3 is None:
            return None
        _, _, remainder = storage_ref.partition("s3://")
        bucket, _, key = remainder.partition("/")
        try:
            result = self._s3.get_object(Bucket=bucket, Key=key)
        except Exception:  # noqa: BLE001 - missing object means no content
            return None
        return result["Body"].read()

    def _compaction_to_item(
        self, content_ref: str, compaction: PayloadCompaction
    ) -> dict[str, Any]:
        chunk_object_keys: list[str] = []
        if compaction.selected_chunks:
            if self._s3 is None or not self._payload_objects_bucket:
                raise RepositoryTableNotConfiguredError("payload_objects_bucket")
            payload_id = content_ref.removeprefix("payload://")
            for index, chunk in enumerate(compaction.selected_chunks):
                key = f"payloads/compactions/{payload_id}/{uuid.uuid4().hex}-{index}.bin"
                self._s3.put_object(
                    Bucket=self._payload_objects_bucket, Key=key, Body=chunk
                )
                chunk_object_keys.append(key)
        return without_none(
            {
                "manifest_ref": compaction.manifest_ref,
                "summary": compaction.summary,
                "selected_chunk_refs": list(compaction.selected_chunk_refs),
                "chunk_object_keys": chunk_object_keys or None,
                "created_at": to_iso(compaction.created_at),
            }
        )

    def _compaction_from_item(self, value: Any) -> PayloadCompaction | None:
        if not value:
            return None
        chunks: list[bytes] = []
        for key in _strings(value.get("chunk_object_keys")):
            if self._s3 is None or not self._payload_objects_bucket:
                break
            try:
                result = self._s3.get_object(
                    Bucket=self._payload_objects_bucket, Key=key
                )
            except Exception:  # noqa: BLE001
                continue
            chunks.append(result["Body"].read())
        return PayloadCompaction(
            manifest_ref=str(value.get("manifest_ref") or ""),
            summary=value.get("summary"),
            selected_chunk_refs=_strings(value.get("selected_chunk_refs")),
            selected_chunks=tuple(chunks),
            created_at=_opt_parse_iso(value.get("created_at"))
            or datetime.now(timezone.utc),
        )

    def put_payload(self, payload: StoredPayload) -> None:
        table = self._require(self._payloads, "payloads")
        storage_ref = self._write_payload_content(payload)
        record = payload.record
        if storage_ref != record.storage_ref:
            record = PayloadRecord(
                **{
                    **{
                        field: getattr(record, field)
                        for field in record.__dataclass_fields__
                    },
                    "storage_provider": "aws_s3",
                    "storage_ref": storage_ref,
                }
            )
        item = payload_record_to_item(record)
        if payload.compaction is not None:
            item["compaction"] = self._compaction_to_item(
                record.content_ref, payload.compaction
            )
        table.put_item(Item=item)

    def get_payload(self, content_ref: str) -> StoredPayload | None:
        table = self._require(self._payloads, "payloads")
        item = table.get_item(Key={"content_ref": content_ref}).get("Item")
        if item is None:
            return None
        record = payload_record_from_item(item)
        return StoredPayload(
            record=record,
            compressed_content=self._read_payload_content(record.storage_ref),
            compaction=self._compaction_from_item(item.get("compaction")),
        )

    def list_payloads(self, *, limit: int | None = None) -> tuple[StoredPayload, ...]:
        table = self._require(self._payloads, "payloads")
        items = self._scan_all(table)
        items.sort(key=lambda item: (str(item.get("created_at") or ""), str(item["content_ref"])))
        if limit is not None:
            items = items[:limit]
        payloads = []
        for item in items:
            record = payload_record_from_item(item)
            payloads.append(
                StoredPayload(
                    record=record,
                    compressed_content=self._read_payload_content(record.storage_ref),
                    compaction=self._compaction_from_item(item.get("compaction")),
                )
            )
        return tuple(payloads)

    def update_payload(self, payload: StoredPayload) -> None:
        self.put_payload(payload)

    # -- threads

    def put_thread(self, thread: ThreadRecord) -> None:
        self._threads.put_item(Item=thread_to_item(thread))

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        item = self._threads.get_item(Key={"thread_id": thread_id}, ConsistentRead=True).get("Item")
        return None if item is None else thread_from_item(item)

    # -- deliveries

    def put_delivery(self, delivery: Delivery) -> None:
        self._deliveries.put_item(Item=delivery_to_item(delivery))

    def get_delivery(self, delivery_id: str) -> Delivery | None:
        item = self._deliveries.get_item(Key={"delivery_id": delivery_id}, ConsistentRead=True).get("Item")
        return None if item is None else delivery_from_item(item)

    def list_deliveries_by_recipient(
        self, recipient_agent_id: str, *, limit: int | None = None
    ) -> tuple[Delivery, ...]:
        items = self._query_all(
            self._deliveries,
            index_name="recipient-created-at-index",
            key_name="recipient_agent_id",
            key_value=recipient_agent_id,
            newest_first=True,
            limit=limit,
        )
        return tuple(delivery_from_item(item) for item in items)

    def list_deliveries_by_recipient_page(
        self, recipient_agent_id: str, *, limit: int, cursor: str | None = None
    ) -> CursorPage[Delivery]:
        if limit < 1:
            raise ValueError("limit must be positive")
        position = decode_cursor(cursor, kind="inbox", scope=recipient_agent_id)
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": self._partition_condition(
                "recipient_agent_id", recipient_agent_id
            ),
            "IndexName": "recipient-created-at-index",
            "ScanIndexForward": False,
            "Limit": limit + 1,
        }
        if position is not None:
            kwargs["ExclusiveStartKey"] = {
                "delivery_id": position.record_id,
                "recipient_agent_id": recipient_agent_id,
                "created_at": position.created_at,
            }
        result = self._deliveries.query(**kwargs)
        raw_items = result.get("Items", [])
        has_more = len(raw_items) > limit or result.get("LastEvaluatedKey") is not None
        page_items = raw_items[:limit]
        # Preserve DynamoDB's query order, including ties, so moderation
        # filtering can resume after the last returned delivery safely.
        deliveries = [delivery_from_item(item) for item in page_items]
        next_cursor = None
        if has_more and deliveries:
            last = page_items[-1]
            next_cursor = cursor_after(
                kind="inbox",
                scope=recipient_agent_id,
                created_at=str(last["created_at"]),
                record_id=str(last["delivery_id"]),
            )
        return CursorPage(tuple(deliveries), next_cursor)

    def list_deliveries_by_sender(
        self, sender_agent_id: str, *, limit: int | None = None
    ) -> tuple[Delivery, ...]:
        items = self._query_all(
            self._deliveries,
            index_name="sender-created-at-index",
            key_name="sender_agent_id",
            key_value=sender_agent_id,
            newest_first=True,
            limit=limit,
        )
        return tuple(delivery_from_item(item) for item in items)

    def list_deliveries_by_message(self, message_id: str) -> tuple[Delivery, ...]:
        items = self._query_all(
            self._deliveries,
            index_name="message-recipient-index",
            key_name="message_id",
            key_value=message_id,
            newest_first=False,
            limit=None,
        )
        return tuple(delivery_from_item(item) for item in items)

    def list_deliveries_by_ids(self, delivery_ids: tuple[str, ...]) -> tuple[Delivery, ...]:
        deliveries: list[Delivery] = []
        for delivery_id in delivery_ids:
            item = self._deliveries.get_item(
                Key={"delivery_id": delivery_id}, ConsistentRead=True
            ).get("Item")
            if item is None:
                raise IdempotencyRecoveryConflict(
                    f"idempotency record references missing delivery: {delivery_id}"
                )
            deliveries.append(delivery_from_item(item))
        return tuple(deliveries)

    def update_delivery(self, delivery: Delivery, *, expected: Delivery | None = None) -> None:
        if expected is None:
            self.put_delivery(delivery)
            return
        try:
            self._deliveries.put_item(
                Item=delivery_to_item(delivery),
                ConditionExpression="#status = :expected_status AND #updated_at = :expected_updated_at",
                ExpressionAttributeNames={"#status": "status", "#updated_at": "updated_at"},
                ExpressionAttributeValues={
                    ":expected_status": expected.status.value,
                    ":expected_updated_at": to_iso(expected.updated_at),
                },
            )
        except Exception as exc:
            code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if code == "ConditionalCheckFailedException":
                raise AtomicCommitConflict("delivery changed concurrently") from exc
            raise

    # -- routing rules

    def put_routing_rule(self, rule: RoutingRule) -> None:
        table = self._require(self._routing_rules, "routing_rules")
        table.put_item(Item=routing_rule_to_item(rule))

    def list_routing_rules(self) -> tuple[RoutingRule, ...]:
        table = self._require(self._routing_rules, "routing_rules")
        items = self._scan_all(table)
        rules = [routing_rule_from_item(item) for item in items]
        rules.sort(key=lambda rule: (to_iso(rule.created_at), rule.rule_id))
        return tuple(rules)

    # -- idempotency (messages)

    def get_idempotent_message_id(
        self, sender_agent_id: str, idempotency_key: str
    ) -> str | None:
        item = self._idempotency.get_item(
            Key={
                "sender_agent_id": sender_agent_id,
                "idempotency_key": idempotency_key,
            }
        ).get("Item")
        if item is None:
            return None
        expires_at = item.get("expires_at")
        if expires_at is not None and int(expires_at) <= int(time.time()):
            return None
        message_id = item.get("message_id")
        if message_id is None:
            if sender_agent_id == GUEST_RATE_SENDER_KEY:
                return None
            raise IdempotencyRecoveryConflict("message idempotency record has no message_id")
        return str(message_id)

    def put_idempotency_key(
        self,
        sender_agent_id: str,
        idempotency_key: str,
        message_id: str,
        *,
        expires_at: datetime | None = None,
        request_fingerprint: str | None = None,
    ) -> None:
        epoch = (
            int(expires_at.timestamp())
            if expires_at is not None
            else int(time.time()) + MESSAGE_IDEMPOTENCY_TTL_SECONDS
        )
        item = self._idempotency_item(
            sender_agent_id,
            idempotency_key,
            message_id=message_id,
            request_fingerprint=request_fingerprint,
        )
        item["expires_at"] = epoch
        self._idempotency.put_item(Item=item)

    def get_idempotency_record(
        self, sender_agent_id: str, idempotency_key: str, *, task: bool = False
    ) -> tuple[str, str | None, int | None] | None:
        stored_key = f"{TASK_IDEMPOTENCY_KEY_PREFIX}{idempotency_key}" if task else idempotency_key
        item = self._idempotency.get_item(
            Key={"sender_agent_id": sender_agent_id, "idempotency_key": stored_key},
            ConsistentRead=True,
        ).get("Item")
        if item is None:
            return None
        expires_at = item.get("expires_at")
        if expires_at is not None and int(expires_at) <= int(time.time()):
            return None
        resource_id = item.get("task_id" if task else "message_id")
        if resource_id is None:
            raise IdempotencyRecoveryConflict("idempotency record has no resource id")
        fingerprint = item.get("request_fingerprint")
        return str(resource_id), None if fingerprint is None else str(fingerprint), None if expires_at is None else int(expires_at)

    def get_idempotency_delivery_ids(
        self, sender_agent_id: str, idempotency_key: str, *, task: bool = False
    ) -> tuple[str, ...]:
        stored_key = f"{TASK_IDEMPOTENCY_KEY_PREFIX}{idempotency_key}" if task else idempotency_key
        item = self._idempotency.get_item(
            Key={"sender_agent_id": sender_agent_id, "idempotency_key": stored_key},
            ConsistentRead=True,
        ).get("Item")
        if item is None:
            return ()
        expires_at = item.get("expires_at")
        if expires_at is not None and int(expires_at) <= int(time.time()):
            return ()
        return tuple(str(value) for value in (item.get("delivery_ids") or ()))

    # -- thread summaries

    def put_thread_summary(self, summary: ThreadSummary) -> None:
        self._thread_summaries.put_item(Item=thread_summary_to_item(summary))

    def get_latest_thread_summary(self, thread_id: str) -> ThreadSummary | None:
        items = self._query_all(
            self._thread_summaries,
            index_name=None,
            key_name="thread_id",
            key_value=thread_id,
            newest_first=True,
            limit=1,
        )
        return thread_summary_from_item(items[0]) if items else None

    # -- tasks

    def put_task(self, task: TaskRecord) -> None:
        table = self._require(self._tasks, "tasks")
        table.put_item(Item=task_to_item(task))

    def commit_task_creation(
        self,
        *,
        message: Message,
        thread: ThreadRecord,
        deliveries: tuple[Delivery, ...],
        task: TaskRecord,
        requester_agent_id: str,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> bool:
        if self._tasks is None:
            raise RepositoryTableNotConfiguredError("tasks")
        actions: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self._messages.name,
                    "Item": message_to_item(message),
                    "ConditionExpression": "attribute_not_exists(message_id)",
                }
            },
            {
                "Put": {
                    "TableName": self._threads.name,
                    "Item": thread_to_item(thread),
                    "ConditionExpression": (
                        "attribute_not_exists(thread_id)"
                        if thread.revision == 0
                        else (
                            "attribute_not_exists(revision) OR revision = :expected_revision"
                            if thread.revision == 1
                            else "revision = :expected_revision"
                        )
                    ),
                    **(
                        {}
                        if thread.revision == 0
                        else {"ExpressionAttributeValues": {":expected_revision": thread.revision - 1}}
                    ),
                }
            },
            *[
                {
                    "Put": {
                        "TableName": self._deliveries.name,
                        "Item": delivery_to_item(delivery),
                        "ConditionExpression": "attribute_not_exists(delivery_id)",
                    }
                }
                for delivery in deliveries
            ],
            {
                "Put": {
                    "TableName": self._tasks.name,
                    "Item": task_to_item(task),
                    "ConditionExpression": "attribute_not_exists(task_id)",
                }
            },
        ]
        if idempotency_key is not None:
            actions.append(
                {
                    "Put": {
                        "TableName": self._idempotency.name,
                        "Item": self._idempotency_item(
                            requester_agent_id,
                            f"{TASK_IDEMPOTENCY_KEY_PREFIX}{idempotency_key}",
                            task_id=task.task_id,
                            delivery_ids=tuple(delivery.delivery_id for delivery in deliveries),
                            request_fingerprint=request_fingerprint,
                        ),
                        "ConditionExpression": "attribute_not_exists(sender_agent_id) OR expires_at <= :now",
                        "ExpressionAttributeValues": {":now": int(time.time())},
                    }
                }
            )
        self._transact_write(actions)
        return True

    def _transact_write(self, actions: list[dict[str, Any]]) -> None:
        if len(actions) > 100:
            raise SendTooLargeError("atomic message transaction exceeds DynamoDB's 100 action limit")
        from boto3.dynamodb.types import TypeSerializer

        serializer = TypeSerializer()
        total_bytes = 0
        for action in actions:
            for operation in action.values():
                item = operation.get("Item") if isinstance(operation, dict) else None
                if item is None:
                    continue
                encoded = json.dumps(
                    serializer.serialize(item), separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
                item_bytes = len(encoded)
                if item_bytes > MAX_DYNAMODB_ITEM_BYTES:
                    raise SendTooLargeError(
                        f"DynamoDB item exceeds {MAX_DYNAMODB_ITEM_BYTES} bytes"
                    )
                total_bytes += item_bytes
        if total_bytes > MAX_DYNAMODB_TRANSACTION_BYTES:
            raise SendTooLargeError(
                f"DynamoDB transaction exceeds {MAX_DYNAMODB_TRANSACTION_BYTES} bytes"
            )
        client = self._messages.meta.client
        try:
            client.transact_write_items(TransactItems=actions)
        except Exception as exc:
            error_code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if error_code in {"TransactionCanceledException", "TransactionConflictException"}:
                raise AtomicCommitConflict("DynamoDB transaction condition failed") from exc
            raise

    @staticmethod
    def _idempotency_item(
        sender_agent_id: str,
        idempotency_key: str,
        *,
        message_id: str | None = None,
        task_id: str | None = None,
        request_fingerprint: str | None = None,
        delivery_ids: tuple[str, ...] = (),
        durable: bool = False,
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
            "sender_agent_id": sender_agent_id,
            "idempotency_key": idempotency_key,
            "created_at": to_iso(datetime.now(timezone.utc)),
        }
        if not durable:
            item["expires_at"] = int(time.time()) + MESSAGE_IDEMPOTENCY_TTL_SECONDS
        if message_id is not None:
            item["message_id"] = message_id
        if task_id is not None:
            item["task_id"] = task_id
        if request_fingerprint is not None:
            item["request_fingerprint"] = request_fingerprint
        if delivery_ids:
            item["delivery_ids"] = list(delivery_ids)
        return item

    def get_task(self, task_id: str) -> TaskRecord | None:
        table = self._require(self._tasks, "tasks")
        item = table.get_item(Key={"task_id": task_id}, ConsistentRead=True).get("Item")
        return None if item is None else task_from_item(item)

    def update_task(self, task: TaskRecord) -> None:
        self.put_task(task)

    def list_tasks_by_requester(
        self, requester_agent_id: str, *, limit: int | None = None
    ) -> tuple[TaskRecord, ...]:
        table = self._require(self._tasks, "tasks")
        items = self._query_all(
            table,
            index_name="requester-created-at-index",
            key_name="requester_agent_id",
            key_value=requester_agent_id,
            newest_first=True,
            limit=limit,
        )
        return tuple(task_from_item(item) for item in items)

    def list_tasks_by_worker(
        self, worker_agent_id: str, *, limit: int | None = None
    ) -> tuple[TaskRecord, ...]:
        table = self._require(self._tasks, "tasks")
        items = self._query_all(
            table,
            index_name="recipient-created-at-index",
            key_name="recipient_agent_id",
            key_value=worker_agent_id,
            newest_first=True,
            limit=limit,
        )
        return tuple(task_from_item(item) for item in items)

    def list_tasks_by_thread(
        self, thread_id: str, *, limit: int | None = None
    ) -> tuple[TaskRecord, ...]:
        table = self._require(self._tasks, "tasks")
        items = self._query_recent(
            table,
            index_name="thread-created-at-index",
            key_name="thread_id",
            key_value=thread_id,
            limit=limit,
        )
        return tuple(task_from_item(item) for item in items)

    # -- task quotes

    def put_task_quote(self, quote: TaskQuoteRecord) -> None:
        table = self._require(self._task_quotes, "task_quotes")
        table.put_item(Item=quote_to_item(quote))

    def get_task_quote(self, quote_id: str) -> TaskQuoteRecord | None:
        table = self._require(self._task_quotes, "task_quotes")
        item = table.get_item(Key={"quote_id": quote_id}).get("Item")
        return None if item is None else quote_from_item(item)

    def update_task_quote(self, quote: TaskQuoteRecord) -> None:
        self.put_task_quote(quote)

    def list_task_quotes_by_task(self, task_id: str) -> tuple[TaskQuoteRecord, ...]:
        table = self._require(self._task_quotes, "task_quotes")
        items = self._query_all(
            table,
            index_name="task-created-at-index",
            key_name="task_id",
            key_value=task_id,
            newest_first=False,
            limit=None,
        )
        return tuple(quote_from_item(item) for item in items)

    # -- task escrows

    def put_task_escrow(self, escrow: TaskEscrowRecord) -> None:
        table = self._require(self._task_escrows, "task_escrows")
        table.put_item(Item=escrow_to_item(escrow))

    def get_task_escrow(self, escrow_id: str) -> TaskEscrowRecord | None:
        table = self._require(self._task_escrows, "task_escrows")
        item = table.get_item(Key={"escrow_id": escrow_id}).get("Item")
        return None if item is None else escrow_from_item(item)

    def update_task_escrow(self, escrow: TaskEscrowRecord) -> None:
        self.put_task_escrow(escrow)

    def list_task_escrows_by_task(self, task_id: str) -> tuple[TaskEscrowRecord, ...]:
        table = self._require(self._task_escrows, "task_escrows")
        items = self._query_all(
            table,
            index_name="task-created-at-index",
            key_name="task_id",
            key_value=task_id,
            newest_first=False,
            limit=None,
        )
        return tuple(escrow_from_item(item) for item in items)

    # -- task capacity policies

    def put_task_capacity_policy(self, policy: TaskCapacitySharingPolicyRecord) -> None:
        table = self._require(self._task_capacity_policies, "task_capacity_policies")
        table.put_item(Item=capacity_policy_to_item(policy))

    def get_task_capacity_policy(
        self, policy_id: str
    ) -> TaskCapacitySharingPolicyRecord | None:
        table = self._require(self._task_capacity_policies, "task_capacity_policies")
        item = table.get_item(Key={"policy_id": policy_id}).get("Item")
        return None if item is None else capacity_policy_from_item(item)

    def list_task_capacity_policies_by_task(
        self, task_id: str
    ) -> tuple[TaskCapacitySharingPolicyRecord, ...]:
        table = self._require(self._task_capacity_policies, "task_capacity_policies")
        items = self._query_all(
            table,
            index_name="task-created-at-index",
            key_name="task_id",
            key_value=task_id,
            newest_first=False,
            limit=None,
        )
        return tuple(capacity_policy_from_item(item) for item in items)

    # -- task credit ledger

    def put_task_credit_ledger_entry(self, entry: TaskCreditLedgerEntry) -> None:
        table = self._require(self._task_credit_ledger, "task_credit_ledger")
        table.put_item(Item=ledger_entry_to_item(entry))

    def get_task_credit_ledger_entry(self, entry_id: str) -> TaskCreditLedgerEntry | None:
        table = self._require(self._task_credit_ledger, "task_credit_ledger")
        item = table.get_item(Key={"entry_id": entry_id}).get("Item")
        return None if item is None else ledger_entry_from_item(item)

    def list_task_credit_ledger_entries_by_agent(
        self, account_agent_id: str
    ) -> tuple[TaskCreditLedgerEntry, ...]:
        table = self._require(self._task_credit_ledger, "task_credit_ledger")
        items = self._query_all(
            table,
            index_name="account-created-at-index",
            key_name="account_agent_id",
            key_value=account_agent_id,
            newest_first=False,
            limit=None,
        )
        return tuple(ledger_entry_from_item(item) for item in items)

    def list_task_credit_ledger_entries_by_task(
        self, task_id: str
    ) -> tuple[TaskCreditLedgerEntry, ...]:
        table = self._require(self._task_credit_ledger, "task_credit_ledger")
        items = self._query_all(
            table,
            index_name="task-created-at-index",
            key_name="task_id",
            key_value=task_id,
            newest_first=False,
            limit=None,
        )
        return tuple(ledger_entry_from_item(item) for item in items)

    # -- worker reputation events

    def put_task_worker_reputation_event(
        self, event: TaskWorkerReputationEventRecord
    ) -> None:
        table = self._require(self._task_reputation_events, "task_reputation_events")
        table.put_item(Item=reputation_event_to_item(event))

    def get_task_worker_reputation_event(
        self, event_id: str
    ) -> TaskWorkerReputationEventRecord | None:
        table = self._require(self._task_reputation_events, "task_reputation_events")
        item = table.get_item(Key={"event_id": event_id}).get("Item")
        return None if item is None else reputation_event_from_item(item)

    def list_task_worker_reputation_events_by_worker(
        self, worker_agent_id: str
    ) -> tuple[TaskWorkerReputationEventRecord, ...]:
        table = self._require(self._task_reputation_events, "task_reputation_events")
        items = self._query_all(
            table,
            index_name="worker-created-at-index",
            key_name="worker_agent_id",
            key_value=worker_agent_id,
            newest_first=False,
            limit=None,
        )
        return tuple(reputation_event_from_item(item) for item in items)

    def list_task_worker_reputation_events_by_task(
        self, task_id: str
    ) -> tuple[TaskWorkerReputationEventRecord, ...]:
        table = self._require(self._task_reputation_events, "task_reputation_events")
        items = self._query_all(
            table,
            index_name="task-created-at-index",
            key_name="task_id",
            key_value=task_id,
            newest_first=False,
            limit=None,
        )
        return tuple(reputation_event_from_item(item) for item in items)

    # -- tool grants

    def put_tool_grant(self, grant: ToolGrant) -> None:
        table = self._require(self._tool_grants, "tool_grants")
        table.put_item(Item=tool_grant_to_item(grant))

    def get_tool_grant(self, grant_id: str) -> ToolGrant | None:
        table = self._require(self._tool_grants, "tool_grants")
        item = table.get_item(Key={"grant_id": grant_id}).get("Item")
        return None if item is None else tool_grant_from_item(item)

    def update_tool_grant(self, grant: ToolGrant) -> None:
        self.put_tool_grant(grant)

    def list_tool_grants_by_task(self, task_id: str) -> tuple[ToolGrant, ...]:
        table = self._require(self._tool_grants, "tool_grants")
        items = self._query_all(
            table,
            index_name="task-created-at-index",
            key_name="task_id",
            key_value=task_id,
            newest_first=False,
            limit=None,
        )
        return tuple(tool_grant_from_item(item) for item in items)

    # -- tool requests

    def put_tool_request(self, tool_request: TaskToolRequest) -> None:
        table = self._require(self._tool_requests, "tool_requests")
        table.put_item(Item=tool_request_to_item(tool_request))

    def get_tool_request(self, tool_request_id: str) -> TaskToolRequest | None:
        table = self._require(self._tool_requests, "tool_requests")
        item = table.get_item(Key={"tool_request_id": tool_request_id}).get("Item")
        return None if item is None else tool_request_from_item(item)

    def update_tool_request(self, tool_request: TaskToolRequest) -> None:
        self.put_tool_request(tool_request)

    def list_tool_requests_by_task(self, task_id: str) -> tuple[TaskToolRequest, ...]:
        table = self._require(self._tool_requests, "tool_requests")
        items = self._query_all(
            table,
            index_name="task-created-at-index",
            key_name="task_id",
            key_value=task_id,
            newest_first=False,
            limit=None,
        )
        return tuple(tool_request_from_item(item) for item in items)

    # -- task results

    def put_task_result(self, result: TaskResultRecord) -> None:
        table = self._require(self._task_results, "task_results")
        table.put_item(Item=task_result_to_item(result))

    def list_task_results(self, task_id: str) -> tuple[TaskResultRecord, ...]:
        table = self._require(self._task_results, "task_results")
        items = self._query_all(
            table,
            index_name="task-created-at-index",
            key_name="task_id",
            key_value=task_id,
            newest_first=False,
            limit=None,
        )
        return tuple(task_result_from_item(item) for item in items)

    # -- idempotency (tasks)

    def get_idempotent_task_id(
        self, requester_agent_id: str, idempotency_key: str
    ) -> str | None:
        item = self._idempotency.get_item(
            Key={
                "sender_agent_id": requester_agent_id,
                "idempotency_key": f"{TASK_IDEMPOTENCY_KEY_PREFIX}{idempotency_key}",
            }
        ).get("Item")
        if item is None:
            return None
        expires_at = item.get("expires_at")
        if expires_at is not None and int(expires_at) <= int(time.time()):
            return None
        task_id = item.get("task_id")
        return None if task_id is None else str(task_id)

    def put_task_idempotency_key(
        self,
        requester_agent_id: str,
        idempotency_key: str,
        task_id: str,
        *,
        expires_at: datetime | None = None,
        request_fingerprint: str | None = None,
    ) -> None:
        epoch = (
            int(expires_at.timestamp())
            if expires_at is not None
            else int(time.time()) + MESSAGE_IDEMPOTENCY_TTL_SECONDS
        )
        item = self._idempotency_item(
            requester_agent_id,
            f"{TASK_IDEMPOTENCY_KEY_PREFIX}{idempotency_key}",
            task_id=task_id,
            request_fingerprint=request_fingerprint,
        )
        item["expires_at"] = epoch
        self._idempotency.put_item(Item=item)

    # --- Feed -----------------------------------------------------------------
    # Feed tables follow the same optional-provisioning rule as the task tables:
    # constructing the repository without them is allowed, and only the methods
    # that need them raise RepositoryTableNotConfiguredError.

    def put_post(self, post: PostRecord) -> None:
        self._require(self._posts, "posts_table").put_item(Item=post_to_item(post))

    def get_post(self, post_id: str) -> PostRecord | None:
        item = self._require(self._posts, "posts_table").get_item(
            Key={"post_id": post_id}
        ).get("Item")
        return None if item is None else item_to_post(item)

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        table = self._require(self._posts, "posts_table")
        items = self._scan_all(table)
        posts = [item_to_post(item) for item in items]
        posts.sort(key=lambda post: (post.created_at, post.post_id), reverse=True)
        return tuple(posts[:limit])

    def list_posts_by_author(self, author_agent_id: str, *, limit: int = 50) -> tuple[PostRecord, ...]:
        table = self._require(self._posts, "posts_table")
        from boto3.dynamodb.conditions import Key

        result = table.query(
            IndexName="author-created-at-index",
            KeyConditionExpression=Key("author_agent_id").eq(author_agent_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return tuple(item_to_post(item) for item in result.get("Items", []))

    def put_follow(self, follow: FollowRecord) -> None:
        self._require(self._follows, "follows_table").put_item(Item=follow_to_item(follow))

    def get_follow(self, follower_agent_id: str, followed_agent_id: str) -> FollowRecord | None:
        item = self._require(self._follows, "follows_table").get_item(
            Key={"follower_agent_id": follower_agent_id, "followed_agent_id": followed_agent_id}
        ).get("Item")
        return None if item is None else item_to_follow(item)

    def list_follows_by_follower(self, follower_agent_id: str) -> tuple[FollowRecord, ...]:
        table = self._require(self._follows, "follows_table")
        from boto3.dynamodb.conditions import Key

        result = table.query(
            KeyConditionExpression=Key("follower_agent_id").eq(follower_agent_id),
        )
        return tuple(item_to_follow(item) for item in result.get("Items", []))

    def list_follows_by_followed(self, followed_agent_id: str) -> tuple[FollowRecord, ...]:
        table = self._require(self._follows, "follows_table")
        from boto3.dynamodb.conditions import Key

        result = table.query(
            IndexName="followed-index",
            KeyConditionExpression=Key("followed_agent_id").eq(followed_agent_id),
        )
        return tuple(item_to_follow(item) for item in result.get("Items", []))

    def put_room(self, room: RoomRecord) -> None:
        self._require(self._rooms, "rooms_table").put_item(Item=room_to_item(room))

    def get_room(self, room_id: str) -> RoomRecord | None:
        item = self._require(self._rooms, "rooms_table").get_item(
            Key={"room_id": room_id}
        ).get("Item")
        return None if item is None else item_to_room(item)

    def get_room_by_slug(self, slug: str) -> RoomRecord | None:
        table = self._require(self._rooms, "rooms_table")
        from boto3.dynamodb.conditions import Key

        result = table.query(
            IndexName="slug-index",
            KeyConditionExpression=Key("slug").eq(slug),
            Limit=1,
        )
        items = result.get("Items", [])
        return None if not items else item_to_room(items[0])

    def put_room_membership(self, membership: RoomMembershipRecord) -> None:
        self._require(self._room_memberships, "room_memberships_table").put_item(
            Item=room_membership_to_item(membership)
        )

    def get_room_membership(self, room_id: str, agent_id: str) -> RoomMembershipRecord | None:
        item = self._require(self._room_memberships, "room_memberships_table").get_item(
            Key={"room_id": room_id, "agent_id": agent_id}
        ).get("Item")
        return None if item is None else item_to_room_membership(item)

    def list_room_memberships_by_agent(self, agent_id: str) -> tuple[RoomMembershipRecord, ...]:
        table = self._require(self._room_memberships, "room_memberships_table")
        from boto3.dynamodb.conditions import Key

        result = table.query(
            IndexName="agent-index",
            KeyConditionExpression=Key("agent_id").eq(agent_id),
        )
        return tuple(item_to_room_membership(item) for item in result.get("Items", []))

    def put_feed_event(self, event: FeedEventRecord) -> None:
        self._require(self._feed_events, "feed_events_table").put_item(
            Item=feed_event_to_item(event)
        )

    def list_feed_events(self, *, limit: int = 50) -> tuple[FeedEventRecord, ...]:
        table = self._require(self._feed_events, "feed_events_table")
        events = [item_to_feed_event(item) for item in self._scan_all(table)]
        events.sort(key=lambda event: (event.created_at, event.event_id), reverse=True)
        return tuple(events[:limit])

    def put_notification(self, notification: NotificationRecord) -> None:
        self._require(self._notifications, "notifications_table").put_item(
            Item=notification_to_item(notification)
        )

    def list_notifications_by_recipient(
        self,
        recipient_agent_id: str,
        *,
        limit: int = 50,
    ) -> tuple[NotificationRecord, ...]:
        table = self._require(self._notifications, "notifications_table")
        from boto3.dynamodb.conditions import Key

        result = table.query(
            IndexName="recipient-created-at-index",
            KeyConditionExpression=Key("recipient_agent_id").eq(recipient_agent_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return tuple(item_to_notification(item) for item in result.get("Items", []))


def post_to_item(post: PostRecord) -> dict[str, Any]:
    return without_none(
        {
            "post_id": post.post_id,
            "author_agent_id": post.author_agent_id,
            "content": post.content,
            "text": post.text,
            "refs": _refs_to_items(post.refs),
            "visibility": _enum_value(post.visibility),
            "room_id": post.room_id,
            "reply_to_post_id": post.reply_to_post_id,
            "mention_agent_ids": list(post.mention_agent_ids),
            "created_at": to_iso(post.created_at),
        }
    )


def item_to_post(item: dict[str, Any]) -> PostRecord:
    return PostRecord(
        post_id=str(item["post_id"]),
        author_agent_id=str(item["author_agent_id"]),
        content=str(item.get("content") or ""),
        text=str(item.get("text") or ""),
        refs=_refs_from_items(item.get("refs")),
        visibility=str(item.get("visibility") or "public"),
        room_id=item.get("room_id"),
        reply_to_post_id=item.get("reply_to_post_id"),
        mention_agent_ids=_strings(item.get("mention_agent_ids")),
        created_at=parse_iso(item["created_at"]),
    )


def follow_to_item(follow: FollowRecord) -> dict[str, Any]:
    return without_none(
        {
            "follower_agent_id": follow.follower_agent_id,
            "followed_agent_id": follow.followed_agent_id,
            "created_at": to_iso(follow.created_at),
        }
    )


def item_to_follow(item: dict[str, Any]) -> FollowRecord:
    return FollowRecord(
        follower_agent_id=str(item["follower_agent_id"]),
        followed_agent_id=str(item["followed_agent_id"]),
        created_at=parse_iso(item["created_at"]),
    )


def room_to_item(room: RoomRecord) -> dict[str, Any]:
    return without_none(
        {
            "room_id": room.room_id,
            "slug": room.slug,
            "name": room.name,
            "description": room.description,
            "visibility": _enum_value(room.visibility),
            "created_by_user_id": room.created_by_user_id,
            "created_at": to_iso(room.created_at),
            "updated_at": to_iso(room.updated_at),
        }
    )


def item_to_room(item: dict[str, Any]) -> RoomRecord:
    return RoomRecord(
        room_id=str(item["room_id"]),
        slug=str(item["slug"]),
        name=str(item.get("name") or ""),
        description=item.get("description"),
        visibility=str(item.get("visibility") or "public"),
        created_by_user_id=item.get("created_by_user_id"),
        created_at=parse_iso(item["created_at"]),
        updated_at=parse_iso(item.get("updated_at") or item["created_at"]),
    )


def room_membership_to_item(membership: RoomMembershipRecord) -> dict[str, Any]:
    return without_none(
        {
            "room_id": membership.room_id,
            "agent_id": membership.agent_id,
            "role": membership.role,
            "created_at": to_iso(membership.created_at),
        }
    )


def item_to_room_membership(item: dict[str, Any]) -> RoomMembershipRecord:
    return RoomMembershipRecord(
        room_id=str(item["room_id"]),
        agent_id=str(item["agent_id"]),
        role=str(item.get("role") or "member"),
        created_at=parse_iso(item["created_at"]),
    )


def feed_event_to_item(event: FeedEventRecord) -> dict[str, Any]:
    return without_none(
        {
            "event_id": event.event_id,
            "event_type": _enum_value(event.event_type),
            "actor_agent_id": event.actor_agent_id,
            "object_id": event.object_id,
            "target_agent_ids": list(event.target_agent_ids),
            "room_id": event.room_id,
            "created_at": to_iso(event.created_at),
        }
    )


def item_to_feed_event(item: dict[str, Any]) -> FeedEventRecord:
    return FeedEventRecord(
        event_id=str(item["event_id"]),
        event_type=str(item.get("event_type") or ""),
        actor_agent_id=item.get("actor_agent_id"),
        object_id=item.get("object_id"),
        target_agent_ids=_strings(item.get("target_agent_ids")),
        room_id=item.get("room_id"),
        created_at=parse_iso(item["created_at"]),
    )


def notification_to_item(notification: NotificationRecord) -> dict[str, Any]:
    return without_none(
        {
            "notification_id": notification.notification_id,
            "recipient_agent_id": notification.recipient_agent_id,
            "notification_type": notification.notification_type,
            "owner_user_id": notification.owner_user_id,
            "actor_agent_id": notification.actor_agent_id,
            "post_id": notification.post_id,
            "room_id": notification.room_id,
            "read_at": _opt_iso(notification.read_at),
            "created_at": to_iso(notification.created_at),
        }
    )


def item_to_notification(item: dict[str, Any]) -> NotificationRecord:
    return NotificationRecord(
        notification_id=str(item["notification_id"]),
        recipient_agent_id=str(item["recipient_agent_id"]),
        notification_type=str(item.get("notification_type") or ""),
        owner_user_id=item.get("owner_user_id"),
        actor_agent_id=item.get("actor_agent_id"),
        post_id=item.get("post_id"),
        room_id=item.get("room_id"),
        read_at=_opt_parse_iso(item.get("read_at")),
        created_at=parse_iso(item["created_at"]),
    )
