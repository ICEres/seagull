from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from ai_provider.domain.models import (
    AdminAuditEvent,
    AiRun,
    AiRunEvent,
    AiRunState,
    BudgetLimit,
    ModelPolicy,
    ProviderConfig,
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ServerCreditBalance,
    ServerCreditLedgerEntry,
    ServerCreditLedgerEntryType,
    UsageRecord,
    UserCreditBalance,
    UserCreditLedgerEntry,
    UserCreditLedgerEntryType,
    utc_now,
)
from ai_provider.providers.base import AiProviderAdapter
from ai_provider.storage.repository import AiProviderRepository


IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]

DEFAULT_MAX_OUTPUT_TOKENS = 512
DEFAULT_COST_UNIT_PER_TOKEN = 1


class AiProviderServiceError(Exception):
    """Base error for AI provider domain failures."""


class InvalidAiRunError(AiProviderServiceError):
    """Raised when an AI run request is invalid."""


class AiProviderService:
    def __init__(
        self,
        repository: AiProviderRepository,
        providers: Mapping[str, AiProviderAdapter],
        *,
        id_factory: IdFactory | None = None,
        clock: Clock = utc_now,
        blocked_input_terms: Sequence[str] = (),
        unsafe_output_terms: Sequence[str] = (),
    ) -> None:
        self._repository = repository
        self._providers = dict(providers)
        self._id_factory = id_factory or self._default_id_factory
        self._clock = clock
        self._blocked_input_terms = tuple(term.strip().casefold() for term in blocked_input_terms if term.strip())
        self._unsafe_output_terms = tuple(term.strip().casefold() for term in unsafe_output_terms if term.strip())

    def create_run(
        self,
        *,
        provider: str,
        model: str,
        actor_agent_id: str,
        owner_user_id: str,
        input_messages: Sequence[ProviderMessage | dict[str, str]],
        system_instructions: str | None = None,
        system_instructions_ref: str | None = None,
        context_refs: Sequence[str] = (),
        content_ref: str | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        temperature: float = 0.2,
        response_format: str = "text",
        tool_policy: str = "disabled",
        task_id: str | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> AiRun:
        request = normalize_provider_request(
            provider=provider,
            model=model,
            actor_agent_id=actor_agent_id,
            owner_user_id=owner_user_id,
            input_messages=input_messages,
            system_instructions=system_instructions,
            system_instructions_ref=system_instructions_ref,
            context_refs=context_refs,
            content_ref=content_ref,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            response_format=response_format,
            tool_policy=tool_policy,
            task_id=task_id,
            message_id=message_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
        )
        if request.provider not in self._providers:
            raise InvalidAiRunError(f"provider is not configured: {request.provider}")

        now = self._clock()
        run = AiRun(
            run_id=self._new_id("airun"),
            provider=request.provider,
            model=request.model,
            actor_agent_id=request.actor_agent_id,
            owner_user_id=request.owner_user_id,
            task_id=request.task_id,
            message_id=request.message_id,
            input_ref=request.content_ref,
            trace_id=request.trace_id,
            created_at=now,
            updated_at=now,
        )
        self._repository.put_run(run)
        self._append_event(run, AiRunState.REQUESTED, "run requested")

        denial = self._preflight_denial(request)
        if denial is not None:
            return self._deny(run, denial)

        run = self._transition(run, AiRunState.SAFETY_CHECKED, "preflight safety and policy checks passed")
        run = self._transition(run, AiRunState.QUEUED, "local run queued")
        run = self._transition(run, AiRunState.RUNNING, "provider call started")

        try:
            response = self._providers[request.provider].generate(request)
        except Exception as exc:
            return self._fail(run, f"provider call failed: {exc}")

        usage = self._record_usage(run, response)
        self._charge_user_credits(run, usage)
        run = replace(
            run,
            provider_run_id=response.provider_run_id,
            finish_reason=response.finish_reason,
            output_text=clean_optional(response.output_text),
            output_ref=clean_optional(response.output_ref),
            usage_id=usage.usage_id,
            updated_at=self._clock(),
        )
        self._repository.put_run(run)

        output_safety_reason = self._output_safety_reason(response)
        if output_safety_reason is not None:
            run = self._transition(
                run,
                AiRunState.OUTPUT_CHECKED,
                "provider output checked",
                usage_id=usage.usage_id,
            )
            return self._quarantine(run, output_safety_reason, usage.usage_id)

        run = self._transition(
            run,
            AiRunState.OUTPUT_CHECKED,
            "provider output checked",
            usage_id=usage.usage_id,
        )
        return self._transition(run, AiRunState.COMPLETED, "run completed", usage_id=usage.usage_id)

    def get_run(self, run_id: str) -> AiRun:
        normalized_run_id = normalized_required(run_id, "run_id")
        run = self._repository.get_run(normalized_run_id)
        if run is None:
            raise InvalidAiRunError(f"AI run not found: {normalized_run_id}")
        return run

    def list_run_events(self, run_id: str) -> tuple[AiRunEvent, ...]:
        normalized_run_id = normalized_required(run_id, "run_id")
        return self._repository.list_run_events(normalized_run_id)

    def list_usage_by_owner(self, owner_user_id: str) -> tuple[UsageRecord, ...]:
        return self._repository.list_usage_by_owner(normalized_required(owner_user_id, "owner_user_id"))

    def list_usage_by_agent(self, agent_id: str) -> tuple[UsageRecord, ...]:
        return self._repository.list_usage_by_agent(normalized_required(agent_id, "agent_id"))

    def grant_user_credits(
        self,
        *,
        admin_actor_id: str,
        owner_user_id: str,
        credit_amount: int,
        reason: str = "manual credit grant",
    ) -> UserCreditLedgerEntry:
        normalized_admin_actor_id = normalized_required(admin_actor_id, "admin_actor_id")
        normalized_owner_user_id = normalized_required(owner_user_id, "owner_user_id")
        normalized_reason = normalized_required(reason, "reason")
        if credit_amount <= 0:
            raise InvalidAiRunError("credit_amount must be greater than zero")
        server_balance = self.get_server_credit_balance()
        if server_balance.available_credits < credit_amount:
            raise InvalidAiRunError("insufficient server credits for user grant")
        entry = UserCreditLedgerEntry(
            entry_id=self._new_id("credit"),
            owner_user_id=normalized_owner_user_id,
            entry_type=UserCreditLedgerEntryType.CREDIT_GRANT,
            credit_delta=credit_amount,
            reason=normalized_reason,
            created_at=self._clock(),
        )
        self._repository.append_user_credit_ledger_entry(entry)
        server_entry = ServerCreditLedgerEntry(
            entry_id=self._new_id("server_credit"),
            entry_type=ServerCreditLedgerEntryType.USER_CREDIT_GRANT,
            credit_delta=-credit_amount,
            reason=normalized_reason,
            admin_actor_id=normalized_admin_actor_id,
            owner_user_id=normalized_owner_user_id,
            user_credit_entry_id=entry.entry_id,
            created_at=self._clock(),
        )
        self._repository.append_server_credit_ledger_entry(server_entry)
        self._append_admin_audit_event(
            admin_actor_id=normalized_admin_actor_id,
            action="ai.user_credit_grant",
            target_type="owner_user",
            target_id=normalized_owner_user_id,
            reason=normalized_reason,
            metadata={"credit_amount": str(credit_amount), "user_credit_entry_id": entry.entry_id},
        )
        return entry

    def grant_server_credits(
        self,
        *,
        admin_actor_id: str,
        credit_amount: int,
        reason: str = "server credit grant",
    ) -> ServerCreditLedgerEntry:
        normalized_admin_actor_id = normalized_required(admin_actor_id, "admin_actor_id")
        normalized_reason = normalized_required(reason, "reason")
        if credit_amount <= 0:
            raise InvalidAiRunError("credit_amount must be greater than zero")
        entry = ServerCreditLedgerEntry(
            entry_id=self._new_id("server_credit"),
            entry_type=ServerCreditLedgerEntryType.CREDIT_GRANT,
            credit_delta=credit_amount,
            reason=normalized_reason,
            admin_actor_id=normalized_admin_actor_id,
            created_at=self._clock(),
        )
        self._repository.append_server_credit_ledger_entry(entry)
        self._append_admin_audit_event(
            admin_actor_id=normalized_admin_actor_id,
            action="ai.server_credit_grant",
            target_type="server_credit_pool",
            target_id="server",
            reason=normalized_reason,
            metadata={"credit_amount": str(credit_amount)},
        )
        return entry

    def get_server_credit_balance(self) -> ServerCreditBalance:
        return ServerCreditBalance(
            available_credits=sum(entry.credit_delta for entry in self._repository.list_server_credit_ledger())
        )

    def list_server_credit_ledger(self) -> tuple[ServerCreditLedgerEntry, ...]:
        return self._repository.list_server_credit_ledger()

    def get_user_credit_balance(self, owner_user_id: str) -> UserCreditBalance:
        normalized_owner_user_id = normalized_required(owner_user_id, "owner_user_id")
        return UserCreditBalance(
            owner_user_id=normalized_owner_user_id,
            available_credits=sum(
                entry.credit_delta
                for entry in self._repository.list_user_credit_ledger_by_owner(normalized_owner_user_id)
            ),
        )

    def list_user_credit_ledger(self, owner_user_id: str) -> tuple[UserCreditLedgerEntry, ...]:
        return self._repository.list_user_credit_ledger_by_owner(normalized_required(owner_user_id, "owner_user_id"))

    def save_provider_config(
        self,
        *,
        admin_actor_id: str,
        provider: str,
        enabled: bool = True,
        allowed_models: Sequence[str] = (),
        secret_ref: str | None = None,
        region: str | None = None,
        reason: str = "provider config update",
    ) -> ProviderConfig:
        normalized_admin_actor_id = normalized_required(admin_actor_id, "admin_actor_id")
        normalized_provider = normalized_required(provider, "provider")
        normalized_reason = normalized_required(reason, "reason")
        existing = self._repository.get_provider_config(normalized_provider)
        now = self._clock()
        config = ProviderConfig(
            provider_config_id=existing.provider_config_id if existing is not None else self._new_id("provider_config"),
            provider=normalized_provider,
            enabled=enabled,
            allowed_models=clean_string_tuple(allowed_models, "allowed_models"),
            secret_ref=clean_optional(secret_ref),
            region=clean_optional(region),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._repository.put_provider_config(config)
        self._append_admin_audit_event(
            admin_actor_id=normalized_admin_actor_id,
            action="ai.provider_config_update",
            target_type="provider",
            target_id=normalized_provider,
            reason=normalized_reason,
            metadata={
                "enabled": str(config.enabled).lower(),
                "allowed_models": ",".join(config.allowed_models),
            },
        )
        return config

    def get_provider_config(self, provider: str) -> ProviderConfig | None:
        return self._repository.get_provider_config(normalized_required(provider, "provider"))

    def list_provider_configs(self) -> tuple[ProviderConfig, ...]:
        return self._repository.list_provider_configs()

    def list_admin_audit_events(self) -> tuple[AdminAuditEvent, ...]:
        return self._repository.list_admin_audit_events()

    def put_model_policy(self, policy: ModelPolicy) -> None:
        self._repository.put_model_policy(policy)

    def put_budget_limit(self, limit: BudgetLimit) -> None:
        if limit.max_total_tokens < 0:
            raise InvalidAiRunError("max_total_tokens must be greater than or equal to zero")
        self._repository.put_budget_limit(limit)

    def _preflight_denial(self, request: ProviderRequest) -> str | None:
        safety_reason = self._input_safety_reason(request)
        if safety_reason is not None:
            return safety_reason

        provider_config_reason = self._provider_config_reason(request)
        if provider_config_reason is not None:
            return provider_config_reason

        policy_reason = self._model_policy_reason(request)
        if policy_reason is not None:
            return policy_reason

        credit_reason = self._credit_reason(request)
        if credit_reason is not None:
            return credit_reason

        budget_reason = self._budget_reason(request)
        if budget_reason is not None:
            return budget_reason

        return None

    def _input_safety_reason(self, request: ProviderRequest) -> str | None:
        haystack = request_text(request)
        for term in self._blocked_input_terms:
            if term in haystack:
                return f"blocked input term: {term}"
        return None

    def _output_safety_reason(self, response: ProviderResponse) -> str | None:
        output_text = (response.output_text or "").casefold()
        for term in self._unsafe_output_terms:
            if term in output_text:
                return f"unsafe output term: {term}"
        return None

    def _provider_config_reason(self, request: ProviderRequest) -> str | None:
        config = self._repository.get_provider_config(request.provider)
        if config is None:
            return None
        if not config.enabled:
            return f"provider disabled by server owner: {request.provider}"
        if config.allowed_models and request.model not in config.allowed_models:
            return f"model not allowed by provider config {request.provider}: {request.model}"
        return None

    def _model_policy_reason(self, request: ProviderRequest) -> str | None:
        for policy in self._matching_model_policies(request):
            if not policy.enabled:
                return f"model policy disabled: {policy.policy_id}"
            if policy.allowed_providers and request.provider not in policy.allowed_providers:
                return f"provider not allowed by policy {policy.policy_id}: {request.provider}"
            if policy.allowed_models and request.model not in policy.allowed_models:
                return f"model not allowed by policy {policy.policy_id}: {request.model}"
            if policy.max_output_tokens is not None and request.max_output_tokens > policy.max_output_tokens:
                return f"max output tokens exceeds policy {policy.policy_id}: {request.max_output_tokens}"
        return None

    def _credit_reason(self, request: ProviderRequest) -> str | None:
        estimated_cost = estimate_run_cost_units(request)
        available_credits = self.get_user_credit_balance(request.owner_user_id).available_credits
        if available_credits < estimated_cost:
            return f"insufficient user credits for {request.owner_user_id}"
        return None

    def _budget_reason(self, request: ProviderRequest) -> str | None:
        estimate = estimate_run_cost_units(request)
        for limit in self._matching_budget_limits(request):
            used = sum(record.total_tokens for record in self._usage_for_scope(limit.scope_key, request))
            if used + estimate > limit.max_total_tokens:
                return f"token budget exceeded for {limit.scope_key}"
        return None

    def _matching_model_policies(self, request: ProviderRequest) -> tuple[ModelPolicy, ...]:
        return tuple(
            policy
            for scope_key in scope_keys_for(request)
            for policy in self._repository.list_model_policies_by_scope(scope_key)
        )

    def _matching_budget_limits(self, request: ProviderRequest) -> tuple[BudgetLimit, ...]:
        return tuple(
            limit
            for scope_key in scope_keys_for(request)
            for limit in self._repository.list_budget_limits_by_scope(scope_key)
        )

    def _usage_for_scope(self, scope_key: str, request: ProviderRequest) -> tuple[UsageRecord, ...]:
        if scope_key == "global":
            return self._repository.list_usage_records()
        if scope_key.startswith("owner:"):
            return self._repository.list_usage_by_owner(scope_key.removeprefix("owner:"))
        if scope_key.startswith("agent:"):
            return self._repository.list_usage_by_agent(scope_key.removeprefix("agent:"))
        return ()

    def _record_usage(self, run: AiRun, response: ProviderResponse) -> UsageRecord:
        usage = response.usage
        record = UsageRecord(
            usage_id=self._new_id("usage"),
            run_id=run.run_id,
            provider=run.provider,
            model=run.model,
            owner_user_id=run.owner_user_id,
            agent_id=run.actor_agent_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cached_tokens,
            estimated_cost_units=usage.total_tokens * DEFAULT_COST_UNIT_PER_TOKEN,
            task_id=run.task_id,
            message_id=run.message_id,
            created_at=self._clock(),
        )
        self._repository.put_usage_record(record)
        return record

    def _charge_user_credits(self, run: AiRun, usage: UsageRecord) -> UserCreditLedgerEntry:
        cost = usage.estimated_cost_units
        entry = UserCreditLedgerEntry(
            entry_id=self._new_id("credit"),
            owner_user_id=run.owner_user_id,
            entry_type=UserCreditLedgerEntryType.AI_RUN_CHARGE,
            credit_delta=-cost,
            reason=f"AI run charge for {run.run_id}",
            run_id=run.run_id,
            usage_id=usage.usage_id,
            created_at=self._clock(),
        )
        self._repository.append_user_credit_ledger_entry(entry)
        return entry

    def _deny(self, run: AiRun, reason: str) -> AiRun:
        denied = replace(
            run,
            state=AiRunState.DENIED,
            denial_reason=reason,
            safety_reason=reason if reason.startswith("blocked input") else run.safety_reason,
            budget_reason=reason if "budget" in reason else run.budget_reason,
            credit_reason=reason if "credit" in reason else run.credit_reason,
            updated_at=self._clock(),
        )
        self._repository.put_run(denied)
        self._append_event(denied, AiRunState.DENIED, reason)
        return denied

    def _fail(self, run: AiRun, reason: str) -> AiRun:
        failed = replace(run, state=AiRunState.FAILED, denial_reason=reason, updated_at=self._clock())
        self._repository.put_run(failed)
        self._append_event(failed, AiRunState.FAILED, reason)
        return failed

    def _quarantine(self, run: AiRun, reason: str, usage_id: str) -> AiRun:
        quarantined = replace(run, state=AiRunState.QUARANTINED, safety_reason=reason, updated_at=self._clock())
        self._repository.put_run(quarantined)
        self._append_event(quarantined, AiRunState.QUARANTINED, reason, usage_id=usage_id)
        return quarantined

    def _transition(self, run: AiRun, state: AiRunState, reason: str, *, usage_id: str | None = None) -> AiRun:
        updated = replace(run, state=state, updated_at=self._clock())
        self._repository.put_run(updated)
        self._append_event(updated, state, reason, usage_id=usage_id)
        return updated

    def _append_event(
        self,
        run: AiRun,
        state: AiRunState,
        reason: str,
        *,
        usage_id: str | None = None,
    ) -> None:
        self._repository.append_run_event(
            AiRunEvent(
                event_id=self._new_id("aievent"),
                run_id=run.run_id,
                state=state,
                reason=reason,
                usage_id=usage_id,
                trace_id=run.trace_id,
                created_at=self._clock(),
            )
        )

    def _append_admin_audit_event(
        self,
        *,
        admin_actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        reason: str,
        metadata: Mapping[str, str],
    ) -> None:
        self._repository.append_admin_audit_event(
            AdminAuditEvent(
                audit_id=self._new_id("admin_audit"),
                admin_actor_id=admin_actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                reason=reason,
                metadata=metadata,
                created_at=self._clock(),
            )
        )

    def _new_id(self, prefix: str) -> str:
        return self._id_factory(prefix)

    @staticmethod
    def _default_id_factory(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"


def normalize_provider_request(
    *,
    provider: str,
    model: str,
    actor_agent_id: str,
    owner_user_id: str,
    input_messages: Sequence[ProviderMessage | dict[str, str]],
    system_instructions: str | None,
    system_instructions_ref: str | None,
    context_refs: Sequence[str],
    content_ref: str | None,
    max_output_tokens: int,
    temperature: float,
    response_format: str,
    tool_policy: str,
    task_id: str | None,
    message_id: str | None,
    trace_id: str | None,
    idempotency_key: str | None,
) -> ProviderRequest:
    normalized_messages = tuple(normalize_provider_message(message) for message in input_messages)
    normalized_content_ref = clean_optional(content_ref)
    if not normalized_messages and normalized_content_ref is None:
        raise InvalidAiRunError("input_messages or content_ref is required")
    if max_output_tokens <= 0:
        raise InvalidAiRunError("max_output_tokens must be greater than zero")
    if temperature < 0:
        raise InvalidAiRunError("temperature must be greater than or equal to zero")

    return ProviderRequest(
        provider=normalized_required(provider, "provider"),
        model=normalized_required(model, "model"),
        actor_agent_id=normalized_required(actor_agent_id, "actor_agent_id"),
        owner_user_id=normalized_required(owner_user_id, "owner_user_id"),
        input_messages=normalized_messages,
        system_instructions=clean_optional(system_instructions),
        system_instructions_ref=clean_optional(system_instructions_ref),
        context_refs=clean_string_tuple(context_refs, "context_refs"),
        content_ref=normalized_content_ref,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        response_format=normalized_required(response_format, "response_format"),
        tool_policy=normalized_required(tool_policy, "tool_policy"),
        task_id=clean_optional(task_id),
        message_id=clean_optional(message_id),
        trace_id=clean_optional(trace_id),
        idempotency_key=clean_optional(idempotency_key),
    )


def normalize_provider_message(message: ProviderMessage | dict[str, str]) -> ProviderMessage:
    if isinstance(message, ProviderMessage):
        role = normalized_required(message.role, "message.role")
        content = normalized_required(message.content, "message.content")
        return ProviderMessage(role=role, content=content, content_ref=clean_optional(message.content_ref))
    if isinstance(message, dict):
        role = normalized_required(message.get("role", ""), "message.role")
        content = normalized_required(message.get("content", ""), "message.content")
        return ProviderMessage(role=role, content=content, content_ref=clean_optional(message.get("content_ref")))
    raise InvalidAiRunError("input_messages must contain provider messages or objects")


def clean_string_tuple(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise InvalidAiRunError(f"{field_name} must contain only strings")
        stripped = value.strip()
        if stripped:
            cleaned.append(stripped)
    return tuple(cleaned)


def normalized_required(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise InvalidAiRunError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise InvalidAiRunError(f"{field_name} is required")
    return stripped


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidAiRunError("optional string fields must be strings")
    stripped = value.strip()
    return stripped or None


def request_text(request: ProviderRequest) -> str:
    parts = [request.system_instructions or ""]
    parts.extend(message.content for message in request.input_messages)
    parts.extend(request.context_refs)
    if request.content_ref is not None:
        parts.append(request.content_ref)
    return "\n".join(parts).casefold()


def estimate_request_tokens(request: ProviderRequest) -> int:
    text_parts = [request.system_instructions or ""]
    text_parts.extend(message.content for message in request.input_messages)
    token_count = sum(len([part for part in text.strip().split() if part]) for text in text_parts)
    token_count += len(request.context_refs)
    if request.content_ref is not None:
        token_count += 1
    return token_count


def estimate_run_cost_units(request: ProviderRequest) -> int:
    return (estimate_request_tokens(request) + request.max_output_tokens) * DEFAULT_COST_UNIT_PER_TOKEN


def scope_keys_for(request: ProviderRequest) -> tuple[str, ...]:
    return (
        "global",
        f"owner:{request.owner_user_id}",
        f"agent:{request.actor_agent_id}",
    )
