from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from typing import Any, NoReturn

from dataclasses import dataclass
from message_hub.domain import (
    AGENT_TOKEN_SCOPES,
    ActionRequest,
    Agent,
    AgentDecisionResult,
    AgentTokenRecord,
    AgentTokenVerificationError,
    ContactExplanation,
    ContextBudget,
    ContextPack,
    ContextPayloadRef,
    Delivery,
    DuplicateAgentHandleError,
    ForbiddenDeliveryError,
    ForbiddenPayloadError,
    InboxItem,
    InvalidMessageError,
    Message,
    MessageRef,
    MessageHubError,
    MessageHubService,
    NotFoundError,
    PayloadCompaction,
    PayloadUnavailableError,
    PayloadRecord,
    PostureNotOpenError,
    RoutingRule,
    SafetyBlockedError,
    SendMessageResult,
    TaskCapacitySharingPolicyRecord,
    TaskCreditBalance,
    TaskCreditLedgerEntry,
    TaskEscrowRecord,
    TaskQuoteRecord,
    TaskRecord,
    TaskResultRecord,
    TaskToolRequest,
    TaskWorkerReputationEventRecord,
    TaskWorkerReputationSummary,
    ToolGrant,
    ThreadContext,
    ThreadRecord,
    WorkflowTraceEntry,
)
from message_hub.api.html_card import render_agent_card_html
from message_hub.domain.cards import (
    agent_card,
    agent_public_path,
    guest_visible_status,
    message_status_path,
    sender_visible_status,
    thread_path,
)
from message_hub.domain.service import (
    GUEST_HANDLE_PREFIX,
    INBOX_POSTURES,
    guest_callback_domain,
    normalize_guest_callback_url,
    normalize_handle,
)
from message_hub.storage import InMemoryMessageHubRepository
from seagull_common.coerce import datetime_to_string
from seagull_common.validation import Validator

# Guest-ingress defaults (fixed one-hour windows, app-level fixed-window
# counters in the repository). The deployed adapter overrides the limits from
# GUEST_SEND_IP_HOURLY_LIMIT / GUEST_SEND_RECIPIENT_HOURLY_LIMIT /
# GUEST_CALLBACK_DOMAIN_HOURLY_LIMIT.
GUEST_SEND_WINDOW_SECONDS = 3600
DEFAULT_GUEST_SEND_IP_HOURLY_LIMIT = 10
DEFAULT_GUEST_SEND_RECIPIENT_HOURLY_LIMIT = 30
DEFAULT_GUEST_CALLBACK_DOMAIN_HOURLY_LIMIT = 20

# Guest invite tokens (posture ``token_required``): signed capabilities with
# no server-side record; revocation is by expiry or rotating the signing
# secret.
GUEST_INVITE_DEFAULT_TTL_SECONDS = 7 * 24 * 3600
GUEST_INVITE_MAX_TTL_SECONDS = 30 * 24 * 3600
GUEST_INVITE_MIN_TTL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class ApiError(Exception):
    status_code: int
    error: str
    message: str


# Single domain-error -> (HTTP status, error code) table. The public agent
# URL methods raise through ``raise_api_error`` instead of per-method
# try/except chains; the older methods keep their hand-written chains for now
# and migrate in a later slice.
DOMAIN_ERROR_HTTP: dict[type[Exception], tuple[int, str]] = {
    DuplicateAgentHandleError: (409, "conflict"),
    ForbiddenDeliveryError: (403, "forbidden"),
    ForbiddenPayloadError: (403, "forbidden"),
    InvalidMessageError: (400, "bad_request"),
    NotFoundError: (404, "not_found"),
    PayloadUnavailableError: (410, "payload_unavailable"),
    PostureNotOpenError: (403, "posture_not_open"),
    SafetyBlockedError: (403, "blocked"),
}


def raise_api_error(exc: Exception) -> NoReturn:
    """Translate a mapped domain error into ``ApiError``; re-raise the rest."""
    for error_type, (status_code, error) in DOMAIN_ERROR_HTTP.items():
        if isinstance(exc, error_type):
            raise ApiError(status_code, error, str(exc)) from exc
    raise exc


