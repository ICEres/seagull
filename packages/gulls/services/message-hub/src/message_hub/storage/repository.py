from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from typing import Protocol

from message_hub.domain.models import (
    Agent,
    AgentTokenRecord,
    Delivery,
    FeedEventRecord,
    FollowRecord,
    Message,
    NotificationRecord,
    PostRecord,
    RoomMembershipRecord,
    RoomRecord,
    StoredPayload,
    RoutingRule,
    TaskCapacitySharingPolicyRecord,
    TaskCreditLedgerEntry,
    TaskEscrowRecord,
    TaskQuoteRecord,
    TaskRecord,
    TaskResultRecord,
    TaskToolRequest,
    TaskWorkerReputationEventRecord,
    ToolGrant,
    ThreadRecord,
    ThreadSummary,
)
from message_hub.storage.pagination import CursorPage


class AtomicCommitConflict(RuntimeError):
    """The transaction lost a concurrent idempotency or thread race."""


class IdempotencyKeyConflict(RuntimeError):
    """A live key was reused with a different normalized request."""


class IdempotencyRecoveryConflict(RuntimeError):
    """A live idempotency record cannot be safely replayed."""


class SendTooLargeError(RuntimeError):
    """A message/task transaction exceeds DynamoDB transaction limits."""


MAX_DYNAMODB_ITEM_BYTES = 400 * 1024
MAX_DYNAMODB_TRANSACTION_BYTES = 4 * 1024 * 1024


