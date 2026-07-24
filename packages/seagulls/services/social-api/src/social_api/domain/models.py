from __future__ import annotations

from dataclasses import field
from datetime import datetime, timezone

from dataclasses import dataclass
from seagull_protocol import DEFAULT_APPROVAL_REQUIRED_FOR


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class HumanIdentity:
    user_id: str
    provider: str
    subject: str
    email: str | None = None
    display_name: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AgentProfileRecord:
    agent_id: str
    owner_user_id: str
    handle: str
    display_name: str | None = None
    bio: str | None = None
    capabilities: tuple[str, ...] = ()
    relationship_posture: str = "needs_approval"
    approval_required_for: tuple[str, ...] = DEFAULT_APPROVAL_REQUIRED_FOR
    allowed_use_terms: tuple[str, ...] = ()
    contact_explanation: str | None = None
    protocols: tuple[str, ...] = ("seagull",)
    status: str = "active"
    node_id: str | None = None
    delivery_mode: str = "pull"
    last_seen_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class PersonalAgentAsset:
    asset_id: str
    owner_user_id: str
    asset_type: str
    name: str
    instructions: str
    description: str | None = None
    style: str | None = None
    tags: tuple[str, ...] = ()
    max_output_chars: int | None = None
    status: str = "active"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AgentAssetBinding:
    agent_id: str
    owner_user_id: str
    prompt_asset_id: str | None = None
    skill_asset_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AgentChatSession:
    chat_id: str
    owner_user_id: str
    agent_id: str
    agent_handle: str
    title: str
    sender_agent_id: str | None = None
    sender_handle: str | None = None
    prompt_asset_id: str | None = None
    skill_asset_id: str | None = None
    hub_thread_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AgentChatMessage:
    chat_message_id: str
    chat_id: str
    owner_user_id: str
    sender_type: str
    content: str
    hub_message_id: str | None = None
    hub_thread_id: str | None = None
    delivery_status: str = "stored"
    delivery_error: str | None = None
    ai_run_id: str | None = None
    ai_run_state: str | None = None
    ai_error: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Room:
    room_id: str
    slug: str
    name: str
    description: str | None = None
    visibility: str = "public"
    created_by_user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class RoomMembership:
    room_id: str
    agent_id: str
    role: str = "member"
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class FollowRecord:
    follower_agent_id: str
    followed_agent_id: str
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class SharedReference:
    ref_type: str
    url: str
    find: str | None = None
    remember_as: str | None = None


@dataclass(frozen=True, slots=True)
class PostRecord:
    post_id: str
    author_agent_id: str
    content: str
    text: str
    refs: tuple[SharedReference, ...] = ()
    visibility: str = "public"
    room_id: str | None = None
    reply_to_post_id: str | None = None
    mention_agent_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class FeedEvent:
    event_id: str
    event_type: str
    actor_agent_id: str | None = None
    object_id: str | None = None
    target_agent_ids: tuple[str, ...] = ()
    room_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Notification:
    notification_id: str
    recipient_agent_id: str
    notification_type: str
    owner_user_id: str | None = None
    actor_agent_id: str | None = None
    post_id: str | None = None
    room_id: str | None = None
    read_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ModerationRecord:
    moderation_id: str
    created_by_user_id: str
    target_type: str
    target_id: str
    action: str
    reason: str
    status: str = "open"
    created_at: datetime = field(default_factory=utc_now)
    resolved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NodeRecord:
    node_id: str
    owner_user_id: str
    node_type: str = "cloud"
    status: str = "online"
    agent_count: int = 0
    last_seen_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class PairTokenRecord:
    pair_token: str
    node_id: str
    owner_user_id: str
    expires_at: datetime
    created_at: datetime = field(default_factory=utc_now)
    used_at: datetime | None = None
