from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from seagull_protocol import (
    ProtocolError,
    RelationshipPreset,
    normalize_handle,
    normalize_relationship_preset,
    relationship_preset_defaults,
)

from pet_assets import (
    AgentAssetBinding,
    InvalidPetAssetRequestError,
    PersonalAgentAsset,
    PetAssetNotFoundError,
    PetAssetPermissionDeniedError,
    PetAssetService,
)

from social_api.domain.models import (
    AgentChatMessage,
    AgentChatSession,
    AgentProfileRecord,
    FeedEvent,
    FollowRecord,
    HumanIdentity,
    ModerationRecord,
    NodeRecord,
    Notification,
    PairTokenRecord,
    PostRecord,
    Room,
    RoomMembership,
    SharedReference,
    utc_now,
)
from social_api.domain.feed_mirror import FeedMirror, NullFeedMirror
from social_api.domain.feed_source import FeedSource, RepositoryFeedSource
from social_api.domain.human_proxy import (
    InvalidHumanProxyError,
    handle_domain,
    human_proxy_handle,
)
from social_api.storage.repository import AgentProfilePage, SocialRepository


MENTION_RE = re.compile(r"@[a-z0-9][a-z0-9_.-]*:[a-z0-9][a-z0-9.-]*", re.IGNORECASE)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DELIVERY_MODES = {"pull", "webhook", "pull_webhook"}
NODE_TYPES = {"cloud", "lan"}
CHAT_DELIVERY_STATUSES = {"stored", "delivered", "delivery_failed"}

IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]

LOGGER = logging.getLogger(__name__)


class AgentRegistry(Protocol):
    """Port for registering agent handles with the gulls message hub."""

    def register(self, handle: str, display_name: str | None = None) -> None:
        """Ensure the handle exists in the hub's agent registry."""


class NullAgentRegistry:
    """No-op registry for deployments and tests without a message hub."""

    def register(self, handle: str, display_name: str | None = None) -> None:
        return None


class SocialApiError(Exception):
    """Base error for social API domain failures."""


class DuplicateAgentHandleError(SocialApiError):
    """Raised when an agent handle is already used by a profile."""


class DuplicateRoomSlugError(SocialApiError):
    """Raised when a room slug is already used."""


class InvalidSocialRequestError(SocialApiError):
    """Raised when a social API request is invalid."""


class NotFoundError(SocialApiError):
    """Raised when a required social object is missing."""


class PermissionDeniedError(SocialApiError):
    """Raised when a human cannot operate on a requested agent."""


class AgentRegistryUnavailableError(SocialApiError):
    """Raised when gulls could not register a handle and is required to.

    gulls owns identity and handles, so when a registry is configured a
    profile it does not know about must not be presented as created.
    """


@contextmanager
def _pet_asset_errors() -> Iterator[None]:
    """Re-raise Pet asset failures as the social API's own error types.

    The Pet layer raises its own exceptions so it stays independent of
    seagulls. Mapping them here keeps the HTTP status mapping in
    ``api/local.py`` -- and every existing response body -- unchanged.
    """
    try:
        yield
    except InvalidPetAssetRequestError as exc:
        raise InvalidSocialRequestError(str(exc)) from exc
    except PetAssetNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except PetAssetPermissionDeniedError as exc:
        raise PermissionDeniedError(str(exc)) from exc


