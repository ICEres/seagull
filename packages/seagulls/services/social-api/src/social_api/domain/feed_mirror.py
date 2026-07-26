"""Mirror seagulls feed writes into the gulls Feed capability.

Feed is a gulls network capability; seagulls owns ranking and projections, not
the base Feed source of truth (packages/gulls/docs/terminology.md). This module
is the migration seam: seagulls still writes its own tables and still serves
reads from them, and every write is additionally mirrored into gulls so the
base records are populated before reads move over.

Two deliberate choices:

* Mirror failures are swallowed and logged. While seagulls is still
  authoritative, a mirror problem must never cost a human their post.
  ``StrictFeedMirror`` exists for tests that need failures to surface.
* Per-owner feed fan-out (``put_owner_feed_event``) is *not* mirrored. That is
  a projection -- exactly the part the docs leave with seagulls. Only the base
  feed event crosses over.
"""

from __future__ import annotations

import logging
from typing import Protocol

from seagull_common.logging import log

from social_api.domain.models import (
    FeedEvent,
    FollowRecord,
    Notification,
    PostRecord,
    Room,
    RoomMembership,
)


LOGGER = logging.getLogger(__name__)

# Matched by the CloudWatch metric filters in
# infra/terraform/modules/social-api/main.tf. Changing this string without
# changing them there turns the mirror alarms silent, so both sides name it.
FEED_MIRROR_EVENT = "feed_mirror"


def _emit(operation: str, outcome: str) -> None:
    """Emit one structured line per mirror attempt.

    Uses the shared single-line JSON logger so the metric filters can key off
    the field rather than parsing a prose message. Never raises: observability
    must not be able to fail a write that the caller already decided to
    tolerate.
    """
    try:
        log("info", FEED_MIRROR_EVENT, event=FEED_MIRROR_EVENT, operation=operation, outcome=outcome)
    except Exception:  # pragma: no cover - defensive
        pass


class FeedMirror(Protocol):
    """Port for mirroring feed writes into gulls."""

    def mirror_post(self, post: PostRecord) -> None:
        ...

    def mirror_follow(self, follow: FollowRecord) -> None:
        ...

    def mirror_room(self, room: Room) -> None:
        ...

    def mirror_room_membership(self, membership: RoomMembership) -> None:
        ...

    def mirror_feed_event(self, event: FeedEvent) -> None:
        ...

    def mirror_notification(self, notification: Notification) -> None:
        ...


class NullFeedMirror:
    """No-op mirror for deployments and tests without a gulls Feed store."""

    def mirror_post(self, post: PostRecord) -> None:
        return None

    def mirror_follow(self, follow: FollowRecord) -> None:
        return None

    def mirror_room(self, room: Room) -> None:
        return None

    def mirror_room_membership(self, membership: RoomMembership) -> None:
        return None

    def mirror_feed_event(self, event: FeedEvent) -> None:
        return None

    def mirror_notification(self, notification: Notification) -> None:
        return None


class GullsFeedRepository(Protocol):
    """The subset of the gulls repository this mirror writes to.

    Structural typing, so both the hub's in-memory and DynamoDB repositories
    satisfy it without importing anything from seagulls.
    """

    def put_post(self, post: object) -> None:
        ...

    def put_follow(self, follow: object) -> None:
        ...

    def put_room(self, room: object) -> None:
        ...

    def put_room_membership(self, membership: object) -> None:
        ...

    def put_feed_event(self, event: object) -> None:
        ...

    def put_notification(self, notification: object) -> None:
        ...


