from __future__ import annotations

import base64
import hmac
import json
import os
from typing import Any
from urllib.parse import unquote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import boto3

from social_api.api.local import (
    agent_asset_binding_to_dict,
    agent_chat_message_to_dict,
    agent_chat_session_to_dict,
    generate_agent_chat_reply,
    agent_profile_to_dict,
    dashboard_summary_to_dict,
    follow_to_dict,
    human_identity_to_dict,
    moderation_record_to_dict,
    node_to_dict,
    notification_to_dict,
    pair_token_to_dict,
    personal_agent_asset_to_dict,
    post_to_dict,
    room_membership_to_dict,
    room_to_dict,
)
from social_api.domain import (
    DuplicateAgentHandleError,
    DuplicateRoomSlugError,
    HumanIdentity,
    InvalidSocialRequestError,
    NotFoundError,
    PermissionDeniedError,
    SocialApiService,
)
from social_api.storage.dynamodb import DynamoDbSocialRepository


def secret_env(name: str) -> str:
    direct = os.environ.get(name, "").strip()
    secret_arn = os.environ.get(f"{name}_ARN", "").strip()
    if direct or not secret_arn:
        return direct
    try:
        result = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    except Exception as exc:
        print(json.dumps({"level": "warning", "message": f"could not load secret {name}: {exc}"}))
        return ""
    secret = result.get("SecretString")
    if isinstance(secret, str):
        return secret.strip()
    encoded = result.get("SecretBinary")
    if isinstance(encoded, (bytes, bytearray)):
        return base64.b64decode(encoded).decode("utf-8").strip()
    if isinstance(encoded, str):
        return base64.b64decode(encoded).decode("utf-8").strip()
    return ""


APP_NAME = os.environ.get("APP_NAME", "seagull-social-api")
SOCIAL_AUTH_REQUIRED = os.environ.get("SOCIAL_AUTH_REQUIRED", "true").lower() not in {"0", "false", "no"}
SOCIAL_AUTH_BYPASS_SECRET = secret_env("SOCIAL_AUTH_BYPASS_SECRET")
AI_PROVIDER_API_URL = os.environ.get("AI_PROVIDER_API_URL", "").strip().rstrip("/")
AI_PROVIDER_ADMIN_SECRET = secret_env("AI_PROVIDER_ADMIN_SECRET")
AI_REPLY_PROVIDER = os.environ.get("AI_REPLY_PROVIDER", "").strip()
AI_REPLY_MODEL = os.environ.get("AI_REPLY_MODEL", "").strip()
AI_REPLY_MAX_OUTPUT_TOKENS = int(os.environ.get("AI_REPLY_MAX_OUTPUT_TOKENS", "512"))
AI_REPLY_TIMEOUT_SECONDS = float(os.environ.get("AI_REPLY_TIMEOUT_SECONDS", "20"))

dynamodb = boto3.resource("dynamodb")
repository = DynamoDbSocialRepository(
    identities_table=dynamodb.Table(os.environ["IDENTITIES_TABLE"]),
    profiles_table=dynamodb.Table(os.environ["PROFILES_TABLE"]),
    personal_agent_assets_table=dynamodb.Table(os.environ["PERSONAL_AGENT_ASSETS_TABLE"]),
    agent_asset_bindings_table=dynamodb.Table(os.environ["AGENT_ASSET_BINDINGS_TABLE"]),
    agent_chats_table=dynamodb.Table(os.environ["AGENT_CHATS_TABLE"]),
    agent_chat_messages_table=dynamodb.Table(os.environ["AGENT_CHAT_MESSAGES_TABLE"]),
    nodes_table=dynamodb.Table(os.environ["NODES_TABLE"]),
    pair_tokens_table=dynamodb.Table(os.environ["PAIR_TOKENS_TABLE"]),
    rooms_table=dynamodb.Table(os.environ["ROOMS_TABLE"]),
    room_memberships_table=dynamodb.Table(os.environ["ROOM_MEMBERSHIPS_TABLE"]),
    follows_table=dynamodb.Table(os.environ["FOLLOWS_TABLE"]),
    posts_table=dynamodb.Table(os.environ["POSTS_TABLE"]),
    feed_events_table=dynamodb.Table(os.environ["FEED_EVENTS_TABLE"]),
    notifications_table=dynamodb.Table(os.environ["NOTIFICATIONS_TABLE"]),
    moderation_table=dynamodb.Table(os.environ["MODERATION_TABLE"]),
)