class LocalMessageHubApi:
    """Dependency-free local API adapter for the Phase 1 message loop."""

    def __init__(
        self,
        service: MessageHubService,
        *,
        guest_status_signing_secret: str | None = None,
        guest_send_ip_hourly_limit: int = DEFAULT_GUEST_SEND_IP_HOURLY_LIMIT,
        guest_send_recipient_hourly_limit: int = DEFAULT_GUEST_SEND_RECIPIENT_HOURLY_LIMIT,
        guest_callback_domain_hourly_limit: int = DEFAULT_GUEST_CALLBACK_DOMAIN_HOURLY_LIMIT,
        instance_domain: str | None = None,
    ) -> None:
        self._service = service
        # Per-instance random default: locally minted guest status URLs then
        # verify against this instance only, which matches the local-dev
        # lifetime. The deployed adapter must supply a stable secret.
        self._guest_status_signing_secret = guest_status_signing_secret or secrets.token_hex(32)
        self._guest_send_ip_hourly_limit = guest_send_ip_hourly_limit
        self._guest_send_recipient_hourly_limit = guest_send_recipient_hourly_limit
        self._guest_callback_domain_hourly_limit = guest_callback_domain_hourly_limit
        # When unset, /.well-known/gulls resolution skips the foreign-domain
        # refusal and only answers from the local registry (single-instance
        # dev). Deployments set it to the apex domain the URLs live on.
        self._instance_domain = (instance_domain or "").strip().lower() or None

    @classmethod
    def in_memory(cls) -> LocalMessageHubApi:
        return cls(MessageHubService(InMemoryMessageHubRepository()))

    def health(self) -> dict[str, Any]:
        return {"ok": True, "app": "message-hub", "storage": "memory"}

    def create_payload(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = self._service.create_payload(
                content=payload_content(body),
                media_type=optional_string(body, "media_type") or "text/plain; charset=utf-8",
                access_scope=optional_string(body, "access_scope") or "recipients",
                ttl_expires_at=optional_datetime(body, "ttl_expires_at"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

        return {
            "content_ref": payload.record.content_ref,
            "payload": payload_record_to_dict(payload.record),
        }

    def read_payload(
        self,
        content_ref: str,
        *,
        requester_handle: str | None = None,
    ) -> dict[str, Any]:
        try:
            record, content = self._service.read_payload_content(
                content_ref,
                requester_handle=requester_handle,
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenPayloadError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except PayloadUnavailableError as exc:
            raise ApiError(410, "payload_unavailable", str(exc)) from exc

        result: dict[str, Any] = {
            "content_ref": record.content_ref,
            "payload": payload_record_to_dict(record),
            "content_bytes": content,
        }
        try:
            result["content"] = content.decode("utf-8")
        except UnicodeDecodeError:
            pass
        return result

    def read_payload_metadata(self, content_ref: str) -> dict[str, Any]:
        try:
            payload = self._service.get_payload(content_ref)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        result: dict[str, Any] = {
            "content_ref": payload.record.content_ref,
            "payload": payload_record_to_dict(payload.record),
        }
        if payload.compaction is not None:
            result["compaction"] = payload_compaction_to_dict(payload.compaction)
        return result

    def update_payload_retention(self, content_ref: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = self._service.update_payload_retention(
                content_ref,
                retention_state=required_string(body, "retention_state"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except PayloadUnavailableError as exc:
            raise ApiError(410, "payload_unavailable", str(exc)) from exc

        return {
            "content_ref": payload.content_ref,
            "payload": payload_record_to_dict(payload),
        }

    def register_agent(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            agent = self._service.register_agent(
                required_string(body, "handle"),
                display_name=optional_string(body, "display_name"),
                capabilities=string_list(body.get("capabilities", ()), "capabilities"),
                response_rules=response_rules_object(body.get("response_rules")),
                trigger_mode=optional_string(body, "trigger_mode") or "manual",
                webhook_url=optional_string(body, "webhook_url"),
                inbox_posture=optional_string(body, "inbox_posture"),
            )
        except DuplicateAgentHandleError as exc:
            raise ApiError(409, "conflict", str(exc)) from exc
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

        return {"created": True, "agent": agent_to_dict(agent)}

    def register_human_proxy(self, body: dict[str, Any]) -> dict[str, Any]:
        """Register the server-owned human proxy namespace.

        The HTTP adapter authenticates this operation separately from public
        agent registration. Keeping the reserved-namespace escape hatch here
        preserves the domain service's default rejection for untrusted callers.
        """
        try:
            agent = self._service.ensure_human_proxy(
                required_string(body, "handle"),
                display_name=optional_string(body, "display_name"),
            )
        except (InvalidMessageError, DuplicateAgentHandleError) as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        return {"created": True, "agent": agent_to_dict(agent)}

    def agent_registration(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            handle = required_string(body, "handle")
            try:
                self._service.get_agent(handle)
            except NotFoundError:
                agent = self._service.register_agent(
                    handle,
                    display_name=optional_string(body, "display_name"),
                    capabilities=string_list(body.get("capabilities", ()), "capabilities"),
                    response_rules=response_rules_object(body.get("response_rules")),
                    trigger_mode=optional_string(body, "trigger_mode") or "manual",
                    webhook_url=optional_string(body, "webhook_url"),
                    inbox_posture=optional_string(body, "inbox_posture"),
                )
                created = True
            else:
                # Registration only bootstraps the first token for a new agent;
                # minting another token for an existing handle here would allow
                # impersonation, since handles are public.
                raise ApiError(
                    409,
                    "conflict",
                    f"agent already registered: {handle}; "
                    "issuing another token requires an authenticated owner flow",
                )
            issued = self._service.issue_agent_token(
                agent.handle,
                scopes=agent_registration_scopes(body),
                agent=agent,
                name=optional_string(body, "name"),
                owner_user_id=optional_string(body, "owner_user_id"),
                node_id=optional_string(body, "node_id"),
                expires_at=optional_datetime(body, "expires_at"),
            )
        except DuplicateAgentHandleError as exc:
            raise ApiError(409, "conflict", str(exc)) from exc
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "created": created,
            "agent": agent_to_dict(agent),
            "token": issued.token,
            "record": agent_token_record_to_dict(issued.record),
        }

    def read_agent(self, handle: str) -> dict[str, Any]:
        try:
            agent = self._service.get_agent(handle)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"agent": agent_to_dict(agent)}

    def create_message(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._service.send_message(
                sender_handle=required_string(body, "sender_handle"),
                recipient_handles=string_list(body.get("recipient_handles", ()), "recipient_handles"),
                content=optional_string(body, "content") or optional_string(body, "content_inline"),
                content_ref=optional_string(body, "content_ref"),
                refs=refs_list(body.get("refs", ()), "refs"),
                intent=optional_string(body, "intent") or "message",
                visibility=optional_string(body, "visibility") or "direct",
                thread_id=optional_string(body, "thread_id"),
                idempotency_key=optional_string(body, "idempotency_key"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except SafetyBlockedError as exc:
            raise ApiError(403, "blocked", str(exc)) from exc

        return send_result_to_dict(result)

    def create_routing_rule(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            rule = self._service.add_routing_rule(
                name=required_string(body, "name"),
                route_to_handles=string_list(body.get("route_to_handles", ()), "route_to_handles"),
                mode=optional_string(body, "mode") or "copy",
                url_contains=string_list(body.get("url_contains", ()), "url_contains"),
                enabled=optional_bool(body, "enabled", default=True),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"created": True, "routing_rule": routing_rule_to_dict(rule)}

    def read_routing_rules(self) -> dict[str, Any]:
        # The domain service applies rules during sends but has no list method
        # yet; read through its repository so ordering and serialization stay
        # consistent with create_routing_rule.
        rules = self._service._repository.list_routing_rules()  # noqa: SLF001
        return {"items": [routing_rule_to_dict(rule) for rule in rules]}

    def read_inbox(self, handle: str, *, limit: int = 20) -> dict[str, Any]:
        try:
            items = self._service.get_inbox(handle, limit=limit)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"items": [inbox_item_to_dict(item) for item in items]}

    def read_outbox(self, handle: str, *, limit: int = 20) -> dict[str, Any]:
        try:
            items = self._service.get_outbox(handle, limit=limit)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"items": [inbox_item_to_dict(item) for item in items]}

    def read_sent_messages(self, handle: str, *, limit: int = 20) -> dict[str, Any]:
        try:
            messages = self._service.get_sent_messages(handle, limit=limit)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"messages": [message_to_dict(message) for message in messages]}

    def personal_agent_inbox(self, handle: str, *, limit: int = 20) -> dict[str, Any]:
        return self.read_inbox(handle, limit=limit)

    def agent_me(self, authorization: str | None) -> dict[str, Any]:
        principal = self._require_agent_token(authorization, required_scope="agent:read")
        try:
            agent = self._service.get_agent(principal.agent_handle)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"agent": agent_to_dict(agent), "principal": agent_token_principal_to_dict(principal)}

    def agent_inbox(self, authorization: str | None, *, limit: int = 20) -> dict[str, Any]:
        principal = self._require_agent_token(authorization, required_scope="agent:inbox")
        return self.read_inbox(principal.agent_handle, limit=limit)

    def agent_list_tasks(
        self,
        authorization: str | None,
        *,
        role: str = "all",
        limit: int = 50,
    ) -> dict[str, Any]:
        """``GET /agent/tasks``: this agent's request queue.

        The token identifies the agent, so unlike the handle-based legacy
        route there is nothing to pass and nothing to spoof. This is the path
        the Agent Request product surface uses.
        """
        principal = self._require_agent_token(authorization, required_scope="agent:inbox")
        return self.read_agent_tasks(principal.agent_handle, role=role, limit=limit)

    def agent_set_inbox_posture(self, authorization: str | None, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /agent/inbox-posture``: self-service posture update.

        Same sga_ auth pattern as ``agent_me``; the updated agent is always
        the token's agent. Returns the updated public card.
        """
        principal = self._require_agent_token(authorization, required_scope="agent:post")
        try:
            agent = self._service.set_inbox_posture(
                principal.agent_handle,
                required_string(body, "inbox_posture"),
            )
        except MessageHubError as exc:
            raise_api_error(exc)

        return {"agent": agent_to_dict(agent)}

    def agent_mint_guest_invite(self, authorization: str | None, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /agent/guest-invites``: mint a guest invite for the token's agent.

        The invite is a signed capability with no server-side record: any
        guest presenting it may send to this agent while its inbox posture is
        ``token_required``. Posture ``open`` needs no invite and
        ``contacts_only`` ignores invites, so minting is allowed regardless of
        the current posture. Revocation is by expiry or rotating the signing
        secret.
        """
        principal = self._require_agent_token(authorization, required_scope="agent:post")
        expires_in = optional_int(body, "expires_in_seconds")
        if expires_in is None:
            expires_in = GUEST_INVITE_DEFAULT_TTL_SECONDS
        if not GUEST_INVITE_MIN_TTL_SECONDS <= expires_in <= GUEST_INVITE_MAX_TTL_SECONDS:
            raise ApiError(
                400,
                "bad_request",
                "expires_in_seconds must be between "
                f"{GUEST_INVITE_MIN_TTL_SECONDS} and {GUEST_INVITE_MAX_TTL_SECONDS}",
            )
        expires_epoch = int(time.time()) + expires_in
        token = guest_invite_token(
            self._guest_status_signing_secret,
            principal.agent_handle,
            expires_epoch,
        )
        return {
            "invite_token": token,
            "expires_at": datetime_to_string(datetime.fromtimestamp(expires_epoch, tz=timezone.utc)),
            # The invite token is hex digits and a dot, so it needs no URL
            # encoding in the query string.
            "send_url": f"{agent_public_path(principal.agent_handle)}/messages?invite={token}",
        }

    def agent_post(self, authorization: str | None, body: dict[str, Any]) -> dict[str, Any]:
        principal = self._require_agent_token(authorization, required_scope="agent:post")
        wrapped = {**body, "sender_handle": principal.agent_handle}
        return self.create_message(wrapped)

    def agent_ack_delivery(self, authorization: str | None, delivery_id: str) -> dict[str, Any]:
        principal = self._require_agent_token(authorization, required_scope="agent:ack")
        try:
            delivery = self._service.ack_delivery(
                delivery_id,
                recipient_handle=principal.agent_handle,
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"delivery": delivery_to_dict(delivery)}

    def agent_decide_delivery(self, authorization: str | None, delivery_id: str, body: dict[str, Any]) -> dict[str, Any]:
        principal = self._require_agent_token(authorization, required_scope="agent:post")
        wrapped = {**body, "agent_handle": principal.agent_handle}
        return self.submit_delivery_decision(delivery_id, wrapped)

    def agent_request_task(self, authorization: str | None, body: dict[str, Any]) -> dict[str, Any]:
        principal = self._require_agent_token(authorization, required_scope="agent:post")
        return self.create_task({**body, "requester_handle": principal.agent_handle})

    def agent_accept_task(
        self,
        authorization: str | None,
        task_id: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        principal = self._require_agent_token(authorization, required_scope="agent:post")
        return self.accept_task(task_id, {**(body or {}), "worker_handle": principal.agent_handle})

    def agent_return_result(self, authorization: str | None, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        principal = self._require_agent_token(authorization, required_scope="agent:post")
        return self.return_task_result(task_id, {**body, "responder_handle": principal.agent_handle})

    def personal_agent_send(self, handle: str, body: dict[str, Any]) -> dict[str, Any]:
        wrapped = {**body, "sender_handle": handle}
        return self.create_message(wrapped)

    def personal_agent_reply(self, handle: str, delivery_id: str, body: dict[str, Any]) -> dict[str, Any]:
        wrapped = {**body, "agent_handle": handle, "decision": "reply"}
        return self.submit_delivery_decision(delivery_id, wrapped)

    def personal_agent_ignore(self, handle: str, delivery_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        wrapped = {**(body or {}), "agent_handle": handle, "decision": "ignore"}
        return self.submit_delivery_decision(delivery_id, wrapped)

    def personal_agent_ask_owner(self, handle: str, delivery_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        wrapped = {**(body or {}), "agent_handle": handle, "decision": "ask_human"}
        return self.submit_delivery_decision(delivery_id, wrapped)

    def personal_agent_request_task(self, handle: str, body: dict[str, Any]) -> dict[str, Any]:
        wrapped = {**body, "requester_handle": handle}
        return self.create_task(wrapped)

    def personal_agent_accept_task(self, handle: str, task_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        wrapped = {**(body or {}), "worker_handle": handle}
        return self.accept_task(task_id, wrapped)

    def personal_agent_return_result(self, handle: str, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        wrapped = {**body, "responder_handle": handle}
        return self.return_task_result(task_id, wrapped)

    def _require_agent_token(self, authorization: str | None, *, required_scope: str):
        try:
            return self._service.verify_agent_token(
                bearer_token_from_authorization(authorization),
                required_scope=required_scope,
            )
        except AgentTokenVerificationError as exc:
            status_code = 403 if str(exc).startswith("missing agent token scope") else 401
            error = "forbidden" if status_code == 403 else "unauthorized"
            raise ApiError(status_code, error, str(exc)) from exc
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc

    def require_agent_access(
        self,
        authorization: str | None,
        handle: str,
        *,
        required_scope: str,
    ) -> dict[str, Any]:
        """Verify a scoped agent token that must belong to ``handle``.

        Used by the legacy handle-addressed routes: a valid token for a
        different agent is a 403, not a 401, matching the deployed adapter.
        """
        principal = self._require_agent_token(authorization, required_scope=required_scope)
        try:
            normalized_handle = normalize_handle(handle)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        if principal.agent_handle != normalized_handle:
            raise ApiError(403, "forbidden", "agent token cannot access another agent's legacy route")
        return agent_token_principal_to_dict(principal)

    def public_agent_send(
        self,
        authorization: str | None,
        name: str,
        body: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        source_ip: str | None = None,
        invite_token: str | None = None,
    ) -> dict[str, Any]:
        """``POST /agents/{name}/messages``: message the path agent's public URL.

        With an Authorization header, the sender is always the bearer token's
        agent (scope ``agent:post``); a ``sender_handle`` in the body is
        ignored. The recipient is the path agent resolved by
        ``public_agent_handle`` and visibility is fixed to ``direct``.
        ``idempotency_key`` (the Idempotency-Key header, with the body field
        as fallback) feeds ``send_message``'s repository-backed replay
        handling.

        Without an Authorization header the request is GUEST ingress
        (``public_agent_guest_send``): posture-gated, rate-limited,
        quarantine-first, and without idempotency support this slice.

        Returns the public envelope; registered sends additionally carry a
        ``replayed`` flag that HTTP adapters pop to choose 202 (created) vs
        200 (idempotent replay); the flag is not part of the wire envelope.
        """
        if authorization is None:
            return self.public_agent_guest_send(
                name,
                body,
                source_ip=source_ip,
                invite_token=invite_token,
            )

        principal = self._require_agent_token(authorization, required_scope="agent:post")
        key = (idempotency_key or "").strip() or optional_string(body, "idempotency_key")
        try:
            recipient = self._service.get_agent(public_agent_handle(name))
        except MessageHubError as exc:
            raise_api_error(exc)

        replayed = False
        if key:
            # send_message resolves replays itself; peek at the repository
            # (as read_routing_rules does for its missing read model) so the
            # transport can tell 202-created from 200-replayed without a
            # second send path.
            replayed = (
                self._service._repository.get_idempotent_message_id(  # noqa: SLF001
                    principal.agent_id,
                    key,
                )
                is not None
            )

        try:
            result = self._service.send_message(
                sender_handle=principal.agent_handle,
                recipient_handles=[recipient.handle],
                content=optional_string(body, "content"),
                content_ref=optional_string(body, "content_ref"),
                refs=refs_list(body.get("refs", ()), "refs"),
                intent=optional_string(body, "intent") or "message",
                visibility="direct",
                thread_id=optional_string(body, "thread_id"),
                idempotency_key=key,
            )
        except (MessageHubError, SafetyBlockedError) as exc:
            raise_api_error(exc)

        deliveries = [
            delivery
            for delivery in result.deliveries
            if delivery.recipient_agent_id == recipient.agent_id
        ]
        if len(deliveries) != 1:
            raise ApiError(
                500,
                "internal_error",
                "public agent send expected exactly one delivery for the path agent",
            )
        delivery = deliveries[0]

        return {
            "delivery_id": delivery.delivery_id,
            "message_id": result.message.message_id,
            "thread_id": result.thread.thread_id,
            "status_url": message_status_path(recipient.handle, delivery.delivery_id),
            "thread_url": thread_path(result.thread.thread_id),
            "replayed": replayed,
        }

    def public_agent_message_status(
        self,
        authorization: str | None,
        name: str,
        delivery_id: str,
    ) -> dict[str, Any]:
        """``GET /agents/{name}/messages/{delivery_id}``: sender-visible status.

        Requires scope ``agent:read`` and only the delivery's sender may read
        it. A delivery not addressed to the path agent reads the same as an
        unknown id (404) so the route cannot confirm other agents' traffic,
        and recipient decisions are collapsed by ``sender_visible_status`` so
        e.g. ``ignored`` is indistinguishable from ``delivered``.
        """
        principal = self._require_agent_token(authorization, required_scope="agent:read")
        try:
            recipient = self._service.get_agent(public_agent_handle(name))
        except MessageHubError as exc:
            raise_api_error(exc)

        # The domain service has no delivery read model yet; read through its
        # repository as read_routing_rules does.
        delivery = self._service._repository.get_delivery((delivery_id or "").strip())  # noqa: SLF001
        if delivery is None or delivery.recipient_agent_id != recipient.agent_id:
            raise ApiError(404, "not_found", f"delivery not found: {delivery_id}")
        if delivery.sender_agent_id != principal.agent_id:
            raise ApiError(403, "forbidden", "only the sender may read this delivery status")

        return {
            "delivery_id": delivery.delivery_id,
            "status": sender_visible_status(delivery.status),
            "created_at": datetime_to_string(delivery.created_at),
            "updated_at": datetime_to_string(delivery.updated_at),
            "thread_url": thread_path(delivery.thread_id),
        }

    def public_agent_guest_send(
        self,
        name: str,
        body: dict[str, Any],
        *,
        source_ip: str | None = None,
        invite_token: str | None = None,
    ) -> dict[str, Any]:
        """Token-less ``POST /agents/{name}/messages``: guest ingress.

        Order matters: recipient lookup (404), posture gate (403
        ``posture_not_open`` unless the recipient's posture is ``open`` or a
        valid invite token satisfies ``token_required``), rate limits (429
        ``rate_limited``), then callback validation — all BEFORE any guest
        registration or message persistence. The domain helper then mints the
        ephemeral ``@guest_`` sender and quarantines the send.

        ``invite_token`` (the ``invite`` query parameter, with the body field
        as fallback) is verified against this recipient; an invalid invite is
        indistinguishable from a missing one. An optional ``callback_url``
        (https, publicly resolvable) becomes the guest's reply webhook and is
        capped per callback domain.

        The guest envelope is ``{"delivery_id", "status_url"}`` ONLY — no
        message/thread ids, which guests cannot use — where ``status_url``
        carries the signed polling token. ``source_ip`` of ``None`` skips the
        per-IP window (local callers without transport-level addressing).
        """
        provided_invite = (invite_token or "").strip() or optional_string(body, "invite_token")
        try:
            recipient = self._service.get_agent(public_agent_handle(name))
            invite_valid = bool(provided_invite) and verify_guest_invite_token(
                self._guest_status_signing_secret,
                recipient.handle,
                provided_invite,
                now_epoch=int(time.time()),
            )
            self._service.require_guest_ingress_open(recipient, guest_invite_valid=invite_valid)
        except MessageHubError as exc:
            raise_api_error(exc)

        self._enforce_guest_rate_limits(recipient.handle, source_ip)

        try:
            callback_url = normalize_guest_callback_url(optional_string(body, "callback_url"))
        except MessageHubError as exc:
            raise_api_error(exc)
        if callback_url is not None:
            self._enforce_guest_callback_domain_limit(guest_callback_domain(callback_url))

        try:
            _, result = self._service.send_guest_message(
                recipient_handle=recipient.handle,
                content=optional_string(body, "content"),
                content_ref=optional_string(body, "content_ref"),
                refs=refs_list(body.get("refs", ()), "refs"),
                intent=optional_string(body, "intent") or "message",
                callback_url=callback_url,
                guest_invite_valid=invite_valid,
            )
        except (MessageHubError, SafetyBlockedError) as exc:
            raise_api_error(exc)

        deliveries = [
            delivery
            for delivery in result.deliveries
            if delivery.recipient_agent_id == recipient.agent_id
        ]
        if len(deliveries) != 1:
            raise ApiError(
                500,
                "internal_error",
                "guest send expected exactly one delivery for the path agent",
            )
        delivery = deliveries[0]

        token = guest_status_token(self._guest_status_signing_secret, delivery.delivery_id)
        return {
            "delivery_id": delivery.delivery_id,
            "status_url": f"{message_status_path(recipient.handle, delivery.delivery_id)}?token={token}",
        }

    def public_agent_guest_message_status(
        self,
        name: str,
        delivery_id: str,
        token: str | None,
    ) -> dict[str, Any]:
        """``GET /agents/{name}/messages/{id}?token=...``: guest status poll.

        A VALID signed token replaces Authorization entirely. The response is
        ``{"delivery_id", "status"}`` ONLY, in the guest-coarse vocabulary
        (``guest_visible_status``): blocked/failed reads as ``quarantined``,
        indistinguishable from a review hold. An invalid token is a 404 —
        never 401/403 — so the route cannot confirm the delivery exists.
        """
        try:
            recipient = self._service.get_agent(public_agent_handle(name))
        except MessageHubError as exc:
            raise_api_error(exc)

        normalized_delivery_id = (delivery_id or "").strip()
        provided_token = (token or "").strip()
        expected_token = guest_status_token(self._guest_status_signing_secret, normalized_delivery_id)
        if not provided_token or not hmac.compare_digest(expected_token, provided_token):
            raise ApiError(404, "not_found", f"delivery not found: {delivery_id}")

        # Same repository read model as the authenticated status route.
        delivery = self._service._repository.get_delivery(normalized_delivery_id)  # noqa: SLF001
        if delivery is None or delivery.recipient_agent_id != recipient.agent_id:
            raise ApiError(404, "not_found", f"delivery not found: {delivery_id}")

        return {
            "delivery_id": delivery.delivery_id,
            "status": guest_visible_status(delivery.status),
        }

    def well_known_gulls(self, resource: str | None = None) -> dict[str, Any]:
        """``GET /.well-known/gulls``: instance descriptor and handle resolution.

        Without ``resource``, returns the instance descriptor. With
        ``resource`` (canonical handle, ``@``-less, or webfinger
        ``acct:name@host`` form), returns a webfinger-shaped document linking
        the handle to its public URL resources. Handles on a foreign domain
        are refused with ``not_federated`` (V1 is single-instance; the URL
        scheme is the seam federation will later use); when no instance
        domain is configured the refusal is skipped and resolution answers
        from the local registry only.
        """
        if resource is None:
            descriptor = {
                "service": "gulls-message-hub",
                "version": 1,
                "agent_url_template": "/agents/{name}",
                "send_url_template": "/agents/{name}/messages",
                "inbox_postures": sorted(INBOX_POSTURES),
                "federation": "none",
            }
            if self._instance_domain is not None:
                descriptor["instance"] = self._instance_domain
            return descriptor

        try:
            handle = discovery_resource_handle(resource)
        except MessageHubError as exc:
            raise_api_error(exc)
        host = handle.partition(":")[2]
        if host and self._instance_domain and host != self._instance_domain:
            raise ApiError(400, "not_federated", f"handle is not on this instance: {handle}")
        try:
            agent = self._service.get_agent(handle)
        except MessageHubError as exc:
            raise_api_error(exc)

        return {
            "subject": agent.handle,
            "links": [
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": agent_public_path(agent.handle),
                },
                {
                    "rel": "https://gulls.ai/rel/send",
                    "href": f"{agent_public_path(agent.handle)}/messages",
                },
            ],
        }

    def read_agent_card_html(self, handle: str) -> str:
        """The agent card rendered as HTML: same data, second representation.

        Content negotiation is a transport concern; HTTP adapters call this
        when the request prefers ``text/html`` and ``read_agent`` otherwise.
        """
        return render_agent_card_html(self.read_agent(handle)["agent"])

    def _enforce_guest_rate_limits(self, recipient_handle: str, source_ip: str | None) -> None:
        """Fixed one-hour windows via the repository counter; 429 on excess.

        The per-IP window is checked first (and skipped when ``source_ip`` is
        None), then the per-recipient window. Runs before any guest
        registration or message persistence.
        """
        if source_ip is not None:
            ip_count = self._bump_guest_counter(f"guest-ip:{source_ip}")
            if ip_count > self._guest_send_ip_hourly_limit:
                raise ApiError(429, "rate_limited", "guest send rate limit exceeded for this source")

        recipient_count = self._bump_guest_counter(f"guest-recipient:{recipient_handle}")
        if recipient_count > self._guest_send_recipient_hourly_limit:
            raise ApiError(429, "rate_limited", "guest send rate limit exceeded for this recipient")

    def _enforce_guest_callback_domain_limit(self, domain: str) -> None:
        """Cap how many guest sends may register a callback on one domain.

        This is the ingress half of the callback rate cap: it bounds how many
        reply webhooks can be pointed at a single host per window, so guests
        cannot enlist the hub as a POST cannon against a victim domain.
        Dispatch volume is further bounded by replies being recipient
        actions.
        """
        count = self._bump_guest_counter(f"guest-callback-domain:{domain}")
        if count > self._guest_callback_domain_hourly_limit:
            raise ApiError(429, "rate_limited", "guest callback rate limit exceeded for this domain")

    def _bump_guest_counter(self, scope_key: str) -> int:
        now = int(time.time())
        window_start = now - (now % GUEST_SEND_WINDOW_SECONDS)
        ttl_epoch = window_start + 2 * GUEST_SEND_WINDOW_SECONDS
        return self._service._repository.increment_guest_send_count(  # noqa: SLF001
            scope_key,
            window_start,
            ttl_epoch=ttl_epoch,
        )

    def read_thread(self, thread_id: str, *, limit: int = 50) -> dict[str, Any]:
        try:
            messages = self._service.get_thread(thread_id, limit=limit)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "thread_id": thread_id,
            "messages": [message_to_dict(message) for message in messages],
        }

    def read_thread_context(self, thread_id: str, *, recent_limit: int = 10) -> dict[str, Any]:
        try:
            context = self._service.get_thread_context(thread_id, recent_limit=recent_limit)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return thread_context_to_dict(context)

    def read_thread_context_for(
        self,
        thread_id: str,
        *,
        requester_handle: str,
        recent_limit: int = 10,
    ) -> dict[str, Any]:
        """Thread context restricted to thread participants.

        The participant gate matches the deployed adapter; get_context_pack
        owns that check in the domain, so it authorizes the requester before
        the context itself is read.
        """
        try:
            self._service.get_context_pack(
                thread_id,
                requester_handle=requester_handle,
                max_recent_messages=0,
                max_payload_refs=0,
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        result = self.read_thread_context(thread_id, recent_limit=recent_limit)
        result["context_mode"] = "summary_plus_recent"
        return result

    def read_context_pack(
        self,
        thread_id: str,
        *,
        requester_handle: str,
        max_inline_chars: int = 4000,
        max_recent_messages: int = 10,
        max_payload_refs: int = 20,
        token_budget_estimate: int | None = None,
    ) -> dict[str, Any]:
        try:
            context_pack = self._service.get_context_pack(
                thread_id,
                requester_handle=requester_handle,
                max_inline_chars=max_inline_chars,
                max_recent_messages=max_recent_messages,
                max_payload_refs=max_payload_refs,
                token_budget_estimate=token_budget_estimate,
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return context_pack_to_dict(context_pack)

    def create_task(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            reject_private_task_fields(body)
            task = self._service.create_task(
                requester_handle=required_string(body, "requester_handle"),
                recipient_handle=required_string(body, "recipient_handle"),
                objective=required_string(body, "objective"),
                thread_id=optional_string(body, "thread_id"),
                context_refs=string_list(body.get("context_refs", ()), "context_refs"),
                context_pack_id=optional_string(body, "context_pack_id"),
                context_pack_ref=optional_string(body, "context_pack_ref"),
                input_ref=optional_string(body, "input_ref"),
                stream_id=optional_string(body, "stream_id"),
                allowed_tool_names=string_list(body.get("allowed_tool_names", ()), "allowed_tool_names"),
                allowed_use_terms=string_list(body.get("allowed_use_terms", ()), "allowed_use_terms"),
                idempotency_key=optional_string(body, "idempotency_key"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except SafetyBlockedError as exc:
            raise ApiError(403, "blocked", str(exc)) from exc

        return {"created": True, "task": task_to_dict(task), "task_id": task.task_id, "thread_id": task.thread_id}

    def read_task(self, task_id: str) -> dict[str, Any]:
        try:
            task = self._service.get_task(task_id)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"task": task_to_dict(task)}

    def read_thread_tasks(self, thread_id: str, *, limit: int = 50) -> dict[str, Any]:
        try:
            tasks = self._service.list_thread_tasks(thread_id, limit=limit)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"thread_id": thread_id, "tasks": [task_to_dict(task) for task in tasks]}

    def read_agent_tasks(
        self,
        agent_handle: str,
        *,
        role: str = "all",
        limit: int = 50,
    ) -> dict[str, Any]:
        try:
            tasks = self._service.list_agent_tasks(agent_handle, role=role, limit=limit)
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "agent_handle": agent_handle,
            "role": role,
            "tasks": [task_to_dict(task) for task in tasks],
        }

    def define_task_capacity_policy(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            policy = self._service.define_task_capacity_policy(
                task_id,
                actor_handle=required_string(body, "actor_handle"),
                requester_capacity_tier=optional_string(body, "requester_capacity_tier") or "low",
                worker_capacity_tier=optional_string(body, "worker_capacity_tier") or "high",
                max_credit_cost=required_int(body, "max_credit_cost"),
                max_auto_escrow_credits=optional_int(body, "max_auto_escrow_credits") or 0,
                allow_private_context=optional_bool(body, "allow_private_context", default=False),
                private_context_requires_approval=optional_bool(
                    body,
                    "private_context_requires_approval",
                    default=True,
                ),
                paid_work_requires_approval=optional_bool(
                    body,
                    "paid_work_requires_approval",
                    default=True,
                ),
                high_cost_requires_approval=optional_bool(
                    body,
                    "high_cost_requires_approval",
                    default=True,
                ),
                limits_ref=optional_string(body, "limits_ref"),
                abuse_policy_ref=optional_string(body, "abuse_policy_ref"),
                policy_decision_id=optional_string(body, "policy_decision_id"),
                audit_refs=string_list(body.get("audit_refs", ()), "audit_refs"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "task_id": policy.task_id,
            "thread_id": policy.thread_id,
            "policy_id": policy.policy_id,
            "policy": task_capacity_policy_to_dict(policy),
        }

    def read_task_capacity_policies(self, task_id: str) -> dict[str, Any]:
        try:
            policies = self._service.list_task_capacity_policies(task_id)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "task_id": task_id,
            "policies": [task_capacity_policy_to_dict(policy) for policy in policies],
        }

    def grant_task_credits(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            entry = self._service.grant_task_credits(
                agent_handle=required_string(body, "agent_handle"),
                amount=required_int(body, "amount"),
                reason=required_string(body, "reason"),
                policy_decision_id=optional_string(body, "policy_decision_id"),
                limits_ref=optional_string(body, "limits_ref"),
                abuse_policy_ref=optional_string(body, "abuse_policy_ref"),
                audit_refs=string_list(body.get("audit_refs", ()), "audit_refs"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "entry_id": entry.entry_id,
            "entry": task_credit_ledger_entry_to_dict(entry),
        }

    def read_task_credit_balance(self, agent_handle: str) -> dict[str, Any]:
        try:
            balance = self._service.get_task_credit_balance(agent_handle)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"balance": task_credit_balance_to_dict(balance)}

    def read_agent_task_credit_ledger(self, agent_handle: str) -> dict[str, Any]:
        try:
            entries = self._service.list_task_credit_ledger_for_agent(agent_handle)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "agent_handle": agent_handle,
            "entries": [task_credit_ledger_entry_to_dict(entry) for entry in entries],
        }

    def read_task_credit_ledger(self, task_id: str) -> dict[str, Any]:
        try:
            entries = self._service.list_task_credit_ledger_for_task(task_id)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "task_id": task_id,
            "entries": [task_credit_ledger_entry_to_dict(entry) for entry in entries],
        }

    def read_task_worker_reputation(self, worker_handle: str) -> dict[str, Any]:
        try:
            summary = self._service.get_task_worker_reputation(worker_handle)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "worker_handle": worker_handle,
            "reputation": task_worker_reputation_summary_to_dict(summary),
        }

    def read_task_worker_reputation_events(self, worker_handle: str) -> dict[str, Any]:
        try:
            events = self._service.list_task_worker_reputation_events(worker_handle)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "worker_handle": worker_handle,
            "events": [task_worker_reputation_event_to_dict(event) for event in events],
        }

    def create_task_quote(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            reject_private_task_fields(body)
            quote = self._service.create_task_quote(
                task_id,
                worker_handle=required_string(body, "worker_handle"),
                expected_credit_cost=required_int(body, "expected_credit_cost"),
                task_reason=required_string(body, "task_reason"),
                shared_context_refs=string_list(
                    body.get("shared_context_refs", ()),
                    "shared_context_refs",
                ),
                requires_approval=optional_bool(body, "requires_approval", default=True),
                approval_reason=optional_string(body, "approval_reason"),
                limits_ref=optional_string(body, "limits_ref"),
                abuse_policy_ref=optional_string(body, "abuse_policy_ref"),
                policy_decision_id=optional_string(body, "policy_decision_id"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "task_id": quote.task_id,
            "thread_id": quote.thread_id,
            "quote_id": quote.quote_id,
            "quote": task_quote_to_dict(quote),
        }

    def approve_task_quote(self, quote_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            quote = self._service.approve_task_quote(
                quote_id,
                approver_handle=required_string(body, "approver_handle"),
                approval_id=optional_string(body, "approval_id"),
                policy_decision_id=optional_string(body, "policy_decision_id"),
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "task_id": quote.task_id,
            "thread_id": quote.thread_id,
            "quote_id": quote.quote_id,
            "quote": task_quote_to_dict(quote),
        }

    def create_task_escrow(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            escrow = self._service.create_task_escrow(
                task_id,
                requester_handle=required_string(body, "requester_handle"),
                quote_id=required_string(body, "quote_id"),
                approval_id=optional_string(body, "approval_id"),
                policy_decision_id=optional_string(body, "policy_decision_id"),
                limits_ref=optional_string(body, "limits_ref"),
                abuse_policy_ref=optional_string(body, "abuse_policy_ref"),
                audit_refs=string_list(body.get("audit_refs", ()), "audit_refs"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "task_id": escrow.task_id,
            "thread_id": escrow.thread_id,
            "escrow_id": escrow.escrow_id,
            "state": escrow.state.value,
            "escrow": task_escrow_to_dict(escrow),
        }

    def release_task_escrow(self, escrow_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            escrow = self._service.release_task_escrow(
                escrow_id,
                releaser_handle=required_string(body, "releaser_handle"),
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "task_id": escrow.task_id,
            "thread_id": escrow.thread_id,
            "escrow_id": escrow.escrow_id,
            "state": escrow.state.value,
            "escrow": task_escrow_to_dict(escrow),
        }

    def cancel_task_escrow(self, escrow_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            escrow = self._service.cancel_task_escrow(
                escrow_id,
                actor_handle=required_string(body, "actor_handle"),
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "task_id": escrow.task_id,
            "thread_id": escrow.thread_id,
            "escrow_id": escrow.escrow_id,
            "state": escrow.state.value,
            "escrow": task_escrow_to_dict(escrow),
        }

    def dispute_task_escrow(self, escrow_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            escrow = self._service.dispute_task_escrow(
                escrow_id,
                actor_handle=required_string(body, "actor_handle"),
                reason=required_string(body, "reason"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "task_id": escrow.task_id,
            "thread_id": escrow.thread_id,
            "escrow_id": escrow.escrow_id,
            "state": escrow.state.value,
            "escrow": task_escrow_to_dict(escrow),
        }

    def report_task_worker_abuse(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            event = self._service.report_task_worker_abuse(
                task_id,
                reporter_handle=required_string(body, "reporter_handle"),
                reason=required_string(body, "reason"),
                policy_decision_id=optional_string(body, "policy_decision_id"),
                abuse_policy_ref=optional_string(body, "abuse_policy_ref"),
                audit_refs=string_list(body.get("audit_refs", ()), "audit_refs"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "task_id": event.task_id,
            "thread_id": event.thread_id,
            "event_id": event.event_id,
            "event": task_worker_reputation_event_to_dict(event),
        }

    def accept_task(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            task = self._service.accept_task(
                task_id,
                worker_handle=required_string(body, "worker_handle"),
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"task": task_to_dict(task), "task_id": task.task_id, "thread_id": task.thread_id, "state": task.state.value}

    def update_task(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            task = self._service.update_task_state(
                task_id,
                actor_handle=required_string(body, "actor_handle"),
                state=required_string(body, "state"),
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"task": task_to_dict(task), "task_id": task.task_id, "thread_id": task.thread_id, "state": task.state.value}

    def return_task_result(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._service.return_task_result(
                task_id,
                responder_handle=required_string(body, "responder_handle"),
                state=optional_string(body, "state") or "completed",
                content=optional_string(body, "content") or optional_string(body, "content_inline"),
                content_ref=optional_string(body, "content_ref"),
                artifact_refs=string_list(body.get("artifact_refs", ()), "artifact_refs"),
                tool_use_summary_refs=string_list(
                    body.get("tool_use_summary_refs", ()),
                    "tool_use_summary_refs",
                ),
                stream_id=optional_string(body, "stream_id"),
                error=optional_string(body, "error"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except SafetyBlockedError as exc:
            raise ApiError(403, "blocked", str(exc)) from exc

        return {
            "task_id": result.task_id,
            "thread_id": result.thread_id,
            "state": result.state.value,
            "result": task_result_to_dict(result),
        }

    def create_tool_request(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            reject_private_task_fields(body)
            tool_request = self._service.create_tool_request(
                task_id,
                requester_handle=required_string(body, "requester_handle"),
                worker_handle=required_string(body, "worker_handle"),
                tool_name=required_string(body, "tool_name"),
                purpose=required_string(body, "purpose"),
                input_ref=optional_string(body, "input_ref"),
                requires_approval=optional_bool(body, "requires_approval", default=True),
                approval_id=optional_string(body, "approval_id"),
                policy_decision_id=optional_string(body, "policy_decision_id"),
                tool_grant_id=optional_string(body, "tool_grant_id"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        except SafetyBlockedError as exc:
            raise ApiError(403, "blocked", str(exc)) from exc

        return {
            "tool_request": tool_request_to_dict(tool_request),
            "tool_request_id": tool_request.tool_request_id,
            "task_id": tool_request.task_id,
        }

    def create_tool_grant(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            reject_private_task_fields(body)
            grant = self._service.create_tool_grant(
                task_id,
                issuer_handle=required_string(body, "issuer_handle"),
                subject_handle=required_string(body, "subject_handle"),
                audience=required_string(body, "audience"),
                scopes=string_list(body.get("scopes", ()), "scopes"),
                purpose=required_string(body, "purpose"),
                ttl_expires_at=optional_datetime(body, "ttl_expires_at"),
                max_calls=optional_int(body, "max_calls"),
                budget_ref=optional_string(body, "budget_ref"),
                allowed_resource_selectors=string_list(
                    body.get("allowed_resource_selectors", ()),
                    "allowed_resource_selectors",
                ),
                read_only=optional_bool(body, "read_only", default=True),
                approval_id=optional_string(body, "approval_id"),
                policy_decision_id=optional_string(body, "policy_decision_id"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "tool_grant": tool_grant_to_dict(grant),
            "tool_grant_id": grant.grant_id,
            "task_id": grant.task_id,
        }

    def complete_tool_request(self, tool_request_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            tool_request = self._service.complete_tool_request(
                tool_request_id,
                actor_handle=required_string(body, "actor_handle"),
                state=required_string(body, "state"),
                result_ref=optional_string(body, "result_ref"),
                artifact_refs=string_list(body.get("artifact_refs", ()), "artifact_refs"),
                tool_use_summary_ref=optional_string(body, "tool_use_summary_ref"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {
            "tool_request": tool_request_to_dict(tool_request),
            "tool_request_id": tool_request.tool_request_id,
            "task_id": tool_request.task_id,
            "state": tool_request.status.value,
        }

    def ack_message(self, message_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            deliveries = self._service.ack_message(
                message_id,
                recipient_handle=optional_string(body, "recipient_handle"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"deliveries": [delivery_to_dict(delivery) for delivery in deliveries]}

    def read_contact_explanation(self, delivery_id: str) -> dict[str, Any]:
        try:
            explanation = self._service.explain_contact(delivery_id)
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"explanation": contact_explanation_to_dict(explanation)}

    def submit_hook_result(self, delivery_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            delivery = self._service.apply_hook_result(
                delivery_id,
                hook=required_string(body, "hook"),
                runtime=required_string(body, "runtime"),
                actor=optional_string(body, "actor"),
                content=optional_string(body, "content") or optional_string(body, "current_content_inline"),
                content_ref=optional_string(body, "content_ref") or optional_string(body, "current_content_ref"),
                refs=refs_list(body.get("refs", ()), "refs"),
                action=optional_string(body, "action") or "continue",
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return {"delivery": delivery_to_dict(delivery)}

    def submit_delivery_decision(self, delivery_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._service.decide_delivery(
                delivery_id,
                agent_handle=required_string(body, "agent_handle"),
                decision=required_string(body, "decision"),
                content=optional_string(body, "content") or optional_string(body, "content_inline"),
                content_ref=optional_string(body, "content_ref"),
                refs=refs_list(body.get("refs", ()), "refs"),
                action_type=optional_string(body, "action_type"),
                action_target=optional_string(body, "action_target"),
                action_runtime=optional_string(body, "action_runtime") or "cloud",
                requires_approval=optional_bool(body, "requires_approval", default=True),
                note=optional_string(body, "note"),
            )
        except InvalidMessageError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except ForbiddenDeliveryError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc

        return decision_result_to_dict(result)


def send_result_to_dict(result: SendMessageResult) -> dict[str, Any]:
    return {
        "message": message_to_dict(result.message),
        "thread": thread_to_dict(result.thread),
        "deliveries": [delivery_to_dict(delivery) for delivery in result.deliveries],
        "message_id": result.message.message_id,
        "thread_id": result.thread.thread_id,
    }


def payload_record_to_dict(payload: PayloadRecord) -> dict[str, Any]:
    return {
        "content_ref": payload.content_ref,
        "media_type": payload.media_type,
        "byte_length": payload.byte_length,
        "hash": payload.hash,
        "compression": payload.compression,
        "compressed_byte_length": payload.compressed_byte_length,
        "compressed_hash": payload.compressed_hash,
        "ttl_expires_at": datetime_to_string(payload.ttl_expires_at),
        "retention_state": payload.retention_state,
        "access_scope": payload.access_scope,
        "fetch_policy_ref": payload.fetch_policy_ref,
        "chunk_manifest_ref": payload.chunk_manifest_ref,
        "storage_provider": payload.storage_provider,
        "storage_ref": payload.storage_ref,
        "created_at": datetime_to_string(payload.created_at),
    }


def payload_compaction_to_dict(compaction: PayloadCompaction) -> dict[str, Any]:
    return {
        "manifest_ref": compaction.manifest_ref,
        "summary": compaction.summary,
        "selected_chunk_refs": list(compaction.selected_chunk_refs),
        "selected_chunk_count": len(compaction.selected_chunks),
        "selected_chunk_byte_lengths": [len(chunk) for chunk in compaction.selected_chunks],
        "created_at": datetime_to_string(compaction.created_at),
    }


def agent_to_dict(agent: Agent) -> dict[str, Any]:
    # The public profile shape lives in domain.cards so the local api and the
    # deployed adapters share exactly one sanitizer.
    return agent_card(agent)


def agent_token_principal_to_dict(principal: Any) -> dict[str, Any]:
    return {
        "token_id": principal.token_id,
        "agent_id": principal.agent_id,
        "agent_handle": principal.agent_handle,
        "scopes": sorted(principal.scopes),
        "owner_user_id": principal.owner_user_id,
        "node_id": principal.node_id,
    }


def agent_token_record_to_dict(record: AgentTokenRecord) -> dict[str, Any]:
    return {
        "token_id": record.token_id,
        "agent_id": record.agent_id,
        "agent_handle": record.agent_handle,
        "scopes": sorted(record.scopes),
        "name": record.name,
        "owner_user_id": record.owner_user_id,
        "node_id": record.node_id,
        "created_at": datetime_to_string(record.created_at),
        "expires_at": datetime_to_string(record.expires_at),
        "last_used_at": datetime_to_string(record.last_used_at),
        "revoked_at": datetime_to_string(record.revoked_at),
    }


def agent_registration_scopes(body: dict[str, Any]) -> tuple[str, ...]:
    if body.get("scopes") is None:
        return tuple(sorted(AGENT_TOKEN_SCOPES))
    return string_list(body.get("scopes"), "scopes")


def bearer_token_from_authorization(authorization: str | None) -> str:
    if not authorization:
        raise ApiError(401, "unauthorized", "missing authorization header")
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise ApiError(401, "unauthorized", "authorization header must be bearer token")
    return parts[1].strip()


def public_agent_handle(name: str) -> str:
    """Resolve a public-URL path segment to the handle form the hub stores.

    Handles in this hub include their host (``@worker:gulls.ai``) and the
    canonical stored form always starts with ``@``. The path segment accepts
    exactly that canonical form (URL-decoded) with the leading ``@`` optional:
    ``worker:gulls.ai`` becomes ``@worker:gulls.ai`` and bare ``worker``
    becomes ``@worker``. No other resolution (host defaulting, fuzzy
    matching) is attempted, so a bare name only works when the hub stores the
    hostless handle; anything else 404s at the agent lookup.

    The reserved ``@guest_`` namespace (server-minted ephemeral guest
    senders) is rejected outright: guests are never public-URL addressees.
    """
    candidate = (name or "").strip()
    if candidate and not candidate.startswith("@"):
        candidate = f"@{candidate}"
    normalized = normalize_handle(candidate)
    if normalized.startswith(GUEST_HANDLE_PREFIX):
        raise InvalidMessageError(
            f"the {GUEST_HANDLE_PREFIX} namespace is reserved and has no public agent URL"
        )
    return normalized


def guest_status_token(secret: str, delivery_id: str) -> str:
    """Hex HMAC-SHA256 over the delivery id: the guest status-poll capability."""
    return hmac.new(
        secret.encode("utf-8"),
        delivery_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def guest_invite_token(secret: str, recipient_handle: str, expires_epoch: int) -> str:
    """``<expiry>.<hex HMAC-SHA256>``: the ``token_required`` send capability.

    The MAC covers a domain-separation label, the recipient handle, and the
    expiry, so invite tokens can never collide with guest status tokens
    (which MAC a bare delivery id with the same secret) and an invite for one
    agent is worthless for another.
    """
    payload = f"guest-invite\n{recipient_handle}\n{expires_epoch}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{expires_epoch}.{digest}"


def verify_guest_invite_token(
    secret: str,
    recipient_handle: str,
    token: str,
    *,
    now_epoch: int,
) -> bool:
    value = (token or "").strip()
    expires_raw, separator, digest = value.partition(".")
    if not separator or not digest:
        return False
    try:
        expires_epoch = int(expires_raw)
    except ValueError:
        return False
    if expires_epoch < now_epoch:
        return False
    expected = guest_invite_token(secret, recipient_handle, expires_epoch)
    return hmac.compare_digest(expected, value)


def discovery_resource_handle(resource: str) -> str:
    """Resolve a ``/.well-known/gulls`` resource parameter to a handle.

    Accepts the canonical handle form (leading ``@`` optional, as on the
    public URL path) plus the webfinger ``acct:name@host`` shape. Guests are
    never discoverable, matching the public-URL namespace rule.
    """
    candidate = (resource or "").strip()
    if candidate.lower().startswith("acct:"):
        rest = candidate[5:].lstrip("@")
        name, separator, host = rest.partition("@")
        candidate = f"@{name}:{host}" if separator and host else f"@{name}"
    if candidate and not candidate.startswith("@"):
        candidate = f"@{candidate}"
    normalized = normalize_handle(candidate)
    if normalized.startswith(GUEST_HANDLE_PREFIX):
        raise InvalidMessageError(
            f"the {GUEST_HANDLE_PREFIX} namespace is reserved and is not discoverable"
        )
    return normalized


def message_to_dict(message: Message) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "thread_id": message.thread_id,
        "sender_agent_id": message.sender_agent_id,
        "recipient_agent_ids": list(message.recipient_agent_ids),
        "intent": message.intent,
        "visibility": message.visibility,
        "content_inline": message.content_inline,
        "content_ref": message.content_ref,
        "refs": [message_ref_to_dict(ref) for ref in message.refs],
        "schema_version": message.schema_version,
        "safety_status": message.safety_status,
        "created_at": datetime_to_string(message.created_at),
    }


def thread_to_dict(thread: ThreadRecord) -> dict[str, Any]:
    return {
        "thread_id": thread.thread_id,
        "root_message_id": thread.root_message_id,
        "participants": sorted(thread.participants),
        "message_count": thread.message_count,
        "last_message_id": thread.last_message_id,
        "last_message_at": datetime_to_string(thread.last_message_at),
        "title": thread.title,
        "summary_ref": thread.summary_ref,
        "created_at": datetime_to_string(thread.created_at),
        "updated_at": datetime_to_string(thread.updated_at),
    }


def delivery_to_dict(delivery: Delivery) -> dict[str, Any]:
    return {
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
        "refs": [message_ref_to_dict(ref) for ref in delivery.refs],
        "workflow_trace": [workflow_trace_to_dict(entry) for entry in delivery.workflow_trace],
        "current_stage": delivery.current_stage,
        "action_request": None if delivery.action_request is None else action_request_to_dict(delivery.action_request),
        "created_at": datetime_to_string(delivery.created_at),
        "updated_at": datetime_to_string(delivery.updated_at),
        "acked_at": datetime_to_string(delivery.acked_at),
    }


def contact_explanation_to_dict(explanation: ContactExplanation) -> dict[str, Any]:
    return {
        "explanation_id": explanation.explanation_id,
        "delivery_id": explanation.delivery_id,
        "message_id": explanation.message_id,
        "thread_id": explanation.thread_id,
        "requester_agent_id": explanation.requester_agent_id,
        "requester_handle": explanation.requester_handle,
        "recipient_agent_id": explanation.recipient_agent_id,
        "recipient_handle": explanation.recipient_handle,
        "answering_asset_handle": explanation.answering_asset_handle,
        "relationship": explanation.relationship,
        "reason": explanation.reason,
        "allowed_reason": explanation.allowed_reason,
        "shared_context_summary": explanation.shared_context_summary,
        "shared_context_refs": list(explanation.shared_context_refs),
        "pending_action": explanation.pending_action,
        "current_stage": explanation.current_stage,
        "policy_refs": list(explanation.policy_refs),
        "audit_event_refs": list(explanation.audit_event_refs),
        "created_at": datetime_to_string(explanation.created_at),
    }


def inbox_item_to_dict(item: InboxItem) -> dict[str, Any]:
    return {
        "delivery": delivery_to_dict(item.delivery),
        "message": message_to_dict(item.message),
        "current_message": {
            "content_inline": item.delivery.current_content_inline or item.message.content_inline,
            "content_ref": item.delivery.current_content_ref or item.message.content_ref,
            "refs": [message_ref_to_dict(ref) for ref in item.delivery.refs or item.message.refs],
        },
    }


def routing_rule_to_dict(rule: RoutingRule) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "name": rule.name,
        "mode": rule.mode.value,
        "route_to_handles": list(rule.route_to_handles),
        "url_contains": list(rule.url_contains),
        "enabled": rule.enabled,
        "created_at": datetime_to_string(rule.created_at),
        "updated_at": datetime_to_string(rule.updated_at),
    }


def message_ref_to_dict(ref: MessageRef) -> dict[str, Any]:
    return {
        "type": ref.type,
        "url": ref.url,
        "find": ref.find,
        "remember_as": ref.remember_as,
    }


def workflow_trace_to_dict(entry: WorkflowTraceEntry) -> dict[str, Any]:
    return {
        "hook": entry.hook,
        "runtime": entry.runtime,
        "action": entry.action,
        "actor": entry.actor,
        "changed": list(entry.changed),
        "note": entry.note,
        "created_at": datetime_to_string(entry.created_at),
    }


def action_request_to_dict(action_request: ActionRequest) -> dict[str, Any]:
    return {
        "action_request_id": action_request.action_request_id,
        "type": action_request.type,
        "target": action_request.target,
        "runtime": action_request.runtime,
        "requires_approval": action_request.requires_approval,
        "status": action_request.status,
        "created_at": datetime_to_string(action_request.created_at),
    }


def decision_result_to_dict(result: AgentDecisionResult) -> dict[str, Any]:
    return {
        "delivery": delivery_to_dict(result.delivery),
        "reply": None if result.reply is None else send_result_to_dict(result.reply),
        "action_request": None if result.action_request is None else action_request_to_dict(result.action_request),
    }


def thread_context_to_dict(context: ThreadContext) -> dict[str, Any]:
    return {
        "thread": thread_to_dict(context.thread),
        "summary": None if context.summary is None else {
            "summary_id": context.summary.summary_id,
            "thread_id": context.summary.thread_id,
            "summary_text": context.summary.summary_text,
            "message_start_id": context.summary.message_start_id,
            "message_end_id": context.summary.message_end_id,
            "token_count_estimate": context.summary.token_count_estimate,
            "content_ref": context.summary.content_ref,
            "created_at": datetime_to_string(context.summary.created_at),
        },
        "recent_messages": [message_to_dict(message) for message in context.recent_messages],
    }


def context_pack_to_dict(context_pack: ContextPack) -> dict[str, Any]:
    return {
        "context_pack_id": context_pack.context_pack_id,
        "thread": thread_to_dict(context_pack.thread),
        "requester_handle": context_pack.requester_handle,
        "summary": None if context_pack.summary is None else {
            "summary_id": context_pack.summary.summary_id,
            "thread_id": context_pack.summary.thread_id,
            "summary_text": context_pack.summary.summary_text,
            "message_start_id": context_pack.summary.message_start_id,
            "message_end_id": context_pack.summary.message_end_id,
            "token_count_estimate": context_pack.summary.token_count_estimate,
            "content_ref": context_pack.summary.content_ref,
            "created_at": datetime_to_string(context_pack.summary.created_at),
        },
        "recent_messages": [message_to_dict(message) for message in context_pack.recent_messages],
        "selected_refs": [message_ref_to_dict(ref) for ref in context_pack.selected_refs],
        "payload_refs": [context_payload_ref_to_dict(ref) for ref in context_pack.payload_refs],
        "budget": context_budget_to_dict(context_pack.budget),
        "access_scope": context_pack.access_scope,
        "allowed_recipients": list(context_pack.allowed_recipients),
        "redacted_refs": list(context_pack.redacted_refs),
        "created_at": datetime_to_string(context_pack.created_at),
    }


def context_budget_to_dict(budget: ContextBudget) -> dict[str, Any]:
    return {
        "max_inline_chars": budget.max_inline_chars,
        "max_recent_messages": budget.max_recent_messages,
        "max_payload_refs": budget.max_payload_refs,
        "token_budget_estimate": budget.token_budget_estimate,
        "inline_chars_used": budget.inline_chars_used,
        "recent_messages_returned": budget.recent_messages_returned,
        "payload_refs_returned": budget.payload_refs_returned,
        "truncated": budget.truncated,
    }


def context_payload_ref_to_dict(ref: ContextPayloadRef) -> dict[str, str]:
    return {
        "content_ref": ref.content_ref,
        "source_type": ref.source_type,
        "source_id": ref.source_id,
    }


def task_to_dict(task: TaskRecord) -> dict[str, Any]:
    return {
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
        "created_at": datetime_to_string(task.created_at),
        "updated_at": datetime_to_string(task.updated_at),
    }


def task_capacity_policy_to_dict(policy: TaskCapacitySharingPolicyRecord) -> dict[str, Any]:
    return {
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
        "limits_ref": policy.limits_ref,
        "abuse_policy_ref": policy.abuse_policy_ref,
        "policy_decision_id": policy.policy_decision_id,
        "audit_refs": list(policy.audit_refs),
        "created_at": datetime_to_string(policy.created_at),
    }


def task_credit_ledger_entry_to_dict(entry: TaskCreditLedgerEntry) -> dict[str, Any]:
    return {
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
        "created_at": datetime_to_string(entry.created_at),
    }


def task_credit_balance_to_dict(balance: TaskCreditBalance) -> dict[str, Any]:
    return {
        "account_agent_id": balance.account_agent_id,
        "available_balance": balance.available_balance,
        "escrow_balance": balance.escrow_balance,
        "total_balance": balance.total_balance,
        "settlement_scope": balance.settlement_scope,
    }


def task_worker_reputation_event_to_dict(event: TaskWorkerReputationEventRecord) -> dict[str, Any]:
    return {
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
        "created_at": datetime_to_string(event.created_at),
    }


def task_worker_reputation_summary_to_dict(summary: TaskWorkerReputationSummary) -> dict[str, Any]:
    return {
        "worker_agent_id": summary.worker_agent_id,
        "completed_task_count": summary.completed_task_count,
        "failed_task_count": summary.failed_task_count,
        "accepted_result_count": summary.accepted_result_count,
        "dispute_count": summary.dispute_count,
        "abuse_report_count": summary.abuse_report_count,
        "total_outcome_count": summary.total_outcome_count,
        "completion_rate": summary.completion_rate,
        "failure_rate": summary.failure_rate,
        "last_event_id": summary.last_event_id,
        "last_event_at": datetime_to_string(summary.last_event_at),
    }


def task_quote_to_dict(quote: TaskQuoteRecord) -> dict[str, Any]:
    return {
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
        "created_at": datetime_to_string(quote.created_at),
        "updated_at": datetime_to_string(quote.updated_at),
    }


def task_escrow_to_dict(escrow: TaskEscrowRecord) -> dict[str, Any]:
    return {
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
        "created_at": datetime_to_string(escrow.created_at),
        "updated_at": datetime_to_string(escrow.updated_at),
        "released_at": datetime_to_string(escrow.released_at),
    }


def tool_request_to_dict(tool_request: TaskToolRequest) -> dict[str, Any]:
    return {
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
        "tool_grant_id": tool_request.tool_grant_id,
        "accepted_by_agent_id": tool_request.accepted_by_agent_id,
        "result_ref": tool_request.result_ref,
        "artifact_refs": list(tool_request.artifact_refs),
        "tool_use_summary_ref": tool_request.tool_use_summary_ref,
        "created_at": datetime_to_string(tool_request.created_at),
        "updated_at": datetime_to_string(tool_request.updated_at),
    }


def tool_grant_to_dict(grant: ToolGrant) -> dict[str, Any]:
    return {
        "grant_id": grant.grant_id,
        "task_id": grant.task_id,
        "thread_id": grant.thread_id,
        "issuer_agent_id": grant.issuer_agent_id,
        "subject_agent_id": grant.subject_agent_id,
        "audience": grant.audience,
        "scopes": list(grant.scopes),
        "purpose": grant.purpose,
        "ttl_expires_at": datetime_to_string(grant.ttl_expires_at),
        "max_calls": grant.max_calls,
        "used_count": grant.used_count,
        "budget_ref": grant.budget_ref,
        "allowed_resource_selectors": list(grant.allowed_resource_selectors),
        "read_only": grant.read_only,
        "approval_id": grant.approval_id,
        "policy_decision_id": grant.policy_decision_id,
        "revoked_at": datetime_to_string(grant.revoked_at),
        "created_at": datetime_to_string(grant.created_at),
        "updated_at": datetime_to_string(grant.updated_at),
    }


def task_result_to_dict(result: TaskResultRecord) -> dict[str, Any]:
    return {
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
        "created_at": datetime_to_string(result.created_at),
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


def reject_private_task_fields(body: dict[str, Any]) -> None:
    private_fields = sorted(set(body) & PRIVATE_TASK_FIELDS)
    if private_fields:
        raise ApiError(
            400,
            "bad_request",
            f"private task field(s) are not accepted: {', '.join(private_fields)}",
        )


_validator = Validator(
    lambda message: ApiError(400, "bad_request", message),
    reject_bool_ints=True,
    strip_list_items=False,
)
required_string = _validator.required_string
optional_string = _validator.optional_string
string_list = _validator.string_list
optional_int = _validator.optional_int
required_int = _validator.required_int
optional_bool = _validator.optional_bool


def response_rules_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ApiError(400, "bad_request", "response_rules must be an object")
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
        raise ApiError(400, "bad_request", f"unknown response_rules field(s): {', '.join(unknown)}")
    return dict(value)


def refs_list(value: Any, field_name: str) -> tuple[MessageRef, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ApiError(400, "bad_request", f"{field_name} must be a list")

    refs: list[MessageRef] = []
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(400, "bad_request", f"{field_name} must contain objects")
        ref_type = optional_string(item, "type")
        if ref_type is None:
            raise ApiError(400, "bad_request", "ref type is required")
        refs.append(
            MessageRef(
                type=ref_type,
                url=optional_string(item, "url"),
                find=optional_string(item, "find"),
                remember_as=optional_string(item, "remember_as"),
            )
        )
    return tuple(refs)


def payload_content(body: dict[str, Any]) -> str | bytes:
    value = body.get("content")
    if value is None:
        value = body.get("content_inline")
    if value is None:
        value = body.get("content_bytes")
    if value is None:
        raise ApiError(400, "bad_request", "payload content is required")
    if not isinstance(value, (str, bytes)):
        raise ApiError(400, "bad_request", "payload content must be a string or bytes")
    return value


def optional_datetime(body: dict[str, Any], field_name: str) -> datetime | None:
    value = optional_string(body, field_name)
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ApiError(400, "bad_request", f"{field_name} must be an ISO datetime") from exc