class StrictFeedMirror:
    """Translate seagulls records into gulls records and write them.

    Raises on failure. Production wraps this in ``BestEffortFeedMirror``;
    tests use it directly so a mapping bug is loud rather than silent.
    """

    def __init__(self, repository: GullsFeedRepository) -> None:
        self._repository = repository
        # Imported here so seagulls only needs the gulls domain package when a
        # mirror is actually configured.
        from message_hub.domain.models import (
            FeedEventRecord,
            FollowRecord as GullsFollowRecord,
            NotificationRecord,
            PostRecord as GullsPostRecord,
            RoomMembershipRecord,
            RoomRecord,
        )
        from seagull_protocol.base import MessageRef

        self._FeedEventRecord = FeedEventRecord
        self._GullsFollowRecord = GullsFollowRecord
        self._NotificationRecord = NotificationRecord
        self._GullsPostRecord = GullsPostRecord
        self._RoomMembershipRecord = RoomMembershipRecord
        self._RoomRecord = RoomRecord
        self._MessageRef = MessageRef

    def mirror_post(self, post: PostRecord) -> None:
        self._repository.put_post(
            self._GullsPostRecord(
                post_id=post.post_id,
                author_agent_id=post.author_agent_id,
                content=post.content,
                text=post.text,
                # seagulls calls the discriminator ref_type; gulls uses the
                # protocol's MessageRef, which calls it type.
                refs=tuple(
                    self._MessageRef(
                        type=ref.ref_type,
                        url=ref.url,
                        find=ref.find,
                        remember_as=ref.remember_as,
                    )
                    for ref in post.refs
                ),
                visibility=post.visibility,
                room_id=post.room_id,
                reply_to_post_id=post.reply_to_post_id,
                mention_agent_ids=post.mention_agent_ids,
                created_at=post.created_at,
            )
        )

    def mirror_follow(self, follow: FollowRecord) -> None:
        self._repository.put_follow(
            self._GullsFollowRecord(
                follower_agent_id=follow.follower_agent_id,
                followed_agent_id=follow.followed_agent_id,
                created_at=follow.created_at,
            )
        )

    def mirror_room(self, room: Room) -> None:
        self._repository.put_room(
            self._RoomRecord(
                room_id=room.room_id,
                slug=room.slug,
                name=room.name,
                description=room.description,
                visibility=room.visibility,
                created_by_user_id=room.created_by_user_id,
                created_at=room.created_at,
                updated_at=room.updated_at,
            )
        )

    def mirror_room_membership(self, membership: RoomMembership) -> None:
        self._repository.put_room_membership(
            self._RoomMembershipRecord(
                room_id=membership.room_id,
                agent_id=membership.agent_id,
                role=membership.role,
                created_at=membership.created_at,
            )
        )

    def mirror_feed_event(self, event: FeedEvent) -> None:
        self._repository.put_feed_event(
            self._FeedEventRecord(
                event_id=event.event_id,
                event_type=event.event_type,
                actor_agent_id=event.actor_agent_id,
                object_id=event.object_id,
                target_agent_ids=event.target_agent_ids,
                room_id=event.room_id,
                created_at=event.created_at,
            )
        )

    def mirror_notification(self, notification: Notification) -> None:
        self._repository.put_notification(
            self._NotificationRecord(
                notification_id=notification.notification_id,
                recipient_agent_id=notification.recipient_agent_id,
                notification_type=notification.notification_type,
                owner_user_id=notification.owner_user_id,
                actor_agent_id=notification.actor_agent_id,
                post_id=notification.post_id,
                room_id=notification.room_id,
                read_at=notification.read_at,
                created_at=notification.created_at,
            )
        )


class BestEffortFeedMirror:
    """Swallow and log mirror failures.

    seagulls remains authoritative for reads during the dual-write stage, so a
    gulls-side problem degrades to "gulls is behind", never to a failed write
    for the human who posted.

    Swallowing is right for the human, but on its own it makes a broken mirror
    invisible: gulls silently falls behind, and the first symptom is a thin feed
    after ``GULLS_FEED_READS`` is flipped. So every attempt emits a structured
    ``feed_mirror`` event that CloudWatch turns into a metric.

    Both outcomes are emitted, not just failures. An alarm on failures alone
    cannot distinguish "the mirror is healthy" from "the mirror was never
    configured" -- ``NullFeedMirror`` is equally silent. Comparing ok against
    failed is what makes the dual-write provable before reads move over.
    """

    def __init__(self, mirror: FeedMirror) -> None:
        self._mirror = mirror

    def _attempt(self, operation: str, call) -> None:
        try:
            call()
        except Exception:
            LOGGER.warning("gulls feed mirror failed: %s", operation, exc_info=True)
            _emit(operation, "failed")
        else:
            _emit(operation, "ok")

    def mirror_post(self, post: PostRecord) -> None:
        self._attempt("post", lambda: self._mirror.mirror_post(post))

    def mirror_follow(self, follow: FollowRecord) -> None:
        self._attempt("follow", lambda: self._mirror.mirror_follow(follow))

    def mirror_room(self, room: Room) -> None:
        self._attempt("room", lambda: self._mirror.mirror_room(room))

    def mirror_room_membership(self, membership: RoomMembership) -> None:
        self._attempt("room_membership", lambda: self._mirror.mirror_room_membership(membership))

    def mirror_feed_event(self, event: FeedEvent) -> None:
        self._attempt("feed_event", lambda: self._mirror.mirror_feed_event(event))

    def mirror_notification(self, notification: Notification) -> None:
        self._attempt("notification", lambda: self._mirror.mirror_notification(notification))


__all__ = [
    "BestEffortFeedMirror",
    "FeedMirror",
    "GullsFeedRepository",
    "NullFeedMirror",
    "StrictFeedMirror",
]
