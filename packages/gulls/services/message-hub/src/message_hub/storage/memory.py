from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from threading import RLock

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
    RoutingRule,
    StoredPayload,
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
    utc_now,
)
from message_hub.storage.pagination import CursorPage, cursor_after, decode_cursor


class InMemoryMessageHubRepository:
    """Small repository for tests and local development."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._agents_by_id: dict[str, Agent] = {}
        self._agent_id_by_handle: dict[str, str] = {}
        self._agent_tokens_by_id: dict[str, AgentTokenRecord] = {}
        self._agent_token_ids_by_agent: dict[str, list[str]] = defaultdict(list)
        self._messages_by_id: dict[str, Message] = {}
        self._message_ids_by_thread: dict[str, list[str]] = defaultdict(list)
        self._message_ids_by_sender: dict[str, list[str]] = defaultdict(list)
        self._message_ids_by_content_ref: dict[str, list[str]] = defaultdict(list)
        self._payloads_by_ref: dict[str, StoredPayload] = {}
        self._threads_by_id: dict[str, ThreadRecord] = {}
        # Feed: the base one-to-many capability.
        self._posts_by_id: dict[str, PostRecord] = {}
        self._post_ids_by_author: dict[str, list[str]] = defaultdict(list)
        self._follows: dict[tuple[str, str], FollowRecord] = {}
        self._rooms_by_id: dict[str, RoomRecord] = {}
        self._room_id_by_slug: dict[str, str] = {}
        self._room_memberships: dict[tuple[str, str], RoomMembershipRecord] = {}
        self._feed_events_by_id: dict[str, FeedEventRecord] = {}
        self._notifications_by_id: dict[str, NotificationRecord] = {}
        self._deliveries_by_id: dict[str, Delivery] = {}
        self._delivery_ids_by_recipient: dict[str, list[str]] = defaultdict(list)
        self._delivery_ids_by_sender: dict[str, list[str]] = defaultdict(list)
        self._delivery_ids_by_message: dict[str, list[str]] = defaultdict(list)
        self._routing_rules_by_id: dict[str, RoutingRule] = {}
        self._routing_rule_ids: list[str] = []
        self._idempotency: dict[tuple[str, str], tuple[str, datetime | None]] = {}
        self._summaries_by_thread: dict[str, list[ThreadSummary]] = defaultdict(list)
        self._tasks_by_id: dict[str, TaskRecord] = {}
        self._task_ids_by_thread: dict[str, list[str]] = defaultdict(list)
        self._task_quotes_by_id: dict[str, TaskQuoteRecord] = {}
        self._task_quote_ids_by_task: dict[str, list[str]] = defaultdict(list)
        self._task_escrows_by_id: dict[str, TaskEscrowRecord] = {}
        self._task_escrow_ids_by_task: dict[str, list[str]] = defaultdict(list)
        self._task_capacity_policies_by_id: dict[str, TaskCapacitySharingPolicyRecord] = {}
        self._task_capacity_policy_ids_by_task: dict[str, list[str]] = defaultdict(list)
        self._task_credit_ledger_entries_by_id: dict[str, TaskCreditLedgerEntry] = {}
        self._task_credit_ledger_entry_ids_by_agent: dict[str, list[str]] = defaultdict(list)
        self._task_credit_ledger_entry_ids_by_task: dict[str, list[str]] = defaultdict(list)
        self._task_worker_reputation_events_by_id: dict[str, TaskWorkerReputationEventRecord] = {}
        self._task_worker_reputation_event_ids_by_worker: dict[str, list[str]] = defaultdict(list)
        self._task_worker_reputation_event_ids_by_task: dict[str, list[str]] = defaultdict(list)
        self._tool_grants_by_id: dict[str, ToolGrant] = {}
        self._tool_grant_ids_by_task: dict[str, list[str]] = defaultdict(list)
        self._tool_requests_by_id: dict[str, TaskToolRequest] = {}
        self._tool_request_ids_by_task: dict[str, list[str]] = defaultdict(list)
        self._task_results_by_task: dict[str, list[TaskResultRecord]] = defaultdict(list)
        self._task_idempotency: dict[tuple[str, str], tuple[str, datetime | None]] = {}
        # (scope_key, window_start_epoch) -> (count, ttl_epoch)
        self._guest_send_counts: dict[tuple[str, int], tuple[int, int]] = {}

    def add_agent(self, agent: Agent) -> None:
        with self._lock:
            if agent.agent_id in self._agents_by_id:
                raise ValueError(f"agent already exists: {agent.agent_id}")
            if agent.handle in self._agent_id_by_handle:
                raise ValueError(f"agent handle already exists: {agent.handle}")

            self._agents_by_id[agent.agent_id] = agent
            self._agent_id_by_handle[agent.handle] = agent.agent_id

    def get_agent(self, agent_id: str) -> Agent | None:
        with self._lock:
            return self._agents_by_id.get(agent_id)

    def get_agent_by_handle(self, handle: str) -> Agent | None:
        with self._lock:
            agent_id = self._agent_id_by_handle.get(handle)
            if agent_id is None:
                return None
            return self._agents_by_id[agent_id]

    def update_agent(self, agent: Agent) -> None:
        with self._lock:
            existing = self._agents_by_id.get(agent.agent_id)
            if existing is None:
                raise ValueError(f"agent does not exist: {agent.agent_id}")
            if existing.handle != agent.handle:
                raise ValueError(f"agent handle is immutable: {existing.handle}")
            self._agents_by_id[agent.agent_id] = agent

    def increment_guest_send_count(
        self,
        scope_key: str,
        window_start_epoch: int,
        *,
        ttl_epoch: int,
    ) -> int:
        now = int(time.time())
        with self._lock:
            expired = [
                key
                for key, (_, expires_at) in self._guest_send_counts.items()
                if expires_at <= now
            ]
            for key in expired:
                del self._guest_send_counts[key]

            key = (scope_key, int(window_start_epoch))
            count = self._guest_send_counts.get(key, (0, 0))[0] + 1
            self._guest_send_counts[key] = (count, int(ttl_epoch))
            return count

    def put_agent_token(self, token: AgentTokenRecord) -> None:
        with self._lock:
            if token.token_id in self._agent_tokens_by_id:
                raise ValueError(f"agent token already exists: {token.token_id}")
            self._agent_tokens_by_id[token.token_id] = token
            self._agent_token_ids_by_agent[token.agent_id].append(token.token_id)

    def get_agent_token(self, token_id: str) -> AgentTokenRecord | None:
        with self._lock:
            return self._agent_tokens_by_id.get(token_id)

    def update_agent_token(self, token: AgentTokenRecord) -> None:
        with self._lock:
            if token.token_id not in self._agent_tokens_by_id:
                raise ValueError(f"agent token does not exist: {token.token_id}")
            self._agent_tokens_by_id[token.token_id] = token

    def list_agent_tokens_by_agent(self, agent_id: str) -> tuple[AgentTokenRecord, ...]:
        with self._lock:
            tokens = [
                self._agent_tokens_by_id[token_id]
                for token_id in self._agent_token_ids_by_agent.get(agent_id, [])
                if token_id in self._agent_tokens_by_id
            ]

        tokens.sort(key=lambda token: (token.created_at, token.token_id), reverse=True)
        return tuple(tokens)

    def put_message(self, message: Message) -> None:
        with self._lock:
            if message.message_id in self._messages_by_id:
                raise ValueError(f"message already exists: {message.message_id}")

            self._messages_by_id[message.message_id] = message
            self._message_ids_by_thread[message.thread_id].append(message.message_id)
            self._message_ids_by_sender[message.sender_agent_id].append(message.message_id)
            if message.content_ref is not None:
                self._message_ids_by_content_ref[message.content_ref].append(message.message_id)

    def get_message(self, message_id: str) -> Message | None:
        with self._lock:
            return self._messages_by_id.get(message_id)

    def list_thread_messages(self, thread_id: str, *, limit: int | None = None) -> tuple[Message, ...]:
        with self._lock:
            messages = [
                self._messages_by_id[message_id]
                for message_id in self._message_ids_by_thread.get(thread_id, [])
            ]

        messages.sort(key=lambda message: (message.created_at, message.message_id))
        if limit is not None:
            messages = messages[-limit:]
        return tuple(messages)

    def list_thread_messages_page(
        self, thread_id: str, *, limit: int, cursor: str | None = None
    ) -> CursorPage[Message]:
        if limit < 1:
            raise ValueError("limit must be positive")
        position = decode_cursor(cursor, kind="thread", scope=thread_id)
        with self._lock:
            messages = [
                self._messages_by_id[message_id]
                for message_id in self._message_ids_by_thread.get(thread_id, [])
            ]
        messages.sort(key=lambda message: (message.created_at, message.message_id))
        if position is not None:
            messages = [
                message
                for message in messages
                if (message.created_at.isoformat(), message.message_id)
                < (position.created_at, position.record_id)
            ]
        page = messages[-limit:]
        has_more = len(messages) > len(page)
        next_cursor = None
        if has_more and page:
            oldest = page[0]
            next_cursor = cursor_after(
                kind="thread",
                scope=thread_id,
                created_at=oldest.created_at,
                record_id=oldest.message_id,
            )
        return CursorPage(tuple(page), next_cursor)

    def list_messages_by_sender(self, sender_agent_id: str, *, limit: int | None = None) -> tuple[Message, ...]:
        with self._lock:
            messages = [
                self._messages_by_id[message_id]
                for message_id in self._message_ids_by_sender.get(sender_agent_id, [])
            ]

        messages.sort(key=lambda message: (message.created_at, message.message_id), reverse=True)
        if limit is not None:
            messages = messages[:limit]
        return tuple(messages)

    def list_messages_by_content_ref(self, content_ref: str) -> tuple[Message, ...]:
        with self._lock:
            messages = [
                self._messages_by_id[message_id]
                for message_id in self._message_ids_by_content_ref.get(content_ref, [])
            ]

        messages.sort(key=lambda message: (message.created_at, message.message_id))
        return tuple(messages)

    def put_payload(self, payload: StoredPayload) -> None:
        with self._lock:
            content_ref = payload.record.content_ref
            if content_ref in self._payloads_by_ref:
                raise ValueError(f"payload already exists: {content_ref}")
            self._payloads_by_ref[content_ref] = payload

    def get_payload(self, content_ref: str) -> StoredPayload | None:
        with self._lock:
            return self._payloads_by_ref.get(content_ref)

    def list_payloads(self, *, limit: int | None = None) -> tuple[StoredPayload, ...]:
        with self._lock:
            payloads = list(self._payloads_by_ref.values())

        payloads.sort(key=lambda payload: (payload.record.created_at, payload.record.content_ref))
        if limit is not None:
            payloads = payloads[:limit]
        return tuple(payloads)

    def update_payload(self, payload: StoredPayload) -> None:
        with self._lock:
            content_ref = payload.record.content_ref
            if content_ref not in self._payloads_by_ref:
                raise ValueError(f"payload does not exist: {content_ref}")
            self._payloads_by_ref[content_ref] = payload

    def put_thread(self, thread: ThreadRecord) -> None:
        with self._lock:
            self._threads_by_id[thread.thread_id] = thread

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        with self._lock:
            return self._threads_by_id.get(thread_id)

    def put_delivery(self, delivery: Delivery) -> None:
        with self._lock:
            if delivery.delivery_id in self._deliveries_by_id:
                raise ValueError(f"delivery already exists: {delivery.delivery_id}")

            self._deliveries_by_id[delivery.delivery_id] = delivery
            self._delivery_ids_by_recipient[delivery.recipient_agent_id].append(delivery.delivery_id)
            self._delivery_ids_by_sender[delivery.sender_agent_id].append(delivery.delivery_id)
            self._delivery_ids_by_message[delivery.message_id].append(delivery.delivery_id)

    def get_delivery(self, delivery_id: str) -> Delivery | None:
        with self._lock:
            return self._deliveries_by_id.get(delivery_id)

    def list_deliveries_by_recipient(
        self,
        recipient_agent_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Delivery, ...]:
        return self._list_deliveries(self._delivery_ids_by_recipient.get(recipient_agent_id, []), limit)

    def list_deliveries_by_recipient_page(
        self, recipient_agent_id: str, *, limit: int, cursor: str | None = None
    ) -> CursorPage[Delivery]:
        if limit < 1:
            raise ValueError("limit must be positive")
        position = decode_cursor(cursor, kind="inbox", scope=recipient_agent_id)
        with self._lock:
            deliveries = [
                self._deliveries_by_id[delivery_id]
                for delivery_id in self._delivery_ids_by_recipient.get(recipient_agent_id, [])
                if delivery_id in self._deliveries_by_id
            ]
        deliveries.sort(key=lambda delivery: (delivery.created_at, delivery.delivery_id), reverse=True)
        if position is not None:
            deliveries = [
                delivery
                for delivery in deliveries
                if (delivery.created_at.isoformat(), delivery.delivery_id)
                < (position.created_at, position.record_id)
            ]
        page = deliveries[:limit]
        next_cursor = None
        if len(deliveries) > len(page) and page:
            last = page[-1]
            next_cursor = cursor_after(
                kind="inbox",
                scope=recipient_agent_id,
                created_at=last.created_at,
                record_id=last.delivery_id,
            )
        return CursorPage(tuple(page), next_cursor)

    def list_deliveries_by_sender(
        self,
        sender_agent_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Delivery, ...]:
        return self._list_deliveries(self._delivery_ids_by_sender.get(sender_agent_id, []), limit)

    def list_deliveries_by_message(self, message_id: str) -> tuple[Delivery, ...]:
        return self._list_deliveries(self._delivery_ids_by_message.get(message_id, []), None)

    def update_delivery(self, delivery: Delivery) -> None:
        with self._lock:
            if delivery.delivery_id not in self._deliveries_by_id:
                raise ValueError(f"delivery does not exist: {delivery.delivery_id}")
            self._deliveries_by_id[delivery.delivery_id] = delivery

    def put_routing_rule(self, rule: RoutingRule) -> None:
        with self._lock:
            if rule.rule_id not in self._routing_rules_by_id:
                self._routing_rule_ids.append(rule.rule_id)
            self._routing_rules_by_id[rule.rule_id] = rule

    def list_routing_rules(self) -> tuple[RoutingRule, ...]:
        with self._lock:
            return tuple(
                self._routing_rules_by_id[rule_id]
                for rule_id in self._routing_rule_ids
                if rule_id in self._routing_rules_by_id
            )

    def get_idempotent_message_id(self, sender_agent_id: str, idempotency_key: str) -> str | None:
        key = (sender_agent_id, idempotency_key)
        with self._lock:
            value = self._idempotency.get(key)
            if value is None:
                return None

            message_id, expires_at = value
            if expires_at is not None and expires_at <= utc_now():
                del self._idempotency[key]
                return None

            return message_id

    def put_idempotency_key(
        self,
        sender_agent_id: str,
        idempotency_key: str,
        message_id: str,
        *,
        expires_at: datetime | None = None,
    ) -> None:
        with self._lock:
            self._idempotency[(sender_agent_id, idempotency_key)] = (message_id, expires_at)

    def put_thread_summary(self, summary: ThreadSummary) -> None:
        with self._lock:
            self._summaries_by_thread[summary.thread_id].append(summary)

    def get_latest_thread_summary(self, thread_id: str) -> ThreadSummary | None:
        with self._lock:
            summaries = list(self._summaries_by_thread.get(thread_id, []))

        if not summaries:
            return None

        summaries.sort(key=lambda summary: (summary.created_at, summary.summary_id))
        return summaries[-1]

    def put_task(self, task: TaskRecord) -> None:
        with self._lock:
            if task.task_id in self._tasks_by_id:
                raise ValueError(f"task already exists: {task.task_id}")
            self._tasks_by_id[task.task_id] = task
            self._task_ids_by_thread[task.thread_id].append(task.task_id)

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks_by_id.get(task_id)

    def update_task(self, task: TaskRecord) -> None:
        with self._lock:
            if task.task_id not in self._tasks_by_id:
                raise ValueError(f"task does not exist: {task.task_id}")
            self._tasks_by_id[task.task_id] = task

    def list_tasks_by_requester(
        self, requester_agent_id: str, *, limit: int | None = None
    ) -> tuple[TaskRecord, ...]:
        return self._list_tasks_by(
            lambda task: task.requester_agent_id == requester_agent_id, limit
        )

    def list_tasks_by_worker(
        self, worker_agent_id: str, *, limit: int | None = None
    ) -> tuple[TaskRecord, ...]:
        # "Worker" is whoever the request is addressed to; accepted_by is only
        # set once someone picks it up, so match either.
        return self._list_tasks_by(
            lambda task: worker_agent_id in (task.recipient_agent_id, task.accepted_by_agent_id),
            limit,
        )

    def _list_tasks_by(self, predicate, limit: int | None) -> tuple[TaskRecord, ...]:
        with self._lock:
            tasks = [task for task in self._tasks_by_id.values() if predicate(task)]
        tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
        if limit is not None:
            tasks = tasks[:limit]
        return tuple(tasks)

    def list_tasks_by_thread(self, thread_id: str, *, limit: int | None = None) -> tuple[TaskRecord, ...]:
        with self._lock:
            tasks = [
                self._tasks_by_id[task_id]
                for task_id in self._task_ids_by_thread.get(thread_id, [])
                if task_id in self._tasks_by_id
            ]

        tasks.sort(key=lambda task: (task.created_at, task.task_id))
        if limit is not None:
            tasks = tasks[-limit:]
        return tuple(tasks)

    def put_task_quote(self, quote: TaskQuoteRecord) -> None:
        with self._lock:
            if quote.quote_id in self._task_quotes_by_id:
                raise ValueError(f"task quote already exists: {quote.quote_id}")
            self._task_quotes_by_id[quote.quote_id] = quote
            self._task_quote_ids_by_task[quote.task_id].append(quote.quote_id)

    def get_task_quote(self, quote_id: str) -> TaskQuoteRecord | None:
        with self._lock:
            return self._task_quotes_by_id.get(quote_id)

    def update_task_quote(self, quote: TaskQuoteRecord) -> None:
        with self._lock:
            if quote.quote_id not in self._task_quotes_by_id:
                raise ValueError(f"task quote does not exist: {quote.quote_id}")
            self._task_quotes_by_id[quote.quote_id] = quote

    def list_task_quotes_by_task(self, task_id: str) -> tuple[TaskQuoteRecord, ...]:
        with self._lock:
            quotes = [
                self._task_quotes_by_id[quote_id]
                for quote_id in self._task_quote_ids_by_task.get(task_id, [])
                if quote_id in self._task_quotes_by_id
            ]

        quotes.sort(key=lambda quote: (quote.created_at, quote.quote_id))
        return tuple(quotes)

    def put_task_escrow(self, escrow: TaskEscrowRecord) -> None:
        with self._lock:
            if escrow.escrow_id in self._task_escrows_by_id:
                raise ValueError(f"task escrow already exists: {escrow.escrow_id}")
            self._task_escrows_by_id[escrow.escrow_id] = escrow
            self._task_escrow_ids_by_task[escrow.task_id].append(escrow.escrow_id)

    def get_task_escrow(self, escrow_id: str) -> TaskEscrowRecord | None:
        with self._lock:
            return self._task_escrows_by_id.get(escrow_id)

    def update_task_escrow(self, escrow: TaskEscrowRecord) -> None:
        with self._lock:
            if escrow.escrow_id not in self._task_escrows_by_id:
                raise ValueError(f"task escrow does not exist: {escrow.escrow_id}")
            self._task_escrows_by_id[escrow.escrow_id] = escrow

    def list_task_escrows_by_task(self, task_id: str) -> tuple[TaskEscrowRecord, ...]:
        with self._lock:
            escrows = [
                self._task_escrows_by_id[escrow_id]
                for escrow_id in self._task_escrow_ids_by_task.get(task_id, [])
                if escrow_id in self._task_escrows_by_id
            ]

        escrows.sort(key=lambda escrow: (escrow.created_at, escrow.escrow_id))
        return tuple(escrows)

    def put_task_capacity_policy(self, policy: TaskCapacitySharingPolicyRecord) -> None:
        with self._lock:
            if policy.policy_id in self._task_capacity_policies_by_id:
                raise ValueError(f"task capacity policy already exists: {policy.policy_id}")
            self._task_capacity_policies_by_id[policy.policy_id] = policy
            self._task_capacity_policy_ids_by_task[policy.task_id].append(policy.policy_id)

    def get_task_capacity_policy(self, policy_id: str) -> TaskCapacitySharingPolicyRecord | None:
        with self._lock:
            return self._task_capacity_policies_by_id.get(policy_id)

    def list_task_capacity_policies_by_task(
        self,
        task_id: str,
    ) -> tuple[TaskCapacitySharingPolicyRecord, ...]:
        with self._lock:
            policies = [
                self._task_capacity_policies_by_id[policy_id]
                for policy_id in self._task_capacity_policy_ids_by_task.get(task_id, [])
                if policy_id in self._task_capacity_policies_by_id
            ]

        policies.sort(key=lambda policy: (policy.created_at, policy.policy_id))
        return tuple(policies)

    def put_task_credit_ledger_entry(self, entry: TaskCreditLedgerEntry) -> None:
        with self._lock:
            if entry.entry_id in self._task_credit_ledger_entries_by_id:
                raise ValueError(f"task credit ledger entry already exists: {entry.entry_id}")
            self._task_credit_ledger_entries_by_id[entry.entry_id] = entry
            self._task_credit_ledger_entry_ids_by_agent[entry.account_agent_id].append(entry.entry_id)
            if entry.task_id is not None:
                self._task_credit_ledger_entry_ids_by_task[entry.task_id].append(entry.entry_id)

    def get_task_credit_ledger_entry(self, entry_id: str) -> TaskCreditLedgerEntry | None:
        with self._lock:
            return self._task_credit_ledger_entries_by_id.get(entry_id)

    def list_task_credit_ledger_entries_by_agent(
        self,
        account_agent_id: str,
    ) -> tuple[TaskCreditLedgerEntry, ...]:
        with self._lock:
            entries = [
                self._task_credit_ledger_entries_by_id[entry_id]
                for entry_id in self._task_credit_ledger_entry_ids_by_agent.get(account_agent_id, [])
                if entry_id in self._task_credit_ledger_entries_by_id
            ]

        entries.sort(key=lambda entry: (entry.created_at, entry.entry_id))
        return tuple(entries)

    def list_task_credit_ledger_entries_by_task(self, task_id: str) -> tuple[TaskCreditLedgerEntry, ...]:
        with self._lock:
            entries = [
                self._task_credit_ledger_entries_by_id[entry_id]
                for entry_id in self._task_credit_ledger_entry_ids_by_task.get(task_id, [])
                if entry_id in self._task_credit_ledger_entries_by_id
            ]

        entries.sort(key=lambda entry: (entry.created_at, entry.entry_id))
        return tuple(entries)

    def put_task_worker_reputation_event(self, event: TaskWorkerReputationEventRecord) -> None:
        with self._lock:
            if event.event_id in self._task_worker_reputation_events_by_id:
                raise ValueError(f"task worker reputation event already exists: {event.event_id}")
            self._task_worker_reputation_events_by_id[event.event_id] = event
            self._task_worker_reputation_event_ids_by_worker[event.worker_agent_id].append(event.event_id)
            self._task_worker_reputation_event_ids_by_task[event.task_id].append(event.event_id)

    def get_task_worker_reputation_event(
        self,
        event_id: str,
    ) -> TaskWorkerReputationEventRecord | None:
        with self._lock:
            return self._task_worker_reputation_events_by_id.get(event_id)

    def list_task_worker_reputation_events_by_worker(
        self,
        worker_agent_id: str,
    ) -> tuple[TaskWorkerReputationEventRecord, ...]:
        with self._lock:
            events = [
                self._task_worker_reputation_events_by_id[event_id]
                for event_id in self._task_worker_reputation_event_ids_by_worker.get(worker_agent_id, [])
                if event_id in self._task_worker_reputation_events_by_id
            ]

        events.sort(key=lambda event: (event.created_at, event.event_id))
        return tuple(events)

    def list_task_worker_reputation_events_by_task(
        self,
        task_id: str,
    ) -> tuple[TaskWorkerReputationEventRecord, ...]:
        with self._lock:
            events = [
                self._task_worker_reputation_events_by_id[event_id]
                for event_id in self._task_worker_reputation_event_ids_by_task.get(task_id, [])
                if event_id in self._task_worker_reputation_events_by_id
            ]

        events.sort(key=lambda event: (event.created_at, event.event_id))
        return tuple(events)

    def put_tool_grant(self, grant: ToolGrant) -> None:
        with self._lock:
            if grant.grant_id in self._tool_grants_by_id:
                raise ValueError(f"tool grant already exists: {grant.grant_id}")
            self._tool_grants_by_id[grant.grant_id] = grant
            self._tool_grant_ids_by_task[grant.task_id].append(grant.grant_id)

    def get_tool_grant(self, grant_id: str) -> ToolGrant | None:
        with self._lock:
            return self._tool_grants_by_id.get(grant_id)

    def update_tool_grant(self, grant: ToolGrant) -> None:
        with self._lock:
            if grant.grant_id not in self._tool_grants_by_id:
                raise ValueError(f"tool grant does not exist: {grant.grant_id}")
            self._tool_grants_by_id[grant.grant_id] = grant

    def list_tool_grants_by_task(self, task_id: str) -> tuple[ToolGrant, ...]:
        with self._lock:
            grants = [
                self._tool_grants_by_id[grant_id]
                for grant_id in self._tool_grant_ids_by_task.get(task_id, [])
                if grant_id in self._tool_grants_by_id
            ]

        grants.sort(key=lambda grant: (grant.created_at, grant.grant_id))
        return tuple(grants)

    def put_tool_request(self, tool_request: TaskToolRequest) -> None:
        with self._lock:
            if tool_request.tool_request_id in self._tool_requests_by_id:
                raise ValueError(f"tool request already exists: {tool_request.tool_request_id}")
            self._tool_requests_by_id[tool_request.tool_request_id] = tool_request
            self._tool_request_ids_by_task[tool_request.task_id].append(tool_request.tool_request_id)

    def get_tool_request(self, tool_request_id: str) -> TaskToolRequest | None:
        with self._lock:
            return self._tool_requests_by_id.get(tool_request_id)

    def update_tool_request(self, tool_request: TaskToolRequest) -> None:
        with self._lock:
            if tool_request.tool_request_id not in self._tool_requests_by_id:
                raise ValueError(f"tool request does not exist: {tool_request.tool_request_id}")
            self._tool_requests_by_id[tool_request.tool_request_id] = tool_request

    def list_tool_requests_by_task(self, task_id: str) -> tuple[TaskToolRequest, ...]:
        with self._lock:
            tool_requests = [
                self._tool_requests_by_id[tool_request_id]
                for tool_request_id in self._tool_request_ids_by_task.get(task_id, [])
                if tool_request_id in self._tool_requests_by_id
            ]

        tool_requests.sort(key=lambda tool_request: (tool_request.created_at, tool_request.tool_request_id))
        return tuple(tool_requests)

    def put_task_result(self, result: TaskResultRecord) -> None:
        with self._lock:
            self._task_results_by_task[result.task_id].append(result)

    def list_task_results(self, task_id: str) -> tuple[TaskResultRecord, ...]:
        with self._lock:
            results = list(self._task_results_by_task.get(task_id, []))

        results.sort(key=lambda result: (result.created_at, result.result_id))
        return tuple(results)

    def get_idempotent_task_id(self, requester_agent_id: str, idempotency_key: str) -> str | None:
        key = (requester_agent_id, idempotency_key)
        with self._lock:
            value = self._task_idempotency.get(key)
            if value is None:
                return None

            task_id, expires_at = value
            if expires_at is not None and expires_at <= utc_now():
                del self._task_idempotency[key]
                return None

            return task_id

    def put_task_idempotency_key(
        self,
        requester_agent_id: str,
        idempotency_key: str,
        task_id: str,
        *,
        expires_at: datetime | None = None,
    ) -> None:
        with self._lock:
            self._task_idempotency[(requester_agent_id, idempotency_key)] = (task_id, expires_at)

    def _list_deliveries(self, delivery_ids: list[str], limit: int | None) -> tuple[Delivery, ...]:
        with self._lock:
            deliveries = [
                self._deliveries_by_id[delivery_id]
                for delivery_id in delivery_ids
                if delivery_id in self._deliveries_by_id
            ]

        deliveries.sort(
            key=lambda delivery: (delivery.created_at, delivery.delivery_id),
            reverse=True,
        )
        if limit is not None:
            deliveries = deliveries[:limit]
        return tuple(deliveries)

    # --- Feed -----------------------------------------------------------------

    def put_post(self, post: PostRecord) -> None:
        with self._lock:
            if post.post_id not in self._posts_by_id:
                self._post_ids_by_author[post.author_agent_id].append(post.post_id)
            self._posts_by_id[post.post_id] = post

    def get_post(self, post_id: str) -> PostRecord | None:
        with self._lock:
            return self._posts_by_id.get(post_id)

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        with self._lock:
            posts = list(self._posts_by_id.values())
        return _newest_first(posts, lambda post: (post.created_at, post.post_id), limit)

    def list_posts_by_author(self, author_agent_id: str, *, limit: int = 50) -> tuple[PostRecord, ...]:
        with self._lock:
            posts = [
                self._posts_by_id[post_id]
                for post_id in self._post_ids_by_author.get(author_agent_id, [])
                if post_id in self._posts_by_id
            ]
        return _newest_first(posts, lambda post: (post.created_at, post.post_id), limit)

    def put_follow(self, follow: FollowRecord) -> None:
        with self._lock:
            self._follows[(follow.follower_agent_id, follow.followed_agent_id)] = follow

    def get_follow(self, follower_agent_id: str, followed_agent_id: str) -> FollowRecord | None:
        with self._lock:
            return self._follows.get((follower_agent_id, followed_agent_id))

    def list_follows_by_follower(self, follower_agent_id: str) -> tuple[FollowRecord, ...]:
        with self._lock:
            follows = [
                follow
                for (follower, _), follow in self._follows.items()
                if follower == follower_agent_id
            ]
        follows.sort(key=lambda follow: (follow.created_at, follow.followed_agent_id))
        return tuple(follows)

    def list_follows_by_followed(self, followed_agent_id: str) -> tuple[FollowRecord, ...]:
        with self._lock:
            follows = [
                follow
                for (_, followed), follow in self._follows.items()
                if followed == followed_agent_id
            ]
        follows.sort(key=lambda follow: (follow.created_at, follow.follower_agent_id))
        return tuple(follows)

    def put_room(self, room: RoomRecord) -> None:
        with self._lock:
            self._rooms_by_id[room.room_id] = room
            self._room_id_by_slug[room.slug] = room.room_id

    def get_room(self, room_id: str) -> RoomRecord | None:
        with self._lock:
            return self._rooms_by_id.get(room_id)

    def get_room_by_slug(self, slug: str) -> RoomRecord | None:
        with self._lock:
            room_id = self._room_id_by_slug.get(slug)
            return None if room_id is None else self._rooms_by_id.get(room_id)

    def put_room_membership(self, membership: RoomMembershipRecord) -> None:
        with self._lock:
            self._room_memberships[(membership.room_id, membership.agent_id)] = membership

    def get_room_membership(self, room_id: str, agent_id: str) -> RoomMembershipRecord | None:
        with self._lock:
            return self._room_memberships.get((room_id, agent_id))

    def list_room_memberships_by_agent(self, agent_id: str) -> tuple[RoomMembershipRecord, ...]:
        with self._lock:
            memberships = [
                membership
                for (_, member_agent_id), membership in self._room_memberships.items()
                if member_agent_id == agent_id
            ]
        memberships.sort(key=lambda membership: (membership.created_at, membership.room_id))
        return tuple(memberships)

    def put_feed_event(self, event: FeedEventRecord) -> None:
        with self._lock:
            self._feed_events_by_id[event.event_id] = event

    def list_feed_events(self, *, limit: int = 50) -> tuple[FeedEventRecord, ...]:
        with self._lock:
            events = list(self._feed_events_by_id.values())
        return _newest_first(events, lambda event: (event.created_at, event.event_id), limit)

    def put_notification(self, notification: NotificationRecord) -> None:
        with self._lock:
            self._notifications_by_id[notification.notification_id] = notification

    def list_notifications_by_recipient(
        self,
        recipient_agent_id: str,
        *,
        limit: int = 50,
    ) -> tuple[NotificationRecord, ...]:
        with self._lock:
            notifications = [
                notification
                for notification in self._notifications_by_id.values()
                if notification.recipient_agent_id == recipient_agent_id
            ]
        return _newest_first(
            notifications,
            lambda notification: (notification.created_at, notification.notification_id),
            limit,
        )


def _newest_first(records, key, limit):
    """Sort newest-first and apply a limit, matching the hub's list ordering."""
    records.sort(key=key, reverse=True)
    if limit is not None:
        records = records[:limit]
    return tuple(records)
