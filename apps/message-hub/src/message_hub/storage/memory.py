from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from threading import RLock

from message_hub.domain.models import (
    Agent,
    Delivery,
    Message,
    RoutingRule,
    StoredPayload,
    TaskRecord,
    TaskResultRecord,
    TaskToolRequest,
    ToolGrant,
    ThreadRecord,
    ThreadSummary,
    utc_now,
)


class InMemoryMessageHubRepository:
    """Small repository for tests and local development."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._agents_by_id: dict[str, Agent] = {}
        self._agent_id_by_handle: dict[str, str] = {}
        self._messages_by_id: dict[str, Message] = {}
        self._message_ids_by_thread: dict[str, list[str]] = defaultdict(list)
        self._message_ids_by_sender: dict[str, list[str]] = defaultdict(list)
        self._message_ids_by_content_ref: dict[str, list[str]] = defaultdict(list)
        self._payloads_by_ref: dict[str, StoredPayload] = {}
        self._threads_by_id: dict[str, ThreadRecord] = {}
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
        self._tool_grants_by_id: dict[str, ToolGrant] = {}
        self._tool_grant_ids_by_task: dict[str, list[str]] = defaultdict(list)
        self._tool_requests_by_id: dict[str, TaskToolRequest] = {}
        self._tool_request_ids_by_task: dict[str, list[str]] = defaultdict(list)
        self._task_results_by_task: dict[str, list[TaskResultRecord]] = defaultdict(list)
        self._task_idempotency: dict[tuple[str, str], tuple[str, datetime | None]] = {}

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