def _build_feed_mirror():
    """Dual-write feed records into the gulls Feed tables.

    Feed is a gulls network capability; seagulls still serves reads from its
    own tables during the migration but mirrors every write across. Table names
    are GULLS_*-prefixed because this Lambda already binds POSTS_TABLE and
    friends to the *seagulls* tables.

    Returns None when the gulls tables are not configured, so an environment
    applied before they existed keeps working unchanged.
    """
    names = {
        "posts_table": os.environ.get("GULLS_POSTS_TABLE", "").strip(),
        "follows_table": os.environ.get("GULLS_FOLLOWS_TABLE", "").strip(),
        "rooms_table": os.environ.get("GULLS_ROOMS_TABLE", "").strip(),
        "room_memberships_table": os.environ.get("GULLS_ROOM_MEMBERSHIPS_TABLE", "").strip(),
        "feed_events_table": os.environ.get("GULLS_FEED_EVENTS_TABLE", "").strip(),
        "notifications_table": os.environ.get("GULLS_NOTIFICATIONS_TABLE", "").strip(),
    }
    if not all(names.values()):
        return None

    from message_hub.storage.dynamodb import DynamoDbMessageHubRepository
    from social_api.domain.feed_mirror import BestEffortFeedMirror, StrictFeedMirror

    gulls_repository = DynamoDbMessageHubRepository(
        # Only the Feed tables are needed; the rest of the hub repository is
        # unused here and stays unconfigured.
        agents_table=None,
        messages_table=None,
        threads_table=None,
        deliveries_table=None,
        idempotency_table=None,
        thread_summaries_table=None,
        **{key: dynamodb.Table(name) for key, name in names.items()},
    )
    return BestEffortFeedMirror(StrictFeedMirror(gulls_repository)), gulls_repository