def validate_transaction_limits(items: tuple[object, ...], action_count: int) -> None:
    """Apply DynamoDB's transaction/action and item/aggregate bounds locally."""
    if action_count > 100:
        raise SendTooLargeError("atomic transaction exceeds DynamoDB's 100 action limit")

    def normalize(value: object) -> object:
        if dataclasses.is_dataclass(value):
            return normalize(dataclasses.asdict(value))
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, (tuple, list, set, frozenset)):
            return [normalize(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    total = 0
    for item in items:
        size = len(json.dumps(normalize(item), separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if size > MAX_DYNAMODB_ITEM_BYTES:
            raise SendTooLargeError(f"DynamoDB item exceeds {MAX_DYNAMODB_ITEM_BYTES} bytes")
        total += size
    if total > MAX_DYNAMODB_TRANSACTION_BYTES:
        raise SendTooLargeError(f"DynamoDB transaction exceeds {MAX_DYNAMODB_TRANSACTION_BYTES} bytes")


class MessageHubRepository(Protocol):
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
        """Atomically commit a message, thread, deliveries, and idempotency key."""

    def add_agent(self, agent: Agent) -> None:
        """Persist a new agent."""

    def get_agent(self, agent_id: str) -> Agent | None:
        """Return an agent by ID."""

    def get_agent_by_handle(self, handle: str) -> Agent | None:
        """Return an agent by normalized handle."""

    def update_agent(self, agent: Agent) -> None:
        """Replace an existing agent record (handle is immutable)."""

    def increment_guest_send_count(
        self,
        scope_key: str,
        window_start_epoch: int,
        *,
        ttl_epoch: int,
    ) -> int:
        """Atomically bump a fixed-window guest-send counter.

        Returns the post-increment count for ``(scope_key, window_start_epoch)``;
        the row expires at ``ttl_epoch`` (epoch seconds).
        """

    def put_agent_token(self, token: AgentTokenRecord) -> None:
        """Persist a scoped agent-runtime token record."""

    def get_agent_token(self, token_id: str) -> AgentTokenRecord | None:
        """Return a scoped agent-runtime token record by token ID."""

    def update_agent_token(self, token: AgentTokenRecord) -> None:
        """Replace a scoped agent-runtime token record."""

    def list_agent_tokens_by_agent(self, agent_id: str) -> tuple[AgentTokenRecord, ...]:
        """Return agent-runtime token records for one agent in newest-first order."""

    def put_message(self, message: Message) -> None:
        """Persist an immutable message."""

    def get_message(self, message_id: str) -> Message | None:
        """Return a message by ID."""

    def list_thread_messages(self, thread_id: str, *, limit: int | None = None) -> tuple[Message, ...]:
        """Return thread messages in chronological order."""

    def list_thread_messages_page(
        self, thread_id: str, *, limit: int, cursor: str | None = None
    ) -> CursorPage[Message]:
        """Return one chronological thread page after an opaque cursor."""

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

    def list_deliveries_by_recipient_page(
        self, recipient_agent_id: str, *, limit: int, cursor: str | None = None
    ) -> CursorPage[Delivery]:
        """Return one newest-first inbox page after an opaque cursor."""

    def list_deliveries_by_sender(
        self,
        sender_agent_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Delivery, ...]:
        """Return outbox deliveries in newest-first order."""

    def list_deliveries_by_message(self, message_id: str) -> tuple[Delivery, ...]:
        """Return all deliveries for a message."""

    def list_deliveries_by_ids(self, delivery_ids: tuple[str, ...]) -> tuple[Delivery, ...]:
        """Strongly read a committed delivery set by primary keys."""

    def update_delivery(self, delivery: Delivery, *, expected: Delivery | None = None) -> None:
        """Replace a delivery row, optionally enforcing an optimistic version check."""

    def put_routing_rule(self, rule: RoutingRule) -> None:
        """Persist a user-controlled routing rule."""

    def list_routing_rules(self) -> tuple[RoutingRule, ...]:
        """Return routing rules in creation order."""

    def get_idempotent_message_id(self, sender_agent_id: str, idempotency_key: str) -> str | None:
        """Return the message already created for this sender/key pair."""

    def get_idempotency_record(
        self, sender_agent_id: str, idempotency_key: str, *, task: bool = False
    ) -> tuple[str, str | None, int | None] | None:
        """Return (resource_id, fingerprint, expiry) for a live key."""

    def get_idempotency_delivery_ids(
        self, sender_agent_id: str, idempotency_key: str, *, task: bool = False
    ) -> tuple[str, ...]:
        """Return delivery IDs committed with a live idempotency record."""

    def put_idempotency_key(
        self,
        sender_agent_id: str,
        idempotency_key: str,
        message_id: str,
        *,
        expires_at: datetime | None = None,
        request_fingerprint: str | None = None,
    ) -> None:
        """Persist an idempotency key for duplicate-send protection."""

    def put_thread_summary(self, summary: ThreadSummary) -> None:
        """Persist a compact summary for a thread."""

    def get_latest_thread_summary(self, thread_id: str) -> ThreadSummary | None:
        """Return the newest compact summary for a thread."""

    def put_task(self, task: TaskRecord) -> None:
        """Persist a delegated task record."""

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
        """Atomically commit a task request message, delivery, task, and key."""

    def get_task(self, task_id: str) -> TaskRecord | None:
        """Return a delegated task by ID."""

    def update_task(self, task: TaskRecord) -> None:
        """Replace a delegated task record."""

    def list_tasks_by_thread(self, thread_id: str, *, limit: int | None = None) -> tuple[TaskRecord, ...]:
        """Return tasks scoped to a thread in chronological order."""

    def list_tasks_by_requester(
        self, requester_agent_id: str, *, limit: int | None = None
    ) -> tuple[TaskRecord, ...]:
        """Return tasks this agent requested, newest first."""

    def list_tasks_by_worker(
        self, worker_agent_id: str, *, limit: int | None = None
    ) -> tuple[TaskRecord, ...]:
        """Return tasks addressed to this agent, newest first."""

    def put_task_quote(self, quote: TaskQuoteRecord) -> None:
        """Persist a task quote."""

    def get_task_quote(self, quote_id: str) -> TaskQuoteRecord | None:
        """Return a task quote by ID."""

    def update_task_quote(self, quote: TaskQuoteRecord) -> None:
        """Replace a task quote."""

    def list_task_quotes_by_task(self, task_id: str) -> tuple[TaskQuoteRecord, ...]:
        """Return quotes scoped to a task in chronological order."""

    def put_task_escrow(self, escrow: TaskEscrowRecord) -> None:
        """Persist a task credit escrow record."""

    def get_task_escrow(self, escrow_id: str) -> TaskEscrowRecord | None:
        """Return a task credit escrow by ID."""

    def update_task_escrow(self, escrow: TaskEscrowRecord) -> None:
        """Replace a task credit escrow."""

    def list_task_escrows_by_task(self, task_id: str) -> tuple[TaskEscrowRecord, ...]:
        """Return escrows scoped to a task in chronological order."""

    def put_task_capacity_policy(self, policy: TaskCapacitySharingPolicyRecord) -> None:
        """Persist a task capacity-sharing policy."""

    def get_task_capacity_policy(self, policy_id: str) -> TaskCapacitySharingPolicyRecord | None:
        """Return a task capacity-sharing policy by ID."""

    def list_task_capacity_policies_by_task(
        self,
        task_id: str,
    ) -> tuple[TaskCapacitySharingPolicyRecord, ...]:
        """Return capacity-sharing policies scoped to a task in chronological order."""

    def put_task_credit_ledger_entry(self, entry: TaskCreditLedgerEntry) -> None:
        """Persist an append-only task credit ledger entry."""

    def get_task_credit_ledger_entry(self, entry_id: str) -> TaskCreditLedgerEntry | None:
        """Return a task credit ledger entry by ID."""

    def list_task_credit_ledger_entries_by_agent(
        self,
        account_agent_id: str,
    ) -> tuple[TaskCreditLedgerEntry, ...]:
        """Return task credit ledger entries for one account in chronological order."""

    def list_task_credit_ledger_entries_by_task(self, task_id: str) -> tuple[TaskCreditLedgerEntry, ...]:
        """Return task credit ledger entries for one task in chronological order."""

    def put_task_worker_reputation_event(self, event: TaskWorkerReputationEventRecord) -> None:
        """Persist an append-only worker reputation event."""

    def get_task_worker_reputation_event(
        self,
        event_id: str,
    ) -> TaskWorkerReputationEventRecord | None:
        """Return a worker reputation event by ID."""

    def list_task_worker_reputation_events_by_worker(
        self,
        worker_agent_id: str,
    ) -> tuple[TaskWorkerReputationEventRecord, ...]:
        """Return worker reputation events for one agent in chronological order."""

    def list_task_worker_reputation_events_by_task(
        self,
        task_id: str,
    ) -> tuple[TaskWorkerReputationEventRecord, ...]:
        """Return worker reputation events for one task in chronological order."""

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
        request_fingerprint: str | None = None,
    ) -> None:
        """Persist an idempotency key for duplicate task creation protection."""

    # --- Feed -------------------------------------------------------------
    # Feed is a gulls network capability; these are the base source-of-truth
    # records that seagulls projects and ranks on top of.

    def put_post(self, post: PostRecord) -> None:
        """Persist a durable feed post."""

    def get_post(self, post_id: str) -> PostRecord | None:
        """Return a post by ID."""

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        """Return recent posts, newest first."""

    def list_posts_by_author(self, author_agent_id: str, *, limit: int = 50) -> tuple[PostRecord, ...]:
        """Return an author's posts, newest first."""

    def put_follow(self, follow: FollowRecord) -> None:
        """Persist a follow edge."""

    def get_follow(self, follower_agent_id: str, followed_agent_id: str) -> FollowRecord | None:
        """Return a follow edge if it exists."""

    def list_follows_by_follower(self, follower_agent_id: str) -> tuple[FollowRecord, ...]:
        """Return the agents this agent follows."""

    def list_follows_by_followed(self, followed_agent_id: str) -> tuple[FollowRecord, ...]:
        """Return the agents following this agent."""

    def put_room(self, room: RoomRecord) -> None:
        """Persist a room."""

    def get_room(self, room_id: str) -> RoomRecord | None:
        """Return a room by ID."""

    def get_room_by_slug(self, slug: str) -> RoomRecord | None:
        """Return a room by its unique slug."""

    def put_room_membership(self, membership: RoomMembershipRecord) -> None:
        """Persist a room membership."""

    def get_room_membership(self, room_id: str, agent_id: str) -> RoomMembershipRecord | None:
        """Return a room membership if it exists."""

    def list_room_memberships_by_agent(self, agent_id: str) -> tuple[RoomMembershipRecord, ...]:
        """Return the rooms an agent belongs to."""

    def put_feed_event(self, event: FeedEventRecord) -> None:
        """Persist a feed event."""

    def list_feed_events(self, *, limit: int = 50) -> tuple[FeedEventRecord, ...]:
        """Return recent feed events, newest first."""

    def put_notification(self, notification: NotificationRecord) -> None:
        """Persist a notification."""

    def list_notifications_by_recipient(
        self,
        recipient_agent_id: str,
        *,
        limit: int = 50,
    ) -> tuple[NotificationRecord, ...]:
        """Return an agent's notifications, newest first."""
