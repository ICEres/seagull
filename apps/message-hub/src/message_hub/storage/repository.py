from __future__ import annotations

from datetime import datetime
from typing import Protocol

from message_hub.domain.models import (
    Agent,
    Delivery,
    Message,
    StoredPayload,
    RoutingRule,
    TaskRecord,
    TaskResultRecord,
    TaskToolRequest,
    ToolGrant,
    ThreadRecord,
    ThreadSummary,
)


class MessageHubRepository(Protocol):
    def add_agent(self, agent: Agent) -> None:
        """Persist a new agent."""

    def get_agent(self, agent_id: str) -> Agent | None:
        """Return an agent by ID."""

    def get_agent_by_handle(self, handle: str) -> Agent | None:
        """Return an agent by normalized handle."""

    def put_message(self, message: Message) -> None:
        """Persist an immutable message."""

    def get_message(self, message_id: str) -> Message | None:
        """Return a message by ID."""

    def list_thread_messages(self, thread_id: str, *, limit: int | None = None) -> tuple[Message, ...]:
        """Return thread messages in chronological order."""

    def list_messages_by_sender(self, sender_agent_id: str, *, limit: int | None = None) -> tuple[Message, ...]:
        """Return messages created by an agent in newest-first order."""

    def list_messages_by_content_ref(self, content_ref: str) -> tuple[Message, ...]:
        """Return messages that reference a payload by content_ref."""

    def put_payload(self, payload: StoredPayload) -> None:
        """Persist a compressed payload blob and metadata."""

    def get_payload(self, content_ref: str) -> StoredPayload | None:
        """Return a compressed payload by content reference."""

    def list_payloads(self, *, limit: int | None = None) -> tuple[StoredPayload, ...]:
        """Return payloads in creation order."""

    def update_payload(self, payload: StoredPayload) -> None:
        """Replace a payload blob and metadata."""

    def put_thread(self, thread: ThreadRecord) -> None:
        """Create or replace thread metadata."""

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        """Return thread metadata."""

    def put_delivery(self, delivery: Delivery) -> None:
        """Persist a per-recipient delivery row."""

    def get_delivery(self, delivery_id: str) -> Delivery | None:
        """Return a delivery by ID."""

    def list_deliveries_by_recipient(
        self,
        recipient_agent_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Delivery, ...]:
        """Return inbox deliveries in newest-first order."""

    def list_deliveries_by_sender(
        self,
        sender_agent_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Delivery, ...]:
        """Return outbox deliveries in newest-first order."""

    def list_deliveries_by_message(self, message_id: str) -> tuple[Delivery, ...]:
        """Return all deliveries for a message."""

    def update_delivery(self, delivery: Delivery) -> None:
        """Replace a delivery row."""

    def put_routing_rule(self, rule: RoutingRule) -> None:
        """Persist a user-controlled routing rule."""

    def list_routing_rules(self) -> tuple[RoutingRule, ...]:
        """Return routing rules in creation order."""

    def get_idempotent_message_id(self, sender_agent_id: str, idempotency_key: str) -> str | None:
        """Return the message already created for this sender/key pair."""

    def put_idempotency_key(
        self,
        sender_agent_id: str,
        idempotency_key: str,
        message_id: str,
        *,
        expires_at: datetime | None = None,
    ) -> None:
        """Persist an idempotency key for duplicate-send protection."""

    def put_thread_summary(self, summary: ThreadSummary) -> None:
        """Persist a compact summary for a thread."""

    def get_latest_thread_summary(self, thread_id: str) -> ThreadSummary | None:
        """Return the newest compact summary for a thread."""

    def put_task(self, task: TaskRecord) -> None:
        """Persist a delegated task record."""

    def get_task(self, task_id: str) -> TaskRecord | None:
        """Return a delegated task by ID."""

    def update_task(self, task: TaskRecord) -> None:
        """Replace a delegated task record."""

    def list_tasks_by_thread(self, thread_id: str, *, limit: int | None = None) -> tuple[TaskRecord, ...]:
        """Return tasks scoped to a thread in chronological order."""

    def put_tool_grant(self, grant: ToolGrant) -> None:
        """Persist a task-scoped tool grant."""

    def get_tool_grant(self, grant_id: str) -> ToolGrant | None:
        """Return a tool grant by ID."""

    def update_tool_grant(self, grant: ToolGrant) -> None:
        """Replace a task-scoped tool grant."""

    def list_tool_grants_by_task(self, task_id: str) -> tuple[ToolGrant, ...]:
        """Return tool grants scoped to a task in chronological order."""

    def put_tool_request(self, tool_request: TaskToolRequest) -> None:
        """Persist a task-scoped tool request."""

    def get_tool_request(self, tool_request_id: str) -> TaskToolRequest | None:
        """Return a task-scoped tool request by ID."""

    def update_tool_request(self, tool_request: TaskToolRequest) -> None:
        """Replace a task-scoped tool request."""

    def list_tool_requests_by_task(self, task_id: str) -> tuple[TaskToolRequest, ...]:
        """Return tool requests for a task in chronological order."""

    def put_task_result(self, result: TaskResultRecord) -> None:
        """Persist a durable task result record."""

    def list_task_results(self, task_id: str) -> tuple[TaskResultRecord, ...]:
        """Return durable task results in chronological order."""

    def get_idempotent_task_id(self, requester_agent_id: str, idempotency_key: str) -> str | None:
        """Return the task already created for this requester/key pair."""

    def put_task_idempotency_key(
        self,
        requester_agent_id: str,
        idempotency_key: str,
        task_id: str,
        *,
        expires_at: datetime | None = None,
    ) -> None:
        """Persist an idempotency key for duplicate task creation protection."""
