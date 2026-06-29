from __future__ import annotations

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


class InMemorySocialRepository:
    def __init__(self) -> None:
        self._identities: dict[str, HumanIdentity] = {}
        self._identity_by_provider_subject: dict[tuple[str, str], str] = {}
        self._profiles: dict[str, AgentProfileRecord] = {}
        self._profile_by_handle: dict[str, str] = {}
        self._assets: dict[str, PersonalAgentAsset] = {}
        self._asset_ids_by_owner: dict[str, set[str]] = {}
        self._asset_bindings: dict[str, AgentAssetBinding] = {}
        self._agent_chats: dict[str, AgentChatSession] = {}
        self._agent_chat_ids_by_owner: dict[str, set[str]] = {}
        self._agent_chat_messages: dict[str, AgentChatMessage] = {}
        self._agent_chat_message_ids_by_chat: dict[str, set[str]] = {}
        self._nodes: dict[str, NodeRecord] = {}
        self._node_ids_by_owner: dict[str, set[str]] = {}
        self._pair_tokens: dict[str, PairTokenRecord] = {}
        self._rooms: dict[str, Room] = {}
        self._room_by_slug: dict[str, str] = {}
        self._memberships: dict[tuple[str, str], RoomMembership] = {}
        self._follows: dict[tuple[str, str], FollowRecord] = {}
        self._posts: dict[str, PostRecord] = {}
        self._feed_events: dict[str, FeedEvent] = {}
        self._notifications: dict[str, Notification] = {}
        self._moderation_records: dict[str, ModerationRecord] = {}

    def put_human_identity(self, identity: HumanIdentity) -> None:
        self._identities[identity.user_id] = identity
        self._identity_by_provider_subject[(identity.provider, identity.subject)] = identity.user_id

    def get_human_identity(self, user_id: str) -> HumanIdentity | None:
        return self._identities.get(user_id)

    def get_human_identity_by_provider_subject(self, provider: str, subject: str) -> HumanIdentity | None:
        user_id = self._identity_by_provider_subject.get((provider, subject))
        if user_id is None:
            return None
        return self._identities.get(user_id)

    def put_agent_profile(self, profile: AgentProfileRecord) -> None:
        self._profiles[profile.agent_id] = profile
        self._profile_by_handle[profile.handle] = profile.agent_id

    def get_agent_profile(self, agent_id: str) -> AgentProfileRecord | None:
        return self._profiles.get(agent_id)

    def get_agent_profile_by_handle(self, handle: str) -> AgentProfileRecord | None:
        agent_id = self._profile_by_handle.get(handle)
        if agent_id is None:
            return None
        return self._profiles.get(agent_id)

    def list_agent_profiles_by_owner(self, owner_user_id: str) -> tuple[AgentProfileRecord, ...]:
        return tuple(
            sorted(
                (profile for profile in self._profiles.values() if profile.owner_user_id == owner_user_id),
                key=lambda profile: profile.created_at,
            )
        )

    def put_personal_agent_asset(self, asset: PersonalAgentAsset) -> None:
        self._assets[asset.asset_id] = asset
        self._asset_ids_by_owner.setdefault(asset.owner_user_id, set()).add(asset.asset_id)

    def get_personal_agent_asset(self, asset_id: str) -> PersonalAgentAsset | None:
        return self._assets.get(asset_id)

    def list_personal_agent_assets_by_owner(self, owner_user_id: str) -> tuple[PersonalAgentAsset, ...]:
        asset_ids = self._asset_ids_by_owner.get(owner_user_id, set())
        return tuple(sorted((self._assets[asset_id] for asset_id in asset_ids), key=lambda asset: asset.created_at))

    def put_agent_asset_binding(self, binding: AgentAssetBinding) -> None:
        self._asset_bindings[binding.agent_id] = binding

    def get_agent_asset_binding(self, agent_id: str) -> AgentAssetBinding | None:
        return self._asset_bindings.get(agent_id)

    def put_agent_chat_session(self, chat: AgentChatSession) -> None:
        self._agent_chats[chat.chat_id] = chat
        self._agent_chat_ids_by_owner.setdefault(chat.owner_user_id, set()).add(chat.chat_id)

    def get_agent_chat_session(self, chat_id: str) -> AgentChatSession | None:
        return self._agent_chats.get(chat_id)

    def list_agent_chat_sessions_by_owner(self, owner_user_id: str) -> tuple[AgentChatSession, ...]:
        chat_ids = self._agent_chat_ids_by_owner.get(owner_user_id, set())
        return tuple(sorted((self._agent_chats[chat_id] for chat_id in chat_ids), key=lambda chat: chat.updated_at, reverse=True))

    def put_agent_chat_message(self, message: AgentChatMessage) -> None:
        self._agent_chat_messages[message.chat_message_id] = message
        self._agent_chat_message_ids_by_chat.setdefault(message.chat_id, set()).add(message.chat_message_id)

    def get_agent_chat_message(self, chat_message_id: str) -> AgentChatMessage | None:
        return self._agent_chat_messages.get(chat_message_id)

    def list_agent_chat_messages_by_chat(self, chat_id: str) -> tuple[AgentChatMessage, ...]:
        message_ids = self._agent_chat_message_ids_by_chat.get(chat_id, set())
        return tuple(sorted((self._agent_chat_messages[message_id] for message_id in message_ids), key=lambda message: message.created_at))

    def put_node(self, node: NodeRecord) -> None:
        self._nodes[node.node_id] = node
        self._node_ids_by_owner.setdefault(node.owner_user_id, set()).add(node.node_id)

    def get_node(self, node_id: str) -> NodeRecord | None:
        return self._nodes.get(node_id)

    def list_nodes_by_owner(self, owner_user_id: str) -> tuple[NodeRecord, ...]:
        node_ids = self._node_ids_by_owner.get(owner_user_id, set())
        return tuple(sorted((self._nodes[node_id] for node_id in node_ids), key=lambda node: node.created_at))

    def put_pair_token(self, token: PairTokenRecord) -> None:
        self._pair_tokens[token.pair_token] = token

    def get_pair_token(self, pair_token: str) -> PairTokenRecord | None:
        return self._pair_tokens.get(pair_token)

    def put_room(self, room: Room) -> None:
        self._rooms[room.room_id] = room
        self._room_by_slug[room.slug] = room.room_id

    def get_room(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)

    def get_room_by_slug(self, slug: str) -> Room | None:
        room_id = self._room_by_slug.get(slug)
        if room_id is None:
            return None
        return self._rooms.get(room_id)

    def put_room_membership(self, membership: RoomMembership) -> None:
        self._memberships[(membership.room_id, membership.agent_id)] = membership

    def get_room_membership(self, room_id: str, agent_id: str) -> RoomMembership | None:
        return self._memberships.get((room_id, agent_id))

    def list_room_memberships_by_agent(self, agent_id: str) -> tuple[RoomMembership, ...]:
        return tuple(membership for membership in self._memberships.values() if membership.agent_id == agent_id)

    def put_follow(self, follow: FollowRecord) -> None:
        self._follows[(follow.follower_agent_id, follow.followed_agent_id)] = follow

    def get_follow(self, follower_agent_id: str, followed_agent_id: str) -> FollowRecord | None:
        return self._follows.get((follower_agent_id, followed_agent_id))

    def list_follows_by_follower(self, follower_agent_id: str) -> tuple[FollowRecord, ...]:
        return tuple(follow for follow in self._follows.values() if follow.follower_agent_id == follower_agent_id)

    def put_post(self, post: PostRecord) -> None:
        self._posts[post.post_id] = post

    def get_post(self, post_id: str) -> PostRecord | None:
        return self._posts.get(post_id)

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        return tuple(sorted(self._posts.values(), key=lambda post: post.created_at, reverse=True)[:limit])

    def put_feed_event(self, event: FeedEvent) -> None:
        self._feed_events[event.event_id] = event

    def list_feed_events(self, *, limit: int = 50) -> tuple[FeedEvent, ...]:
        return tuple(sorted(self._feed_events.values(), key=lambda event: event.created_at, reverse=True)[:limit])

    def put_notification(self, notification: Notification) -> None:
        self._notifications[notification.notification_id] = notification

    def list_notifications_by_recipient(self, recipient_agent_id: str, *, limit: int = 50) -> tuple[Notification, ...]:
        notifications = (
            notification
            for notification in self._notifications.values()
            if notification.recipient_agent_id == recipient_agent_id
        )
        return tuple(sorted(notifications, key=lambda notification: notification.created_at, reverse=True)[:limit])

    def put_moderation_record(self, record: ModerationRecord) -> None:
        self._moderation_records[record.moderation_id] = record

    def list_moderation_records(self, *, limit: int = 50) -> tuple[ModerationRecord, ...]:
        return tuple(
            sorted(
                self._moderation_records.values(),
                key=lambda record: record.created_at,
                reverse=True,
            )[:limit]
        )
