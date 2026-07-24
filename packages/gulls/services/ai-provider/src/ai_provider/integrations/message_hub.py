from __future__ import annotations

from dataclasses import dataclass
from ai_provider.domain import AiProviderService, AiRun, AiRunState

from message_hub.domain import MessageHubService, TaskRecord, TaskResultRecord, TaskState


APPROVED_TASK_STATES = frozenset(
    {
        TaskState.APPROVED,
        TaskState.ESCROWED,
        TaskState.ACCEPTED,
        TaskState.RUNNING,
    }
)


class AiTaskNotApprovedError(Exception):
    """Raised when a message-hub task is not approved for AI execution."""


@dataclass(frozen=True, slots=True)
class AiTaskRunResult:
    run: AiRun
    task_result: TaskResultRecord | None = None


class MessageHubAiTaskRunner:
    """Run approved message-hub tasks through the AI provider service."""

    def __init__(self, ai_provider: AiProviderService, message_hub: MessageHubService) -> None:
        self._ai_provider = ai_provider
        self._message_hub = message_hub

    def run_task(
        self,
        task_id: str,
        *,
        provider: str,
        model: str,
        responder_handle: str,
        owner_user_id: str,
        system_instructions: str | None = None,
        system_instructions_ref: str | None = None,
        max_output_tokens: int = 512,
        temperature: float = 0.2,
        response_format: str = "text",
        tool_policy: str = "disabled",
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> AiTaskRunResult:
        task = self._message_hub.get_task(task_id)
        if task.state not in APPROVED_TASK_STATES:
            raise AiTaskNotApprovedError(f"task is not approved for AI execution: {task.task_id}")

        run = self._ai_provider.create_run(
            provider=provider,
            model=model,
            actor_agent_id=task.accepted_by_agent_id or task.recipient_agent_id,
            owner_user_id=owner_user_id,
            input_messages=({"role": "user", "content": task.objective},),
            system_instructions=system_instructions,
            system_instructions_ref=system_instructions_ref,
            context_refs=task_context_refs(task),
            content_ref=task.input_ref,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            response_format=response_format,
            tool_policy=tool_policy,
            task_id=task.task_id,
            message_id=task.request_message_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key or f"message-hub-task:{task.task_id}",
        )
        if run.state != AiRunState.COMPLETED:
            return AiTaskRunResult(run=run)

        result = self._message_hub.return_task_result(
            task.task_id,
            responder_handle=responder_handle,
            content=None if run.output_ref is not None else run.output_text,
            content_ref=run.output_ref,
            artifact_refs=(f"seagull://ai-runs/{run.run_id}",),
        )
        return AiTaskRunResult(run=run, task_result=result)


def task_context_refs(task: TaskRecord) -> tuple[str, ...]:
    refs: list[str] = []
    refs.extend(ref for ref in task.context_refs if ref)
    if task.context_pack_ref:
        refs.append(task.context_pack_ref)
    return tuple(refs)