def _build_feed_source(gulls_repository):
    """Serve base Feed records from gulls once it is the source of truth.

    Gated separately from the mirror so the cutover is its own step: dual-write
    first, then flip reads. Falls back to the seagulls tables for posts written
    before the mirror began, and if a gulls read fails.
    """
    if gulls_repository is None or os.environ.get("GULLS_FEED_READS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        return None

    from social_api.domain.feed_source import (
        FallbackFeedSource,
        GullsFeedSource,
        RepositoryFeedSource,
    )

    return FallbackFeedSource(
        GullsFeedSource(gulls_repository),
        RepositoryFeedSource(repository),
    )


_mirror_result = _build_feed_mirror()
feed_mirror, _gulls_feed_repository = _mirror_result if _mirror_result else (None, None)
feed_source = _build_feed_source(_gulls_feed_repository)


class MessageHubAgentRegistry:
    """AgentRegistry port backed by the gulls message hub.

    M0.2 (public-agent-urls plan): the hub is the authoritative agent
    registry, so handles are registered at profile creation instead of on
    every chat send. POST /agents is an idempotent get-or-create; failures
    are handled best-effort by the domain service.
    """

    def register(self, handle: str, display_name: str | None = None) -> None:
        message_api_url = os.environ.get("MESSAGE_API_URL", "").strip().rstrip("/")
        if not message_api_url:
            return
        register_message_hub_agent(message_api_url, handle, display_name=display_name)


def _build_chat_source():
    """Serve chat message content from the gulls Inbox once it holds it.

    Gated separately from the chat mirror so the cutover is its own step, the
    same order the Feed migration used. Which messages a chat holds stays a
    seagulls projection; only what each one says moves.

    Wrapped so a gulls-side failure degrades to the stored seagulls copy rather
    than emptying a conversation.
    """
    if os.environ.get("GULLS_CHAT_READS", "").strip().lower() not in {"1", "true", "yes"}:
        return None

    # Chat content lives in the hub's messages table, which the Feed repository
    # deliberately leaves unconfigured -- so this needs its own binding rather
    # than reusing the one the Feed mirror built.
    messages_table_name = os.environ.get("GULLS_MESSAGES_TABLE", "").strip()
    if not messages_table_name:
        return None

    from message_hub.storage.dynamodb import DynamoDbMessageHubRepository
    from social_api.domain.chat_source import GullsChatSource, SafeChatSource

    return SafeChatSource(
        GullsChatSource(
            DynamoDbMessageHubRepository(
                agents_table=None,
                messages_table=dynamodb.Table(messages_table_name),
                threads_table=None,
                deliveries_table=None,
                idempotency_table=None,
                thread_summaries_table=None,
            )
        )
    )


service = SocialApiService(
    repository,
    agent_registry=MessageHubAgentRegistry(),
    feed_mirror=feed_mirror,
    feed_source=feed_source,
    # Pins every human proxy to one namespace so a person has a single network
    # identity rather than one per agent domain they chat. Unset falls back to
    # the chatted agent's domain, which keeps unconfigured environments working.
    human_proxy_domain=os.environ.get("HUMAN_PROXY_DOMAIN", "").strip(),
    chat_source=_build_chat_source(),
)


class BadRequest(ValueError):
    pass


class Unauthorized(ValueError):
    pass


def redacted_event(event: dict[str, Any]) -> dict[str, Any]:
    # Headers carry the caller's Authorization token plus x-seagull-admin-secret /
    # x-seagull-legacy-secret / x-seagull-auth-bypass-secret; the body carries
    # private post, reply, and direct-message content. Keep both out of logs.
    return {
        "rawPath": event.get("rawPath"),
        "requestContext": event.get("requestContext"),
        "queryStringParameters": event.get("queryStringParameters"),
        "headers": "[redacted]",
        "body": "[redacted]" if event.get("body") is not None else None,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "/")

    try:
        if method == "OPTIONS":
            return cors_response()

        if method == "GET" and path == "/health":
            return response(200, {"ok": True, "app": APP_NAME, "storage": "dynamodb"})

        if method == "GET" and path == "/me":
            identity = identity_from_event(event)
            return response(200, {"identity": human_identity_to_dict(identity)})

        if method == "GET" and path == "/dashboard":
            identity = identity_from_event(event)
            return response(
                200,
                dashboard_summary_to_dict(
                    service,
                    identity,
                    health={"ok": True, "app": APP_NAME, "storage": "dynamodb"},
                ),
            )

        if method == "POST" and path == "/identities":
            identity = identify_human_from_event(event)
            return response(200, {"identity": human_identity_to_dict(identity)})

        if method == "POST" and path == "/nodes":
            body = parse_body(event)
            node = service.create_node(
                owner_user_id=owner_user_id_from_body(event, body),
                node_type=optional_string(body, "node_type") or "cloud",
            )
            return response(200, {"created": True, "node": node_to_dict(node)})

        if method == "GET" and path == "/nodes":
            query = event.get("queryStringParameters") or {}
            nodes = service.list_nodes(owner_user_id_from_query(event, query))
            return response(200, {"items": [node_to_dict(node) for node in nodes]})

        if method == "GET" and path.startswith("/nodes/") and not path.endswith("/pair-tokens"):
            node_id = unquote(path.removeprefix("/nodes/").strip("/"))
            node = service.get_node(
                owner_user_id=owner_user_id_from_value(event, None),
                node_id=node_id,
            )
            return response(200, {"node": node_to_dict(node)})

        if method == "POST" and path.startswith("/nodes/") and path.endswith("/pair-tokens"):
            body = parse_body(event)
            node_id = path_param(path, "/nodes/", "/pair-tokens")
            token = service.create_pair_token(
                owner_user_id=owner_user_id_from_body(event, body),
                node_id=node_id,
                ttl_seconds=optional_body_int(body, "ttl_seconds", default=600),
            )
            return response(200, {"pair_token": pair_token_to_dict(token)})

        if method == "POST" and path == "/agent-registrations":
            body = parse_body(event)
            profile = service.register_agent_with_pair_token(
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
            return response(200, {"created": True, "profile": agent_profile_to_dict(profile)})

        if method == "POST" and path == "/profiles":
            body = parse_body(event)
            profile = service.create_agent_profile(
                owner_user_id=owner_user_id_from_body(event, body),
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
            return response(200, {"created": True, "profile": agent_profile_to_dict(profile)})

        if method == "GET" and path == "/profiles":
            query = event.get("queryStringParameters") or {}
            page = service.list_owned_profiles_page(
                owner_user_id_from_query(event, query),
                limit=optional_query_int(query, "limit", default=50),
                cursor=optional_query_string(query, "cursor"),
                q=optional_query_string(query, "q"),
                status=optional_query_string(query, "status"),
                node_id=optional_query_string(query, "node_id"),
            )
            return response(
                200,
                {
                    "items": [agent_profile_to_dict(profile) for profile in page.items],
                    "next_cursor": page.next_cursor,
                },
            )

        if method == "POST" and path == "/personal-agent-assets":
            body = parse_body(event)
            asset = service.create_personal_agent_asset(
                owner_user_id=owner_user_id_from_body(event, body),
                asset_type=required_string(body, "asset_type"),
                name=required_string(body, "name"),
                instructions=required_string(body, "instructions"),
                description=optional_string(body, "description"),
                style=optional_string(body, "style"),
                tags=string_list(body.get("tags", ()), "tags"),
                max_output_chars=optional_nullable_body_int(body, "max_output_chars"),
            )
            return response(200, {"created": True, "asset": personal_agent_asset_to_dict(asset)})

        if method == "GET" and path == "/personal-agent-assets":
            query = event.get("queryStringParameters") or {}
            assets = service.list_personal_agent_assets(
                owner_user_id_from_query(event, query),
                asset_type=optional_query_string(query, "asset_type"),
            )
            return response(200, {"items": [personal_agent_asset_to_dict(asset) for asset in assets]})

        if method == "GET" and path.startswith("/personal-agent-assets/"):
            query = event.get("queryStringParameters") or {}
            asset_id = unquote(path.removeprefix("/personal-agent-assets/").strip("/"))
            asset = service.get_personal_agent_asset(
                owner_user_id=owner_user_id_from_query(event, query),
                asset_id=asset_id,
            )
            return response(200, {"asset": personal_agent_asset_to_dict(asset)})

        if method == "PUT" and path.startswith("/profiles/") and path.endswith("/asset-binding"):
            body = parse_body(event)
            handle = path_param(path, "/profiles/", "/asset-binding")
            binding = service.set_agent_asset_binding(
                owner_user_id=owner_user_id_from_body(event, body),
                agent_handle=handle,
                prompt_asset_id=optional_string(body, "prompt_asset_id"),
                skill_asset_id=optional_string(body, "skill_asset_id"),
            )
            return response(200, {"binding": agent_asset_binding_to_dict(binding)})

        if method == "GET" and path.startswith("/profiles/") and path.endswith("/asset-binding"):
            query = event.get("queryStringParameters") or {}
            handle = path_param(path, "/profiles/", "/asset-binding")
            binding = service.get_agent_asset_binding(
                owner_user_id=owner_user_id_from_query(event, query),
                agent_handle=handle,
            )
            return response(
                200,
                {"binding": None if binding is None else agent_asset_binding_to_dict(binding)},
            )

        if method == "POST" and path == "/agent-chats":
            body = parse_body(event)
            chat = service.create_agent_chat(
                owner_user_id=owner_user_id_from_body(event, body),
                agent_handle=required_string(body, "agent_handle"),
                title=optional_string(body, "title"),
                sender_handle=optional_string(body, "sender_handle"),
            )
            return response(200, {"created": True, "chat": agent_chat_session_to_dict(chat)})

        if method == "GET" and path == "/agent-chats":
            query = event.get("queryStringParameters") or {}
            chats = service.list_agent_chats(owner_user_id_from_query(event, query))
            return response(200, {"items": [agent_chat_session_to_dict(chat) for chat in chats]})

        if method == "GET" and path.startswith("/agent-chats/") and not path.endswith("/messages"):
            query = event.get("queryStringParameters") or {}
            chat_id = unquote(path.removeprefix("/agent-chats/").strip("/"))
            chat = service.get_agent_chat(
                owner_user_id=owner_user_id_from_query(event, query),
                chat_id=chat_id,
            )
            return response(200, {"chat": agent_chat_session_to_dict(chat)})

        if method == "POST" and path.startswith("/agent-chats/") and path.endswith("/messages"):
            body = parse_body(event)
            chat_id = path_param(path, "/agent-chats/", "/messages")
            owner_user_id = owner_user_id_from_body(event, body)
            chat = service.get_agent_chat(owner_user_id=owner_user_id, chat_id=chat_id)
            message = service.create_agent_chat_message(
                owner_user_id=owner_user_id,
                chat_id=chat.chat_id,
                content=required_string(body, "content"),
            )
            message = deliver_agent_chat_message(owner_user_id, chat, message)
            reply = None
            if ai_reply_enabled():
                message, reply = generate_agent_chat_reply(
                    service,
                    AiProviderRunClient(),
                    owner_user_id=owner_user_id,
                    chat=chat,
                    message=message,
                )
            return response(
                200,
                {
                    "message": agent_chat_message_to_dict(message),
                    "reply": None if reply is None else agent_chat_message_to_dict(reply),
                },
            )

        if method == "GET" and path.startswith("/agent-chats/") and path.endswith("/messages"):
            query = event.get("queryStringParameters") or {}
            chat_id = path_param(path, "/agent-chats/", "/messages")
            messages = service.list_agent_chat_messages(
                owner_user_id=owner_user_id_from_query(event, query),
                chat_id=chat_id,
            )
            return response(200, {"items": [agent_chat_message_to_dict(message) for message in messages]})

        if method == "PATCH" and path.startswith("/profiles/"):
            body = parse_body(event)
            handle = unquote(path.removeprefix("/profiles/").strip("/"))
            profile = service.update_agent_profile(
                owner_user_id=owner_user_id_from_body(event, body),
                handle=handle,
                display_name=optional_string(body, "display_name"),
                bio=optional_string(body, "bio"),
                capabilities=optional_string_list(body, "capabilities"),
                relationship_posture=optional_string(body, "relationship_posture"),
                approval_required_for=optional_string_list(body, "approval_required_for"),
                allowed_use_terms=optional_string_list(body, "allowed_use_terms"),
                contact_explanation=optional_string(body, "contact_explanation"),
            )
            return response(200, {"profile": agent_profile_to_dict(profile)})

        if method == "POST" and path == "/rooms":
            body = parse_body(event)
            room = service.create_room(
                owner_user_id=owner_user_id_from_body(event, body),
                slug=required_string(body, "slug"),
                name=required_string(body, "name"),
                description=optional_string(body, "description"),
                visibility=optional_string(body, "visibility") or "public",
            )
            return response(200, {"created": True, "room": room_to_dict(room)})

        if method == "POST" and path.startswith("/rooms/") and path.endswith("/memberships"):
            body = parse_body(event)
            room_slug = path_param(path, "/rooms/", "/memberships")
            membership = service.join_room(
                owner_user_id=owner_user_id_from_body(event, body),
                room_slug=room_slug,
                agent_handle=required_string(body, "agent_handle"),
                role=optional_string(body, "role") or "member",
            )
            return response(200, {"membership": room_membership_to_dict(membership)})

        if method == "POST" and path == "/follows":
            body = parse_body(event)
            follow = service.follow_agent(
                owner_user_id=owner_user_id_from_body(event, body),
                follower_handle=required_string(body, "follower_handle"),
                followed_handle=required_string(body, "followed_handle"),
            )
            return response(200, {"follow": follow_to_dict(follow)})

        if method == "POST" and path == "/posts":
            body = parse_body(event)
            post = service.create_post(
                owner_user_id=owner_user_id_from_body(event, body),
                author_handle=required_string(body, "author_handle"),
                content=optional_string(body, "content"),
                text=optional_string(body, "text"),
                refs=reference_list(body.get("refs", ())),
                visibility=optional_string(body, "visibility") or "public",
                room_slug=optional_string(body, "room_slug"),
                reply_to_post_id=optional_string(body, "reply_to_post_id"),
            )
            return response(200, {"post": post_to_dict(post)})

        if method == "GET" and path == "/feed":
            query = event.get("queryStringParameters") or {}
            posts = service.get_home_feed(
                owner_user_id_from_query(event, query),
                limit=optional_query_int(query, "limit", default=50),
            )
            return response(200, {"items": [post_to_dict(post) for post in posts]})

        if method == "GET" and path.startswith("/profiles/") and path.endswith("/notifications"):
            query = event.get("queryStringParameters") or {}
            handle = path_param(path, "/profiles/", "/notifications")
            notifications = service.list_notifications(
                owner_user_id=owner_user_id_from_query(event, query),
                agent_handle=handle,
                limit=optional_query_int(query, "limit", default=50),
            )
            return response(200, {"items": [notification_to_dict(notification) for notification in notifications]})

        if method == "POST" and path == "/moderation":
            body = parse_body(event)
            record = service.create_moderation_record(
                owner_user_id=owner_user_id_from_body(event, body),
                target_type=required_string(body, "target_type"),
                target_id=required_string(body, "target_id"),
                action=required_string(body, "action"),
                reason=required_string(body, "reason"),
            )
            return response(200, {"moderation": moderation_record_to_dict(record)})

        if method == "GET" and path == "/moderation":
            require_authenticated_identity(event)
            query = event.get("queryStringParameters") or {}
            records = service.list_moderation_records(limit=optional_query_int(query, "limit", default=50))
            return response(200, {"items": [moderation_record_to_dict(record) for record in records]})

        return response(404, {"error": "not_found", "method": method, "path": path})
    except Unauthorized as exc:
        return response(401, {"error": "unauthorized", "message": str(exc)})
    except BadRequest as exc:
        return response(400, {"error": "bad_request", "message": str(exc)})
    except InvalidSocialRequestError as exc:
        return response(400, {"error": "bad_request", "message": str(exc)})
    except PermissionDeniedError as exc:
        return response(403, {"error": "forbidden", "message": str(exc)})
    except NotFoundError as exc:
        return response(404, {"error": "not_found", "message": str(exc)})
    except (DuplicateAgentHandleError, DuplicateRoomSlugError) as exc:
        return response(409, {"error": "conflict", "message": str(exc)})
    except Exception as exc:
        print(json.dumps({"level": "error", "message": str(exc), "event": redacted_event(event)}, default=str))
        return response(500, {"error": "internal_error"})


def ai_reply_enabled() -> bool:
    return bool(AI_PROVIDER_API_URL and AI_PROVIDER_ADMIN_SECRET and AI_REPLY_PROVIDER and AI_REPLY_MODEL)


class AiProviderRunClient:
    """Synchronous AI provider run client for chat response steps."""

    def create_run(self, request: dict[str, Any]) -> dict[str, Any]:
        body = dict(request)
        body["provider"] = AI_REPLY_PROVIDER
        body["model"] = AI_REPLY_MODEL
        body["max_output_tokens"] = AI_REPLY_MAX_OUTPUT_TOKENS
        payload = json.dumps(
            {key: value for key, value in body.items() if value is not None},
            separators=(",", ":"),
        ).encode("utf-8")
        http_request = Request(
            f"{AI_PROVIDER_API_URL}/ai-runs",
            data=payload,
            headers={
                "content-type": "application/json",
                "x-seagull-admin-secret": AI_PROVIDER_ADMIN_SECRET,
            },
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=AI_REPLY_TIMEOUT_SECONDS) as result:
                raw = result.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"AI provider run failed: HTTP {exc.code} {detail}") from exc
        parsed = json.loads(raw or "{}")
        run = parsed.get("run") if isinstance(parsed, dict) else None
        if not isinstance(run, dict):
            raise RuntimeError("AI provider response must include a run object")
        return run


def deliver_agent_chat_message(owner_user_id: str, chat: Any, message: Any) -> Any:
    if not chat.sender_handle:
        return message
    message_api_url = os.environ.get("MESSAGE_API_URL", "").strip().rstrip("/")
    if not message_api_url:
        return message

    payload = {
        "sender_handle": chat.sender_handle,
        "recipient_handles": [chat.agent_handle],
        "content": message.content,
        "thread_id": chat.hub_thread_id,
        "intent": "chat",
        "visibility": "direct",
    }
    try:
        try:
            result = post_message_hub_json(message_api_url, "/messages", payload)
        except HTTPError as exc:
            if exc.code != 404:
                raise
            # Legacy backfill: profiles created before M0.2 were never
            # registered with the hub at creation time. Register both handles
            # once and retry the send a single time.
            register_message_hub_agent(message_api_url, chat.sender_handle)
            register_message_hub_agent(message_api_url, chat.agent_handle)
            result = post_message_hub_json(message_api_url, "/messages", payload)
    except Exception as exc:
        return service.record_agent_chat_message_delivery(
            owner_user_id=owner_user_id,
            chat_message_id=message.chat_message_id,
            delivery_status="delivery_failed",
            delivery_error=str(exc),
        )

    hub_message = result.get("message") if isinstance(result.get("message"), dict) else {}
    return service.record_agent_chat_message_delivery(
        owner_user_id=owner_user_id,
        chat_message_id=message.chat_message_id,
        delivery_status="delivered",
        hub_message_id=optional_payload_string(hub_message, "message_id") or optional_payload_string(result, "message_id"),
        hub_thread_id=optional_payload_string(result, "thread_id") or optional_payload_string(hub_message, "thread_id"),
    )


def register_message_hub_agent(base_url: str, handle: str, display_name: str | None = None) -> None:
    try:
        post_message_hub_json(base_url, "/agents", {"handle": handle, "display_name": display_name})
    except HTTPError as exc:
        if exc.code == 409:
            return
        raise


def post_message_hub_json(base_url: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({key: value for key, value in body.items() if value is not None}).encode("utf-8")
    headers = {"content-type": "application/json"}
    legacy_secret = secret_env("MESSAGE_HUB_LEGACY_ROUTE_SECRET")
    if legacy_secret:
        headers["x-seagull-legacy-secret"] = legacy_secret
    request = Request(f"{base_url}{path}", data=payload, headers=headers, method="POST")
    with urlopen(request, timeout=5) as result:
        raw = result.read().decode("utf-8")
    parsed = json.loads(raw or "{}")
    if not isinstance(parsed, dict):
        raise BadRequest("message hub response must be a JSON object")
    return parsed


def optional_payload_string(payload: dict[str, Any], field_name: str) -> str | None:
    value = payload.get(field_name)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body")
    if raw_body is None:
        return {}
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise BadRequest("body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    return body


def owner_user_id_from_body(event: dict[str, Any], body: dict[str, Any]) -> str:
    return owner_user_id_from_value(event, optional_string(body, "owner_user_id"))


def owner_user_id_from_query(event: dict[str, Any], query: dict[str, Any]) -> str:
    return owner_user_id_from_value(event, optional_query_string(query, "owner_user_id"))


def owner_user_id_from_value(event: dict[str, Any], owner_user_id: str | None) -> str:
    identity = optional_authenticated_identity(event)
    if identity is None:
        if SOCIAL_AUTH_REQUIRED:
            raise Unauthorized("authentication is required")
        require_auth_bypass_secret(event)
        if owner_user_id is None:
            raise BadRequest("owner_user_id is required")
        return owner_user_id
    if owner_user_id is not None and owner_user_id != identity.user_id:
        raise PermissionDeniedError("owner_user_id does not match authenticated user")
    return identity.user_id


def require_authenticated_identity(event: dict[str, Any]) -> HumanIdentity | None:
    identity = optional_authenticated_identity(event)
    if identity is None and SOCIAL_AUTH_REQUIRED:
        raise Unauthorized("authentication is required")
    if identity is None:
        require_auth_bypass_secret(event)
    return identity


def identity_from_event(event: dict[str, Any]) -> HumanIdentity:
    identity = optional_authenticated_identity(event)
    if identity is None:
        raise Unauthorized("authentication is required")
    return identity


def identify_human_from_event(event: dict[str, Any]) -> HumanIdentity:
    identity = optional_authenticated_identity(event)
    if identity is not None:
        return identity
    if SOCIAL_AUTH_REQUIRED:
        raise Unauthorized("authentication is required")
    require_auth_bypass_secret(event)
    body = parse_body(event)
    return service.identify_human(
        provider=required_string(body, "provider"),
        subject=required_string(body, "subject"),
        email=optional_string(body, "email"),
        display_name=optional_string(body, "display_name"),
    )


def require_auth_bypass_secret(event: dict[str, Any]) -> None:
    if is_auth_bypass_request(event):
        return
    if not SOCIAL_AUTH_BYPASS_SECRET:
        raise Unauthorized("authentication is required")
    raise Unauthorized("auth bypass secret is required")


def is_auth_bypass_request(event: dict[str, Any]) -> bool:
    if not SOCIAL_AUTH_BYPASS_SECRET:
        return False
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    provided = headers.get("x-seagull-auth-bypass-secret")
    return isinstance(provided, str) and hmac.compare_digest(provided, SOCIAL_AUTH_BYPASS_SECRET)


def optional_authenticated_identity(event: dict[str, Any]) -> HumanIdentity | None:
    claims = jwt_claims(event)
    if not claims:
        return None
    subject = optional_claim(claims, "sub")
    if subject is None:
        raise Unauthorized("authenticated token is missing subject")
    return service.identify_human(
        provider="cognito",
        subject=subject,
        email=optional_claim(claims, "email"),
        display_name=optional_claim(claims, "name") or optional_claim(claims, "cognito:username"),
    )


def jwt_claims(event: dict[str, Any]) -> dict[str, Any] | None:
    authorizer = event.get("requestContext", {}).get("authorizer", {})
    jwt = authorizer.get("jwt", {}) if isinstance(authorizer, dict) else {}
    claims = jwt.get("claims", {}) if isinstance(jwt, dict) else {}
    return claims if isinstance(claims, dict) else None


def optional_claim(claims: dict[str, Any], name: str) -> str | None:
    value = claims.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            **cors_headers(),
        },
        "body": json.dumps(body, separators=(",", ":"), default=str),
    }


def cors_response() -> dict[str, Any]:
    return {
        "statusCode": 204,
        "headers": cors_headers(),
        "body": "",
    }


def cors_headers() -> dict[str, str]:
    return {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET,OPTIONS,PATCH,POST,PUT",
        "access-control-allow-headers": "authorization,content-type,x-seagull-auth-bypass-secret",
        "access-control-max-age": "300",
    }


def path_param(path: str, prefix: str, suffix: str) -> str:
    return unquote(path.removeprefix(prefix).removesuffix(suffix).strip("/"))


def required_string(body: dict[str, Any], field_name: str) -> str:
    value = optional_string(body, field_name)
    if value is None:
        raise BadRequest(f"{field_name} is required")
    return value


def optional_string(body: dict[str, Any], field_name: str) -> str | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadRequest(f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None


def string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise BadRequest(f"{field_name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise BadRequest(f"{field_name} must contain only strings")
    return tuple(item.strip() for item in value if item.strip())


def optional_string_list(body: dict[str, Any], field_name: str) -> tuple[str, ...] | None:
    if field_name not in body:
        return None
    return string_list(body.get(field_name), field_name)


def reference_list(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise BadRequest("refs must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise BadRequest("refs must contain objects")
    return tuple(value)


def optional_body_int(body: dict[str, Any], field_name: str, *, default: int) -> int:
    value = body.get(field_name)
    if value is None:
        return default
    if not isinstance(value, int):
        raise BadRequest(f"{field_name} must be an integer")
    return value


def optional_nullable_body_int(body: dict[str, Any], field_name: str) -> int | None:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int):
        raise BadRequest(f"{field_name} must be an integer")
    return value


def required_query_string(query: dict[str, Any], field_name: str) -> str:
    value = optional_query_string(query, field_name)
    if value is None:
        raise BadRequest(f"{field_name} is required")
    return value


def optional_query_string(query: dict[str, Any], field_name: str) -> str | None:
    value = query.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadRequest(f"{field_name} must be a string")
    stripped = value.strip()
    return stripped or None


def optional_query_int(query: dict[str, Any], field_name: str, *, default: int) -> int:
    value = query.get(field_name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise BadRequest(f"{field_name} must be an integer") from exc
    return max(1, min(parsed, 100))
