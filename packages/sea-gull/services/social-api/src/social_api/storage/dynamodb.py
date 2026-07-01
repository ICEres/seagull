from __future__ import annotations

from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key

from social_api.domain.models import (
    AgentAssetBinding,
    AgentChatMessage,
    AgentChatSession,
    AgentProfileRecord,
    DEFAULT_APPROVAL_REQUIRED_FOR,
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
    SharedReference,
)
from social_api.storage.repository import AgentProfilePage, decode_cursor, encode_cursor


class DynamoDbSocialRepository:
    def __init__(
        self,
        *,
        identities_table: Any,
        profiles_table: Any,
        personal_agent_assets_table: Any,
        agent_asset_bindings_table: Any,
        agent_chats_table: Any,
        agent_chat_messages_table: Any,
        nodes_table: Any,
        pair_tokens_table: Any,
        rooms_table: Any,
        room_memberships_table: Any,
        follows_table: Any,
        posts_table: Any,
        feed_events_table: Any,
        notifications_table: Any,
        moderation_table: Any,
    ) -> None:
        self._identities_table = identities_table
        self._profiles_table = profiles_table
        self._personal_agent_assets_table = personal_agent_assets_table
        self._agent_asset_bindings_table = agent_asset_bindings_table
        self._agent_chats_table = agent_chats_table
        self._agent_chat_messages_table = agent_chat_messages_table
        self._nodes_table = nodes_table
        self._pair_tokens_table = pair_tokens_table
        self._rooms_table = rooms_table
        self._room_memberships_table = room_memberships_table
        self._follows_table = follows_table
        self._posts_table = posts_table
        self._feed_events_table = feed_events_table
        self._notifications_table = notifications_table
        self._moderation_table = moderation_table

    def put_human_identity(self, identity: HumanIdentity) -> None:
        self._identities_table.put_item(Item=human_identity_to_item(identity))

    def get_human_identity(self, user_id: str) -> HumanIdentity | None:
        return optional_item(
            self._identities_table.get_item(Key={"user_id": user_id}).get("Item"),
            item_to_human_identity,
        )

    def get_human_identity_by_provider_subject(self, provider: str, subject: str) -> HumanIdentity | None:
        result = self._identities_table.query(
            IndexName="provider-subject-index",
            KeyConditionExpression=Key("provider_subject").eq(provider_subject(provider, subject)),
            Limit=1,
        )
        items = result.get("Items", [])
        if not items:
            return None
        return item_to_human_identity(items[0])

    def put_agent_profile(self, profile: AgentProfileRecord) -> None:
        self._profiles_table.put_item(Item=agent_profile_to_item(profile))

    def get_agent_profile(self, agent_id: str) -> AgentProfileRecord | None:
        return optional_item(
            self._profiles_table.get_item(Key={"agent_id": agent_id}).get("Item"),
            item_to_agent_profile,
        )

    def get_agent_profile_by_handle(self, handle: str) -> AgentProfileRecord | None:
        result = self._profiles_table.query(
            IndexName="handle-index",
            KeyConditionExpression=Key("handle").eq(handle),
            Limit=1,
        )
        items = result.get("Items", [])
        if not items:
            return None
        return item_to_agent_profile(items[0])

    def list_agent_profiles_by_owner(self, owner_user_id: str) -> tuple[AgentProfileRecord, ...]:
        result = self._profiles_table.query(
            IndexName="owner-created-at-index",
            KeyConditionExpression=Key("owner_user_id").eq(owner_user_id),
            ScanIndexForward=True,
        )
        return tuple(item_to_agent_profile(item) for item in result.get("Items", []))

    def count_agent_profiles_by_owner(self, owner_user_id: str) -> int:
        count = 0
        exclusive_start_key: dict[str, Any] | None = None
        while True:
            query_args: dict[str, Any] = {
                "IndexName": "owner-created-at-index",
                "KeyConditionExpression": Key("owner_user_id").eq(owner_user_id),
                "Select": "COUNT",
            }
            if exclusive_start_key is not None:
                query_args["ExclusiveStartKey"] = exclusive_start_key
            result = self._profiles_table.query(**query_args)
            count += int(result.get("Count", 0))
            next_key = result.get("LastEvaluatedKey")
            if not isinstance(next_key, dict):
                return count
            exclusive_start_key = next_key

    def list_agent_profiles_by_owner_page(
        self,
        owner_user_id: str,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> AgentProfilePage:
        query_args: dict[str, Any] = {
            "IndexName": "owner-created-at-index",
            "KeyConditionExpression": Key("owner_user_id").eq(owner_user_id),
            "ScanIndexForward": True,
            "Limit": limit,
        }
        if cursor is not None:
            payload = decode_cursor(cursor)
            if payload.get("owner_user_id") != owner_user_id:
                raise ValueError("cursor does not match owner_user_id")
            exclusive_start_key = payload.get("exclusive_start_key")
            if not isinstance(exclusive_start_key, dict):
                raise ValueError("cursor is invalid")
            query_args["ExclusiveStartKey"] = exclusive_start_key

        result = self._profiles_table.query(**query_args)
        next_key = result.get("LastEvaluatedKey")
        next_cursor = (
            encode_cursor({"owner_user_id": owner_user_id, "exclusive_start_key": next_key})
            if isinstance(next_key, dict)
            else None
        )
        return AgentProfilePage(
            items=tuple(item_to_agent_profile(item) for item in result.get("Items", [])),
            next_cursor=next_cursor,
        )

    def put_personal_agent_asset(self, asset: PersonalAgentAsset) -> None:
        self._personal_agent_assets_table.put_item(Item=personal_agent_asset_to_item(asset))

    def get_personal_agent_asset(self, asset_id: str) -> PersonalAgentAsset | None:
        return optional_item(
            self._personal_agent_assets_table.get_item(Key={"asset_id": asset_id}).get("Item"),
            item_to_personal_agent_asset,
        )

    def list_personal_agent_assets_by_owner(self, owner_user_id: str) -> tuple[PersonalAgentAsset, ...]:
        result = self._personal_agent_assets_table.query(
            IndexName="owner-created-at-index",
            KeyConditionExpression=Key("owner_user_id").eq(owner_user_id),
            ScanIndexForward=True,
        )
        return tuple(item_to_personal_agent_asset(item) for item in result.get("Items", []))

    def put_agent_asset_binding(self, binding: AgentAssetBinding) -> None:
        self._agent_asset_bindings_table.put_item(Item=agent_asset_binding_to_item(binding))

    def get_agent_asset_binding(self, agent_id: str) -> AgentAssetBinding | None:
        return optional_item(
            self._agent_asset_bindings_table.get_item(Key={"agent_id": agent_id}).get("Item"),
            item_to_agent_asset_binding,
        )

    def put_agent_chat_session(self, chat: AgentChatSession) -> None:
        self._agent_chats_table.put_item(Item=agent_chat_session_to_item(chat))

    def get_agent_chat_session(self, chat_id: str) -> AgentChatSession | None:
        return optional_item(
            self._agent_chats_table.get_item(Key={"chat_id": chat_id}).get("Item"),
            item_to_agent_chat_session,
        )

    def list_agent_chat_sessions_by_owner(self, owner_user_id: str) -> tuple[AgentChatSession, ...]:
        result = self._agent_chats_table.query(
            IndexName="owner-updated-at-index",
            KeyConditionExpression=Key("owner_user_id").eq(owner_user_id),
            ScanIndexForward=False,
        )
        return tuple(item_to_agent_chat_session(item) for item in result.get("Items", []))

    def put_agent_chat_message(self, message: AgentChatMessage) -> None:
        self._agent_chat_messages_table.put_item(Item=agent_chat_message_to_item(message))

    def get_agent_chat_message(self, chat_message_id: str) -> AgentChatMessage | None:
        return optional_item(
            self._agent_chat_messages_table.get_item(Key={"chat_message_id": chat_message_id}).get("Item"),
            item_to_agent_chat_message,
        )

    def list_agent_chat_messages_by_chat(self, chat_id: str) -> tuple[AgentChatMessage, ...]:
        result = self._agent_chat_messages_table.query(
            IndexName="chat-created-at-index",
            KeyConditionExpression=Key("chat_id").eq(chat_id),
            ScanIndexForward=True,
        )
        return tuple(item_to_agent_chat_message(item) for item in result.get("Items", []))

    def put_node(self, node: NodeRecord) -> None:
        self._nodes_table.put_item(Item=node_to_item(node))

    def get_node(self, node_id: str) -> NodeRecord | None:
        return optional_item(
            self._nodes_table.get_item(Key={"node_id": node_id}).get("Item"),
            item_to_node,
        )

    def list_nodes_by_owner(self, owner_user_id: str) -> tuple[NodeRecord, ...]:
        result = self._nodes_table.query(
            IndexName="owner-created-at-index",
            KeyConditionExpression=Key("owner_user_id").eq(owner_user_id),
            ScanIndexForward=True,
        )
        return tuple(item_to_node(item) for item in result.get("Items", []))

    def put_pair_token(self, token: PairTokenRecord) -> None:
        self._pair_tokens_table.put_item(Item=pair_token_to_item(token))

    def get_pair_token(self, pair_token: str) -> PairTokenRecord | None:
        return optional_item(
            self._pair_tokens_table.get_item(Key={"pair_token": pair_token}).get("Item"),
            item_to_pair_token,
        )

    def put_room(self, room: Room) -> None:
        self._rooms_table.put_item(Item=room_to_item(room))

    def get_room(self, room_id: str) -> Room | None:
        return optional_item(
            self._rooms_table.get_item(Key={"room_id": room_id}).get("Item"),
            item_to_room,
        )

    def get_room_by_slug(self, slug: str) -> Room | None:
        result = self._rooms_table.query(
            IndexName="slug-index",
            KeyConditionExpression=Key("slug").eq(slug),
            Limit=1,
        )
        items = result.get("Items", [])
        if not items:
            return None
        return item_to_room(items[0])

    def put_room_membership(self, membership: RoomMembership) -> None:
        self._room_memberships_table.put_item(Item=room_membership_to_item(membership))

    def get_room_membership(self, room_id: str, agent_id: str) -> RoomMembership | None:
        return optional_item(
            self._room_memberships_table.get_item(
                Key={
                    "room_id": room_id,
                    "agent_id": agent_id,
                }
            ).get("Item"),
            item_to_room_membership,
        )

    def list_room_memberships_by_agent(self, agent_id: str) -> tuple[RoomMembership, ...]:
        result = self._room_memberships_table.query(
            IndexName="agent-index",
            KeyConditionExpression=Key("agent_id").eq(agent_id),
        )
        return tuple(item_to_room_membership(item) for item in result.get("Items", []))

    def put_follow(self, follow: FollowRecord) -> None:
        self._follows_table.put_item(Item=follow_to_item(follow))

    def get_follow(self, follower_agent_id: str, followed_agent_id: str) -> FollowRecord | None:
        return optional_item(
            self._follows_table.get_item(
                Key={
                    "follower_agent_id": follower_agent_id,
                    "followed_agent_id": followed_agent_id,
                }
            ).get("Item"),
            item_to_follow,
        )

    def list_follows_by_follower(self, follower_agent_id: str) -> tuple[FollowRecord, ...]:
        result = self._follows_table.query(
            KeyConditionExpression=Key("follower_agent_id").eq(follower_agent_id),
        )
        return tuple(item_to_follow(item) for item in result.get("Items", []))

    def put_post(self, post: PostRecord) -> None:
        self._posts_table.put_item(Item=post_to_item(post))

    def get_post(self, post_id: str) -> PostRecord | None:
        return optional_item(
            self._posts_table.get_item(Key={"post_id": post_id}).get("Item"),
            item_to_post,
        )

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        result = self._posts_table.scan(Limit=limit)
        posts = sorted(
            (item_to_post(item) for item in result.get("Items", [])),
            key=lambda post: post.created_at,
            reverse=True,
        )
        return tuple(posts[:limit])

    def put_feed_event(self, event: FeedEvent) -> None:
        self._feed_events_table.put_item(Item=feed_event_to_item(event))

    def list_feed_events(self, *, limit: int = 50) -> tuple[FeedEvent, ...]:
        result = self._feed_events_table.scan(Limit=limit)
        events = sorted(
            (item_to_feed_event(item) for item in result.get("Items", [])),
            key=lambda event: event.created_at,
            reverse=True,
        )
        return tuple(events[:limit])

    def put_notification(self, notification: Notification) -> None:
        self._notifications_table.put_item(Item=notification_to_item(notification))

    def list_notifications_by_recipient(
        self,
        recipient_agent_id: str,
        *,
        limit: int = 50,
    ) -> tuple[Notification, ...]:
        result = self._notifications_table.query(
            IndexName="recipient-created-at-index",
            KeyConditionExpression=Key("recipient_agent_id").eq(recipient_agent_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return tuple(item_to_notification(item) for item in result.get("Items", []))

    def put_moderation_record(self, record: ModerationRecord) -> None:
        self._moderation_table.put_item(Item=moderation_record_to_item(record))

    def list_moderation_records(self, *, limit: int = 50) -> tuple[ModerationRecord, ...]:
        result = self._moderation_table.scan(Limit=limit)
        records = sorted(
            (item_to_moderation_record(item) for item in result.get("Items", [])),
            key=lambda record: record.created_at,
            reverse=True,
        )
        return tuple(records[:limit])


def human_identity_to_item(identity: HumanIdentity) -> dict[str, Any]:
    return without_none(
        {
            "user_id": identity.user_id,
            "provider": identity.provider,
            "subject": identity.subject,
            "provider_subject": provider_subject(identity.provider, identity.subject),
            "email": identity.email,
            "display_name": identity.display_name,
            "created_at": identity.created_at.isoformat(),
            "updated_at": identity.updated_at.isoformat(),
        }
    )


def item_to_human_identity(item: dict[str, Any]) -> HumanIdentity:
    return HumanIdentity(
        user_id=item["user_id"],
        provider=item["provider"],
        subject=item["subject"],
        email=item.get("email"),
        display_name=item.get("display_name"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def agent_profile_to_item(profile: AgentProfileRecord) -> dict[str, Any]:
    return without_none(
        {
            "agent_id": profile.agent_id,
            "owner_user_id": profile.owner_user_id,
            "handle": profile.handle,
            "display_name": profile.display_name,
            "bio": profile.bio,
            "capabilities": list(profile.capabilities),
            "relationship_posture": profile.relationship_posture,
            "approval_required_for": list(profile.approval_required_for),
            "allowed_use_terms": list(profile.allowed_use_terms),
            "contact_explanation": profile.contact_explanation,
            "protocols": list(profile.protocols),
            "status": profile.status,
            "node_id": profile.node_id,
            "delivery_mode": profile.delivery_mode,
            "last_seen_at": None if profile.last_seen_at is None else profile.last_seen_at.isoformat(),
            "created_at": profile.created_at.isoformat(),
            "updated_at": profile.updated_at.isoformat(),
        }
    )


def item_to_agent_profile(item: dict[str, Any]) -> AgentProfileRecord:
    return AgentProfileRecord(
        agent_id=item["agent_id"],
        owner_user_id=item["owner_user_id"],
        handle=item["handle"],
        display_name=item.get("display_name"),
        bio=item.get("bio"),
        capabilities=tuple(item.get("capabilities", [])),
        relationship_posture=item.get("relationship_posture", "needs_approval"),
        approval_required_for=tuple(item.get("approval_required_for", DEFAULT_APPROVAL_REQUIRED_FOR)),
        allowed_use_terms=tuple(item.get("allowed_use_terms", [])),
        contact_explanation=item.get("contact_explanation"),
        protocols=tuple(item.get("protocols", ("seagull",))),
        status=item.get("status", "active"),
        node_id=item.get("node_id"),
        delivery_mode=item.get("delivery_mode", "pull"),
        last_seen_at=None if item.get("last_seen_at") is None else datetime.fromisoformat(item["last_seen_at"]),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def personal_agent_asset_to_item(asset: PersonalAgentAsset) -> dict[str, Any]:
    return without_none(
        {
            "asset_id": asset.asset_id,
            "owner_user_id": asset.owner_user_id,
            "asset_type": asset.asset_type,
            "name": asset.name,
            "instructions": asset.instructions,
            "description": asset.description,
            "style": asset.style,
            "tags": list(asset.tags),
            "max_output_chars": asset.max_output_chars,
            "status": asset.status,
            "created_at": asset.created_at.isoformat(),
            "updated_at": asset.updated_at.isoformat(),
        }
    )


def item_to_personal_agent_asset(item: dict[str, Any]) -> PersonalAgentAsset:
    max_output_chars = item.get("max_output_chars")
    return PersonalAgentAsset(
        asset_id=item["asset_id"],
        owner_user_id=item["owner_user_id"],
        asset_type=item["asset_type"],
        name=item["name"],
        instructions=item["instructions"],
        description=item.get("description"),
        style=item.get("style"),
        tags=tuple(item.get("tags", [])),
        max_output_chars=None if max_output_chars is None else int(max_output_chars),
        status=item.get("status", "active"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def agent_asset_binding_to_item(binding: AgentAssetBinding) -> dict[str, Any]:
    return without_none(
        {
            "agent_id": binding.agent_id,
            "owner_user_id": binding.owner_user_id,
            "prompt_asset_id": binding.prompt_asset_id,
            "skill_asset_id": binding.skill_asset_id,
            "created_at": binding.created_at.isoformat(),
            "updated_at": binding.updated_at.isoformat(),
        }
    )


def item_to_agent_asset_binding(item: dict[str, Any]) -> AgentAssetBinding:
    return AgentAssetBinding(
        agent_id=item["agent_id"],
        owner_user_id=item["owner_user_id"],
        prompt_asset_id=item.get("prompt_asset_id"),
        skill_asset_id=item.get("skill_asset_id"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def agent_chat_session_to_item(chat: AgentChatSession) -> dict[str, Any]:
    return without_none(
        {
            "chat_id": chat.chat_id,
            "owner_user_id": chat.owner_user_id,
            "agent_id": chat.agent_id,
            "agent_handle": chat.agent_handle,
            "title": chat.title,
            "sender_agent_id": chat.sender_agent_id,
            "sender_handle": chat.sender_handle,
            "prompt_asset_id": chat.prompt_asset_id,
            "skill_asset_id": chat.skill_asset_id,
            "hub_thread_id": chat.hub_thread_id,
            "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat(),
        }
    )


def item_to_agent_chat_session(item: dict[str, Any]) -> AgentChatSession:
    return AgentChatSession(
        chat_id=item["chat_id"],
        owner_user_id=item["owner_user_id"],
        agent_id=item["agent_id"],
        agent_handle=item["agent_handle"],
        title=item["title"],
        sender_agent_id=item.get("sender_agent_id"),
        sender_handle=item.get("sender_handle"),
        prompt_asset_id=item.get("prompt_asset_id"),
        skill_asset_id=item.get("skill_asset_id"),
        hub_thread_id=item.get("hub_thread_id"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def agent_chat_message_to_item(message: AgentChatMessage) -> dict[str, Any]:
    return without_none(
        {
            "chat_message_id": message.chat_message_id,
            "chat_id": message.chat_id,
            "owner_user_id": message.owner_user_id,
            "sender_type": message.sender_type,
            "content": message.content,
            "hub_message_id": message.hub_message_id,
            "hub_thread_id": message.hub_thread_id,
            "delivery_status": message.delivery_status,
            "delivery_error": message.delivery_error,
            "created_at": message.created_at.isoformat(),
            "updated_at": message.updated_at.isoformat(),
        }
    )


def item_to_agent_chat_message(item: dict[str, Any]) -> AgentChatMessage:
    return AgentChatMessage(
        chat_message_id=item["chat_message_id"],
        chat_id=item["chat_id"],
        owner_user_id=item["owner_user_id"],
        sender_type=item.get("sender_type", "human"),
        content=item["content"],
        hub_message_id=item.get("hub_message_id"),
        hub_thread_id=item.get("hub_thread_id"),
        delivery_status=item.get("delivery_status", "stored"),
        delivery_error=item.get("delivery_error"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def node_to_item(node: NodeRecord) -> dict[str, Any]:
    return without_none(
        {
            "node_id": node.node_id,
            "owner_user_id": node.owner_user_id,
            "node_type": node.node_type,
            "status": node.status,
            "agent_count": node.agent_count,
            "last_seen_at": None if node.last_seen_at is None else node.last_seen_at.isoformat(),
            "created_at": node.created_at.isoformat(),
            "updated_at": node.updated_at.isoformat(),
        }
    )


def item_to_node(item: dict[str, Any]) -> NodeRecord:
    return NodeRecord(
        node_id=item["node_id"],
        owner_user_id=item["owner_user_id"],
        node_type=item.get("node_type", "cloud"),
        status=item.get("status", "online"),
        agent_count=int(item.get("agent_count", 0)),
        last_seen_at=None if item.get("last_seen_at") is None else datetime.fromisoformat(item["last_seen_at"]),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def pair_token_to_item(token: PairTokenRecord) -> dict[str, Any]:
    return without_none(
        {
            "pair_token": token.pair_token,
            "node_id": token.node_id,
            "owner_user_id": token.owner_user_id,
            "expires_at": token.expires_at.isoformat(),
            "expires_at_epoch": int(token.expires_at.timestamp()),
            "created_at": token.created_at.isoformat(),
            "used_at": None if token.used_at is None else token.used_at.isoformat(),
        }
    )


def item_to_pair_token(item: dict[str, Any]) -> PairTokenRecord:
    return PairTokenRecord(
        pair_token=item["pair_token"],
        node_id=item["node_id"],
        owner_user_id=item["owner_user_id"],
        expires_at=datetime.fromisoformat(item["expires_at"]),
        created_at=datetime.fromisoformat(item["created_at"]),
        used_at=None if item.get("used_at") is None else datetime.fromisoformat(item["used_at"]),
    )


def room_to_item(room: Room) -> dict[str, Any]:
    return without_none(
        {
            "room_id": room.room_id,
            "slug": room.slug,
            "name": room.name,
            "description": room.description,
            "visibility": room.visibility,
            "created_by_user_id": room.created_by_user_id,
            "created_at": room.created_at.isoformat(),
            "updated_at": room.updated_at.isoformat(),
        }
    )


def item_to_room(item: dict[str, Any]) -> Room:
    return Room(
        room_id=item["room_id"],
        slug=item["slug"],
        name=item["name"],
        description=item.get("description"),
        visibility=item.get("visibility", "public"),
        created_by_user_id=item.get("created_by_user_id"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def room_membership_to_item(membership: RoomMembership) -> dict[str, Any]:
    return {
        "room_id": membership.room_id,
        "agent_id": membership.agent_id,
        "role": membership.role,
        "created_at": membership.created_at.isoformat(),
    }


def item_to_room_membership(item: dict[str, Any]) -> RoomMembership:
    return RoomMembership(
        room_id=item["room_id"],
        agent_id=item["agent_id"],
        role=item.get("role", "member"),
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def follow_to_item(follow: FollowRecord) -> dict[str, Any]:
    return {
        "follower_agent_id": follow.follower_agent_id,
        "followed_agent_id": follow.followed_agent_id,
        "created_at": follow.created_at.isoformat(),
    }


def item_to_follow(item: dict[str, Any]) -> FollowRecord:
    return FollowRecord(
        follower_agent_id=item["follower_agent_id"],
        followed_agent_id=item["followed_agent_id"],
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def post_to_item(post: PostRecord) -> dict[str, Any]:
    return without_none(
        {
            "post_id": post.post_id,
            "author_agent_id": post.author_agent_id,
            "content": post.content,
            "text": post.text,
            "refs": [shared_reference_to_item(ref) for ref in post.refs],
            "visibility": post.visibility,
            "room_id": post.room_id,
            "reply_to_post_id": post.reply_to_post_id,
            "mention_agent_ids": list(post.mention_agent_ids),
            "created_at": post.created_at.isoformat(),
        }
    )


def item_to_post(item: dict[str, Any]) -> PostRecord:
    content = item["content"]
    return PostRecord(
        post_id=item["post_id"],
        author_agent_id=item["author_agent_id"],
        content=content,
        text=item.get("text", content),
        refs=tuple(item_to_shared_reference(ref) for ref in item.get("refs", [])),
        visibility=item.get("visibility", "public"),
        room_id=item.get("room_id"),
        reply_to_post_id=item.get("reply_to_post_id"),
        mention_agent_ids=tuple(item.get("mention_agent_ids", [])),
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def shared_reference_to_item(ref: SharedReference) -> dict[str, Any]:
    return without_none(
        {
            "type": ref.ref_type,
            "url": ref.url,
            "find": ref.find,
            "remember_as": ref.remember_as,
        }
    )


def item_to_shared_reference(item: dict[str, Any]) -> SharedReference:
    return SharedReference(
        ref_type=item["type"],
        url=item["url"],
        find=item.get("find"),
        remember_as=item.get("remember_as"),
    )


def feed_event_to_item(event: FeedEvent) -> dict[str, Any]:
    return without_none(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "actor_agent_id": event.actor_agent_id,
            "object_id": event.object_id,
            "target_agent_ids": list(event.target_agent_ids),
            "room_id": event.room_id,
            "created_at": event.created_at.isoformat(),
        }
    )


def item_to_feed_event(item: dict[str, Any]) -> FeedEvent:
    return FeedEvent(
        event_id=item["event_id"],
        event_type=item["event_type"],
        actor_agent_id=item.get("actor_agent_id"),
        object_id=item.get("object_id"),
        target_agent_ids=tuple(item.get("target_agent_ids", [])),
        room_id=item.get("room_id"),
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def notification_to_item(notification: Notification) -> dict[str, Any]:
    return without_none(
        {
            "notification_id": notification.notification_id,
            "recipient_agent_id": notification.recipient_agent_id,
            "notification_type": notification.notification_type,
            "actor_agent_id": notification.actor_agent_id,
            "post_id": notification.post_id,
            "room_id": notification.room_id,
            "read_at": None if notification.read_at is None else notification.read_at.isoformat(),
            "created_at": notification.created_at.isoformat(),
        }
    )


def item_to_notification(item: dict[str, Any]) -> Notification:
    return Notification(
        notification_id=item["notification_id"],
        recipient_agent_id=item["recipient_agent_id"],
        notification_type=item["notification_type"],
        actor_agent_id=item.get("actor_agent_id"),
        post_id=item.get("post_id"),
        room_id=item.get("room_id"),
        read_at=None if item.get("read_at") is None else datetime.fromisoformat(item["read_at"]),
        created_at=datetime.fromisoformat(item["created_at"]),
    )


def moderation_record_to_item(record: ModerationRecord) -> dict[str, Any]:
    return without_none(
        {
            "moderation_id": record.moderation_id,
            "created_by_user_id": record.created_by_user_id,
            "target_type": record.target_type,
            "target_id": record.target_id,
            "action": record.action,
            "reason": record.reason,
            "status": record.status,
            "created_at": record.created_at.isoformat(),
            "resolved_at": None if record.resolved_at is None else record.resolved_at.isoformat(),
        }
    )


def item_to_moderation_record(item: dict[str, Any]) -> ModerationRecord:
    return ModerationRecord(
        moderation_id=item["moderation_id"],
        created_by_user_id=item["created_by_user_id"],
        target_type=item["target_type"],
        target_id=item["target_id"],
        action=item["action"],
        reason=item["reason"],
        status=item.get("status", "open"),
        created_at=datetime.fromisoformat(item["created_at"]),
        resolved_at=None if item.get("resolved_at") is None else datetime.fromisoformat(item["resolved_at"]),
    )


def optional_item(item: dict[str, Any] | None, converter):
    if item is None:
        return None
    return converter(item)


def provider_subject(provider: str, subject: str) -> str:
    return f"{provider}#{subject}"


def without_none(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}
