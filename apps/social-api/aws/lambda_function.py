import base64
import json
import os
from typing import Any
from urllib.parse import unquote

import boto3

from social_api.api.local import (
    agent_profile_to_dict,
    dashboard_summary_to_dict,
    follow_to_dict,
    human_identity_to_dict,
    moderation_record_to_dict,
    node_to_dict,
    notification_to_dict,
    pair_token_to_dict,
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


APP_NAME = os.environ.get("APP_NAME", "seagull-social-api")
SOCIAL_AUTH_REQUIRED = os.environ.get("SOCIAL_AUTH_REQUIRED", "false").lower() == "true"

dynamodb = boto3.resource("dynamodb")
repository = DynamoDbSocialRepository(
    identities_table=dynamodb.Table(os.environ["IDENTITIES_TABLE"]),
    profiles_table=dynamodb.Table(os.environ["PROFILES_TABLE"]),
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
service = SocialApiService(repository)


class BadRequest(ValueError):
    pass


class Unauthorized(ValueError):
    pass


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
            body = parse_body(event)
            identity = service.identify_human(
                provider=required_string(body, "provider"),
                subject=required_string(body, "subject"),
                email=optional_string(body, "email"),
                display_name=optional_string(body, "display_name"),
            )
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
                protocols=string_list(body.get("protocols", ("seagull",)), "protocols"),
            )
            return response(200, {"created": True, "profile": agent_profile_to_dict(profile)})

        if method == "GET" and path == "/profiles":
            query = event.get("queryStringParameters") or {}
            profiles = service.list_owned_profiles(
                owner_user_id_from_query(event, query),
                limit=optional_query_int(query, "limit", default=50),
                q=optional_query_string(query, "q"),
                status=optional_query_string(query, "status"),
                node_id=optional_query_string(query, "node_id"),
            )
            return response(200, {"items": [agent_profile_to_dict(profile) for profile in profiles]})

        if method == "PATCH" and path.startswith("/profiles/"):
            body = parse_body(event)
            handle = unquote(path.removeprefix("/profiles/").strip("/"))
            profile = service.update_agent_profile(
                owner_user_id=owner_user_id_from_body(event, body),
                handle=handle,
                display_name=optional_string(body, "display_name"),
                bio=optional_string(body, "bio"),
                capabilities=optional_string_list(body, "capabilities"),
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
        print(json.dumps({"level": "error", "message": str(exc), "event": event}, default=str))
        return response(500, {"error": "internal_error"})


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
    return identity


def identity_from_event(event: dict[str, Any]) -> HumanIdentity:
    identity = optional_authenticated_identity(event)
    if identity is None:
        raise Unauthorized("authentication is required")
    return identity


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
        "access-control-allow-methods": "GET,OPTIONS,PATCH,POST",
        "access-control-allow-headers": "authorization,content-type",
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
