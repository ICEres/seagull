from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from seagull_protocol import ProtocolError, normalize_handle

from social_api.domain.models import (
    AgentProfileRecord,
    DEFAULT_APPROVAL_REQUIRED_FOR,
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
from social_api.storage.repository import SocialRepository


MENTION_RE = re.compile(r"@[a-z0-9][a-z0-9_.-]*:[a-z0-9][a-z0-9.-]*", re.IGNORECASE)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DELIVERY_MODES = {"pull", "webhook", "pull_webhook"}
NODE_TYPES = {"cloud", "lan"}

IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]


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


class SocialApiService:
    def __init__(
        self,
        repository: SocialRepository,
        *,
        id_factory: IdFactory | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory or self._default_id_factory
        self._clock = clock

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
            updated = replace(
                existing,
                email=clean_optional(email),
                display_name=clean_optional(display_name),
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
        approval_required_for: Sequence[str] = DEFAULT_APPROVAL_REQUIRED_FOR,
        allowed_use_terms: Sequence[str] = (),
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
        profile = AgentProfileRecord(
            agent_id=self._new_id("agent"),
            owner_user_id=owner_user_id,
            handle=normalized_handle,
            display_name=clean_optional(display_name),
            bio=clean_optional(bio),
            capabilities=clean_string_tuple(capabilities, "capabilities"),
            relationship_posture=normalized_required(relationship_posture, "relationship_posture"),
            approval_required_for=clean_string_tuple(approval_required_for, "approval_required_for"),
            allowed_use_terms=clean_string_tuple(allowed_use_terms, "allowed_use_terms"),
            contact_explanation=clean_optional(contact_explanation),
            protocols=clean_string_tuple(protocols, "protocols") or ("seagull",),
            node_id=clean_optional(node_id),
            delivery_mode=normalize_delivery_mode(delivery_mode),
            last_seen_at=last_seen_at,
            created_at=now,
            updated_at=now,
        )
        self._repository.put_agent_profile(profile)
        return profile

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
        updated = replace(
            profile,
            display_name=clean_optional(display_name) if display_name is not None else profile.display_name,
            bio=clean_optional(bio) if bio is not None else profile.bio,
            capabilities=clean_string_tuple(capabilities, "capabilities") if capabilities is not None else profile.capabilities,
            relationship_posture=normalized_required(relationship_posture, "relationship_posture")
            if relationship_posture is not None
            else profile.relationship_posture,
            approval_required_for=clean_string_tuple(approval_required_for, "approval_required_for")
            if approval_required_for is not None
            else profile.approval_required_for,
            allowed_use_terms=clean_string_tuple(allowed_use_terms, "allowed_use_terms")
            if allowed_use_terms is not None
            else profile.allowed_use_terms,
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
        approval_required_for: Sequence[str] = DEFAULT_APPROVAL_REQUIRED_FOR,
        allowed_use_terms: Sequence[str] = (),
        contact_explanation: str | None = None,
        protocols: Sequence[str] = ("seagull",),
        delivery_mode: str = "pull",
    ) -> AgentProfileRecord:
        token = self._repository.get_pair_token(normalized_required(pair_token, "pair_token"))
        now = self._clock()
        if token is None or token.used_at is not None or token.expires_at <= now:
            raise InvalidSocialRequestError("pair_token is invalid or expired")

        node = self._require_node(token.node_id)
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
        self._repository.put_feed_event(
            FeedEvent(
                event_id=self._new_id("event"),
                event_type="post",
                actor_agent_id=author.agent_id,
                object_id=post.post_id,
                target_agent_ids=post.mention_agent_ids,
                room_id=post.room_id,
                created_at=now,
            )
        )
        for mentioned in mentioned_profiles:
            if mentioned.agent_id == author.agent_id:
                continue
            self._repository.put_notification(
                Notification(
                    notification_id=self._new_id("notification"),
                    recipient_agent_id=mentioned.agent_id,
                    notification_type="mention",
                    actor_agent_id=author.agent_id,
                    post_id=post.post_id,
                    room_id=post.room_id,
                    created_at=now,
                )
            )
        return post

    def get_home_feed(self, owner_user_id: str, *, limit: int = 50) -> tuple[PostRecord, ...]:
        owned_profiles = self._repository.list_agent_profiles_by_owner(owner_user_id)
        if not owned_profiles:
            self._require_identity(owner_user_id)
            return ()

        visible_agent_ids = {profile.agent_id for profile in owned_profiles}
        for profile in owned_profiles:
            for follow in self._repository.list_follows_by_follower(profile.agent_id):
                visible_agent_ids.add(follow.followed_agent_id)

        posts = []
        for post in self._repository.list_posts(limit=limit * 3):
            if post.author_agent_id in visible_agent_ids or visible_agent_ids.intersection(post.mention_agent_ids):
                posts.append(post)
            if len(posts) >= limit:
                break
        return tuple(posts)

    def list_notifications(
        self,
        *,
        owner_user_id: str,
        agent_handle: str,
        limit: int = 50,
    ) -> tuple[Notification, ...]:
        profile = self._require_profile_by_handle(agent_handle)
        self._require_owner(owner_user_id, profile)
        return self._repository.list_notifications_by_recipient(profile.agent_id, limit=limit)

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


def normalize_limit(limit: int) -> int:
    if not isinstance(limit, int):
        raise InvalidSocialRequestError("limit must be an integer")
    return max(1, min(limit, 100))


def normalize_pair_token_ttl(ttl_seconds: int) -> int:
    if not isinstance(ttl_seconds, int):
        raise InvalidSocialRequestError("ttl_seconds must be an integer")
    return max(1, min(ttl_seconds, 3600))


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
