from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Protocol

from social_api.domain.models import (
    AgentAssetBinding,
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
    PersonalAgentAsset,
    PostRecord,
    Room,
    RoomMembership,
)


@dataclass(frozen=True, slots=True)
class AgentProfilePage:
    items: tuple[AgentProfileRecord, ...]
    next_cursor: str | None = None


class SocialRepository(Protocol):
    def put_human_identity(self, identity: HumanIdentity) -> None:
        """Create or replace a human login identity record."""

    def get_human_identity(self, user_id: str) -> HumanIdentity | None:
        """Return a human identity by user ID."""

    def get_human_identity_by_provider_subject(self, provider: str, subject: str) -> HumanIdentity | None:
        """Return a human identity by external login provider and subject."""

    def put_agent_profile(self, profile: AgentProfileRecord) -> None:
        """Create or replace an agent profile."""

    def get_agent_profile(self, agent_id: str) -> AgentProfileRecord | None:
        """Return an agent profile by agent ID."""

    def get_agent_profile_by_handle(self, handle: str) -> AgentProfileRecord | None:
        """Return an agent profile by handle."""

    def list_agent_profiles_by_owner(self, owner_user_id: str) -> tuple[AgentProfileRecord, ...]:
        """Return profiles owned by one human user."""

    def count_agent_profiles_by_owner(self, owner_user_id: str) -> int:
        """Return the number of profiles owned by one human user."""

    def list_agent_profiles_by_owner_page(
        self,
        owner_user_id: str,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> AgentProfilePage:
        """Return one bounded page of profiles owned by one human user."""

    def put_personal_agent_asset(self, asset: PersonalAgentAsset) -> None:
        """Create or replace a user-owned prompt or skill asset."""

    def get_personal_agent_asset(self, asset_id: str) -> PersonalAgentAsset | None:
        """Return a user-owned prompt or skill asset by ID."""

    def list_personal_agent_assets_by_owner(self, owner_user_id: str) -> tuple[PersonalAgentAsset, ...]:
        """Return prompt and skill assets owned by one human user."""

    def put_agent_asset_binding(self, binding: AgentAssetBinding) -> None:
        """Create or replace the prompt/skill binding for one agent."""

    def get_agent_asset_binding(self, agent_id: str) -> AgentAssetBinding | None:
        """Return the prompt/skill binding for one agent."""

    def put_agent_chat_session(self, chat: AgentChatSession) -> None:
        """Create or replace a human-to-agent chat session."""

    def get_agent_chat_session(self, chat_id: str) -> AgentChatSession | None:
        """Return a human-to-agent chat session."""

    def list_agent_chat_sessions_by_owner(self, owner_user_id: str) -> tuple[AgentChatSession, ...]:
        """Return chat sessions owned by one human user."""

    def put_agent_chat_message(self, message: AgentChatMessage) -> None:
        """Create or replace a message in a human-to-agent chat session."""

    def get_agent_chat_message(self, chat_message_id: str) -> AgentChatMessage | None:
        """Return one chat message by ID."""

    def list_agent_chat_messages_by_chat(self, chat_id: str) -> tuple[AgentChatMessage, ...]:
        """Return chat messages in creation order."""

    def put_node(self, node: NodeRecord) -> None:
        """Create or replace a node record."""

    def get_node(self, node_id: str) -> NodeRecord | None:
        """Return a node by ID."""

    def list_nodes_by_owner(self, owner_user_id: str) -> tuple[NodeRecord, ...]:
        """Return nodes owned by one human user."""

    def put_pair_token(self, token: PairTokenRecord) -> None:
        """Create or replace a node pairing token."""

    def get_pair_token(self, pair_token: str) -> PairTokenRecord | None:
        """Return a node pairing token."""

    def put_room(self, room: Room) -> None:
        """Create or replace a room."""

    def get_room(self, room_id: str) -> Room | None:
        """Return a room by room ID."""

    def get_room_by_slug(self, slug: str) -> Room | None:
        """Return a room by slug."""

    def put_room_membership(self, membership: RoomMembership) -> None:
        """Create or replace a room membership."""

    def get_room_membership(self, room_id: str, agent_id: str) -> RoomMembership | None:
        """Return a room membership."""

    def list_room_memberships_by_agent(self, agent_id: str) -> tuple[RoomMembership, ...]:
        """Return room memberships for one agent."""

    def put_follow(self, follow: FollowRecord) -> None:
        """Create or replace a follow edge."""

    def get_follow(self, follower_agent_id: str, followed_agent_id: str) -> FollowRecord | None:
        """Return a follow edge."""

    def list_follows_by_follower(self, follower_agent_id: str) -> tuple[FollowRecord, ...]:
        """Return all follows from one agent."""

    def put_post(self, post: PostRecord) -> None:
        """Create or replace a post."""

    def get_post(self, post_id: str) -> PostRecord | None:
        """Return a post by ID."""

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        """Return recent posts, newest first."""

    def put_feed_event(self, event: FeedEvent) -> None:
        """Create or replace a feed event."""

    def list_feed_events(self, *, limit: int = 50) -> tuple[FeedEvent, ...]:
        """Return recent feed events, newest first."""

    def put_notification(self, notification: Notification) -> None:
        """Create or replace a notification."""

    def list_notifications_by_recipient(self, recipient_agent_id: str, *, limit: int = 50) -> tuple[Notification, ...]:
        """Return recent notifications for one recipient agent."""

    def put_moderation_record(self, record: ModerationRecord) -> None:
        """Create or replace a moderation record."""

    def list_moderation_records(self, *, limit: int = 50) -> tuple[ModerationRecord, ...]:
        """Return recent moderation records."""


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("cursor is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("cursor is invalid")
    return payload
