from __future__ import annotations

import gzip
import hashlib
import secrets
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from message_hub.domain.events import delivery_created_event
from message_hub.domain.models import (
    ActionRequest,
    AgentDecisionResult,
    Agent,
    AgentTokenPrincipal,
    AgentTokenRecord,
    ContactExplanation,
    ContextBudget,
    ContextPack,
    ContextPayloadRef,
    Delivery,
    DeliveryStatus,
    InboxItem,
    IssuedAgentToken,
    Message,
    MessageRef,
    PayloadCompaction,
    PayloadRecord,
    PayloadRetentionWorkerResult,
    RoutingRule,
    RoutingRuleMode,
    SendMessageResult,
    StoredPayload,
    TASK_CREDIT_SETTLEMENT_SCOPE,
    TASK_INACTIVE_STATES,
    TaskCapacityRole,
    TaskCapacitySharingPolicyRecord,
    TaskCapacityTier,
    TaskCreditBalance,
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
    TaskWorkerReputationSummary,
    ToolGrant,
    ThreadContext,
    ThreadRecord,
    ThreadSummary,
    WorkflowTraceEntry,
    utc_now,
)
from message_hub.domain.safety import (
    LocalSafetyEvaluator,
    SafetyCheckRequest,
    SafetyEvaluator,
    require_deliverable,
    safety_status_for,
)
from message_hub.storage.repository import MessageHubRepository


class MessageHubError(Exception):
    """Base error for message hub domain failures."""


class DuplicateAgentHandleError(MessageHubError):
    """Raised when an agent handle is already registered."""


class InvalidMessageError(MessageHubError):
    """Raised when a send request cannot produce a valid message."""


class NotFoundError(MessageHubError):
    """Raised when a required agent, message, thread, or delivery is missing."""


class ForbiddenDeliveryError(MessageHubError):
    """Raised when an agent tries to mutate another agent's delivery."""


class ForbiddenPayloadError(MessageHubError):
    """Raised when a requester cannot fetch a payload."""


class PayloadUnavailableError(MessageHubError):
    """Raised when payload metadata exists but content bytes are unavailable."""


class AgentTokenVerificationError(MessageHubError):
    """Raised when scoped agent-runtime token validation fails."""


IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]
DeliveryEventPublisher = Callable[[dict[str, Any]], None]
DEFAULT_CONTEXT_MAX_INLINE_CHARS = 4000
DEFAULT_CONTEXT_MAX_RECENT_MESSAGES = 10
DEFAULT_CONTEXT_MAX_PAYLOAD_REFS = 20
MAX_ENVELOPE_INLINE_CHARS = 4000
DEFAULT_CONTACT_RELATIONSHIP = "needs_approval"
CONTACT_EXPLANATION_SUMMARY_CHARS = 280
MAX_TASK_CREDIT_QUOTE = 1_000_000
PAYLOAD_RETENTION_READY = "ready"
PAYLOAD_RETENTION_EXPIRED = "expired"
PAYLOAD_RETENTION_COMPACTED = "compacted"
PAYLOAD_RETENTION_DELETED = "deleted"
PAYLOAD_RETENTION_STATES = {
    PAYLOAD_RETENTION_READY,
    PAYLOAD_RETENTION_EXPIRED,
    PAYLOAD_RETENTION_COMPACTED,
    PAYLOAD_RETENTION_DELETED,
}
AGENT_TOKEN_PREFIX = "sga"
AGENT_TOKEN_SCOPES = frozenset(
    {
        "agent:read",
        "agent:inbox",
        "agent:post",
        "agent:ack",
    }
)
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


