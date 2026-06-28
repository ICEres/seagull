from __future__ import annotations

import gzip
import hashlib
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
    ContextBudget,
    ContextPack,
    ContextPayloadRef,
    Delivery,
    DeliveryStatus,
    InboxItem,
    Message,
    MessageRef,
    PayloadRecord,
    RoutingRule,
    RoutingRuleMode,
    SendMessageResult,
    StoredPayload,
    TaskRecord,
    TaskResultRecord,
    TaskState,
    TaskToolRequest,
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


IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]
DeliveryEventPublisher = Callable[[dict[str, Any]], None]
DEFAULT_CONTEXT_MAX_INLINE_CHARS = 4000
DEFAULT_CONTEXT_MAX_RECENT_MESSAGES = 10
DEFAULT_CONTEXT_MAX_PAYLOAD_REFS = 20
MAX_ENVELOPE_INLINE_CHARS = 4000
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
            ttl_expires_at=ttl_expires_at,
            retention_state="ready",
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
        return payload

    def read_payload_content(self, content_ref: str) -> tuple[PayloadRecord, bytes]:
        payload = self.get_payload(content_ref)
        return payload.record, gzip.decompress(payload.compressed_content)

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
    ) -> TaskToolRequest:
        task = self._require_task(task_id)
        requester = self._require_agent_by_handle(requester_handle)
        worker = self._require_agent_by_handle(worker_handle)
        if requester.agent_id != task.requester_agent_id:
            raise ForbiddenDeliveryError("only the task requester can request delegated tool use")
        if worker.agent_id != task.recipient_agent_id:
            raise ForbiddenDeliveryError("tool request worker must be the task recipient")

        now = self._clock()
        tool_request = TaskToolRequest(
            tool_request_id=self._new_id("tool_request"),
            task_id=task.task_id,
            thread_id=task.thread_id,
            requester_agent_id=requester.agent_id,
            worker_agent_id=worker.agent_id,
            tool_name=normalize_required(tool_name, "tool_name"),
            purpose=normalize_required(purpose, "purpose"),
            input_ref=normalized_optional_string(input_ref),
            requires_approval=requires_approval,
            status=TaskState.NEEDS_APPROVAL if requires_approval else TaskState.REQUESTED,
            approval_id=normalized_optional_string(approval_id),
            policy_decision_id=normalized_optional_string(policy_decision_id),
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

        for delivery, recipient in zip(deliveries, recipients, strict=True):
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


def normalize_payload_access_scope(access_scope: str) -> str:
    normalized = normalize_required(access_scope, "access_scope").lower()
    if normalized not in {"owner", "thread", "recipients", "public"}:
        raise InvalidMessageError("access_scope must be owner, thread, recipients, or public")
    return normalized


def payload_hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


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


def task_ref(task_id: str, label: str) -> MessageRef:
    return MessageRef(type="task", url=f"seagull://tasks/{task_id}", remember_as=label)


def require_bounded_int(value: int, field_name: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int):
        raise InvalidMessageError(f"{field_name} must be an integer")
    if value < minimum:
        raise InvalidMessageError(f"{field_name} must be at least {minimum}")
    if value > maximum:
        return maximum
    return value


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
