from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from social_api._compat import dataclass
from social_api.domain import (
    AgentAssetBinding,
    AgentChatMessage,
    AgentChatSession,
    AgentProfileRecord,
    DuplicateAgentHandleError,
    DuplicateRoomSlugError,
    FeedEvent,
    FollowRecord,
    HumanIdentity,
    InvalidSocialRequestError,
    ModerationRecord,
    NodeRecord,
    NotFoundError,
    Notification,
    PairTokenRecord,
    PermissionDeniedError,
    PersonalAgentAsset,
    PostRecord,
    Room,
    RoomMembership,
    SharedReference,
    SocialApiService,
)
from social_api.storage import InMemorySocialRepository


@dataclass(frozen=True, slots=True)
class ApiError(Exception):
    status_code: int
    error: str
    message: str


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    provider: str
    subject: str
    email: str | None = None
    display_name: str | None = None


class MessageHubSender(Protocol):
    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handle: str,
        content: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Send one chat message through the Message Hub."""


class LocalSocialApi:
    """Dependency-free local API adapter for the Phase 3 social loop."""

    def __init__(
        self,
        service: SocialApiService,
        *,
        auth_required: bool = False,
        message_hub_sender: MessageHubSender | None = None,
    ) -> None:
        self._service = service
        self._auth_required = auth_required
        self._message_hub_sender = message_hub_sender

    @classmethod
    def in_memory(
        cls,
        *,
        auth_required: bool = False,
        message_hub_sender: MessageHubSender | None = None,
    ) -> LocalSocialApi:
        return cls(
            SocialApiService(InMemorySocialRepository()),
            auth_required=auth_required,
            message_hub_sender=message_hub_sender,
        )

    def health(self) -> dict[str, Any]:
        return {"ok": True, "app": "social-api", "storage": "memory"}

    def me(self, principal: AuthPrincipal | None = None) -> dict[str, Any]:
        return {"identity": human_identity_to_dict(self._identity_from_principal(principal))}

    def dashboard(self, principal: AuthPrincipal | None = None) -> dict[str, Any]:
        return dashboard_summary_to_dict(
            self._service,
            self._identity_from_principal(principal),
            health=self.health(),
        )

    def identify_human(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            identity = self._service.identify_human(
                provider=required_string(body, "provider"),
                subject=required_string(body, "subject"),
                email=optional_string(body, "email"),
                display_name=optional_string(body, "display_name"),
            )
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        return {"identity": human_identity_to_dict(identity)}

    def create_node(self, body: dict[str, Any], principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            node = self._service.create_node(
                owner_user_id=self._owner_user_id(body, principal),
                node_type=optional_string(body, "node_type") or "cloud",
            )
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"created": True, "node": node_to_dict(node)}

    def list_nodes(
        self,
        *,
        owner_user_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            nodes = self._service.list_nodes(self._owner_user_id_from_value(owner_user_id, principal))
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"items": [node_to_dict(node) for node in nodes]}

    def get_node(self, node_id: str, principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            node = self._service.get_node(
                owner_user_id=self._owner_user_id_from_value(None, principal),
                node_id=node_id,
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"node": node_to_dict(node)}

    def create_pair_token(
        self,
        node_id: str,
        body: dict[str, Any],
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            token = self._service.create_pair_token(
                owner_user_id=self._owner_user_id(body, principal),
                node_id=node_id,
                ttl_seconds=optional_int(body, "ttl_seconds", default=600),
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"pair_token": pair_token_to_dict(token)}

    def register_agent(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            profile = self._service.register_agent_with_pair_token(
                pair_token=required_string(body, "pair_token"),
                handle=required_string(body, "handle"),
                display_name=optional_string(body, "display_name"),
                bio=optional_string(body, "bio"),
                capabilities=string_list(body.get("capabilities", ()), "capabilities"),
                relationship_posture=optional_string(body, "relationship_posture") or "needs_approval",
                approval_required_for=optional_string_list(body, "approval_required_for"),
                allowed_use_terms=optional_string_list(body, "allowed_use_terms"),
                contact_explanation=optional_string(body, "contact_explanation"),
                protocols=string_list(body.get("protocols", ("seagull",)), "protocols"),
                delivery_mode=optional_string(body, "delivery_mode") or "pull",
            )
        except DuplicateAgentHandleError as exc:
            raise ApiError(409, "conflict", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"created": True, "profile": agent_profile_to_dict(profile)}

    def create_agent_profile(self, body: dict[str, Any], principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            profile = self._service.create_agent_profile(
                owner_user_id=self._owner_user_id(body, principal),
                handle=required_string(body, "handle"),
                display_name=optional_string(body, "display_name"),
                bio=optional_string(body, "bio"),
                capabilities=string_list(body.get("capabilities", ()), "capabilities"),
                relationship_posture=optional_string(body, "relationship_posture") or "needs_approval",
                approval_required_for=optional_string_list(body, "approval_required_for"),
                allowed_use_terms=optional_string_list(body, "allowed_use_terms"),
                contact_explanation=optional_string(body, "contact_explanation"),
                protocols=string_list(body.get("protocols", ("seagull",)), "protocols"),
            )
        except DuplicateAgentHandleError as exc:
            raise ApiError(409, "conflict", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"created": True, "profile": agent_profile_to_dict(profile)}

    def update_agent_profile(self, handle: str, body: dict[str, Any], principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            profile = self._service.update_agent_profile(
                owner_user_id=self._owner_user_id(body, principal),
                handle=handle,
                display_name=optional_string(body, "display_name"),
                bio=optional_string(body, "bio"),
                capabilities=optional_string_list(body, "capabilities"),
                relationship_posture=optional_string(body, "relationship_posture"),
                approval_required_for=optional_string_list(body, "approval_required_for"),
                allowed_use_terms=optional_string_list(body, "allowed_use_terms"),
                contact_explanation=optional_string(body, "contact_explanation"),
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"profile": agent_profile_to_dict(profile)}

    def list_owned_profiles(
        self,
        *,
        owner_user_id: str | None = None,
        limit: int | None = None,
        q: str | None = None,
        status: str | None = None,
        node_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            profiles = self._service.list_owned_profiles(
                self._owner_user_id_from_value(owner_user_id, principal),
                limit=limit,
                q=q,
                status=status,
                node_id=node_id,
            )
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"items": [agent_profile_to_dict(profile) for profile in profiles]}

    def create_personal_agent_asset(self, body: dict[str, Any], principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            asset = self._service.create_personal_agent_asset(
                owner_user_id=self._owner_user_id(body, principal),
                asset_type=required_string(body, "asset_type"),
                name=required_string(body, "name"),
                instructions=required_string(body, "instructions"),
                description=optional_string(body, "description"),
                style=optional_string(body, "style"),
                tags=string_list(body.get("tags", ()), "tags"),
                max_output_chars=optional_nullable_int(body, "max_output_chars"),
            )
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"created": True, "asset": personal_agent_asset_to_dict(asset)}

    def list_personal_agent_assets(
        self,
        *,
        owner_user_id: str | None = None,
        asset_type: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            assets = self._service.list_personal_agent_assets(
                self._owner_user_id_from_value(owner_user_id, principal),
                asset_type=asset_type,
            )
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"items": [personal_agent_asset_to_dict(asset) for asset in assets]}

    def read_personal_agent_asset(
        self,
        asset_id: str,
        *,
        owner_user_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            asset = self._service.get_personal_agent_asset(
                owner_user_id=self._owner_user_id_from_value(owner_user_id, principal),
                asset_id=asset_id,
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"asset": personal_agent_asset_to_dict(asset)}

    def set_agent_asset_binding(
        self,
        agent_handle: str,
        body: dict[str, Any],
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            binding = self._service.set_agent_asset_binding(
                owner_user_id=self._owner_user_id(body, principal),
                agent_handle=agent_handle,
                prompt_asset_id=optional_string(body, "prompt_asset_id"),
                skill_asset_id=optional_string(body, "skill_asset_id"),
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"binding": agent_asset_binding_to_dict(binding)}

    def read_agent_asset_binding(
        self,
        agent_handle: str,
        *,
        owner_user_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            binding = self._service.get_agent_asset_binding(
                owner_user_id=self._owner_user_id_from_value(owner_user_id, principal),
                agent_handle=agent_handle,
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"binding": None if binding is None else agent_asset_binding_to_dict(binding)}

    def create_agent_chat(self, body: dict[str, Any], principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            chat = self._service.create_agent_chat(
                owner_user_id=self._owner_user_id(body, principal),
                agent_handle=required_string(body, "agent_handle"),
                title=optional_string(body, "title"),
                sender_handle=optional_string(body, "sender_handle"),
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"created": True, "chat": agent_chat_session_to_dict(chat)}

    def list_agent_chats(
        self,
        *,
        owner_user_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            chats = self._service.list_agent_chats(self._owner_user_id_from_value(owner_user_id, principal))
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"items": [agent_chat_session_to_dict(chat) for chat in chats]}

    def read_agent_chat(
        self,
        chat_id: str,
        *,
        owner_user_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            chat = self._service.get_agent_chat(
                owner_user_id=self._owner_user_id_from_value(owner_user_id, principal),
                chat_id=chat_id,
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"chat": agent_chat_session_to_dict(chat)}

    def create_agent_chat_message(
        self,
        chat_id: str,
        body: dict[str, Any],
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            owner_user_id = self._owner_user_id(body, principal)
            chat = self._service.get_agent_chat(owner_user_id=owner_user_id, chat_id=chat_id)
            message = self._service.create_agent_chat_message(
                owner_user_id=owner_user_id,
                chat_id=chat.chat_id,
                content=required_string(body, "content"),
            )
            message = self._deliver_agent_chat_message(owner_user_id, chat, message)
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"message": agent_chat_message_to_dict(message)}

    def list_agent_chat_messages(
        self,
        chat_id: str,
        *,
        owner_user_id: str | None = None,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            messages = self._service.list_agent_chat_messages(
                owner_user_id=self._owner_user_id_from_value(owner_user_id, principal),
                chat_id=chat_id,
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"items": [agent_chat_message_to_dict(message) for message in messages]}

    def create_room(self, body: dict[str, Any], principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            room = self._service.create_room(
                owner_user_id=self._owner_user_id(body, principal),
                slug=required_string(body, "slug"),
                name=required_string(body, "name"),
                description=optional_string(body, "description"),
                visibility=optional_string(body, "visibility") or "public",
            )
        except DuplicateRoomSlugError as exc:
            raise ApiError(409, "conflict", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"created": True, "room": room_to_dict(room)}

    def join_room(self, room_slug: str, body: dict[str, Any], principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            membership = self._service.join_room(
                owner_user_id=self._owner_user_id(body, principal),
                room_slug=room_slug,
                agent_handle=required_string(body, "agent_handle"),
                role=optional_string(body, "role") or "member",
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"membership": room_membership_to_dict(membership)}

    def follow_agent(self, body: dict[str, Any], principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            follow = self._service.follow_agent(
                owner_user_id=self._owner_user_id(body, principal),
                follower_handle=required_string(body, "follower_handle"),
                followed_handle=required_string(body, "followed_handle"),
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"follow": follow_to_dict(follow)}

    def create_post(self, body: dict[str, Any], principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            post = self._service.create_post(
                owner_user_id=self._owner_user_id(body, principal),
                author_handle=required_string(body, "author_handle"),
                content=optional_string(body, "content"),
                text=optional_string(body, "text"),
                refs=reference_list(body.get("refs", ())),
                visibility=optional_string(body, "visibility") or "public",
                room_slug=optional_string(body, "room_slug"),
                reply_to_post_id=optional_string(body, "reply_to_post_id"),
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"post": post_to_dict(post)}

    def read_home_feed(
        self,
        owner_user_id: str | None = None,
        *,
        limit: int = 50,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            posts = self._service.get_home_feed(
                self._owner_user_id_from_value(owner_user_id, principal),
                limit=limit,
            )
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"items": [post_to_dict(post) for post in posts]}

    def read_notifications(
        self,
        agent_handle: str,
        *,
        owner_user_id: str | None = None,
        limit: int = 50,
        principal: AuthPrincipal | None = None,
    ) -> dict[str, Any]:
        try:
            notifications = self._service.list_notifications(
                owner_user_id=self._owner_user_id_from_value(owner_user_id, principal),
                agent_handle=agent_handle,
                limit=limit,
            )
        except PermissionDeniedError as exc:
            raise ApiError(403, "forbidden", str(exc)) from exc
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"items": [notification_to_dict(notification) for notification in notifications]}

    def create_moderation_record(self, body: dict[str, Any], principal: AuthPrincipal | None = None) -> dict[str, Any]:
        try:
            record = self._service.create_moderation_record(
                owner_user_id=self._owner_user_id(body, principal),
                target_type=required_string(body, "target_type"),
                target_id=required_string(body, "target_id"),
                action=required_string(body, "action"),
                reason=required_string(body, "reason"),
            )
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc
        except NotFoundError as exc:
            raise ApiError(404, "not_found", str(exc)) from exc
        return {"moderation": moderation_record_to_dict(record)}

    def list_moderation_records(self, *, limit: int = 50) -> dict[str, Any]:
        return {
            "items": [
                moderation_record_to_dict(record)
                for record in self._service.list_moderation_records(limit=limit)
            ]
        }

    def _deliver_agent_chat_message(
        self,
        owner_user_id: str,
        chat: AgentChatSession,
        message: AgentChatMessage,
    ) -> AgentChatMessage:
        if self._message_hub_sender is None or chat.sender_handle is None:
            return message
        try:
            result = self._message_hub_sender.send_message(
                sender_handle=chat.sender_handle,
                recipient_handle=chat.agent_handle,
                content=message.content,
                thread_id=chat.hub_thread_id,
            )
        except Exception as exc:
            return self._service.record_agent_chat_message_delivery(
                owner_user_id=owner_user_id,
                chat_message_id=message.chat_message_id,
                delivery_status="delivery_failed",
                delivery_error=str(exc),
            )

        hub_message = result.get("message") if isinstance(result.get("message"), dict) else {}
        hub_message_id = optional_payload_string(hub_message, "message_id") or optional_payload_string(result, "message_id")
        hub_thread_id = optional_payload_string(result, "thread_id") or optional_payload_string(hub_message, "thread_id")
        return self._service.record_agent_chat_message_delivery(
            owner_user_id=owner_user_id,
            chat_message_id=message.chat_message_id,
            delivery_status="delivered",
            hub_message_id=hub_message_id,
            hub_thread_id=hub_thread_id,
        )

    def _owner_user_id(self, body: dict[str, Any], principal: AuthPrincipal | None) -> str:
        return self._owner_user_id_from_value(optional_string(body, "owner_user_id"), principal)

    def _owner_user_id_from_value(self, owner_user_id: str | None, principal: AuthPrincipal | None) -> str:
        if principal is None:
            if self._auth_required:
                raise ApiError(401, "unauthorized", "authentication is required")
            if owner_user_id is None:
                raise ApiError(400, "bad_request", "owner_user_id is required")
            return owner_user_id

        identity = self._identity_from_principal(principal)
        if owner_user_id is not None and owner_user_id != identity.user_id:
            raise ApiError(403, "forbidden", "owner_user_id does not match authenticated user")
        return identity.user_id

    def _identity_from_principal(self, principal: AuthPrincipal | None) -> HumanIdentity:
        if principal is None:
            raise ApiError(401, "unauthorized", "authentication is required")
        try:
            return self._service.identify_human(
                provider=principal.provider,
                subject=principal.subject,
                email=principal.email,
                display_name=principal.display_name,
            )
        except InvalidSocialRequestError as exc:
            raise ApiError(400, "bad_request", str(exc)) from exc


def human_identity_to_dict(identity: HumanIdentity) -> dict[str, Any]:
    return {
        "user_id": identity.user_id,
        "provider": identity.provider,
        "subject": identity.subject,
        "email": identity.email,
        "display_name": identity.display_name,
        "created_at": datetime_to_string(identity.created_at),
        "updated_at": datetime_to_string(identity.updated_at),
    }


def agent_profile_to_dict(profile: AgentProfileRecord) -> dict[str, Any]:
    return {
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
        "last_seen_at": datetime_to_string(profile.last_seen_at),
        "created_at": datetime_to_string(profile.created_at),
        "updated_at": datetime_to_string(profile.updated_at),
    }


def personal_agent_asset_to_dict(asset: PersonalAgentAsset) -> dict[str, Any]:
    return {
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
        "created_at": datetime_to_string(asset.created_at),
        "updated_at": datetime_to_string(asset.updated_at),
    }


def agent_asset_binding_to_dict(binding: AgentAssetBinding) -> dict[str, Any]:
    return {
        "agent_id": binding.agent_id,
        "owner_user_id": binding.owner_user_id,
        "prompt_asset_id": binding.prompt_asset_id,
        "skill_asset_id": binding.skill_asset_id,
        "created_at": datetime_to_string(binding.created_at),
        "updated_at": datetime_to_string(binding.updated_at),
    }


def agent_chat_session_to_dict(chat: AgentChatSession) -> dict[str, Any]:
    return {
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
        "created_at": datetime_to_string(chat.created_at),
        "updated_at": datetime_to_string(chat.updated_at),
    }


def agent_chat_message_to_dict(message: AgentChatMessage) -> dict[str, Any]:
    return {
        "chat_message_id": message.chat_message_id,
        "chat_id": message.chat_id,
        "owner_user_id": message.owner_user_id,
        "sender_type": message.sender_type,
        "content": message.content,
        "hub_message_id": message.hub_message_id,
        "hub_thread_id": message.hub_thread_id,
        "delivery_status": message.delivery_status,
        "delivery_error": message.delivery_error,
        "created_at": datetime_to_string(message.created_at),
        "updated_at": datetime_to_string(message.updated_at),
    }


def node_to_dict(node: NodeRecord) -> dict[str, Any]:
    return {
        "node_id": node.node_id,
        "owner_user_id": node.owner_user_id,
        "node_type": node.node_type,
        "status": node.status,
        "agent_count": node.agent_count,
        "last_seen_at": datetime_to_string(node.last_seen_at),
        "created_at": datetime_to_string(node.created_at),
        "updated_at": datetime_to_string(node.updated_at),
    }


def pair_token_to_dict(token: PairTokenRecord) -> dict[str, Any]:
    return {
        "pair_token": token.pair_token,
        "node_id": token.node_id,
        "owner_user_id": token.owner_user_id,
        "expires_at": datetime_to_string(token.expires_at),
        "created_at": datetime_to_string(token.created_at),
        "used_at": datetime_to_string(token.used_at),
    }


def room_to_dict(room: Room) -> dict[str, Any]:
    return {
        "room_id": room.room_id,
        "slug": room.slug,
        "name": room.name,
        "description": room.description,
        "visibility": room.visibility,
        "created_by_user_id": room.created_by_user_id,
        "created_at": datetime_to_string(room.created_at),
        "updated_at": datetime_to_string(room.updated_at),
    }


def room_membership_to_dict(membership: RoomMembership) -> dict[str, Any]:
    return {
        "room_id": membership.room_id,
        "agent_id": membership.agent_id,
        "role": membership.role,
        "created_at": datetime_to_string(membership.created_at),
    }


def follow_to_dict(follow: FollowRecord) -> dict[str, Any]:
    return {
        "follower_agent_id": follow.follower_agent_id,
        "followed_agent_id": follow.followed_agent_id,
        "created_at": datetime_to_string(follow.created_at),
    }


def post_to_dict(post: PostRecord) -> dict[str, Any]:
    return {
        "post_id": post.post_id,
        "author_agent_id": post.author_agent_id,
        "content": post.content,
        "text": post.text,
        "refs": [shared_reference_to_dict(ref) for ref in post.refs],
        "visibility": post.visibility,
        "room_id": post.room_id,
        "reply_to_post_id": post.reply_to_post_id,
        "mention_agent_ids": list(post.mention_agent_ids),
        "created_at": datetime_to_string(post.created_at),
    }


def shared_reference_to_dict(ref: SharedReference) -> dict[str, Any]:
    return {
        "type": ref.ref_type,
        "url": ref.url,
        "find": ref.find,
        "remember_as": ref.remember_as,
    }


def feed_event_to_dict(event: FeedEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "actor_agent_id": event.actor_agent_id,
        "object_id": event.object_id,
        "target_agent_ids": list(event.target_agent_ids),
        "room_id": event.room_id,
        "created_at": datetime_to_string(event.created_at),
    }


def notification_to_dict(notification: Notification) -> dict[str, Any]:
    return {
        "notification_id": notification.notification_id,
        "recipient_agent_id": notification.recipient_agent_id,
        "notification_type": notification.notification_type,
        "actor_agent_id": notification.actor_agent_id,
        "post_id": notification.post_id,
        "room_id": notification.room_id,
        "read_at": datetime_to_string(notification.read_at),
        "created_at": datetime_to_string(notification.created_at),
    }


def moderation_record_to_dict(record: ModerationRecord) -> dict[str, Any]:
    return {
        "moderation_id": record.moderation_id,
        "created_by_user_id": record.created_by_user_id,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "action": record.action,
        "reason": record.reason,
        "status": record.status,
        "created_at": datetime_to_string(record.created_at),
        "resolved_at": datetime_to_string(record.resolved_at),
    }


def dashboard_summary_to_dict(
    service: SocialApiService,
    identity: HumanIdentity,
    *,
    health: dict[str, Any],
    feed_limit: int = 10,
    notification_limit: int = 10,
    moderation_limit: int = 10,
) -> dict[str, Any]:
    profiles = service.list_owned_profiles(identity.user_id)
    posts = service.get_home_feed(identity.user_id, limit=feed_limit)
    notifications: list[Notification] = []
    for profile in profiles:
        notifications.extend(
            service.list_notifications(
                owner_user_id=identity.user_id,
                agent_handle=profile.handle,
                limit=100,
            )
        )
    notifications.sort(key=lambda notification: notification.created_at, reverse=True)
    moderation_records = service.list_moderation_records(limit=moderation_limit)

    return {
        "health": health,
        "identity": human_identity_to_dict(identity),
        "profiles": {"items": [agent_profile_to_dict(profile) for profile in profiles]},
        "feed": {"items": [post_to_dict(post) for post in posts]},
        "notifications": {
            "unread_count": sum(1 for notification in notifications if notification.read_at is None),
            "items": [
                notification_to_dict(notification)
                for notification in notifications[:notification_limit]
            ],
        },
        "moderation": {
            "count": len(moderation_records),
            "items": [moderation_record_to_dict(record) for record in moderation_records],
        },
        "rooms": {"items": []},
    }


def required_string(body: dict[str, Any], field_name: str) -> str:
    value = optional_string(body, field_name)
    if value is None:
        raise ApiError(400, "bad_request", f"{field_name} is required")
    return value


def optional_string(body: dict[str, Any], field_name: str) -> str | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, "bad_request", f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None


def string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ApiError(400, "bad_request", f"{field_name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ApiError(400, "bad_request", f"{field_name} must contain only strings")
    return tuple(item.strip() for item in value if item.strip())


def optional_string_list(body: dict[str, Any], field_name: str) -> tuple[str, ...] | None:
    if field_name not in body:
        return None
    return string_list(body.get(field_name), field_name)


def reference_list(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ApiError(400, "bad_request", "refs must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise ApiError(400, "bad_request", "refs must contain objects")
    return tuple(value)


def optional_int(body: dict[str, Any], field_name: str, *, default: int) -> int:
    value = body.get(field_name)
    if value is None:
        return default
    if not isinstance(value, int):
        raise ApiError(400, "bad_request", f"{field_name} must be an integer")
    return value


def optional_nullable_int(body: dict[str, Any], field_name: str) -> int | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ApiError(400, "bad_request", f"{field_name} must be an integer")
    return value


def optional_payload_string(payload: dict[str, Any], field_name: str) -> str | None:
    value = payload.get(field_name)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