class SocialApiService:
    def __init__(
        self,
        repository: SocialRepository,
        *,
        id_factory: IdFactory | None = None,
        clock: Clock = utc_now,
        agent_registry: AgentRegistry | None = None,
        feed_mirror: FeedMirror | None = None,
        feed_source: FeedSource | None = None,
        require_agent_registry: bool | None = None,
        human_proxy_domain: str | None = None,
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory or self._default_id_factory
        self._clock = clock
        self._agent_registry = agent_registry or NullAgentRegistry()
        # gulls owns identity and handles, so a handle it rejects is arguably
        # not a usable profile. Enabling this makes that literal: registration
        # failure surfaces instead of leaving a seagulls-only ghost.
        #
        # Defaults to off. Registration has been best-effort by deliberate
        # design (the hub's POST /agents is an idempotent get-or-create, and
        # local dev runs with no hub), so turning it on trades a silent
        # inconsistency for a hard failure when the hub blips -- a deployment
        # decision, not one to make silently on everyone's behalf.
        self._require_agent_registry = bool(require_agent_registry)
        # Feed source of truth is moving to gulls; mirror every feed write
        # there while seagulls still serves reads from its own tables.
        self._feed_mirror = feed_mirror or NullFeedMirror()
        # Which posts appear, and in what order, stays a seagulls projection.
        # What a post *is* comes from here -- gulls once configured, the
        # seagulls tables until then (terminology.md:55).
        self._feed_source = feed_source or RepositoryFeedSource(repository)
        # Pins every human proxy to one namespace so a person has a single
        # network identity. Unset means "follow the agent being chatted", which
        # keeps tests and local runs working with no configuration but gives a
        # human one proxy per domain.
        self._human_proxy_domain = (human_proxy_domain or "").strip().lower() or None
        # The social repository already implements the five methods
        # PetAssetRepository declares, so it satisfies the port structurally --
        # assets keep living in the same two tables.
        self._pet_assets = PetAssetService(
            repository,
            id_factory=self._new_id,
            clock=clock,
        )

    def identify_human(
        self,
        *,
        provider: str,
        subject: str,
        email: str | None = None,
        display_name: str | None = None,
    ) -> HumanIdentity:
        provider = normalized_required(provider, "provider")
        subject = normalized_required(subject, "subject")
        existing = self._repository.get_human_identity_by_provider_subject(provider, subject)
        now = self._clock()
        if existing is not None:
            # Only overwrite stored fields when a fresh value is actually supplied;
            # a request whose JWT lacks email/name must not wipe the stored ones.
            resolved_email = clean_optional(email)
            if resolved_email is None:
                resolved_email = existing.email
            resolved_display_name = clean_optional(display_name)
            if resolved_display_name is None:
                resolved_display_name = existing.display_name
            if resolved_email == existing.email and resolved_display_name == existing.display_name:
                # Nothing changed; avoid a DynamoDB write on every authenticated request.
                return existing
            updated = replace(
                existing,
                email=resolved_email,
                display_name=resolved_display_name,
                updated_at=now,
            )
            self._repository.put_human_identity(updated)
            return updated

        identity = HumanIdentity(
            user_id=self._new_id("user"),
            provider=provider,
            subject=subject,
            email=clean_optional(email),
            display_name=clean_optional(display_name),
            created_at=now,
            updated_at=now,
        )
        self._repository.put_human_identity(identity)
        return identity

    def create_agent_profile(
        self,
        *,
        owner_user_id: str,
        handle: str,
        display_name: str | None = None,
        bio: str | None = None,
        capabilities: Sequence[str] = (),
        relationship_posture: str = "needs_approval",
        approval_required_for: Sequence[str] | None = None,
        allowed_use_terms: Sequence[str] | None = None,
        contact_explanation: str | None = None,
        protocols: Sequence[str] = ("seagull",),
        node_id: str | None = None,
        delivery_mode: str = "pull",
        last_seen_at: datetime | None = None,
    ) -> AgentProfileRecord:
        self._require_identity(owner_user_id)
        if node_id is not None:
            node = self._require_node(node_id)
            self._require_node_owner(owner_user_id, node)
        normalized_handle = normalize_agent_handle(handle)
        if self._repository.get_agent_profile_by_handle(normalized_handle) is not None:
            raise DuplicateAgentHandleError(f"agent handle already exists: {normalized_handle}")

        now = self._clock()
        normalized_relationship_posture, normalized_approval_required_for, normalized_allowed_use_terms = (
            normalize_relationship_policy(
                relationship_posture=relationship_posture,
                approval_required_for=approval_required_for,
                allowed_use_terms=allowed_use_terms,
            )
        )
        profile = AgentProfileRecord(
            agent_id=self._new_id("agent"),
            owner_user_id=owner_user_id,
            handle=normalized_handle,
            display_name=clean_optional(display_name),
            bio=clean_optional(bio),
            capabilities=clean_string_tuple(capabilities, "capabilities"),
            relationship_posture=normalized_relationship_posture,
            approval_required_for=normalized_approval_required_for,
            allowed_use_terms=normalized_allowed_use_terms,
            contact_explanation=clean_optional(contact_explanation),
            protocols=clean_string_tuple(protocols, "protocols") or ("seagull",),
            node_id=clean_optional(node_id),
            delivery_mode=normalize_delivery_mode(delivery_mode),
            last_seen_at=last_seen_at,
            created_at=now,
            updated_at=now,
        )
        self._repository.put_agent_profile(profile)
        # gulls owns identity and handles; the local profile table only keeps
        # product metadata on top. The hub's POST /agents is an idempotent
        # get-or-create, so re-registering an existing handle is safe.
        self._register_agent_handle(profile)
        return profile

    def _register_agent_handle(self, profile: AgentProfileRecord) -> None:
        try:
            self._agent_registry.register(profile.handle, display_name=profile.display_name)
        except Exception as exc:
            if self._require_agent_registry:
                # A profile gulls does not know about has no identity on the
                # network, so surface the failure rather than creating a
                # seagulls-only ghost.
                raise AgentRegistryUnavailableError(
                    f"gulls agent registry rejected handle {profile.handle}: {exc}"
                ) from exc
            # No registry configured (local dev, single-store deployments):
            # there is no gulls to be authoritative, so carry on.
            LOGGER.warning("agent registry registration failed for %s: %s", profile.handle, exc)

    def update_agent_profile(
        self,
        *,
        owner_user_id: str,
        handle: str,
        display_name: str | None = None,
        bio: str | None = None,
        capabilities: Sequence[str] | None = None,
        relationship_posture: str | None = None,
        approval_required_for: Sequence[str] | None = None,
        allowed_use_terms: Sequence[str] | None = None,
        contact_explanation: str | None = None,
    ) -> AgentProfileRecord:
        profile = self._require_profile_by_handle(handle)
        self._require_owner(owner_user_id, profile)
        normalized_relationship_posture, normalized_approval_required_for, normalized_allowed_use_terms = (
            normalize_relationship_policy(
                relationship_posture=relationship_posture
                if relationship_posture is not None
                else profile.relationship_posture,
                approval_required_for=approval_required_for,
                allowed_use_terms=allowed_use_terms,
                current_approval_required_for=profile.approval_required_for
                if relationship_posture is None
                else None,
                current_allowed_use_terms=profile.allowed_use_terms
                if relationship_posture is None
                else None,
            )
        )
        updated = replace(
            profile,
            display_name=clean_optional(display_name) if display_name is not None else profile.display_name,
            bio=clean_optional(bio) if bio is not None else profile.bio,
            capabilities=clean_string_tuple(capabilities, "capabilities") if capabilities is not None else profile.capabilities,
            relationship_posture=normalized_relationship_posture,
            approval_required_for=normalized_approval_required_for,
            allowed_use_terms=normalized_allowed_use_terms,
            contact_explanation=clean_optional(contact_explanation)
            if contact_explanation is not None
            else profile.contact_explanation,
            updated_at=self._clock(),
        )
        self._repository.put_agent_profile(updated)
        return updated

    def list_owned_profiles(
        self,
        owner_user_id: str,
        *,
        limit: int | None = None,
        q: str | None = None,
        status: str | None = None,
        node_id: str | None = None,
    ) -> tuple[AgentProfileRecord, ...]:
        self._require_identity(owner_user_id)
        profiles = self._repository.list_agent_profiles_by_owner(owner_user_id)
        query = clean_optional(q)
        normalized_status = clean_optional(status)
        normalized_node_id = clean_optional(node_id)

        if query is not None:
            lowered_query = query.lower()
            profiles = tuple(
                profile
                for profile in profiles
                if lowered_query in profile.handle.lower()
                or (profile.display_name is not None and lowered_query in profile.display_name.lower())
                or any(lowered_query in capability.lower() for capability in profile.capabilities)
                or lowered_query in profile.relationship_posture.lower()
                or any(lowered_query in term.lower() for term in profile.allowed_use_terms)
            )
        if normalized_status is not None:
            profiles = tuple(profile for profile in profiles if profile.status == normalized_status)
        if normalized_node_id is not None:
            profiles = tuple(profile for profile in profiles if profile.node_id == normalized_node_id)

        if limit is None:
            return profiles
        return profiles[:normalize_limit(limit)]

    def list_owned_profiles_page(
        self,
        owner_user_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
        q: str | None = None,
        status: str | None = None,
        node_id: str | None = None,
    ) -> AgentProfilePage:
        normalized_limit = normalize_limit(limit)
        query = clean_optional(q)
        normalized_status = clean_optional(status)
        normalized_node_id = clean_optional(node_id)
        normalized_cursor = clean_optional(cursor)

        if query is not None or normalized_status is not None or normalized_node_id is not None:
            if normalized_cursor is not None:
                raise InvalidSocialRequestError("cursor is not supported with profile filters yet")
            return AgentProfilePage(
                items=self.list_owned_profiles(
                    owner_user_id,
                    limit=normalized_limit,
                    q=query,
                    status=normalized_status,
                    node_id=normalized_node_id,
                )
            )

        self._require_identity(owner_user_id)
        try:
            return self._repository.list_agent_profiles_by_owner_page(
                owner_user_id,
                limit=normalized_limit,
                cursor=normalized_cursor,
            )
        except ValueError as exc:
            raise InvalidSocialRequestError(str(exc)) from exc

    def count_owned_profiles(self, owner_user_id: str) -> int:
        self._require_identity(owner_user_id)
        return self._repository.count_agent_profiles_by_owner(owner_user_id)

    # Asset operations below delegate to the Pet product layer. seagulls still
    # resolves the handle and checks who owns the *agent* -- that is profile
    # territory -- then hands Pet the resolved agent id.

    def create_personal_agent_asset(
        self,
        *,
        owner_user_id: str,
        asset_type: str,
        name: str,
        instructions: str,
        description: str | None = None,
        style: str | None = None,
        tags: Sequence[str] = (),
        max_output_chars: int | None = None,
    ) -> PersonalAgentAsset:
        self._require_identity(owner_user_id)
        with _pet_asset_errors():
            return self._pet_assets.create_personal_agent_asset(
                owner_user_id=owner_user_id,
                asset_type=asset_type,
                name=name,
                instructions=instructions,
                description=description,
                style=style,
                tags=tags,
                max_output_chars=max_output_chars,
            )

    def list_personal_agent_assets(
        self,
        owner_user_id: str,
        *,
        asset_type: str | None = None,
    ) -> tuple[PersonalAgentAsset, ...]:
        self._require_identity(owner_user_id)
        with _pet_asset_errors():
            return self._pet_assets.list_personal_agent_assets(
                owner_user_id,
                asset_type=asset_type,
            )

    def get_personal_agent_asset(
        self,
        *,
        owner_user_id: str,
        asset_id: str,
    ) -> PersonalAgentAsset:
        with _pet_asset_errors():
            return self._pet_assets.get_personal_agent_asset(
                owner_user_id=owner_user_id,
                asset_id=asset_id,
            )

    def set_agent_asset_binding(
        self,
        *,
        owner_user_id: str,
        agent_handle: str,
        prompt_asset_id: str | None = None,
        skill_asset_id: str | None = None,
    ) -> AgentAssetBinding:
        profile = self._require_profile_by_handle(agent_handle)
        self._require_owner(owner_user_id, profile)
        with _pet_asset_errors():
            return self._pet_assets.set_agent_asset_binding(
                owner_user_id=owner_user_id,
                agent_id=profile.agent_id,
                prompt_asset_id=prompt_asset_id,
                skill_asset_id=skill_asset_id,
            )

    def get_owned_profile(
        self,
        *,
        owner_user_id: str,
        agent_handle: str,
    ) -> AgentProfileRecord:
        profile = self._require_profile_by_handle(agent_handle)
        self._require_owner(owner_user_id, profile)
        return profile

    def get_agent_asset_binding(
        self,
        *,
        owner_user_id: str,
        agent_handle: str,
    ) -> AgentAssetBinding | None:
        profile = self._require_profile_by_handle(agent_handle)
        self._require_owner(owner_user_id, profile)
        return self._pet_assets.get_agent_asset_binding(profile.agent_id)

    def create_agent_chat(
        self,
        *,
        owner_user_id: str,
        agent_handle: str,
        title: str | None = None,
        sender_handle: str | None = None,
    ) -> AgentChatSession:
        profile = self._require_profile_by_handle(agent_handle)
        self._require_owner(owner_user_id, profile)
        sender = None
        if sender_handle is not None:
            sender = self._require_profile_by_handle(sender_handle)
            self._require_owner(owner_user_id, sender)

        # Without a sender the chat cannot enter the shared Inbox at all: the
        # delivery step returns early on a null sender_handle. The web never
        # passes one, so every real chat used to be seagulls-only. Fall back to
        # the owner's stable human proxy so the message reaches gulls.
        resolved_sender_handle = None if sender is None else sender.handle
        resolved_sender_agent_id = None if sender is None else sender.agent_id
        if resolved_sender_handle is None:
            resolved_sender_handle = self._ensure_human_proxy_handle(
                owner_user_id, agent_handle=profile.handle
            )

        binding = self._repository.get_agent_asset_binding(profile.agent_id)
        now = self._clock()
        chat = AgentChatSession(
            chat_id=self._new_id("chat"),
            owner_user_id=owner_user_id,
            agent_id=profile.agent_id,
            agent_handle=profile.handle,
            title=clean_optional(title) or f"Chat with {profile.display_name or profile.handle}",
            sender_agent_id=resolved_sender_agent_id,
            sender_handle=resolved_sender_handle,
            prompt_asset_id=None if binding is None else binding.prompt_asset_id,
            skill_asset_id=None if binding is None else binding.skill_asset_id,
            created_at=now,
            updated_at=now,
        )
        self._repository.put_agent_chat_session(chat)
        return chat

    def list_agent_chats(self, owner_user_id: str) -> tuple[AgentChatSession, ...]:
        self._require_identity(owner_user_id)
        return self._repository.list_agent_chat_sessions_by_owner(owner_user_id)

    def get_agent_chat(
        self,
        *,
        owner_user_id: str,
        chat_id: str,
    ) -> AgentChatSession:
        chat = self._require_agent_chat(chat_id)
        self._require_chat_owner(owner_user_id, chat)
        return chat

    def create_agent_chat_message(
        self,
        *,
        owner_user_id: str,
        chat_id: str,
        content: str,
    ) -> AgentChatMessage:
        chat = self._require_agent_chat(chat_id)
        self._require_chat_owner(owner_user_id, chat)
        now = self._clock()
        message = AgentChatMessage(
            chat_message_id=self._new_id("chatmsg"),
            chat_id=chat.chat_id,
            owner_user_id=owner_user_id,
            sender_type="human",
            content=normalized_required(content, "content"),
            created_at=now,
            updated_at=now,
        )
        self._repository.put_agent_chat_message(message)
        self._repository.put_agent_chat_session(replace(chat, updated_at=now))
        return message

    def list_agent_chat_messages(
        self,
        *,
        owner_user_id: str,
        chat_id: str,
    ) -> tuple[AgentChatMessage, ...]:
        chat = self._require_agent_chat(chat_id)
        self._require_chat_owner(owner_user_id, chat)
        return self._repository.list_agent_chat_messages_by_chat(chat.chat_id)

    def record_agent_chat_message_delivery(
        self,
        *,
        owner_user_id: str,
        chat_message_id: str,
        delivery_status: str,
        hub_message_id: str | None = None,
        hub_thread_id: str | None = None,
        delivery_error: str | None = None,
    ) -> AgentChatMessage:
        message = self._require_agent_chat_message(chat_message_id)
        chat = self._require_agent_chat(message.chat_id)
        self._require_chat_owner(owner_user_id, chat)
        now = self._clock()
        updated = replace(
            message,
            hub_message_id=clean_optional(hub_message_id),
            hub_thread_id=clean_optional(hub_thread_id),
            delivery_status=normalize_chat_delivery_status(delivery_status),
            delivery_error=clean_optional(delivery_error),
            updated_at=now,
        )
        self._repository.put_agent_chat_message(updated)
        self._repository.put_agent_chat_session(
            replace(
                chat,
                hub_thread_id=updated.hub_thread_id or chat.hub_thread_id,
                updated_at=now,
            )
        )
        return updated

    def create_agent_chat_reply(
        self,
        *,
        owner_user_id: str,
        chat_id: str,
        content: str,
        ai_run_id: str | None = None,
        ai_run_state: str | None = None,
    ) -> AgentChatMessage:
        chat = self._require_agent_chat(chat_id)
        self._require_chat_owner(owner_user_id, chat)
        now = self._clock()
        reply = AgentChatMessage(
            chat_message_id=self._new_id("chatmsg"),
            chat_id=chat.chat_id,
            owner_user_id=owner_user_id,
            sender_type="agent",
            content=normalized_required(content, "content"),
            ai_run_id=clean_optional(ai_run_id),
            ai_run_state=clean_optional(ai_run_state),
            created_at=now,
            updated_at=now,
        )
        self._repository.put_agent_chat_message(reply)
        self._repository.put_agent_chat_session(replace(chat, updated_at=now))
        return reply

    def record_agent_chat_message_ai_state(
        self,
        *,
        owner_user_id: str,
        chat_message_id: str,
        ai_run_id: str | None = None,
        ai_run_state: str | None = None,
        ai_error: str | None = None,
    ) -> AgentChatMessage:
        message = self._require_agent_chat_message(chat_message_id)
        chat = self._require_agent_chat(message.chat_id)
        self._require_chat_owner(owner_user_id, chat)
        updated = replace(
            message,
            ai_run_id=clean_optional(ai_run_id),
            ai_run_state=clean_optional(ai_run_state),
            ai_error=clean_optional(ai_error),
            updated_at=self._clock(),
        )
        self._repository.put_agent_chat_message(updated)
        return updated

    def create_node(
        self,
        *,
        owner_user_id: str,
        node_type: str = "cloud",
    ) -> NodeRecord:
        self._require_identity(owner_user_id)
        now = self._clock()
        node = NodeRecord(
            node_id=self._new_id("node"),
            owner_user_id=owner_user_id,
            node_type=normalize_node_type(node_type),
            status="online",
            agent_count=0,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        self._repository.put_node(node)
        return node

    def list_nodes(self, owner_user_id: str) -> tuple[NodeRecord, ...]:
        self._require_identity(owner_user_id)
        return self._repository.list_nodes_by_owner(owner_user_id)

    def get_node(self, *, owner_user_id: str, node_id: str) -> NodeRecord:
        node = self._require_node(node_id)
        self._require_node_owner(owner_user_id, node)
        return node

    def create_pair_token(
        self,
        *,
        owner_user_id: str,
        node_id: str,
        ttl_seconds: int = 600,
    ) -> PairTokenRecord:
        node = self.get_node(owner_user_id=owner_user_id, node_id=node_id)
        now = self._clock()
        token = PairTokenRecord(
            pair_token=self._new_id("pair"),
            node_id=node.node_id,
            owner_user_id=node.owner_user_id,
            expires_at=now + timedelta(seconds=normalize_pair_token_ttl(ttl_seconds)),
            created_at=now,
        )
        self._repository.put_pair_token(token)
        return token

    def register_agent_with_pair_token(
        self,
        *,
        pair_token: str,
        handle: str,
        display_name: str | None = None,
        bio: str | None = None,
        capabilities: Sequence[str] = (),
        relationship_posture: str = "needs_approval",
        approval_required_for: Sequence[str] | None = None,
        allowed_use_terms: Sequence[str] | None = None,
        contact_explanation: str | None = None,
        protocols: Sequence[str] = ("seagull",),
        delivery_mode: str = "pull",
    ) -> AgentProfileRecord:
        token = self._repository.get_pair_token(normalized_required(pair_token, "pair_token"))
        now = self._clock()
        if token is None or token.used_at is not None or token.expires_at <= now:
            raise InvalidSocialRequestError("pair_token is invalid or expired")

        node = self._require_node(token.node_id)
        # create_agent_profile also registers the handle with the hub agent
        # registry (M0.2), so pair-token registration needs no extra call.
        profile = self.create_agent_profile(
            owner_user_id=token.owner_user_id,
            handle=handle,
            display_name=display_name,
            bio=bio,
            capabilities=capabilities,
            relationship_posture=relationship_posture,
            approval_required_for=approval_required_for,
            allowed_use_terms=allowed_use_terms,
            contact_explanation=contact_explanation,
            protocols=protocols,
            node_id=node.node_id,
            delivery_mode=delivery_mode,
            last_seen_at=now,
        )
        self._repository.put_pair_token(replace(token, used_at=now))
        self._repository.put_node(
            replace(
                node,
                agent_count=node.agent_count + 1,
                last_seen_at=now,
                updated_at=now,
            )
        )
        return profile

    def create_room(
        self,
        *,
        owner_user_id: str,
        slug: str,
        name: str,
        description: str | None = None,
        visibility: str = "public",
    ) -> Room:
        self._require_identity(owner_user_id)
        normalized_slug = normalize_slug(slug)
        if self._repository.get_room_by_slug(normalized_slug) is not None:
            raise DuplicateRoomSlugError(f"room slug already exists: {normalized_slug}")

        now = self._clock()
        room = Room(
            room_id=self._new_id("room"),
            slug=normalized_slug,
            name=normalized_required(name, "name"),
            description=clean_optional(description),
            visibility=normalized_required(visibility, "visibility"),
            created_by_user_id=owner_user_id,
            created_at=now,
            updated_at=now,
        )
        self._repository.put_room(room)
        self._feed_mirror.mirror_room(room)
        return room

    def join_room(
        self,
        *,
        owner_user_id: str,
        room_slug: str,
        agent_handle: str,
        role: str = "member",
    ) -> RoomMembership:
        room = self._require_room_by_slug(room_slug)
        profile = self._require_profile_by_handle(agent_handle)
        self._require_owner(owner_user_id, profile)
        existing = self._repository.get_room_membership(room.room_id, profile.agent_id)
        if existing is not None:
            return existing

        membership = RoomMembership(
            room_id=room.room_id,
            agent_id=profile.agent_id,
            role=normalized_required(role, "role"),
            created_at=self._clock(),
        )
        self._repository.put_room_membership(membership)
        self._feed_mirror.mirror_room_membership(membership)
        return membership

    def follow_agent(
        self,
        *,
        owner_user_id: str,
        follower_handle: str,
        followed_handle: str,
    ) -> FollowRecord:
        follower = self._require_profile_by_handle(follower_handle)
        followed = self._require_profile_by_handle(followed_handle)
        self._require_owner(owner_user_id, follower)
        if follower.agent_id == followed.agent_id:
            raise InvalidSocialRequestError("agent cannot follow itself")

        existing = self._repository.get_follow(follower.agent_id, followed.agent_id)
        if existing is not None:
            return existing

        follow = FollowRecord(
            follower_agent_id=follower.agent_id,
            followed_agent_id=followed.agent_id,
            created_at=self._clock(),
        )
        self._repository.put_follow(follow)
        self._feed_mirror.mirror_follow(follow)
        for post in self._repository.list_posts_by_author(followed.agent_id, limit=50):
            self._put_owner_feed_event_for_post(follower.owner_user_id, post)
        return follow

    def create_post(
        self,
        *,
        owner_user_id: str,
        author_handle: str,
        content: str | None = None,
        text: str | None = None,
        refs: Sequence[SharedReference | dict[str, Any]] = (),
        visibility: str = "public",
        room_slug: str | None = None,
        reply_to_post_id: str | None = None,
    ) -> PostRecord:
        author = self._require_profile_by_handle(author_handle)
        self._require_owner(owner_user_id, author)
        clean_text = normalized_required(text if text is not None else content, "text")
        clean_refs = clean_shared_references(refs)
        room = self._room_for_post(room_slug, author)
        if reply_to_post_id is not None and self._repository.get_post(reply_to_post_id) is None:
            raise NotFoundError(f"post not found: {reply_to_post_id}")

        mentioned_profiles = self._mentioned_profiles(clean_text)
        now = self._clock()
        post = PostRecord(
            post_id=self._new_id("post"),
            author_agent_id=author.agent_id,
            content=clean_text,
            text=clean_text,
            refs=clean_refs,
            visibility=normalized_required(visibility, "visibility"),
            room_id=None if room is None else room.room_id,
            reply_to_post_id=clean_optional(reply_to_post_id),
            mention_agent_ids=tuple(profile.agent_id for profile in mentioned_profiles),
            created_at=now,
        )
        self._repository.put_post(post)
        self._feed_mirror.mirror_post(post)
        feed_event = FeedEvent(
            event_id=self._new_id("event"),
            event_type="post",
            actor_agent_id=author.agent_id,
            object_id=post.post_id,
            target_agent_ids=post.mention_agent_ids,
            room_id=post.room_id,
            created_at=now,
        )
        self._repository.put_feed_event(feed_event)
        self._feed_mirror.mirror_feed_event(feed_event)
        # Per-owner fan-out below stays a seagulls projection and is not
        # mirrored: gulls owns the base Feed record, seagulls owns ranking.
        owner_feed_user_ids = {author.owner_user_id}
        owner_feed_user_ids.update(profile.owner_user_id for profile in mentioned_profiles)
        for follow in self._repository.list_follows_by_followed(author.agent_id):
            follower = self._repository.get_agent_profile(follow.follower_agent_id)
            if follower is not None:
                owner_feed_user_ids.add(follower.owner_user_id)
        for owner_feed_user_id in owner_feed_user_ids:
            self._repository.put_owner_feed_event(
                owner_feed_user_id,
                replace(feed_event, event_id=owner_feed_event_id(owner_feed_user_id, post.post_id)),
            )
        for mentioned in mentioned_profiles:
            if mentioned.agent_id == author.agent_id:
                continue
            notification = Notification(
                notification_id=self._new_id("notification"),
                recipient_agent_id=mentioned.agent_id,
                notification_type="mention",
                owner_user_id=mentioned.owner_user_id,
                actor_agent_id=author.agent_id,
                post_id=post.post_id,
                room_id=post.room_id,
                created_at=now,
            )
            self._repository.put_notification(notification)
            self._feed_mirror.mirror_notification(notification)
        return post

    def get_home_feed(self, owner_user_id: str, *, limit: int = 50) -> tuple[PostRecord, ...]:
        self._require_identity(owner_user_id)
        normalized_limit = normalize_limit(limit)
        return self._posts_from_feed_events(
            self._repository.list_feed_events_by_owner(owner_user_id, limit=normalized_limit),
            limit=normalized_limit,
        )

    def get_home_feed_for_profiles(
        self,
        owner_user_id: str,
        owned_profiles: Sequence[AgentProfileRecord],
        *,
        limit: int = 50,
    ) -> tuple[PostRecord, ...]:
        normalized_limit = normalize_limit(limit)
        for profile in owned_profiles:
            self._require_owner(owner_user_id, profile)
        self._require_identity(owner_user_id)
        return self._posts_from_feed_events(
            self._repository.list_feed_events_by_owner(owner_user_id, limit=normalized_limit),
            limit=normalized_limit,
        )

    def list_notifications(
        self,
        *,
        owner_user_id: str,
        agent_handle: str,
        limit: int = 50,
    ) -> tuple[Notification, ...]:
        profile = self._require_profile_by_handle(agent_handle)
        self._require_owner(owner_user_id, profile)
        return self._repository.list_notifications_by_recipient(
            profile.agent_id,
            limit=normalize_limit(limit),
        )

    def list_notifications_by_owner(self, owner_user_id: str, *, limit: int = 50) -> tuple[Notification, ...]:
        self._require_identity(owner_user_id)
        return self._repository.list_notifications_by_owner(owner_user_id, limit=normalize_limit(limit))

    def count_unread_notifications_by_owner(self, owner_user_id: str) -> int:
        self._require_identity(owner_user_id)
        return self._repository.count_unread_notifications_by_owner(owner_user_id)

    def create_moderation_record(
        self,
        *,
        owner_user_id: str,
        target_type: str,
        target_id: str,
        action: str,
        reason: str,
    ) -> ModerationRecord:
        self._require_identity(owner_user_id)
        record = ModerationRecord(
            moderation_id=self._new_id("moderation"),
            created_by_user_id=owner_user_id,
            target_type=normalized_required(target_type, "target_type"),
            target_id=normalized_required(target_id, "target_id"),
            action=normalized_required(action, "action"),
            reason=normalized_required(reason, "reason"),
            created_at=self._clock(),
        )
        self._repository.put_moderation_record(record)
        return record

    def list_moderation_records(self, *, limit: int = 50) -> tuple[ModerationRecord, ...]:
        return self._repository.list_moderation_records(limit=limit)

    def _room_for_post(self, room_slug: str | None, author: AgentProfileRecord) -> Room | None:
        if room_slug is None:
            return None
        room = self._require_room_by_slug(room_slug)
        if self._repository.get_room_membership(room.room_id, author.agent_id) is None:
            raise PermissionDeniedError(f"agent is not a member of room: {room.slug}")
        return room

    def _mentioned_profiles(self, content: str) -> tuple[AgentProfileRecord, ...]:
        profiles = []
        seen_agent_ids = set()
        for raw_handle in MENTION_RE.findall(content):
            normalized_handle = normalize_agent_handle(raw_handle.rstrip(".,;:!?)]}"))
            profile = self._repository.get_agent_profile_by_handle(normalized_handle)
            if profile is None or profile.agent_id in seen_agent_ids:
                continue
            seen_agent_ids.add(profile.agent_id)
            profiles.append(profile)
        return tuple(profiles)

    def _put_owner_feed_event_for_post(self, owner_user_id: str, post: PostRecord) -> None:
        self._repository.put_owner_feed_event(
            owner_user_id,
            FeedEvent(
                event_id=owner_feed_event_id(owner_user_id, post.post_id),
                event_type="post",
                actor_agent_id=post.author_agent_id,
                object_id=post.post_id,
                target_agent_ids=post.mention_agent_ids,
                room_id=post.room_id,
                created_at=post.created_at,
            ),
        )

    def _posts_from_feed_events(
        self,
        events: Sequence[FeedEvent],
        *,
        limit: int,
    ) -> tuple[PostRecord, ...]:
        posts: list[PostRecord] = []
        seen_post_ids: set[str] = set()
        for event in events:
            if event.object_id is None or event.object_id in seen_post_ids:
                continue
            post = self._feed_source.get_post(event.object_id)
            if post is None:
                continue
            seen_post_ids.add(post.post_id)
            posts.append(post)
            if len(posts) >= limit:
                break
        return tuple(posts)

    def _require_identity(self, user_id: str) -> HumanIdentity:
        identity = self._repository.get_human_identity(normalized_required(user_id, "user_id"))
        if identity is None:
            raise NotFoundError(f"user not found: {user_id}")
        return identity

    def _require_profile_by_handle(self, handle: str) -> AgentProfileRecord:
        normalized_handle = normalize_agent_handle(handle)
        profile = self._repository.get_agent_profile_by_handle(normalized_handle)
        if profile is None:
            raise NotFoundError(f"agent profile not found: {normalized_handle}")
        return profile

    def _ensure_human_proxy_handle(self, owner_user_id: str, *, agent_handle: str) -> str | None:
        """Resolve the owner's proxy handle and make sure gulls knows it.

        Registration is best-effort for the same reason profile registration is:
        ``POST /agents`` is an idempotent get-or-create, and local runs have no
        hub at all. A failure here costs the mirror for this chat, which the
        mirror metrics surface -- it must not stop the human starting one.

        Returns None if no handle can be derived, which leaves the chat exactly
        as it behaved before: seagulls-only, no delivery attempt.
        """
        domain = self._human_proxy_domain
        if domain is None:
            try:
                domain = handle_domain(agent_handle)
            except InvalidHumanProxyError:
                return None
        try:
            handle = human_proxy_handle(owner_user_id, domain=domain)
        except InvalidHumanProxyError:
            return None

        identity = self._repository.get_human_identity(owner_user_id)
        display_name = None if identity is None else identity.display_name
        try:
            self._agent_registry.register(handle, display_name)
        except Exception:  # noqa: BLE001 - best effort, same as profile registration
            LOGGER.warning("could not register human proxy %s", handle, exc_info=True)
        return handle

    def _require_agent_chat(self, chat_id: str) -> AgentChatSession:
        normalized_chat_id = normalized_required(chat_id, "chat_id")
        chat = self._repository.get_agent_chat_session(normalized_chat_id)
        if chat is None:
            raise NotFoundError(f"agent chat not found: {normalized_chat_id}")
        return chat

    def _require_agent_chat_message(self, chat_message_id: str) -> AgentChatMessage:
        normalized_message_id = normalized_required(chat_message_id, "chat_message_id")
        message = self._repository.get_agent_chat_message(normalized_message_id)
        if message is None:
            raise NotFoundError(f"agent chat message not found: {normalized_message_id}")
        return message

    def _require_room_by_slug(self, slug: str) -> Room:
        normalized_slug = normalize_slug(slug)
        room = self._repository.get_room_by_slug(normalized_slug)
        if room is None:
            raise NotFoundError(f"room not found: {normalized_slug}")
        return room

    def _require_node(self, node_id: str) -> NodeRecord:
        normalized_node_id = normalized_required(node_id, "node_id")
        node = self._repository.get_node(normalized_node_id)
        if node is None:
            raise NotFoundError(f"node not found: {normalized_node_id}")
        return node

    @staticmethod
    def _require_owner(owner_user_id: str, profile: AgentProfileRecord) -> None:
        if profile.owner_user_id != normalized_required(owner_user_id, "owner_user_id"):
            raise PermissionDeniedError(f"user does not own agent: {profile.handle}")

    @staticmethod
    def _require_chat_owner(owner_user_id: str, chat: AgentChatSession) -> None:
        if chat.owner_user_id != normalized_required(owner_user_id, "owner_user_id"):
            raise PermissionDeniedError(f"user does not own agent chat: {chat.chat_id}")

    @staticmethod
    def _require_node_owner(owner_user_id: str, node: NodeRecord) -> None:
        if node.owner_user_id != normalized_required(owner_user_id, "owner_user_id"):
            raise PermissionDeniedError(f"user does not own node: {node.node_id}")

    def _new_id(self, prefix: str) -> str:
        return self._id_factory(prefix)

    @staticmethod
    def _default_id_factory(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"


def normalize_agent_handle(handle: str) -> str:
    try:
        return normalize_handle(handle)
    except ProtocolError as exc:
        raise InvalidSocialRequestError(str(exc)) from exc


def normalize_relationship_policy(
    *,
    relationship_posture: str,
    approval_required_for: Sequence[str] | None = None,
    allowed_use_terms: Sequence[str] | None = None,
    current_approval_required_for: Sequence[str] | None = None,
    current_allowed_use_terms: Sequence[str] | None = None,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    try:
        preset = normalize_relationship_preset(relationship_posture)
    except ProtocolError as exc:
        raise InvalidSocialRequestError(str(exc)) from exc

    defaults = relationship_preset_defaults(preset)
    normalized_approval_required_for = (
        clean_string_tuple(approval_required_for, "approval_required_for")
        if approval_required_for is not None
        else clean_string_tuple(current_approval_required_for, "approval_required_for")
        if current_approval_required_for is not None
        else defaults.approval_required_for
    )
    normalized_allowed_use_terms = (
        clean_string_tuple(allowed_use_terms, "allowed_use_terms")
        if allowed_use_terms is not None
        else clean_string_tuple(current_allowed_use_terms, "allowed_use_terms")
        if current_allowed_use_terms is not None
        else defaults.allowed_use_terms
    )

    if preset == RelationshipPreset.BLOCKED and normalized_allowed_use_terms:
        raise InvalidSocialRequestError("blocked relationship cannot allow use terms")
    return preset.value, normalized_approval_required_for, normalized_allowed_use_terms


def normalize_slug(slug: str) -> str:
    normalized = normalized_required(slug, "slug").lower()
    if not SLUG_RE.fullmatch(normalized):
        raise InvalidSocialRequestError("slug must contain lowercase letters, numbers, or hyphens")
    return normalized


def normalize_delivery_mode(delivery_mode: str) -> str:
    normalized = normalized_required(delivery_mode, "delivery_mode").lower()
    if normalized not in DELIVERY_MODES:
        raise InvalidSocialRequestError("delivery_mode must be pull, webhook, or pull_webhook")
    return normalized


def normalize_node_type(node_type: str) -> str:
    normalized = normalized_required(node_type, "node_type").lower()
    if normalized not in NODE_TYPES:
        raise InvalidSocialRequestError("node_type must be cloud or lan")
    return normalized


def normalize_chat_delivery_status(status: str) -> str:
    normalized = normalized_required(status, "delivery_status").lower()
    if normalized not in CHAT_DELIVERY_STATUSES:
        raise InvalidSocialRequestError("delivery_status must be stored, delivered, or delivery_failed")
    return normalized


def normalize_limit(limit: int) -> int:
    if not isinstance(limit, int):
        raise InvalidSocialRequestError("limit must be an integer")
    return max(1, min(limit, 100))


def normalize_pair_token_ttl(ttl_seconds: int) -> int:
    if not isinstance(ttl_seconds, int):
        raise InvalidSocialRequestError("ttl_seconds must be an integer")
    return max(1, min(ttl_seconds, 3600))


def owner_feed_event_id(owner_user_id: str, post_id: str) -> str:
    return f"owner_feed:{owner_user_id}:{post_id}"


def normalized_required(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise InvalidSocialRequestError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise InvalidSocialRequestError(f"{field_name} is required")
    return stripped


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def clean_string_tuple(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise InvalidSocialRequestError(f"{field_name} must be a list")
    cleaned = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            raise InvalidSocialRequestError(f"{field_name} must contain only strings")
        stripped = value.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            cleaned.append(stripped)
    return tuple(cleaned)


def clean_shared_references(refs: Sequence[SharedReference | dict[str, Any]]) -> tuple[SharedReference, ...]:
    if not isinstance(refs, (list, tuple)):
        raise InvalidSocialRequestError("refs must be a list")

    cleaned: list[SharedReference] = []
    for ref in refs:
        if isinstance(ref, SharedReference):
            shared_ref = ref
        elif isinstance(ref, dict):
            ref_type = normalized_required(ref.get("type"), "refs.type").lower()
            if ref_type != "url":
                raise InvalidSocialRequestError("refs.type must be url")
            shared_ref = SharedReference(
                ref_type=ref_type,
                url=normalized_required(ref.get("url"), "refs.url"),
                find=clean_optional_ref_value(ref.get("find"), "refs.find"),
                remember_as=clean_optional_ref_value(ref.get("remember_as"), "refs.remember_as"),
            )
        else:
            raise InvalidSocialRequestError("refs must contain objects")

        if shared_ref.ref_type != "url":
            raise InvalidSocialRequestError("refs.type must be url")
        cleaned.append(
            SharedReference(
                ref_type=shared_ref.ref_type,
                url=normalized_required(shared_ref.url, "refs.url"),
                find=clean_optional_ref_value(shared_ref.find, "refs.find"),
                remember_as=clean_optional_ref_value(shared_ref.remember_as, "refs.remember_as"),
            )
        )
    return tuple(cleaned)


def clean_optional_ref_value(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidSocialRequestError(f"{field_name} must be a string")
    return clean_optional(value)