class MessageHubService:
    def __init__(
        self,
        repository: MessageHubRepository,
        *,
        id_factory: IdFactory | None = None,
        clock: Clock = utc_now,
        safety_evaluator: SafetyEvaluator | None = None,
        delivery_event_publisher: DeliveryEventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory or self._default_id_factory
        self._clock = clock
        self._safety_evaluator = safety_evaluator or LocalSafetyEvaluator()
        self._delivery_event_publisher = delivery_event_publisher

    def register_agent(
        self,
        handle: str,
        *,
        display_name: str | None = None,
        capabilities: Sequence[str] = (),
        response_rules: dict[str, Any] | None = None,
        trigger_mode: str = "manual",
        webhook_url: str | None = None,
    ) -> Agent:
        normalized_handle = normalize_handle(handle)
        if self._repository.get_agent_by_handle(normalized_handle) is not None:
            raise DuplicateAgentHandleError(f"agent handle already exists: {normalized_handle}")

        normalized_trigger_mode = normalize_trigger_mode(trigger_mode)
        normalized_webhook_url = normalize_webhook_url(webhook_url)
        if normalized_trigger_mode == "webhook" and normalized_webhook_url is None:
            raise InvalidMessageError("webhook_url is required when trigger_mode is webhook")
        if normalized_trigger_mode == "manual" and normalized_webhook_url is not None:
            raise InvalidMessageError("webhook_url requires trigger_mode webhook")

        now = self._clock()
        agent = Agent(
            agent_id=self._new_id("agent"),
            handle=normalized_handle,
            display_name=display_name,
            capabilities=tuple(capabilities),
            response_rules=response_rules,
            trigger_mode=normalized_trigger_mode,
            webhook_url=normalized_webhook_url,
            created_at=now,
            updated_at=now,
        )
        self._repository.add_agent(agent)
        return agent

    def issue_agent_token(
        self,
        agent_handle: str,
        *,
        scopes: Sequence[str],
        name: str | None = None,
        owner_user_id: str | None = None,
        node_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> IssuedAgentToken:
        agent = self._require_agent_by_handle(agent_handle)
        normalized_scopes = normalize_agent_token_scopes(scopes)
        normalized_expires_at = normalize_payload_ttl_expires_at(expires_at)
        token_id = secrets.token_hex(12)
        secret = secrets.token_hex(32)
        token = f"{AGENT_TOKEN_PREFIX}_{token_id}_{secret}"
        now = self._clock()
        record = AgentTokenRecord(
            token_id=token_id,
            token_hash=hash_token_parts(token_id, secret),
            agent_id=agent.agent_id,
            agent_handle=agent.handle,
            scopes=normalized_scopes,
            name=normalized_optional_string(name),
            owner_user_id=normalized_optional_string(owner_user_id),
            node_id=normalized_optional_string(node_id),
            created_at=now,
            expires_at=normalized_expires_at,
        )
        self._repository.put_agent_token(record)
        return IssuedAgentToken(token=token, record=record)

    def verify_agent_token(
        self,
        token: str,
        *,
        required_scope: str | None = None,
        agent_handle: str | None = None,
    ) -> AgentTokenPrincipal:
        token_id, secret = parse_agent_token(token)
        record = self._repository.get_agent_token(token_id)
        if record is None:
            raise AgentTokenVerificationError("agent token not found")
        if not secrets.compare_digest(hash_token_parts(token_id, secret), record.token_hash):
            raise AgentTokenVerificationError("agent token is invalid")

        checked_at = self._clock()
        if record.revoked_at is not None:
            raise AgentTokenVerificationError("agent token is revoked")
        if record.expires_at is not None and record.expires_at <= checked_at:
            raise AgentTokenVerificationError("agent token is expired")

        normalized_scope = normalized_optional_string(required_scope)
        if normalized_scope is not None:
            normalized_scope = normalize_agent_token_scope(normalized_scope)
            if normalized_scope not in record.scopes:
                raise AgentTokenVerificationError(f"missing agent token scope: {normalized_scope}")

        if agent_handle is not None:
            normalized_handle = normalize_handle(agent_handle)
            if normalized_handle != record.agent_handle:
                raise AgentTokenVerificationError(
                    f"agent token cannot access agent: {normalized_handle}"
                )

        updated = replace(record, last_used_at=checked_at)
        self._repository.update_agent_token(updated)
        return AgentTokenPrincipal(
            token_id=updated.token_id,
            agent_id=updated.agent_id,
            agent_handle=updated.agent_handle,
            scopes=frozenset(updated.scopes),
            owner_user_id=updated.owner_user_id,
            node_id=updated.node_id,
        )

    def revoke_agent_token(self, token_id: str) -> AgentTokenRecord:
        normalized_token_id = normalize_required(token_id, "token_id")
        record = self._repository.get_agent_token(normalized_token_id)
        if record is None:
            raise NotFoundError(f"agent token not found: {normalized_token_id}")
        updated = replace(record, revoked_at=self._clock())
        self._repository.update_agent_token(updated)
        return updated

    def add_routing_rule(
        self,
        *,
        name: str,
        route_to_handles: Sequence[str] = (),
        mode: str = "copy",
        url_contains: Sequence[str] = (),
        enabled: bool = True,
    ) -> RoutingRule:
        normalized_name = normalize_required(name, "name")
        normalized_mode = normalize_routing_rule_mode(mode)
        normalized_route_to_handles = tuple(normalize_handle(handle) for handle in route_to_handles)
        normalized_url_contains = tuple(
            value.strip().lower()
            for value in url_contains
            if value.strip()
        )

        if normalized_mode != RoutingRuleMode.BLOCK and not normalized_route_to_handles:
            raise InvalidMessageError("routing rule requires route_to_handles unless mode is block")
        if not normalized_url_contains:
            raise InvalidMessageError("routing rule requires at least one url_contains value")

        for handle in normalized_route_to_handles:
            self._require_agent_by_handle(handle)

        now = self._clock()
        rule = RoutingRule(
            rule_id=self._new_id("routing_rule"),
            name=normalized_name,
            mode=normalized_mode,
            route_to_handles=normalized_route_to_handles,
            url_contains=normalized_url_contains,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        self._repository.put_routing_rule(rule)
        return rule

    def create_payload(
        self,
        *,
        content: str | bytes,
        media_type: str,
        access_scope: str = "recipients",
        ttl_expires_at: datetime | None = None,
    ) -> StoredPayload:
        content_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        normalized_media_type = normalize_required(media_type, "media_type")
        normalized_access_scope = normalize_payload_access_scope(access_scope)
        normalized_ttl_expires_at = normalize_payload_ttl_expires_at(ttl_expires_at)
        compressed_content = gzip.compress(content_bytes, compresslevel=6, mtime=0)
        content_ref = f"payload://{self._new_id('payload')}"
        now = self._clock()
        record = PayloadRecord(
            content_ref=content_ref,
            media_type=normalized_media_type,
            byte_length=len(content_bytes),
            hash=payload_hash(content_bytes),
            compression="gzip",
            compressed_byte_length=len(compressed_content),
            compressed_hash=payload_hash(compressed_content),
            ttl_expires_at=normalized_ttl_expires_at,
            retention_state=PAYLOAD_RETENTION_READY,
            access_scope=normalized_access_scope,
            storage_provider="local_node",
            storage_ref=content_ref,
            created_at=now,
        )
        payload = StoredPayload(record=record, compressed_content=compressed_content)
        self._repository.put_payload(payload)
        return payload

    def get_payload(self, content_ref: str) -> StoredPayload:
        normalized_content_ref = normalize_required(content_ref, "content_ref")
        payload = self._repository.get_payload(normalized_content_ref)
        if payload is None:
            raise NotFoundError(f"payload not found: {normalized_content_ref}")
        return self._refresh_payload_retention(payload)

    def update_payload_retention(self, content_ref: str, *, retention_state: str) -> PayloadRecord:
        normalized_retention_state = normalize_payload_retention_state(retention_state)
        payload = self.get_payload(content_ref)
        if normalized_retention_state == PAYLOAD_RETENTION_READY and payload.compressed_content is None:
            raise InvalidMessageError("cannot restore ready payload state without retained content")

        retained_content = (
            payload.compressed_content
            if normalized_retention_state == PAYLOAD_RETENTION_READY
            else None
        )
        updated = StoredPayload(
            record=replace(payload.record, retention_state=normalized_retention_state),
            compressed_content=retained_content,
        )
        self._repository.update_payload(updated)
        return updated.record

    def read_payload_content(
        self,
        content_ref: str,
        *,
        requester_handle: str | None = None,
    ) -> tuple[PayloadRecord, bytes]:
        payload = self.get_payload(content_ref)
        self._require_payload_fetch_authorized(payload.record, requester_handle)
        if payload.record.retention_state != PAYLOAD_RETENTION_READY:
            raise PayloadUnavailableError(
                f"payload content is {payload.record.retention_state}: {payload.record.content_ref}"
            )
        if payload.compressed_content is None:
            raise PayloadUnavailableError(f"payload content is unavailable: {payload.record.content_ref}")
        return payload.record, gzip.decompress(payload.compressed_content)

    def run_payload_retention_worker(
        self,
        *,
        compact_ready_before: datetime | None = None,
        delete_expired_before: datetime | None = None,
        compact_summary_chars: int = 512,
        compact_chunk_bytes: int = 1024,
        limit: int | None = None,
    ) -> PayloadRetentionWorkerResult:
        normalized_compact_ready_before = normalize_payload_policy_cutoff(
            compact_ready_before,
            "compact_ready_before",
        )
        normalized_delete_expired_before = normalize_payload_policy_cutoff(
            delete_expired_before,
            "delete_expired_before",
        )
        validate_payload_compaction_limits(
            compact_summary_chars=compact_summary_chars,
            compact_chunk_bytes=compact_chunk_bytes,
        )
        if limit is not None and limit < 0:
            raise InvalidMessageError("limit must be non-negative")

        scanned_count = 0
        expired_refs: list[str] = []
        compacted_refs: list[str] = []
        deleted_refs: list[str] = []

        for stored_payload in self._repository.list_payloads(limit=limit):
            scanned_count += 1
            payload = self._refresh_payload_retention(stored_payload)
            if (
                stored_payload.record.retention_state == PAYLOAD_RETENTION_READY
                and payload.record.retention_state == PAYLOAD_RETENTION_EXPIRED
            ):
                expired_refs.append(payload.record.content_ref)

            if should_delete_expired_payload(payload.record, normalized_delete_expired_before):
                self._delete_retained_payload(payload)
                deleted_refs.append(payload.record.content_ref)
                continue

            if should_compact_ready_payload(payload.record, normalized_compact_ready_before):
                if payload.compressed_content is None:
                    continue
                self._compact_payload(
                    payload,
                    summary_chars=compact_summary_chars,
                    chunk_bytes=compact_chunk_bytes,
                )
                compacted_refs.append(payload.record.content_ref)

        return PayloadRetentionWorkerResult(
            scanned_count=scanned_count,
            expired_refs=tuple(expired_refs),
            compacted_refs=tuple(compacted_refs),
            deleted_refs=tuple(deleted_refs),
        )

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handles: Sequence[str] = (),
        content: str | None = None,
        content_ref: str | None = None,
        refs: Sequence[MessageRef | dict[str, str | None]] = (),
        intent: str = "message",
        visibility: str = "direct",
        thread_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> SendMessageResult:
        message_refs = tuple(normalize_message_ref(ref) for ref in refs)
        normalized_content_ref = normalized_optional_string(content_ref)
        if content is None and normalized_content_ref is None and not message_refs:
            raise InvalidMessageError("message content, content_ref, or refs are required")

        sender = self._require_agent_by_handle(sender_handle)
        recipients = self._resolve_recipients(recipient_handles)

        recipients, routing_trace, needs_review = self._apply_routing_rules(
            recipients=recipients,
            content=content,
            content_ref=normalized_content_ref,
            refs=message_refs,
        )
        if not recipients and visibility != "public":
            raise InvalidMessageError("direct or limited messages require at least one recipient")

        if idempotency_key:
            existing_message_id = self._repository.get_idempotent_message_id(
                sender.agent_id,
                idempotency_key,
            )
            if existing_message_id is not None:
                return self._result_for_existing_message(existing_message_id)

        safety_decision = self._safety_evaluator.evaluate_send(
            SafetyCheckRequest(
                sender=sender,
                recipients=recipients,
                content=content,
                content_ref=normalized_content_ref,
                intent=intent,
                visibility=visibility,
                thread_id=thread_id,
            )
        )
        require_deliverable(safety_decision)
        stored_content, stored_content_ref = envelope_content_for_storage(
            content,
            normalized_content_ref,
            "message content",
        )

        now = self._clock()
        resolved_thread_id = thread_id or self._new_id("thread")
        message = Message(
            message_id=self._new_id("message"),
            thread_id=resolved_thread_id,
            sender_agent_id=sender.agent_id,
            recipient_agent_ids=tuple(agent.agent_id for agent in recipients),
            intent=intent,
            visibility=visibility,
            content_inline=stored_content,
            content_ref=stored_content_ref,
            refs=message_refs,
            safety_status=safety_status_for(safety_decision),
            created_at=now,
        )

        existing_thread = self._repository.get_thread(resolved_thread_id)
        if thread_id is not None and existing_thread is None:
            raise NotFoundError(f"thread not found: {thread_id}")

        participants = {sender.agent_id, *(agent.agent_id for agent in recipients)}
        if existing_thread is None:
            thread = ThreadRecord(
                thread_id=resolved_thread_id,
                root_message_id=message.message_id,
                participants=frozenset(participants),
                message_count=1,
                last_message_id=message.message_id,
                last_message_at=now,
                created_at=now,
                updated_at=now,
            )
        else:
            thread = replace(
                existing_thread,
                participants=existing_thread.participants | frozenset(participants),
                message_count=existing_thread.message_count + 1,
                last_message_id=message.message_id,
                last_message_at=now,
                updated_at=now,
            )

        deliveries = tuple(
            Delivery(
                delivery_id=self._new_id("delivery"),
                message_id=message.message_id,
                thread_id=message.thread_id,
                sender_agent_id=sender.agent_id,
                recipient_agent_id=recipient.agent_id,
                status=DeliveryStatus.NEEDS_REVIEW if needs_review else DeliveryStatus.DELIVERED,
                current_content_inline=stored_content,
                current_content_ref=stored_content_ref,
                refs=message_refs,
                workflow_trace=routing_trace,
                current_stage="human.review" if needs_review else "agent.wait",
                created_at=now,
                updated_at=now,
            )
            for recipient in recipients
        )

        self._repository.put_message(message)
        self._repository.put_thread(thread)
        for delivery in deliveries:
            self._repository.put_delivery(delivery)

        self._publish_delivery_created_events(
            deliveries=deliveries,
            message=message,
            sender=sender,
            recipients=recipients,
        )

        if idempotency_key:
            self._repository.put_idempotency_key(
                sender.agent_id,
                idempotency_key,
                message.message_id,
            )

        return SendMessageResult(message=message, thread=thread, deliveries=deliveries)

    def get_inbox(self, handle: str, *, limit: int = 20) -> tuple[InboxItem, ...]:
        agent = self._require_agent_by_handle(handle)
        deliveries = self._repository.list_deliveries_by_recipient(agent.agent_id, limit=limit)
        return tuple(self._inbox_item_for_delivery(delivery) for delivery in deliveries)

    def get_outbox(self, handle: str, *, limit: int = 20) -> tuple[InboxItem, ...]:
        agent = self._require_agent_by_handle(handle)
        deliveries = self._repository.list_deliveries_by_sender(agent.agent_id, limit=limit)
        return tuple(self._inbox_item_for_delivery(delivery) for delivery in deliveries)

    def get_sent_messages(self, handle: str, *, limit: int = 20) -> tuple[Message, ...]:
        agent = self._require_agent_by_handle(handle)
        return self._repository.list_messages_by_sender(agent.agent_id, limit=limit)

    def get_thread(self, thread_id: str, *, limit: int = 50) -> tuple[Message, ...]:
        if self._repository.get_thread(thread_id) is None:
            raise NotFoundError(f"thread not found: {thread_id}")
        return self._repository.list_thread_messages(thread_id, limit=limit)

    def get_thread_context(self, thread_id: str, *, recent_limit: int = 10) -> ThreadContext:
        thread = self._repository.get_thread(thread_id)
        if thread is None:
            raise NotFoundError(f"thread not found: {thread_id}")

        return ThreadContext(
            thread=thread,
            summary=self._repository.get_latest_thread_summary(thread_id),
            recent_messages=self._repository.list_thread_messages(thread_id, limit=recent_limit),
        )

    def explain_contact(self, delivery_id: str) -> ContactExplanation:
        delivery = self._require_delivery(delivery_id)
        message = self._require_message(delivery.message_id)
        thread = self._repository.get_thread(delivery.thread_id)
        if thread is None:
            raise NotFoundError(f"thread not found: {delivery.thread_id}")

        requester = self._require_agent(delivery.sender_agent_id)
        recipient = self._require_agent(delivery.recipient_agent_id)
        relationship = DEFAULT_CONTACT_RELATIONSHIP
        summary = self._repository.get_latest_thread_summary(delivery.thread_id)
        tasks = tuple(
            task
            for task in self._repository.list_tasks_by_thread(delivery.thread_id, limit=100)
            if task.request_message_id == message.message_id
        )

        return ContactExplanation(
            explanation_id=f"contact_explanation_{delivery.delivery_id}",
            delivery_id=delivery.delivery_id,
            message_id=message.message_id,
            thread_id=delivery.thread_id,
            requester_agent_id=requester.agent_id,
            requester_handle=requester.handle,
            recipient_agent_id=recipient.agent_id,
            recipient_handle=recipient.handle,
            answering_asset_handle=recipient.handle,
            relationship=relationship,
            reason=contact_reason(message, delivery, requester, recipient),
            allowed_reason=contact_allowed_reason(message, delivery, relationship),
            shared_context_summary=contact_shared_context_summary(message, delivery, summary),
            shared_context_refs=contact_shared_context_refs(message, delivery, tasks),
            pending_action=contact_pending_action(delivery, tasks),
            current_stage=delivery.current_stage,
            policy_refs=contact_policy_refs(message, delivery, relationship, tasks),
            audit_event_refs=contact_audit_refs(delivery, thread),
            created_at=delivery.updated_at,
        )

    def get_context_pack(
        self,
        thread_id: str,
        *,
        requester_handle: str,
        max_inline_chars: int = DEFAULT_CONTEXT_MAX_INLINE_CHARS,
        max_recent_messages: int = DEFAULT_CONTEXT_MAX_RECENT_MESSAGES,
        max_payload_refs: int = DEFAULT_CONTEXT_MAX_PAYLOAD_REFS,
        token_budget_estimate: int | None = None,
    ) -> ContextPack:
        thread = self._repository.get_thread(thread_id)
        if thread is None:
            raise NotFoundError(f"thread not found: {thread_id}")

        requester = self._require_agent_by_handle(requester_handle)
        if requester.agent_id not in thread.participants:
            raise ForbiddenDeliveryError("agent cannot read context for this thread")

        normalized_max_inline_chars = require_bounded_int(
            max_inline_chars,
            "max_inline_chars",
            minimum=0,
            maximum=20000,
        )
        normalized_max_recent_messages = require_bounded_int(
            max_recent_messages,
            "max_recent_messages",
            minimum=0,
            maximum=50,
        )
        normalized_max_payload_refs = require_bounded_int(
            max_payload_refs,
            "max_payload_refs",
            minimum=0,
            maximum=100,
        )
        if token_budget_estimate is not None:
            token_budget_estimate = require_bounded_int(
                token_budget_estimate,
                "token_budget_estimate",
                minimum=0,
                maximum=1_000_000,
            )

        messages = (
            ()
            if normalized_max_recent_messages == 0
            else self._repository.list_thread_messages(thread_id, limit=normalized_max_recent_messages)
        )
        inline_chars_used = 0
        truncated = False
        budgeted_messages: list[Message] = []
        selected_refs: list[MessageRef] = []
        payload_refs: list[ContextPayloadRef] = []
        redacted_refs: list[str] = []

        for message in messages:
            budgeted_message = message
            if message.content_inline:
                remaining_chars = max(normalized_max_inline_chars - inline_chars_used, 0)
                if len(message.content_inline) <= remaining_chars:
                    inline_chars_used += len(message.content_inline)
                elif remaining_chars > 0:
                    budgeted_message = replace(message, content_inline=message.content_inline[:remaining_chars])
                    inline_chars_used += remaining_chars
                    truncated = True
                    redacted_refs.append(f"message://{message.message_id}/content_inline")
                else:
                    budgeted_message = replace(message, content_inline=None)
                    truncated = True
                    redacted_refs.append(f"message://{message.message_id}/content_inline")

            if message.content_ref:
                if has_private_context_marker(message.content_ref):
                    budgeted_message = replace(budgeted_message, content_ref=None)
                    redacted_refs.append(f"message://{message.message_id}/content_ref")
                elif len(payload_refs) < normalized_max_payload_refs:
                    payload_refs.append(
                        ContextPayloadRef(
                            content_ref=message.content_ref,
                            source_type="message",
                            source_id=message.message_id,
                        )
                    )

            for ref in message.refs:
                if is_private_context_ref(ref):
                    redacted_refs.append(f"message://{message.message_id}/ref")
                    continue
                if len(selected_refs) < normalized_max_payload_refs:
                    selected_refs.append(ref)

            budgeted_messages.append(replace(budgeted_message, refs=()))

        summary = self._repository.get_latest_thread_summary(thread_id)
        context_summary = summary
        if summary is not None and summary.content_ref:
            if has_private_context_marker(summary.content_ref):
                context_summary = replace(summary, content_ref=None)
                redacted_refs.append(f"summary://{summary.summary_id}/content_ref")
            elif len(payload_refs) < normalized_max_payload_refs:
                payload_refs.append(
                    ContextPayloadRef(
                        content_ref=summary.content_ref,
                        source_type="thread_summary",
                        source_id=summary.summary_id,
                    )
                )

        allowed_recipients = tuple(
            sorted(
                agent.handle
                for agent_id in thread.participants
                for agent in (self._repository.get_agent(agent_id),)
                if agent is not None
            )
        )
        budget = ContextBudget(
            max_inline_chars=normalized_max_inline_chars,
            max_recent_messages=normalized_max_recent_messages,
            max_payload_refs=normalized_max_payload_refs,
            token_budget_estimate=token_budget_estimate,
            inline_chars_used=inline_chars_used,
            recent_messages_returned=len(budgeted_messages),
            payload_refs_returned=len(payload_refs),
            truncated=truncated,
        )
        return ContextPack(
            context_pack_id=f"context_pack_{thread.thread_id}_{requester.agent_id}",
            thread=thread,
            requester_handle=requester.handle,
            summary=context_summary,
            recent_messages=tuple(budgeted_messages),
            selected_refs=tuple(selected_refs),
            payload_refs=tuple(payload_refs),
            budget=budget,
            allowed_recipients=allowed_recipients,
            redacted_refs=tuple(redacted_refs),
            created_at=self._clock(),
        )

    def create_task(
        self,
        *,
        requester_handle: str,
        recipient_handle: str,
        objective: str,
        thread_id: str | None = None,
        context_refs: Sequence[str] = (),
        context_pack_id: str | None = None,
        context_pack_ref: str | None = None,
        input_ref: str | None = None,
        stream_id: str | None = None,
        allowed_tool_names: Sequence[str] = (),
        allowed_use_terms: Sequence[str] = (),
        idempotency_key: str | None = None,
    ) -> TaskRecord:
        requester = self._require_agent_by_handle(requester_handle)
        recipient = self._require_agent_by_handle(recipient_handle)
        normalized_objective = normalize_required(objective, "objective")
        require_small_inline(normalized_objective, "objective")
        normalized_context_refs = tuple(normalize_required(ref, "context_ref") for ref in context_refs)
        normalized_allowed_tool_names = tuple(
            normalize_required(tool_name, "allowed_tool_name")
            for tool_name in allowed_tool_names
        )
        normalized_allowed_use_terms = tuple(
            normalize_required(term, "allowed_use_term")
            for term in allowed_use_terms
        )

        if idempotency_key:
            normalized_idempotency_key = normalize_required(idempotency_key, "idempotency_key")
            existing_task_id = self._repository.get_idempotent_task_id(
                requester.agent_id,
                normalized_idempotency_key,
            )
            if existing_task_id is not None:
                existing_task = self._repository.get_task(existing_task_id)
                if existing_task is not None:
                    return existing_task
        else:
            normalized_idempotency_key = None

        safety_decision = self._safety_evaluator.evaluate_send(
            SafetyCheckRequest(
                sender=requester,
                recipients=(recipient,),
                content=None,
                content_ref=None,
                intent="task_request",
                visibility="direct",
                thread_id=thread_id,
            )
        )
        require_deliverable(safety_decision)

        task_id = self._new_id("task")
        notification = self.send_message(
            sender_handle=requester.handle,
            recipient_handles=(recipient.handle,),
            refs=(task_ref(task_id, "task request"),),
            intent="task_request",
            visibility="direct",
            thread_id=thread_id,
        )

        now = self._clock()
        task = TaskRecord(
            task_id=task_id,
            thread_id=notification.thread.thread_id,
            requester_agent_id=requester.agent_id,
            recipient_agent_id=recipient.agent_id,
            objective=normalized_objective,
            request_message_id=notification.message.message_id,
            context_refs=normalized_context_refs,
            context_pack_id=normalized_optional_string(context_pack_id),
            context_pack_ref=normalized_optional_string(context_pack_ref),
            input_ref=normalized_optional_string(input_ref),
            stream_id=normalized_optional_string(stream_id),
            allowed_tool_names=normalized_allowed_tool_names,
            allowed_use_terms=normalized_allowed_use_terms,
            state=TaskState.REQUESTED,
            policy_decision_id=safety_decision.decision_id,
            created_at=now,
            updated_at=now,
        )
        self._repository.put_task(task)
        if normalized_idempotency_key is not None:
            self._repository.put_task_idempotency_key(
                requester.agent_id,
                normalized_idempotency_key,
                task.task_id,
            )
        return task

    def get_task(self, task_id: str) -> TaskRecord:
        return self._require_task(task_id)

    def list_thread_tasks(self, thread_id: str, *, limit: int = 50) -> tuple[TaskRecord, ...]:
        if self._repository.get_thread(thread_id) is None:
            raise NotFoundError(f"thread not found: {thread_id}")
        normalized_limit = require_bounded_int(limit, "limit", minimum=1, maximum=100)
        return self._repository.list_tasks_by_thread(thread_id, limit=normalized_limit)

    def grant_task_credits(
        self,
        *,
        agent_handle: str,
        amount: int,
        reason: str,
        policy_decision_id: str | None = None,
        limits_ref: str | None = None,
        abuse_policy_ref: str | None = None,
        audit_refs: Sequence[str] = (),
    ) -> TaskCreditLedgerEntry:
        agent = self._require_agent_by_handle(agent_handle)
        normalized_amount = require_bounded_int(
            amount,
            "amount",
            minimum=0,
            maximum=MAX_TASK_CREDIT_QUOTE,
        )
        normalized_reason = normalize_required(reason, "reason")
        require_small_inline(normalized_reason, "reason")
        return self._append_task_credit_ledger_entry(
            account_agent_id=agent.agent_id,
            entry_type=TaskCreditLedgerEntryType.CREDIT_GRANT,
            credit_amount=normalized_amount,
            available_delta=normalized_amount,
            reason=normalized_reason,
            policy_decision_id=policy_decision_id,
            limits_ref=limits_ref,
            abuse_policy_ref=abuse_policy_ref,
            audit_refs=audit_refs,
        )

    def get_task_credit_balance(self, agent_handle: str) -> TaskCreditBalance:
        agent = self._require_agent_by_handle(agent_handle)
        return self._task_credit_balance_for_agent_id(agent.agent_id)

    def list_task_credit_ledger_for_agent(
        self,
        agent_handle: str,
    ) -> tuple[TaskCreditLedgerEntry, ...]:
        agent = self._require_agent_by_handle(agent_handle)
        return self._repository.list_task_credit_ledger_entries_by_agent(agent.agent_id)

    def list_task_credit_ledger_for_task(self, task_id: str) -> tuple[TaskCreditLedgerEntry, ...]:
        task = self._require_task(task_id)
        return self._repository.list_task_credit_ledger_entries_by_task(task.task_id)

    def get_task_worker_reputation(self, worker_handle: str) -> TaskWorkerReputationSummary:
        worker = self._require_agent_by_handle(worker_handle)
        return self._task_worker_reputation_summary_for_agent_id(worker.agent_id)

    def list_task_worker_reputation_events(
        self,
        worker_handle: str,
    ) -> tuple[TaskWorkerReputationEventRecord, ...]:
        worker = self._require_agent_by_handle(worker_handle)
        return self._repository.list_task_worker_reputation_events_by_worker(worker.agent_id)

    def report_task_worker_abuse(
        self,
        task_id: str,
        *,
        reporter_handle: str,
        reason: str,
        policy_decision_id: str | None = None,
        abuse_policy_ref: str | None = None,
        audit_refs: Sequence[str] = (),
    ) -> TaskWorkerReputationEventRecord:
        task = self._require_task(task_id)
        reporter = self._require_task_actor(task, reporter_handle)
        if reporter.agent_id == task.recipient_agent_id:
            raise ForbiddenDeliveryError("worker cannot report itself for abuse")
        for event in self._repository.list_task_worker_reputation_events_by_task(task.task_id):
            if (
                event.event_type == TaskWorkerReputationEventType.ABUSE_REPORTED
                and event.reporter_agent_id == reporter.agent_id
            ):
                raise InvalidMessageError("abuse report already exists for this reporter and task")
        normalized_reason = normalize_required(reason, "reason")
        require_small_inline(normalized_reason, "reason")
        return self._record_task_worker_reputation_event(
            task=task,
            event_type=TaskWorkerReputationEventType.ABUSE_REPORTED,
            reporter_agent_id=reporter.agent_id,
            reason=normalized_reason,
            policy_decision_id=policy_decision_id,
            abuse_policy_ref=(
                normalized_optional_string(abuse_policy_ref)
                or "seagull://policies/task-credits/abuse-controls"
            ),
            audit_refs=audit_refs,
        )

    def define_task_capacity_policy(
        self,
        task_id: str,
        *,
        actor_handle: str,
        requester_capacity_tier: str = TaskCapacityTier.LOW.value,
        worker_capacity_tier: str = TaskCapacityTier.HIGH.value,
        max_credit_cost: int,
        max_auto_escrow_credits: int = 0,
        allow_private_context: bool = False,
        private_context_requires_approval: bool = True,
        paid_work_requires_approval: bool = True,
        high_cost_requires_approval: bool = True,
        limits_ref: str | None = None,
        abuse_policy_ref: str | None = None,
        policy_decision_id: str | None = None,
        audit_refs: Sequence[str] = (),
    ) -> TaskCapacitySharingPolicyRecord:
        task = self._require_task(task_id)
        actor = self._require_agent_by_handle(actor_handle)
        if actor.agent_id != task.requester_agent_id:
            raise ForbiddenDeliveryError("only the task requester can define capacity sharing policy")
        for field_name, value in (
            ("allow_private_context", allow_private_context),
            ("private_context_requires_approval", private_context_requires_approval),
            ("paid_work_requires_approval", paid_work_requires_approval),
            ("high_cost_requires_approval", high_cost_requires_approval),
        ):
            if not isinstance(value, bool):
                raise InvalidMessageError(f"{field_name} must be a boolean")
        normalized_max_credit_cost = require_bounded_int(
            max_credit_cost,
            "max_credit_cost",
            minimum=0,
            maximum=MAX_TASK_CREDIT_QUOTE,
        )
        normalized_max_auto_escrow_credits = require_bounded_int(
            max_auto_escrow_credits,
            "max_auto_escrow_credits",
            minimum=0,
            maximum=MAX_TASK_CREDIT_QUOTE,
        )
        if normalized_max_auto_escrow_credits > normalized_max_credit_cost:
            raise InvalidMessageError("max_auto_escrow_credits cannot exceed max_credit_cost")

        policy_id = self._new_id("capacity_policy")
        normalized_audit_refs = tuple(
            normalize_required(ref, "audit_ref")
            for ref in audit_refs
        ) or (f"seagull://tasks/{task.task_id}/capacity-policies/{policy_id}/audit",)
        now = self._clock()
        policy = TaskCapacitySharingPolicyRecord(
            policy_id=policy_id,
            task_id=task.task_id,
            thread_id=task.thread_id,
            requester_agent_id=task.requester_agent_id,
            worker_agent_id=task.recipient_agent_id,
            requester_role=TaskCapacityRole.REQUESTER,
            worker_role=TaskCapacityRole.WORKER,
            requester_capacity_tier=normalize_task_capacity_tier(requester_capacity_tier),
            worker_capacity_tier=normalize_task_capacity_tier(worker_capacity_tier),
            max_credit_cost=normalized_max_credit_cost,
            max_auto_escrow_credits=normalized_max_auto_escrow_credits,
            allow_private_context=allow_private_context,
            private_context_requires_approval=private_context_requires_approval,
            paid_work_requires_approval=paid_work_requires_approval,
            high_cost_requires_approval=high_cost_requires_approval,
            limits_ref=normalized_optional_string(limits_ref) or f"seagull://tasks/{task.task_id}/capacity-limits",
            abuse_policy_ref=(
                normalized_optional_string(abuse_policy_ref)
                or "seagull://policies/task-credits/abuse-controls"
            ),
            policy_decision_id=normalized_optional_string(policy_decision_id),
            audit_refs=normalized_audit_refs,
            created_at=now,
        )
        self._repository.put_task_capacity_policy(policy)
        self._repository.update_task(
            replace(
                task,
                capacity_policy_ids=(*task.capacity_policy_ids, policy.policy_id),
                updated_at=now,
            )
        )
        return policy

    def list_task_capacity_policies(self, task_id: str) -> tuple[TaskCapacitySharingPolicyRecord, ...]:
        task = self._require_task(task_id)
        return self._repository.list_task_capacity_policies_by_task(task.task_id)

    def create_task_quote(
        self,
        task_id: str,
        *,
        worker_handle: str,
        expected_credit_cost: int,
        task_reason: str,
        shared_context_refs: Sequence[str] = (),
        requires_approval: bool = True,
        approval_reason: str | None = None,
        limits_ref: str | None = None,
        abuse_policy_ref: str | None = None,
        policy_decision_id: str | None = None,
    ) -> TaskQuoteRecord:
        task = self._require_task(task_id)
        worker = self._require_agent_by_handle(worker_handle)
        if worker.agent_id != task.recipient_agent_id:
            raise ForbiddenDeliveryError("only the task recipient can quote this task")
        if not isinstance(requires_approval, bool):
            raise InvalidMessageError("requires_approval must be a boolean")

        quote_id = self._new_id("task_quote")
        normalized_cost = require_bounded_int(
            expected_credit_cost,
            "expected_credit_cost",
            minimum=0,
            maximum=MAX_TASK_CREDIT_QUOTE,
        )
        normalized_reason = normalize_required(task_reason, "task_reason")
        require_small_inline(normalized_reason, "task_reason")
        normalized_approval_reason = normalized_optional_string(approval_reason)
        if normalized_approval_reason is not None:
            require_small_inline(normalized_approval_reason, "approval_reason")
        normalized_shared_context_refs = tuple(
            normalize_required(ref, "shared_context_ref")
            for ref in shared_context_refs
        ) or task_shared_context_refs(task)
        policy = self._latest_task_capacity_policy(task)
        requires_approval, policy_approval_reason = self._apply_task_capacity_policy_to_quote(
            policy=policy,
            expected_credit_cost=normalized_cost,
            shared_context_refs=normalized_shared_context_refs,
            requires_approval=requires_approval,
        )
        if normalized_approval_reason is None:
            normalized_approval_reason = policy_approval_reason
        normalized_limits_ref = normalized_optional_string(limits_ref)
        if normalized_limits_ref is None:
            normalized_limits_ref = (
                policy.limits_ref
                if policy is not None
                else f"seagull://tasks/{task.task_id}/limits"
            )
        normalized_abuse_policy_ref = normalized_optional_string(abuse_policy_ref)
        if normalized_abuse_policy_ref is None:
            normalized_abuse_policy_ref = (
                policy.abuse_policy_ref
                if policy is not None
                else "seagull://policies/task-credits/abuse-controls"
            )
        normalized_policy_decision_id = normalized_optional_string(policy_decision_id)
        if normalized_policy_decision_id is None and policy is not None:
            normalized_policy_decision_id = policy.policy_decision_id
        audit_ref = f"seagull://tasks/{task.task_id}/quotes/{quote_id}/audit"

        now = self._clock()
        quote = TaskQuoteRecord(
            quote_id=quote_id,
            task_id=task.task_id,
            thread_id=task.thread_id,
            requester_agent_id=task.requester_agent_id,
            worker_agent_id=worker.agent_id,
            task_reason=normalized_reason,
            expected_credit_cost=normalized_cost,
            shared_context_refs=normalized_shared_context_refs,
            requires_approval=requires_approval,
            approval_reason=normalized_approval_reason,
            policy_decision_id=normalized_policy_decision_id,
            limits_ref=normalized_limits_ref,
            abuse_policy_ref=normalized_abuse_policy_ref,
            audit_refs=(audit_ref,),
            created_at=now,
            updated_at=now,
        )
        self._repository.put_task_quote(quote)
        updated_task = replace(
            task,
            quote_ids=(*task.quote_ids, quote.quote_id),
            state=TaskState.QUOTED,
            updated_at=now,
        )
        self._repository.update_task(updated_task)
        self._send_task_notification(
            task=updated_task,
            sender=worker,
            recipient_agent_id=task.requester_agent_id,
            intent="task_quote",
            label="task quote",
            note=f"{normalized_cost} credits: {normalized_reason}",
            ref=MessageRef(
                type="task_quote",
                url=f"seagull://tasks/{task.task_id}/quotes/{quote.quote_id}",
                remember_as="task quote",
            ),
        )
        return quote

    def approve_task_quote(
        self,
        quote_id: str,
        *,
        approver_handle: str,
        approval_id: str | None = None,
        policy_decision_id: str | None = None,
        note: str | None = None,
    ) -> TaskQuoteRecord:
        quote = self._require_task_quote(quote_id)
        task = self._require_task(quote.task_id)
        approver = self._require_agent_by_handle(approver_handle)
        if approver.agent_id != task.requester_agent_id:
            raise ForbiddenDeliveryError("only the task requester can approve this quote")

        now = self._clock()
        normalized_approval_id = normalized_optional_string(approval_id) or self._new_id("approval")
        updated_quote = replace(
            quote,
            approved_by_agent_id=approver.agent_id,
            approval_id=normalized_approval_id,
            policy_decision_id=normalized_optional_string(policy_decision_id) or quote.policy_decision_id,
            updated_at=now,
        )
        self._repository.update_task_quote(updated_quote)
        updated_task = replace(task, state=TaskState.APPROVED, updated_at=now)
        self._repository.update_task(updated_task)
        self._send_task_notification(
            task=updated_task,
            sender=approver,
            recipient_agent_id=quote.worker_agent_id,
            intent="task_quote_approved",
            label="task quote approved",
            note=note,
            ref=MessageRef(
                type="task_quote",
                url=f"seagull://tasks/{task.task_id}/quotes/{quote.quote_id}",
                remember_as="approved task quote",
            ),
        )
        return updated_quote

    def create_task_escrow(
        self,
        task_id: str,
        *,
        requester_handle: str,
        quote_id: str,
        approval_id: str | None = None,
        policy_decision_id: str | None = None,
        limits_ref: str | None = None,
        abuse_policy_ref: str | None = None,
        audit_refs: Sequence[str] = (),
    ) -> TaskEscrowRecord:
        task = self._require_task(task_id)
        requester = self._require_agent_by_handle(requester_handle)
        if requester.agent_id != task.requester_agent_id:
            raise ForbiddenDeliveryError("only the task requester can escrow credits")

        quote = self._require_task_quote(quote_id)
        if quote.task_id != task.task_id:
            raise InvalidMessageError("quote is not scoped to this task")
        if quote.requires_approval and quote.approved_by_agent_id is None:
            raise InvalidMessageError("quote must be approved before escrow")
        if quote.requires_approval and quote.approval_id is None and approval_id is None:
            raise InvalidMessageError("approved quote requires an approval_id before escrow")
        for existing in self._repository.list_task_escrows_by_task(task.task_id):
            if existing.quote_id == quote.quote_id and existing.state in {TaskState.ESCROWED, TaskState.RELEASED}:
                raise InvalidMessageError("escrow already exists for this quote")
        balance = self._task_credit_balance_for_agent_id(requester.agent_id)
        if balance.available_balance < quote.expected_credit_cost:
            raise ForbiddenDeliveryError("insufficient task credit balance")

        escrow_id = self._new_id("task_escrow")
        normalized_audit_refs = tuple(
            normalize_required(ref, "audit_ref")
            for ref in audit_refs
        ) or (f"seagull://tasks/{task.task_id}/escrows/{escrow_id}/audit",)
        now = self._clock()
        escrow = TaskEscrowRecord(
            escrow_id=escrow_id,
            task_id=task.task_id,
            quote_id=quote.quote_id,
            thread_id=task.thread_id,
            requester_agent_id=task.requester_agent_id,
            worker_agent_id=quote.worker_agent_id,
            credit_amount=quote.expected_credit_cost,
            state=TaskState.ESCROWED,
            approval_id=normalized_optional_string(approval_id) or quote.approval_id,
            policy_decision_id=normalized_optional_string(policy_decision_id) or quote.policy_decision_id,
            limits_ref=normalized_optional_string(limits_ref) or quote.limits_ref,
            abuse_policy_ref=normalized_optional_string(abuse_policy_ref) or quote.abuse_policy_ref,
            audit_refs=normalized_audit_refs,
            created_at=now,
            updated_at=now,
        )
        self._repository.put_task_escrow(escrow)
        updated_task = replace(
            task,
            escrow_ids=(*task.escrow_ids, escrow.escrow_id),
            state=TaskState.ESCROWED,
            updated_at=now,
        )
        self._repository.update_task(updated_task)
        self._append_task_credit_ledger_entry(
            account_agent_id=requester.agent_id,
            entry_type=TaskCreditLedgerEntryType.ESCROW_HOLD,
            credit_amount=escrow.credit_amount,
            available_delta=-escrow.credit_amount,
            escrow_delta=escrow.credit_amount,
            task=updated_task,
            quote=quote,
            escrow=escrow,
            counterparty_agent_id=quote.worker_agent_id,
            reason="Escrowed task credits.",
            policy_decision_id=escrow.policy_decision_id,
            limits_ref=escrow.limits_ref,
            abuse_policy_ref=escrow.abuse_policy_ref,
            audit_refs=escrow.audit_refs,
        )
        self._send_task_notification(
            task=updated_task,
            sender=requester,
            recipient_agent_id=quote.worker_agent_id,
            intent="task_escrow",
            label="task escrow",
            ref=MessageRef(
                type="task_escrow",
                url=f"seagull://tasks/{task.task_id}/escrows/{escrow.escrow_id}",
                remember_as="task escrow",
            ),
        )
        return escrow

    def release_task_escrow(
        self,
        escrow_id: str,
        *,
        releaser_handle: str,
        note: str | None = None,
    ) -> TaskEscrowRecord:
        escrow = self._require_task_escrow(escrow_id)
        task = self._require_task(escrow.task_id)
        releaser = self._require_agent_by_handle(releaser_handle)
        if releaser.agent_id != task.requester_agent_id:
            raise ForbiddenDeliveryError("only the task requester can release escrow")
        if escrow.state not in {TaskState.ESCROWED, TaskState.DISPUTED}:
            raise InvalidMessageError("only escrowed or disputed credits can be released")
        if task.state not in {TaskState.RESULT_ACCEPTED, TaskState.DISPUTED}:
            raise InvalidMessageError("task result must be accepted or disputed before releasing escrow")

        now = self._clock()
        released = replace(
            escrow,
            state=TaskState.RELEASED,
            released_at=now,
            updated_at=now,
        )
        self._repository.update_task_escrow(released)
        updated_task = replace(task, state=TaskState.RELEASED, updated_at=now)
        self._repository.update_task(updated_task)
        self._append_task_credit_ledger_entry(
            account_agent_id=escrow.requester_agent_id,
            entry_type=TaskCreditLedgerEntryType.ESCROW_RELEASE,
            credit_amount=escrow.credit_amount,
            available_delta=0,
            escrow_delta=-escrow.credit_amount,
            task=updated_task,
            escrow=released,
            counterparty_agent_id=escrow.worker_agent_id,
            reason="Released escrowed task credits.",
            policy_decision_id=escrow.policy_decision_id,
            limits_ref=escrow.limits_ref,
            abuse_policy_ref=escrow.abuse_policy_ref,
            audit_refs=escrow.audit_refs,
        )
        self._append_task_credit_ledger_entry(
            account_agent_id=escrow.worker_agent_id,
            entry_type=TaskCreditLedgerEntryType.ESCROW_RELEASE,
            credit_amount=escrow.credit_amount,
            available_delta=escrow.credit_amount,
            task=updated_task,
            escrow=released,
            counterparty_agent_id=escrow.requester_agent_id,
            reason="Received released task credits.",
            policy_decision_id=escrow.policy_decision_id,
            limits_ref=escrow.limits_ref,
            abuse_policy_ref=escrow.abuse_policy_ref,
            audit_refs=escrow.audit_refs,
        )
        self._record_task_worker_reputation_event_once(
            task=updated_task,
            event_type=TaskWorkerReputationEventType.TASK_COMPLETED,
            reporter_agent_id=releaser.agent_id,
            reason=note,
            policy_decision_id=escrow.policy_decision_id,
            limits_ref=escrow.limits_ref,
            abuse_policy_ref=escrow.abuse_policy_ref,
        )
        self._send_task_notification(
            task=updated_task,
            sender=releaser,
            recipient_agent_id=escrow.worker_agent_id,
            intent="task_escrow_released",
            label="task escrow released",
            note=note,
            ref=MessageRef(
                type="task_escrow",
                url=f"seagull://tasks/{task.task_id}/escrows/{escrow.escrow_id}",
                remember_as="released task escrow",
            ),
        )
        return released

    def cancel_task_escrow(
        self,
        escrow_id: str,
        *,
        actor_handle: str,
        note: str | None = None,
    ) -> TaskEscrowRecord:
        escrow = self._require_task_escrow(escrow_id)
        task = self._require_task(escrow.task_id)
        actor = self._require_agent_by_handle(actor_handle)
        if actor.agent_id != task.requester_agent_id:
            raise ForbiddenDeliveryError("only the task requester can cancel escrow")
        if escrow.state not in {TaskState.ESCROWED, TaskState.DISPUTED}:
            raise InvalidMessageError("only escrowed or disputed credits can be canceled")

        now = self._clock()
        canceled = replace(escrow, state=TaskState.CANCELED, updated_at=now)
        self._repository.update_task_escrow(canceled)
        updated_task = replace(task, state=TaskState.CANCELED, updated_at=now)
        self._repository.update_task(updated_task)
        self._append_task_credit_ledger_entry(
            account_agent_id=escrow.requester_agent_id,
            entry_type=TaskCreditLedgerEntryType.ESCROW_CANCEL,
            credit_amount=escrow.credit_amount,
            available_delta=escrow.credit_amount,
            escrow_delta=-escrow.credit_amount,
            task=updated_task,
            escrow=canceled,
            counterparty_agent_id=escrow.worker_agent_id,
            reason="Canceled escrowed task credits.",
            policy_decision_id=escrow.policy_decision_id,
            limits_ref=escrow.limits_ref,
            abuse_policy_ref=escrow.abuse_policy_ref,
            audit_refs=escrow.audit_refs,
        )
        self._send_task_notification(
            task=updated_task,
            sender=actor,
            recipient_agent_id=escrow.worker_agent_id,
            intent="task_escrow_canceled",
            label="task escrow canceled",
            note=note,
            ref=MessageRef(
                type="task_escrow",
                url=f"seagull://tasks/{task.task_id}/escrows/{escrow.escrow_id}",
                remember_as="canceled task escrow",
            ),
        )
        return canceled

    def dispute_task_escrow(
        self,
        escrow_id: str,
        *,
        actor_handle: str,
        reason: str,
    ) -> TaskEscrowRecord:
        escrow = self._require_task_escrow(escrow_id)
        task = self._require_task(escrow.task_id)
        actor = self._require_task_actor(task, actor_handle)
        if escrow.state != TaskState.ESCROWED:
            raise InvalidMessageError("only escrowed credits can be disputed")
        normalized_reason = normalize_required(reason, "reason")
        require_small_inline(normalized_reason, "reason")
        counterparty_agent_id = (
            escrow.worker_agent_id
            if actor.agent_id == escrow.requester_agent_id
            else escrow.requester_agent_id
        )

        now = self._clock()
        disputed = replace(escrow, state=TaskState.DISPUTED, updated_at=now)
        self._repository.update_task_escrow(disputed)
        updated_task = replace(task, state=TaskState.DISPUTED, updated_at=now)
        self._repository.update_task(updated_task)
        self._append_task_credit_ledger_entry(
            account_agent_id=actor.agent_id,
            entry_type=TaskCreditLedgerEntryType.DISPUTE_OPEN,
            credit_amount=escrow.credit_amount,
            available_delta=0,
            task=updated_task,
            escrow=disputed,
            counterparty_agent_id=counterparty_agent_id,
            reason=normalized_reason,
            policy_decision_id=escrow.policy_decision_id,
            limits_ref=escrow.limits_ref,
            abuse_policy_ref=escrow.abuse_policy_ref,
            audit_refs=escrow.audit_refs,
        )
        self._record_task_worker_reputation_event_once(
            task=updated_task,
            event_type=TaskWorkerReputationEventType.DISPUTE_OPENED,
            reporter_agent_id=actor.agent_id,
            reason=normalized_reason,
            policy_decision_id=escrow.policy_decision_id,
            limits_ref=escrow.limits_ref,
            abuse_policy_ref=escrow.abuse_policy_ref,
        )
        self._send_task_notification(
            task=updated_task,
            sender=actor,
            recipient_agent_id=counterparty_agent_id,
            intent="task_escrow_disputed",
            label="task escrow disputed",
            note=normalized_reason,
            ref=MessageRef(
                type="task_escrow",
                url=f"seagull://tasks/{task.task_id}/escrows/{escrow.escrow_id}",
                remember_as="disputed task escrow",
            ),
        )
        return disputed

    def create_tool_grant(
        self,
        task_id: str,
        *,
        issuer_handle: str,
        subject_handle: str,
        audience: str,
        scopes: Sequence[str],
        purpose: str,
        ttl_expires_at: datetime | None = None,
        max_calls: int | None = None,
        budget_ref: str | None = None,
        allowed_resource_selectors: Sequence[str] = (),
        read_only: bool = True,
        approval_id: str | None = None,
        policy_decision_id: str | None = None,
    ) -> ToolGrant:
        task = self._require_task(task_id)
        issuer = self._require_agent_by_handle(issuer_handle)
        subject = self._require_agent_by_handle(subject_handle)
        if issuer.agent_id != task.requester_agent_id:
            raise ForbiddenDeliveryError("only the task requester can issue a tool grant")
        if subject.agent_id != task.recipient_agent_id:
            raise ForbiddenDeliveryError("tool grant subject must be the task recipient")

        normalized_scopes = normalize_non_empty_strings(scopes, "scope")
        now = self._clock()
        grant = ToolGrant(
            grant_id=self._new_id("tool_grant"),
            task_id=task.task_id,
            thread_id=task.thread_id,
            issuer_agent_id=issuer.agent_id,
            subject_agent_id=subject.agent_id,
            audience=normalize_required(audience, "audience"),
            scopes=normalized_scopes,
            purpose=normalize_required(purpose, "purpose"),
            ttl_expires_at=normalize_payload_ttl_expires_at(ttl_expires_at),
            max_calls=normalize_optional_non_negative_int(max_calls, "max_calls"),
            budget_ref=normalized_optional_string(budget_ref),
            allowed_resource_selectors=tuple(
                normalize_required(selector, "allowed_resource_selector")
                for selector in allowed_resource_selectors
            ),
            read_only=read_only,
            approval_id=normalized_optional_string(approval_id),
            policy_decision_id=normalized_optional_string(policy_decision_id),
            created_at=now,
            updated_at=now,
        )
        self._repository.put_tool_grant(grant)
        self._repository.update_task(
            replace(
                task,
                tool_grant_ids=(*task.tool_grant_ids, grant.grant_id),
                updated_at=now,
            )
        )
        return grant

    def get_tool_grant(self, grant_id: str) -> ToolGrant:
        return self._require_tool_grant(grant_id)

    def list_task_tool_grants(self, task_id: str) -> tuple[ToolGrant, ...]:
        task = self._require_task(task_id)
        return self._repository.list_tool_grants_by_task(task.task_id)

    def accept_task(
        self,
        task_id: str,
        *,
        worker_handle: str,
        note: str | None = None,
    ) -> TaskRecord:
        task = self._require_task(task_id)
        worker = self._require_agent_by_handle(worker_handle)
        if worker.agent_id != task.recipient_agent_id:
            raise ForbiddenDeliveryError("only the recipient agent can accept this task")

        now = self._clock()
        updated = replace(
            task,
            state=TaskState.ACCEPTED,
            accepted_by_agent_id=worker.agent_id,
            updated_at=now,
        )
        self._repository.update_task(updated)
        self._send_task_notification(
            task=updated,
            sender=worker,
            recipient_agent_id=task.requester_agent_id,
            intent="status_update",
            label="task accepted",
            note=note,
        )
        return updated

    def update_task_state(
        self,
        task_id: str,
        *,
        actor_handle: str,
        state: str,
        note: str | None = None,
    ) -> TaskRecord:
        task = self._require_task(task_id)
        actor = self._require_task_actor(task, actor_handle)
        task_state = normalize_task_state(state)
        now = self._clock()
        updated = replace(task, state=task_state, updated_at=now)
        self._repository.update_task(updated)
        if task_state == TaskState.RESULT_ACCEPTED:
            self._record_task_worker_reputation_event_once(
                task=updated,
                event_type=TaskWorkerReputationEventType.RESULT_ACCEPTED,
                reporter_agent_id=actor.agent_id,
                reason=note,
            )
        elif task_state == TaskState.COMPLETED:
            self._record_task_worker_reputation_event_once(
                task=updated,
                event_type=TaskWorkerReputationEventType.TASK_COMPLETED,
                reporter_agent_id=actor.agent_id,
                reason=note,
            )
        elif task_state == TaskState.FAILED:
            self._record_task_worker_reputation_event_once(
                task=updated,
                event_type=TaskWorkerReputationEventType.TASK_FAILED,
                reporter_agent_id=actor.agent_id,
                reason=note,
            )
        recipient_agent_id = (
            task.requester_agent_id
            if actor.agent_id != task.requester_agent_id
            else task.recipient_agent_id
        )
        self._send_task_notification(
            task=updated,
            sender=actor,
            recipient_agent_id=recipient_agent_id,
            intent="status_update",
            label=f"task {task_state.value}",
            note=note,
        )
        return updated

    def return_task_result(
        self,
        task_id: str,
        *,
        responder_handle: str,
        state: str = TaskState.COMPLETED.value,
        content: str | None = None,
        content_ref: str | None = None,
        artifact_refs: Sequence[str] = (),
        tool_use_summary_refs: Sequence[str] = (),
        stream_id: str | None = None,
        error: str | None = None,
    ) -> TaskResultRecord:
        task = self._require_task(task_id)
        responder = self._require_task_actor(task, responder_handle)
        if responder.agent_id == task.requester_agent_id:
            raise ForbiddenDeliveryError("requester cannot return its own task result")

        task_state = normalize_task_state(state)
        normalized_artifact_refs = tuple(normalize_required(ref, "artifact_ref") for ref in artifact_refs)
        normalized_tool_use_summary_refs = tuple(
            normalize_required(ref, "tool_use_summary_ref")
            for ref in tool_use_summary_refs
        )
        stored_content, stored_content_ref = envelope_content_for_storage(
            content,
            content_ref,
            "task result content",
        )
        normalized_stream_id = normalized_optional_string(stream_id) or task.stream_id
        if task.stream_id is not None and normalized_stream_id != task.stream_id:
            raise InvalidMessageError("task result stream_id must match task stream_id")
        if (
            stored_content is None
            and stored_content_ref is None
            and not normalized_artifact_refs
            and error is None
        ):
            raise InvalidMessageError("task result requires content, content_ref, artifact_refs, or error")

        result_id = self._new_id("task_result")
        result_ref = f"seagull://tasks/{task.task_id}/results/{result_id}"
        notification = self.send_message(
            sender_handle=responder.handle,
            recipient_handles=(self._require_agent(task.requester_agent_id).handle,),
            content_ref=stored_content_ref,
            refs=(MessageRef(type="task_result", url=result_ref, remember_as="task result"),),
            intent="task_result",
            visibility="direct",
            thread_id=task.thread_id,
        )

        now = self._clock()
        result = TaskResultRecord(
            result_id=result_id,
            task_id=task.task_id,
            thread_id=task.thread_id,
            responder_agent_id=responder.agent_id,
            state=task_state,
            result_message_id=notification.message.message_id,
            stream_id=normalized_stream_id,
            content_inline=stored_content,
            content_ref=stored_content_ref,
            artifact_refs=normalized_artifact_refs,
            tool_use_summary_refs=normalized_tool_use_summary_refs,
            error=normalized_optional_string(error),
            created_at=now,
        )
        self._repository.put_task_result(result)
        updated_task = replace(
            task,
            state=task_state,
            result_message_id=notification.message.message_id,
            result_ref=result_ref,
            stream_id=task.stream_id or normalized_stream_id,
            artifact_refs=tuple(dict.fromkeys((*task.artifact_refs, *normalized_artifact_refs))),
            updated_at=now,
        )
        self._repository.update_task(updated_task)
        if task_state == TaskState.FAILED:
            self._record_task_worker_reputation_event_once(
                task=updated_task,
                event_type=TaskWorkerReputationEventType.TASK_FAILED,
                reporter_agent_id=responder.agent_id,
                reason=error,
            )
        elif task_state == TaskState.COMPLETED:
            self._record_task_worker_reputation_event_once(
                task=updated_task,
                event_type=TaskWorkerReputationEventType.TASK_COMPLETED,
                reporter_agent_id=responder.agent_id,
            )
        elif task_state == TaskState.RESULT_ACCEPTED:
            self._record_task_worker_reputation_event_once(
                task=updated_task,
                event_type=TaskWorkerReputationEventType.RESULT_ACCEPTED,
                reporter_agent_id=responder.agent_id,
            )
        return result

    def create_tool_request(
        self,
        task_id: str,
        *,
        requester_handle: str,
        worker_handle: str,
        tool_name: str,
        purpose: str,
        input_ref: str | None = None,
        requires_approval: bool = True,
        approval_id: str | None = None,
        policy_decision_id: str | None = None,
        tool_grant_id: str | None = None,
    ) -> TaskToolRequest:
        task = self._require_task(task_id)
        requester = self._require_agent_by_handle(requester_handle)
        worker = self._require_agent_by_handle(worker_handle)
        if requester.agent_id != task.requester_agent_id:
            raise ForbiddenDeliveryError("only the task requester can request delegated tool use")
        if worker.agent_id != task.recipient_agent_id:
            raise ForbiddenDeliveryError("tool request worker must be the task recipient")
        normalized_tool_name = normalize_required(tool_name, "tool_name")
        normalized_purpose = normalize_required(purpose, "purpose")
        if task.allowed_tool_names and normalized_tool_name not in task.allowed_tool_names:
            raise InvalidMessageError("tool_name is not allowed for this task")
        normalized_tool_grant_id = normalized_optional_string(tool_grant_id)
        if not requires_approval and normalized_tool_grant_id is None:
            raise InvalidMessageError("tool_grant_id is required when requires_approval is false")
        if normalized_tool_grant_id is not None:
            self._consume_tool_grant_for_request(
                task=task,
                requester=requester,
                worker=worker,
                tool_name=normalized_tool_name,
                grant_id=normalized_tool_grant_id,
            )

        now = self._clock()
        tool_request = TaskToolRequest(
            tool_request_id=self._new_id("tool_request"),
            task_id=task.task_id,
            thread_id=task.thread_id,
            requester_agent_id=requester.agent_id,
            worker_agent_id=worker.agent_id,
            tool_name=normalized_tool_name,
            purpose=normalized_purpose,
            input_ref=normalized_optional_string(input_ref),
            requires_approval=requires_approval,
            status=TaskState.NEEDS_APPROVAL if requires_approval else TaskState.REQUESTED,
            approval_id=normalized_optional_string(approval_id),
            policy_decision_id=normalized_optional_string(policy_decision_id),
            tool_grant_id=normalized_tool_grant_id,
            created_at=now,
            updated_at=now,
        )
        self._repository.put_tool_request(tool_request)
        self._repository.update_task(
            replace(
                task,
                tool_request_ids=(*task.tool_request_ids, tool_request.tool_request_id),
                updated_at=now,
            )
        )
        self._send_task_notification(
            task=task,
            sender=requester,
            recipient_agent_id=worker.agent_id,
            intent="tool_request",
            label="tool request",
            ref=MessageRef(
                type="tool_request",
                url=f"seagull://tasks/{task.task_id}/tool-requests/{tool_request.tool_request_id}",
                remember_as="tool request",
            ),
        )
        return tool_request

    def complete_tool_request(
        self,
        tool_request_id: str,
        *,
        actor_handle: str,
        state: str,
        result_ref: str | None = None,
        artifact_refs: Sequence[str] = (),
        tool_use_summary_ref: str | None = None,
    ) -> TaskToolRequest:
        tool_request = self._require_tool_request(tool_request_id)
        actor = self._require_agent_by_handle(actor_handle)
        if actor.agent_id != tool_request.worker_agent_id:
            raise ForbiddenDeliveryError("only the worker agent can complete this tool request")
        tool_state = normalize_task_state(state)
        if tool_request.tool_grant_id is not None:
            self._require_tool_request_grant_active(tool_request)
        normalized_artifact_refs = tuple(normalize_required(ref, "artifact_ref") for ref in artifact_refs)
        now = self._clock()
        updated = replace(
            tool_request,
            status=tool_state,
            accepted_by_agent_id=(
                actor.agent_id
                if tool_state in {TaskState.ACCEPTED, TaskState.RUNNING, TaskState.RESULT_READY, TaskState.COMPLETED}
                else tool_request.accepted_by_agent_id
            ),
            result_ref=normalized_optional_string(result_ref),
            artifact_refs=normalized_artifact_refs,
            tool_use_summary_ref=normalized_optional_string(tool_use_summary_ref),
            updated_at=now,
        )
        self._repository.update_tool_request(updated)
        return updated

    def ack_message(
        self,
        message_id: str,
        *,
        recipient_handle: str | None = None,
    ) -> tuple[Delivery, ...]:
        deliveries = self._repository.list_deliveries_by_message(message_id)
        if recipient_handle is not None:
            recipient = self._require_agent_by_handle(recipient_handle)
            deliveries = tuple(
                delivery
                for delivery in deliveries
                if delivery.recipient_agent_id == recipient.agent_id
            )

        if not deliveries:
            raise NotFoundError(f"delivery not found for message: {message_id}")

        now = self._clock()
        updated_deliveries = tuple(
            replace(
                delivery,
                status=DeliveryStatus.ACKED,
                updated_at=now,
                acked_at=now,
            )
            for delivery in deliveries
        )

        for delivery in updated_deliveries:
            self._repository.update_delivery(delivery)

        return updated_deliveries

    def apply_hook_result(
        self,
        delivery_id: str,
        *,
        hook: str,
        runtime: str,
        actor: str | None = None,
        content: str | None = None,
        content_ref: str | None = None,
        refs: Sequence[MessageRef | dict[str, str | None]] = (),
        action: str = "continue",
        note: str | None = None,
    ) -> Delivery:
        delivery = self._require_delivery(delivery_id)
        normalized_hook = normalize_hook(hook)
        normalized_runtime = normalize_hook_runtime(runtime)
        normalized_action = normalize_hook_action(action)
        normalized_actor = actor.strip() if actor is not None and actor.strip() else None
        normalized_refs = tuple(normalize_message_ref(ref) for ref in refs)

        changed: list[str] = []
        current_content_inline = delivery.current_content_inline
        current_content_ref = delivery.current_content_ref
        delivery_refs = delivery.refs
        status = delivery.status
        last_error = delivery.last_error
        current_stage = next_stage_after_hook(normalized_hook, delivery.current_stage)

        if content is not None:
            current_content_inline, normalized_content_ref = envelope_content_for_storage(
                content,
                content_ref,
                "delivery content",
            )
            changed.append("current_content_inline")
            if normalized_content_ref is not None:
                current_content_ref = normalized_content_ref
                changed.append("current_content_ref")
        if content_ref is not None:
            normalized_content_ref = normalized_optional_string(content_ref)
            current_content_ref = normalized_content_ref
            if content is None:
                current_content_inline = None
                changed.append("current_content_inline")
            if "current_content_ref" not in changed:
                changed.append("current_content_ref")
        if normalized_refs:
            delivery_refs = (*delivery.refs, *normalized_refs)
            changed.append("refs")

        if normalized_action == "block":
            status = DeliveryStatus.FAILED
            last_error = note or "blocked by hook result"
            current_stage = "blocked"
        elif normalized_action == "review":
            status = DeliveryStatus.NEEDS_REVIEW
            current_stage = "human.review"
        elif normalized_action == "fail":
            status = DeliveryStatus.FAILED
            last_error = note or "hook result failed"
            current_stage = "failed"

        trace = WorkflowTraceEntry(
            hook=normalized_hook,
            runtime=normalized_runtime,
            action=normalized_action,
            actor=normalized_actor,
            changed=tuple(changed),
            note=note,
            created_at=self._clock(),
        )
        updated = replace(
            delivery,
            status=status,
            last_error=last_error,
            current_content_inline=current_content_inline,
            current_content_ref=current_content_ref,
            refs=delivery_refs,
            workflow_trace=(*delivery.workflow_trace, trace),
            current_stage=current_stage,
            updated_at=trace.created_at,
        )
        self._repository.update_delivery(updated)
        return updated

    def decide_delivery(
        self,
        delivery_id: str,
        *,
        agent_handle: str,
        decision: str,
        content: str | None = None,
        content_ref: str | None = None,
        refs: Sequence[MessageRef | dict[str, str | None]] = (),
        action_type: str | None = None,
        action_target: str | None = None,
        action_runtime: str = "cloud",
        requires_approval: bool = True,
        note: str | None = None,
    ) -> AgentDecisionResult:
        delivery = self._require_delivery_for_recipient(delivery_id, agent_handle)
        normalized_decision = normalize_agent_decision(decision)
        normalized_refs = tuple(normalize_message_ref(ref) for ref in refs)
        now = self._clock()
        trace = WorkflowTraceEntry(
            hook="agent.decision",
            runtime="agent_client",
            action=normalized_decision,
            actor=normalize_handle(agent_handle),
            note=note,
            created_at=now,
        )

        if normalized_decision == "reply":
            if content is None and content_ref is None and not normalized_refs:
                raise InvalidMessageError("reply decision requires content, content_ref, or refs")
            sender = self._repository.get_agent(delivery.sender_agent_id)
            if sender is None:
                raise NotFoundError(f"agent not found: {delivery.sender_agent_id}")

            reply = self.send_message(
                sender_handle=agent_handle,
                recipient_handles=[sender.handle],
                content=content,
                content_ref=content_ref,
                refs=normalized_refs,
                intent="reply",
                visibility="direct",
                thread_id=delivery.thread_id,
            )
            updated = replace(
                delivery,
                status=DeliveryStatus.REPLIED,
                workflow_trace=(*delivery.workflow_trace, trace),
                current_stage="done",
                updated_at=now,
                acked_at=now,
            )
            self._repository.update_delivery(updated)
            return AgentDecisionResult(delivery=updated, reply=reply)

        if normalized_decision == "action":
            normalized_action_type = normalize_required(action_type or "", "action_type")
            action_request = ActionRequest(
                action_request_id=self._new_id("action"),
                type=normalized_action_type,
                target=action_target,
                runtime=normalize_hook_runtime(action_runtime),
                requires_approval=requires_approval,
                created_at=now,
            )
            updated = replace(
                delivery,
                status=DeliveryStatus.PENDING_ACTION,
                workflow_trace=(*delivery.workflow_trace, trace),
                current_stage="action.before",
                action_request=action_request,
                updated_at=now,
            )
            self._repository.update_delivery(updated)
            return AgentDecisionResult(delivery=updated, action_request=action_request)

        status = DeliveryStatus.IGNORED if normalized_decision == "ignore" else DeliveryStatus.NEEDS_REVIEW
        updated = replace(
            delivery,
            status=status,
            workflow_trace=(*delivery.workflow_trace, trace),
            current_stage="done" if normalized_decision == "ignore" else "human.review",
            updated_at=now,
            acked_at=now if normalized_decision == "ignore" else delivery.acked_at,
        )
        self._repository.update_delivery(updated)
        return AgentDecisionResult(delivery=updated)

    def save_thread_summary(
        self,
        thread_id: str,
        summary_text: str,
        *,
        message_start_id: str | None = None,
        message_end_id: str | None = None,
        token_count_estimate: int | None = None,
        content_ref: str | None = None,
    ) -> ThreadSummary:
        if self._repository.get_thread(thread_id) is None:
            raise NotFoundError(f"thread not found: {thread_id}")

        summary = ThreadSummary(
            thread_id=thread_id,
            summary_id=self._new_id("summary"),
            summary_text=summary_text,
            message_start_id=message_start_id,
            message_end_id=message_end_id,
            token_count_estimate=token_count_estimate,
            content_ref=content_ref,
            created_at=self._clock(),
        )
        self._repository.put_thread_summary(summary)
        return summary

    def _apply_routing_rules(
        self,
        *,
        recipients: tuple[Agent, ...],
        content: str | None,
        content_ref: str | None,
        refs: tuple[MessageRef, ...],
    ) -> tuple[tuple[Agent, ...], tuple[WorkflowTraceEntry, ...], bool]:
        routed = list(recipients)
        trace: list[WorkflowTraceEntry] = []
        needs_review = False

        for rule in self._repository.list_routing_rules():
            if not rule.enabled or not routing_rule_matches(rule, content=content, content_ref=content_ref, refs=refs):
                continue

            if rule.mode == RoutingRuleMode.BLOCK:
                raise InvalidMessageError(f"message blocked by routing rule: {rule.name}")

            rule_recipients = self._resolve_recipients(rule.route_to_handles)
            if rule.mode in {RoutingRuleMode.DIRECT, RoutingRuleMode.HANDOFF}:
                routed = list(rule_recipients)
            elif rule.mode in {RoutingRuleMode.COPY, RoutingRuleMode.REVIEW}:
                routed = merge_agents(routed, rule_recipients)
                needs_review = needs_review or rule.mode == RoutingRuleMode.REVIEW

            trace.append(
                WorkflowTraceEntry(
                    hook="route.resolve",
                    runtime="cloud",
                    action=rule.mode.value,
                    actor=rule.rule_id,
                    changed=("recipient_agent_ids",),
                    note=rule.name,
                    created_at=self._clock(),
                )
            )

        return tuple(routed), tuple(trace), needs_review

    def _resolve_recipients(self, recipient_handles: Sequence[str]) -> tuple[Agent, ...]:
        recipients: list[Agent] = []
        seen_handles: set[str] = set()

        for handle in recipient_handles:
            normalized_handle = normalize_handle(handle)
            if normalized_handle in seen_handles:
                continue
            recipients.append(self._require_agent_by_handle(normalized_handle))
            seen_handles.add(normalized_handle)

        return tuple(recipients)

    def _require_agent_by_handle(self, handle: str) -> Agent:
        normalized_handle = normalize_handle(handle)
        agent = self._repository.get_agent_by_handle(normalized_handle)
        if agent is None:
            raise NotFoundError(f"agent not found: {normalized_handle}")
        return agent

    def _require_agent(self, agent_id: str) -> Agent:
        agent = self._repository.get_agent(agent_id)
        if agent is None:
            raise NotFoundError(f"agent not found: {agent_id}")
        return agent

    def _require_message(self, message_id: str) -> Message:
        message = self._repository.get_message(message_id)
        if message is None:
            raise NotFoundError(f"message not found: {message_id}")
        return message

    def _require_delivery(self, delivery_id: str) -> Delivery:
        delivery = self._repository.get_delivery(delivery_id)
        if delivery is None:
            raise NotFoundError(f"delivery not found: {delivery_id}")
        return delivery

    def _require_delivery_for_recipient(self, delivery_id: str, agent_handle: str) -> Delivery:
        delivery = self._require_delivery(delivery_id)
        recipient = self._require_agent_by_handle(agent_handle)
        if delivery.recipient_agent_id != recipient.agent_id:
            raise ForbiddenDeliveryError("agent cannot decide another recipient's delivery")
        return delivery

    def _require_task(self, task_id: str) -> TaskRecord:
        task = self._repository.get_task(task_id)
        if task is None:
            raise NotFoundError(f"task not found: {task_id}")
        return task

    def _require_task_quote(self, quote_id: str) -> TaskQuoteRecord:
        normalized_quote_id = normalize_required(quote_id, "quote_id")
        quote = self._repository.get_task_quote(normalized_quote_id)
        if quote is None:
            raise NotFoundError(f"task quote not found: {normalized_quote_id}")
        return quote

    def _require_task_escrow(self, escrow_id: str) -> TaskEscrowRecord:
        normalized_escrow_id = normalize_required(escrow_id, "escrow_id")
        escrow = self._repository.get_task_escrow(normalized_escrow_id)
        if escrow is None:
            raise NotFoundError(f"task escrow not found: {normalized_escrow_id}")
        return escrow

    def _append_task_credit_ledger_entry(
        self,
        *,
        account_agent_id: str,
        entry_type: TaskCreditLedgerEntryType,
        credit_amount: int,
        available_delta: int,
        escrow_delta: int = 0,
        task: TaskRecord | None = None,
        quote: TaskQuoteRecord | None = None,
        escrow: TaskEscrowRecord | None = None,
        counterparty_agent_id: str | None = None,
        reason: str | None = None,
        policy_decision_id: str | None = None,
        limits_ref: str | None = None,
        abuse_policy_ref: str | None = None,
        audit_refs: Sequence[str] = (),
    ) -> TaskCreditLedgerEntry:
        normalized_amount = require_bounded_int(
            credit_amount,
            "credit_amount",
            minimum=0,
            maximum=MAX_TASK_CREDIT_QUOTE,
        )
        require_int_delta(available_delta, "available_delta")
        require_int_delta(escrow_delta, "escrow_delta")
        normalized_reason = normalized_optional_string(reason)
        if normalized_reason is not None:
            require_small_inline(normalized_reason, "reason")
        entry_id = self._new_id("task_credit_entry")
        normalized_audit_refs = tuple(
            normalize_required(ref, "audit_ref")
            for ref in audit_refs
        ) or (f"seagull://task-credit-ledger/{entry_id}/audit",)
        entry = TaskCreditLedgerEntry(
            entry_id=entry_id,
            account_agent_id=normalize_required(account_agent_id, "account_agent_id"),
            entry_type=entry_type,
            credit_amount=normalized_amount,
            available_delta=available_delta,
            escrow_delta=escrow_delta,
            task_id=task.task_id if task is not None else None,
            thread_id=task.thread_id if task is not None else None,
            quote_id=quote.quote_id if quote is not None else (escrow.quote_id if escrow is not None else None),
            escrow_id=escrow.escrow_id if escrow is not None else None,
            counterparty_agent_id=normalized_optional_string(counterparty_agent_id),
            reason=normalized_reason,
            settlement_scope=TASK_CREDIT_SETTLEMENT_SCOPE,
            policy_decision_id=normalized_optional_string(policy_decision_id),
            limits_ref=normalized_optional_string(limits_ref),
            abuse_policy_ref=normalized_optional_string(abuse_policy_ref),
            audit_refs=normalized_audit_refs,
            created_at=self._clock(),
        )
        self._repository.put_task_credit_ledger_entry(entry)
        return entry

    def _task_credit_balance_for_agent_id(self, account_agent_id: str) -> TaskCreditBalance:
        entries = self._repository.list_task_credit_ledger_entries_by_agent(account_agent_id)
        available_balance = sum(entry.available_delta for entry in entries)
        escrow_balance = sum(entry.escrow_delta for entry in entries)
        return TaskCreditBalance(
            account_agent_id=account_agent_id,
            available_balance=available_balance,
            escrow_balance=escrow_balance,
        )

    def _record_task_worker_reputation_event_once(
        self,
        *,
        task: TaskRecord,
        event_type: TaskWorkerReputationEventType,
        reporter_agent_id: str | None = None,
        reason: str | None = None,
        policy_decision_id: str | None = None,
        limits_ref: str | None = None,
        abuse_policy_ref: str | None = None,
    ) -> TaskWorkerReputationEventRecord:
        for event in self._repository.list_task_worker_reputation_events_by_task(task.task_id):
            if event.worker_agent_id == task.recipient_agent_id and event.event_type == event_type:
                return event
        return self._record_task_worker_reputation_event(
            task=task,
            event_type=event_type,
            reporter_agent_id=reporter_agent_id,
            reason=reason,
            policy_decision_id=policy_decision_id,
            limits_ref=limits_ref,
            abuse_policy_ref=abuse_policy_ref,
        )

    def _record_task_worker_reputation_event(
        self,
        *,
        task: TaskRecord,
        event_type: TaskWorkerReputationEventType,
        reporter_agent_id: str | None = None,
        reason: str | None = None,
        policy_decision_id: str | None = None,
        limits_ref: str | None = None,
        abuse_policy_ref: str | None = None,
        audit_refs: Sequence[str] = (),
    ) -> TaskWorkerReputationEventRecord:
        normalized_reason = normalized_optional_string(reason)
        if normalized_reason is not None:
            require_small_inline(normalized_reason, "reason")
        event_id = self._new_id("task_reputation_event")
        normalized_audit_refs = tuple(
            normalize_required(ref, "audit_ref")
            for ref in audit_refs
        ) or (f"seagull://tasks/{task.task_id}/worker-reputation/{event_id}/audit",)
        event = TaskWorkerReputationEventRecord(
            event_id=event_id,
            worker_agent_id=task.recipient_agent_id,
            event_type=event_type,
            task_id=task.task_id,
            thread_id=task.thread_id,
            reporter_agent_id=normalized_optional_string(reporter_agent_id),
            reason=normalized_reason,
            policy_decision_id=normalized_optional_string(policy_decision_id),
            limits_ref=normalized_optional_string(limits_ref),
            abuse_policy_ref=normalized_optional_string(abuse_policy_ref),
            audit_refs=normalized_audit_refs,
            created_at=self._clock(),
        )
        self._repository.put_task_worker_reputation_event(event)
        return event

    def _task_worker_reputation_summary_for_agent_id(
        self,
        worker_agent_id: str,
    ) -> TaskWorkerReputationSummary:
        events = self._repository.list_task_worker_reputation_events_by_worker(worker_agent_id)
        counts = {
            event_type: sum(1 for event in events if event.event_type == event_type)
            for event_type in TaskWorkerReputationEventType
        }
        last_event = events[-1] if events else None
        return TaskWorkerReputationSummary(
            worker_agent_id=worker_agent_id,
            completed_task_count=counts[TaskWorkerReputationEventType.TASK_COMPLETED],
            failed_task_count=counts[TaskWorkerReputationEventType.TASK_FAILED],
            accepted_result_count=counts[TaskWorkerReputationEventType.RESULT_ACCEPTED],
            dispute_count=counts[TaskWorkerReputationEventType.DISPUTE_OPENED],
            abuse_report_count=counts[TaskWorkerReputationEventType.ABUSE_REPORTED],
            last_event_id=None if last_event is None else last_event.event_id,
            last_event_at=None if last_event is None else last_event.created_at,
        )

    def _latest_task_capacity_policy(
        self,
        task: TaskRecord,
    ) -> TaskCapacitySharingPolicyRecord | None:
        policies = self._repository.list_task_capacity_policies_by_task(task.task_id)
        if not policies:
            return None
        return policies[-1]

    def _apply_task_capacity_policy_to_quote(
        self,
        *,
        policy: TaskCapacitySharingPolicyRecord | None,
        expected_credit_cost: int,
        shared_context_refs: tuple[str, ...],
        requires_approval: bool,
    ) -> tuple[bool, str | None]:
        if policy is None:
            return requires_approval, None
        if expected_credit_cost > policy.max_credit_cost:
            raise InvalidMessageError("expected_credit_cost exceeds configured capacity sharing limit")
        has_private_context = any(has_private_context_marker(ref) for ref in shared_context_refs)
        if has_private_context and not policy.allow_private_context:
            raise ForbiddenDeliveryError("capacity sharing policy does not allow private-context sharing")

        approval_reasons: list[str] = []
        if has_private_context and policy.private_context_requires_approval:
            approval_reasons.append("private-context sharing requires approval")
        if expected_credit_cost > 0 and policy.paid_work_requires_approval:
            approval_reasons.append("paid capacity sharing requires approval")
        if expected_credit_cost > policy.max_auto_escrow_credits and policy.high_cost_requires_approval:
            approval_reasons.append("expected cost exceeds auto-escrow limit")
        if approval_reasons:
            return True, "; ".join(approval_reasons)
        return requires_approval, None

    def _require_tool_grant(self, grant_id: str) -> ToolGrant:
        normalized_grant_id = normalize_required(grant_id, "tool_grant_id")
        grant = self._repository.get_tool_grant(normalized_grant_id)
        if grant is None:
            raise NotFoundError(f"tool grant not found: {normalized_grant_id}")
        return grant

    def _require_tool_request(self, tool_request_id: str) -> TaskToolRequest:
        tool_request = self._repository.get_tool_request(tool_request_id)
        if tool_request is None:
            raise NotFoundError(f"tool request not found: {tool_request_id}")
        return tool_request

    def _require_task_actor(self, task: TaskRecord, actor_handle: str) -> Agent:
        actor = self._require_agent_by_handle(actor_handle)
        allowed_agent_ids = {
            task.requester_agent_id,
            task.recipient_agent_id,
        }
        if task.accepted_by_agent_id is not None:
            allowed_agent_ids.add(task.accepted_by_agent_id)
        if actor.agent_id not in allowed_agent_ids:
            raise ForbiddenDeliveryError("agent cannot update this task")
        return actor

    def _consume_tool_grant_for_request(
        self,
        *,
        task: TaskRecord,
        requester: Agent,
        worker: Agent,
        tool_name: str,
        grant_id: str,
    ) -> ToolGrant:
        grant = self._require_active_tool_grant(
            task=task,
            requester=requester,
            worker=worker,
            tool_name=tool_name,
            grant_id=grant_id,
        )
        if grant.max_calls is not None and grant.used_count >= grant.max_calls:
            raise ForbiddenDeliveryError("tool grant call limit exceeded")

        updated = replace(
            grant,
            used_count=grant.used_count + 1,
            updated_at=self._clock(),
        )
        self._repository.update_tool_grant(updated)
        return updated

    def _require_active_tool_grant(
        self,
        *,
        task: TaskRecord,
        requester: Agent,
        worker: Agent,
        tool_name: str,
        grant_id: str,
    ) -> ToolGrant:
        grant = self._require_tool_grant(grant_id)
        if grant.task_id != task.task_id or grant.thread_id != task.thread_id:
            raise ForbiddenDeliveryError("tool grant is not scoped to this task")
        if grant.issuer_agent_id != requester.agent_id:
            raise ForbiddenDeliveryError("tool grant issuer does not match requester")
        if grant.subject_agent_id != worker.agent_id:
            raise ForbiddenDeliveryError("tool grant subject does not match worker")
        if tool_name not in grant.scopes:
            raise ForbiddenDeliveryError("tool grant does not allow this tool")
        if grant.revoked_at is not None:
            raise ForbiddenDeliveryError("tool grant is revoked")
        if grant.ttl_expires_at is not None and grant.ttl_expires_at <= self._clock():
            raise ForbiddenDeliveryError("tool grant is expired")
        return grant

    def _require_tool_request_grant_active(self, tool_request: TaskToolRequest) -> ToolGrant:
        task = self._require_task(tool_request.task_id)
        requester = self._require_agent(tool_request.requester_agent_id)
        worker = self._require_agent(tool_request.worker_agent_id)
        assert tool_request.tool_grant_id is not None
        return self._require_active_tool_grant(
            task=task,
            requester=requester,
            worker=worker,
            tool_name=tool_request.tool_name,
            grant_id=tool_request.tool_grant_id,
        )

    def _send_task_notification(
        self,
        *,
        task: TaskRecord,
        sender: Agent,
        recipient_agent_id: str,
        intent: str,
        label: str,
        note: str | None = None,
        ref: MessageRef | None = None,
    ) -> SendMessageResult:
        recipient = self._require_agent(recipient_agent_id)
        refs = (ref or task_ref(task.task_id, label),)
        if note:
            refs = (*refs, MessageRef(type="note", find=note))
        return self.send_message(
            sender_handle=sender.handle,
            recipient_handles=(recipient.handle,),
            refs=refs,
            intent=intent,
            visibility="direct",
            thread_id=task.thread_id,
        )

    def _inbox_item_for_delivery(self, delivery: Delivery) -> InboxItem:
        message = self._repository.get_message(delivery.message_id)
        if message is None:
            raise NotFoundError(f"message not found: {delivery.message_id}")
        return InboxItem(delivery=delivery, message=message)

    def _result_for_existing_message(self, message_id: str) -> SendMessageResult:
        message = self._repository.get_message(message_id)
        if message is None:
            raise NotFoundError(f"message not found: {message_id}")

        thread = self._repository.get_thread(message.thread_id)
        if thread is None:
            raise NotFoundError(f"thread not found: {message.thread_id}")

        deliveries = self._repository.list_deliveries_by_message(message_id)
        return SendMessageResult(message=message, thread=thread, deliveries=deliveries)

    def _publish_delivery_created_events(
        self,
        *,
        deliveries: tuple[Delivery, ...],
        message: Message,
        sender: Agent,
        recipients: tuple[Agent, ...],
    ) -> None:
        if self._delivery_event_publisher is None:
            return

        if len(deliveries) != len(recipients):
            raise MessageHubError("delivery and recipient counts differ")

        for delivery, recipient in zip(deliveries, recipients):
            if recipient.trigger_mode != "webhook":
                continue
            self._delivery_event_publisher(
                delivery_created_event(
                    delivery=delivery,
                    message=message,
                    sender=sender,
                    recipient=recipient,
                )
            )

    def _refresh_payload_retention(self, payload: StoredPayload) -> StoredPayload:
        record = payload.record
        if record.retention_state != PAYLOAD_RETENTION_READY:
            return payload
        if record.ttl_expires_at is None or record.ttl_expires_at > self._clock():
            return payload

        updated = StoredPayload(
            record=replace(record, retention_state=PAYLOAD_RETENTION_EXPIRED),
            compressed_content=None,
        )
        self._repository.update_payload(updated)
        return updated

    def _require_payload_fetch_authorized(
        self,
        payload: PayloadRecord,
        requester_handle: str | None,
    ) -> None:
        if payload.access_scope == "public":
            return
        if requester_handle is None:
            raise ForbiddenPayloadError(
                f"requester_handle is required for {payload.access_scope} payload access"
            )

        normalized_requester = normalize_handle(requester_handle)
        requester = self._repository.get_agent_by_handle(normalized_requester)
        if requester is None:
            raise ForbiddenPayloadError(f"agent cannot fetch payload: {normalized_requester}")
        if self._payload_fetch_is_allowed_for_agent(payload, requester):
            return

        raise ForbiddenPayloadError(f"agent cannot fetch payload: {normalized_requester}")

    def _payload_fetch_is_allowed_for_agent(self, payload: PayloadRecord, agent: Agent) -> bool:
        messages = self._repository.list_messages_by_content_ref(payload.content_ref)
        if not messages:
            return False

        if payload.access_scope == "owner":
            return any(message.sender_agent_id == agent.agent_id for message in messages)
        if payload.access_scope == "recipients":
            return any(agent.agent_id in message.recipient_agent_ids for message in messages)
        if payload.access_scope == "thread":
            for message in messages:
                thread = self._repository.get_thread(message.thread_id)
                if thread is not None and agent.agent_id in thread.participants:
                    return True
            return False

        return False

    def _compact_payload(
        self,
        payload: StoredPayload,
        *,
        summary_chars: int,
        chunk_bytes: int,
    ) -> None:
        if payload.compressed_content is None:
            return

        content = gzip.decompress(payload.compressed_content)
        now = self._clock()
        manifest_ref = f"{payload.record.content_ref}/manifest/compact"
        chunks = selected_payload_chunks(content, chunk_bytes)
        compaction = PayloadCompaction(
            manifest_ref=manifest_ref,
            summary=payload_summary(content, summary_chars),
            selected_chunk_refs=tuple(
                f"{payload.record.content_ref}/chunk/{index}"
                for index, _chunk in enumerate(chunks)
            ),
            selected_chunks=chunks,
            created_at=now,
        )
        updated_record = replace(
            payload.record,
            retention_state=PAYLOAD_RETENTION_COMPACTED,
            chunk_manifest_ref=manifest_ref,
            storage_ref=manifest_ref,
        )
        self._repository.update_payload(
            StoredPayload(
                record=updated_record,
                compressed_content=None,
                compaction=compaction,
            )
        )

    def _delete_retained_payload(self, payload: StoredPayload) -> None:
        updated_record = replace(
            payload.record,
            retention_state=PAYLOAD_RETENTION_DELETED,
        )
        self._repository.update_payload(
            StoredPayload(
                record=updated_record,
                compressed_content=None,
            )
        )

    def _new_id(self, prefix: str) -> str:
        return self._id_factory(prefix)

    @staticmethod
    def _default_id_factory(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"


def normalize_handle(handle: str) -> str:
    normalized = handle.strip().lower()
    if not normalized:
        raise InvalidMessageError("agent handle is required")
    if not normalized.startswith("@"):
        raise InvalidMessageError("agent handle must start with @")
    return normalized


def normalize_required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise InvalidMessageError(f"{field_name} is required")
    return normalized


def normalize_message_ref(ref: MessageRef | dict[str, str | None]) -> MessageRef:
    if isinstance(ref, MessageRef):
        return ref
    ref_type = normalize_required(str(ref.get("type") or ""), "ref type")
    return MessageRef(
        type=ref_type,
        url=normalized_optional_string(ref.get("url")),
        find=normalized_optional_string(ref.get("find")),
        remember_as=normalized_optional_string(ref.get("remember_as")),
    )


def normalized_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def normalize_non_empty_strings(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    normalized = tuple(normalize_required(value, field_name) for value in values)
    if not normalized:
        raise InvalidMessageError(f"{field_name}s are required")
    return normalized


def normalize_optional_non_negative_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InvalidMessageError(f"{field_name} must be non-negative")
    return value


def normalize_payload_access_scope(access_scope: str) -> str:
    normalized = normalize_required(access_scope, "access_scope").lower()
    if normalized not in {"owner", "thread", "recipients", "public"}:
        raise InvalidMessageError("access_scope must be owner, thread, recipients, or public")
    return normalized


def normalize_payload_retention_state(retention_state: str) -> str:
    normalized = normalize_required(retention_state, "retention_state").lower()
    if normalized not in PAYLOAD_RETENTION_STATES:
        raise InvalidMessageError("retention_state must be ready, expired, compacted, or deleted")
    return normalized


def normalize_payload_ttl_expires_at(ttl_expires_at: datetime | None) -> datetime | None:
    if ttl_expires_at is None:
        return None
    if ttl_expires_at.tzinfo is None or ttl_expires_at.utcoffset() is None:
        raise InvalidMessageError("ttl_expires_at must include a timezone")
    return ttl_expires_at


def normalize_payload_policy_cutoff(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidMessageError(f"{field_name} must include a timezone")
    return value


def validate_payload_compaction_limits(
    *,
    compact_summary_chars: int,
    compact_chunk_bytes: int,
) -> None:
    if not isinstance(compact_summary_chars, int) or compact_summary_chars < 0:
        raise InvalidMessageError("compact_summary_chars must be non-negative")
    if not isinstance(compact_chunk_bytes, int) or compact_chunk_bytes < 0:
        raise InvalidMessageError("compact_chunk_bytes must be non-negative")
    if compact_summary_chars == 0 and compact_chunk_bytes == 0:
        raise InvalidMessageError("compaction requires a summary or selected chunks")


def should_compact_ready_payload(payload: PayloadRecord, compact_ready_before: datetime | None) -> bool:
    if compact_ready_before is None:
        return False
    return payload.retention_state == PAYLOAD_RETENTION_READY and payload.created_at <= compact_ready_before


def should_delete_expired_payload(payload: PayloadRecord, delete_expired_before: datetime | None) -> bool:
    if delete_expired_before is None:
        return False
    if payload.retention_state != PAYLOAD_RETENTION_EXPIRED:
        return False
    expired_at = payload.ttl_expires_at or payload.created_at
    return expired_at <= delete_expired_before


def payload_summary(content: bytes, summary_chars: int) -> str | None:
    if summary_chars == 0:
        return None
    text = content.decode("utf-8", errors="replace")
    if len(text) <= summary_chars:
        return text
    summary = text[:summary_chars].rstrip()
    return f"{summary}..."


def selected_payload_chunks(content: bytes, chunk_bytes: int) -> tuple[bytes, ...]:
    if chunk_bytes == 0 or not content:
        return ()
    if len(content) <= chunk_bytes:
        return (content,)
    if len(content) <= chunk_bytes * 2:
        return (content[:chunk_bytes],)
    return (content[:chunk_bytes], content[-chunk_bytes:])


def payload_hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def hash_token_parts(token_id: str, secret: str) -> str:
    return hashlib.sha256(f"{token_id}.{secret}".encode("utf-8")).hexdigest()


def parse_agent_token(token: str) -> tuple[str, str]:
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != AGENT_TOKEN_PREFIX or not parts[1] or not parts[2]:
        raise AgentTokenVerificationError("agent token has invalid format")
    return parts[1], parts[2]


def normalize_agent_token_scope(scope: str) -> str:
    normalized = normalize_required(scope, "scope").lower()
    if normalized not in AGENT_TOKEN_SCOPES:
        raise InvalidMessageError(f"unknown agent token scope: {normalized}")
    return normalized


def normalize_agent_token_scopes(scopes: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({normalize_agent_token_scope(scope) for scope in scopes}))
    if not normalized:
        raise InvalidMessageError("agent token scopes are required")
    return normalized


def require_small_inline(value: str, field_name: str) -> None:
    if len(value) > MAX_ENVELOPE_INLINE_CHARS:
        raise InvalidMessageError(
            f"{field_name} exceeds {MAX_ENVELOPE_INLINE_CHARS} characters; use refs or content_ref"
        )


def envelope_content_for_storage(
    content: str | None,
    content_ref: str | None,
    field_name: str,
) -> tuple[str | None, str | None]:
    normalized_content_ref = normalized_optional_string(content_ref)
    if content is not None and len(content) > MAX_ENVELOPE_INLINE_CHARS:
        if normalized_content_ref is None:
            raise InvalidMessageError(
                f"{field_name} exceeds {MAX_ENVELOPE_INLINE_CHARS} characters; provide content_ref"
            )
        return None, normalized_content_ref
    return content, normalized_content_ref


def normalize_routing_rule_mode(mode: str) -> RoutingRuleMode:
    normalized = mode.strip().lower()
    try:
        return RoutingRuleMode(normalized)
    except ValueError as exc:
        raise InvalidMessageError("routing rule mode must be direct, copy, handoff, review, or block") from exc


def normalize_hook(hook: str) -> str:
    normalized = hook.strip().lower()
    allowed = {
        "send.before",
        "route.resolve",
        "delivery.before",
        "receive.before",
        "action.before",
        "reply.before",
        "after",
        "agent.decision",
    }
    if normalized not in allowed:
        raise InvalidMessageError("unsupported lifecycle hook")
    return normalized


def normalize_hook_runtime(runtime: str) -> str:
    normalized = runtime.strip().lower()
    if normalized not in {"cloud", "cloud_node", "lan_node", "agent_client"}:
        raise InvalidMessageError("runtime must be cloud, cloud_node, lan_node, or agent_client")
    return normalized


def normalize_hook_action(action: str) -> str:
    normalized = action.strip().lower()
    if normalized not in {"continue", "block", "review", "fail"}:
        raise InvalidMessageError("hook action must be continue, block, review, or fail")
    return normalized


def normalize_agent_decision(decision: str) -> str:
    normalized = decision.strip().lower()
    if normalized not in {"reply", "action", "ignore", "ask_human"}:
        raise InvalidMessageError("agent decision must be reply, action, ignore, or ask_human")
    return normalized


def normalize_task_state(state: str) -> TaskState:
    normalized = state.strip().lower()
    try:
        return TaskState(normalized)
    except ValueError as exc:
        allowed = ", ".join(task_state.value for task_state in TaskState)
        raise InvalidMessageError(f"task state must be one of: {allowed}") from exc


def normalize_task_capacity_tier(tier: str) -> TaskCapacityTier:
    normalized = normalize_required(tier, "capacity_tier").lower()
    try:
        return TaskCapacityTier(normalized)
    except ValueError as exc:
        allowed = ", ".join(capacity_tier.value for capacity_tier in TaskCapacityTier)
        raise InvalidMessageError(f"capacity_tier must be one of: {allowed}") from exc


def task_ref(task_id: str, label: str) -> MessageRef:
    return MessageRef(type="task", url=f"seagull://tasks/{task_id}", remember_as=label)


def task_shared_context_refs(task: TaskRecord) -> tuple[str, ...]:
    values: list[str | None] = [
        *task.context_refs,
        task.context_pack_id,
        task.context_pack_ref,
        task.input_ref,
    ]
    return tuple(dict.fromkeys(value for value in values if value))


def contact_reason(
    message: Message,
    delivery: Delivery,
    requester: Agent,
    recipient: Agent,
) -> str:
    intent = message.intent.replace("_", " ")
    route_entries = tuple(entry for entry in delivery.workflow_trace if entry.hook == "route.resolve")
    if message.intent == "task_request":
        return f"{requester.handle} requested delegated task work from {recipient.handle}."
    if message.intent == "reply":
        return f"{requester.handle} replied to {recipient.handle} in this thread."
    if route_entries:
        route_labels = ", ".join(entry.note or entry.action for entry in route_entries)
        return f"{requester.handle} sent a {intent}; routing delivered it to {recipient.handle} via {route_labels}."
    return f"{requester.handle} sent a {intent} to {recipient.handle}."


def contact_allowed_reason(
    message: Message,
    delivery: Delivery,
    relationship: str,
) -> str:
    reasons = [
        f"message safety status is {message.safety_status}",
        f"relationship is {relationship}",
    ]
    if delivery.status == DeliveryStatus.NEEDS_REVIEW:
        reasons.append("delivery is held for human review")
    elif delivery.status == DeliveryStatus.PENDING_ACTION and delivery.action_request is not None:
        reasons.append(
            "requested action requires approval"
            if delivery.action_request.requires_approval
            else "requested action is preapproved"
        )
    else:
        reasons.append(f"delivery state is {delivery.status.value}")
    return f"Seagull allowed the contact because {'; '.join(reasons)}."


def contact_shared_context_summary(
    message: Message,
    delivery: Delivery,
    summary: ThreadSummary | None,
) -> str:
    if summary is not None and summary.summary_text:
        return truncate_explanation_text(summary.summary_text)
    content = delivery.current_content_inline or message.content_inline
    if content:
        return truncate_explanation_text(content)
    content_ref = delivery.current_content_ref or message.content_ref
    if content_ref:
        return f"Context was shared by reference: {content_ref}."

    refs = delivery.refs or message.refs
    labels = tuple(ref.remember_as or ref.find or ref.type for ref in refs)
    if labels:
        return truncate_explanation_text(f"Context was shared as refs: {', '.join(labels)}.")
    return "No inline context was shared."


def contact_shared_context_refs(
    message: Message,
    delivery: Delivery,
    tasks: tuple[TaskRecord, ...],
) -> tuple[str, ...]:
    values: list[str | None] = [
        message.content_ref,
        delivery.current_content_ref,
    ]
    for ref in (*message.refs, *delivery.refs):
        values.append(ref.url)
    for task in tasks:
        values.extend(task.context_refs)
        values.extend(
            (
                task.context_pack_ref,
                task.input_ref,
                task.result_ref,
            )
        )
        values.extend(task.artifact_refs)
    return unique_strings(values)


def contact_pending_action(delivery: Delivery, tasks: tuple[TaskRecord, ...]) -> str | None:
    if delivery.action_request is not None:
        approval = "requires approval" if delivery.action_request.requires_approval else "preapproved"
        target = f" for {delivery.action_request.target}" if delivery.action_request.target else ""
        return f"{delivery.action_request.type}{target} ({approval})"
    if delivery.status == DeliveryStatus.NEEDS_REVIEW:
        return "human review"
    for task in tasks:
        if task.state not in TASK_INACTIVE_STATES:
            return f"task {task.task_id} is {task.state.value}"
    if delivery.status == DeliveryStatus.PENDING_ACTION:
        return delivery.current_stage
    return None


def contact_policy_refs(
    message: Message,
    delivery: Delivery,
    relationship: str,
    tasks: tuple[TaskRecord, ...],
) -> tuple[str, ...]:
    values: list[str | None] = [
        f"message_safety:{message.safety_status}",
        f"relationship:{relationship}",
    ]
    if delivery.status == DeliveryStatus.NEEDS_REVIEW:
        values.append("delivery_gate:human_review")
    if delivery.action_request is not None:
        values.append(f"action_approval_required:{str(delivery.action_request.requires_approval).lower()}")
    for task in tasks:
        if task.policy_decision_id is not None:
            values.append(f"policy_decision:{task.policy_decision_id}")
    return unique_strings(values)


def contact_audit_refs(delivery: Delivery, thread: ThreadRecord) -> tuple[str, ...]:
    values: list[str | None] = [
        f"delivery:{delivery.delivery_id}:{delivery.status.value}",
        f"message:{delivery.message_id}",
        f"thread:{thread.thread_id}:message_count:{thread.message_count}",
    ]
    values.extend(
        f"workflow_trace:{index}:{entry.hook}:{entry.action}"
        for index, entry in enumerate(delivery.workflow_trace, start=1)
    )
    if delivery.action_request is not None:
        values.append(f"action_request:{delivery.action_request.action_request_id}:{delivery.action_request.status}")
    return unique_strings(values)


def truncate_explanation_text(value: str) -> str:
    if len(value) <= CONTACT_EXPLANATION_SUMMARY_CHARS:
        return value
    summary = value[:CONTACT_EXPLANATION_SUMMARY_CHARS].rstrip()
    return f"{summary}..."


def unique_strings(values: Sequence[str | None]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        normalized.append(stripped)
        seen.add(stripped)
    return tuple(normalized)


def require_bounded_int(value: int, field_name: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int):
        raise InvalidMessageError(f"{field_name} must be an integer")
    if value < minimum:
        raise InvalidMessageError(f"{field_name} must be at least {minimum}")
    if value > maximum:
        return maximum
    return value


def require_int_delta(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidMessageError(f"{field_name} must be an integer")


def is_private_context_ref(ref: MessageRef) -> bool:
    haystacks = (ref.type, ref.url or "", ref.find or "", ref.remember_as or "")
    return has_private_context_marker(*haystacks)


def has_private_context_marker(*values: str) -> bool:
    normalized = " ".join(values).lower()
    return any(marker in normalized for marker in PRIVATE_CONTEXT_REF_MARKERS)


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


def routing_rule_matches(
    rule: RoutingRule,
    *,
    content: str | None,
    content_ref: str | None,
    refs: tuple[MessageRef, ...],
) -> bool:
    haystacks = [content or "", content_ref or ""]
    haystacks.extend(ref.url or "" for ref in refs)
    normalized_haystacks = [haystack.lower() for haystack in haystacks]
    return any(
        needle in haystack
        for needle in rule.url_contains
        for haystack in normalized_haystacks
    )


def merge_agents(existing: Sequence[Agent], additions: Sequence[Agent]) -> list[Agent]:
    merged = list(existing)
    seen = {agent.agent_id for agent in merged}
    for agent in additions:
        if agent.agent_id in seen:
            continue
        merged.append(agent)
        seen.add(agent.agent_id)
    return merged


def normalize_trigger_mode(trigger_mode: str | None) -> str:
    normalized = (trigger_mode or "manual").strip().lower()
    if normalized not in {"manual", "webhook"}:
        raise InvalidMessageError("trigger_mode must be manual or webhook")
    return normalized


def normalize_webhook_url(webhook_url: str | None) -> str | None:
    if webhook_url is None:
        return None
    normalized = webhook_url.strip()
    if not normalized:
        return None
    if not (normalized.startswith("http://") or normalized.startswith("https://")):
        raise InvalidMessageError("webhook_url must start with http:// or https://")
    return normalized
