"""Copy pre-existing seagulls feed rows into the gulls Feed store.

The mirror in ``feed_mirror.py`` only catches *new* writes. Everything written
before it shipped exists solely in the seagulls tables, which is why
``FallbackFeedSource`` still reads both. That fallback is a migration crutch,
not an end state: until the old rows are copied across, the seagulls tables can
never be dropped and gulls is not really the source of truth the docs claim.

This module is the one-shot that closes that gap.

Two properties matter:

* **It reuses ``FeedMirror`` for translation.** Backfill deliberately does not
  own a second copy of the seagulls-to-gulls mapping. One implementation means
  backfilled rows and live-mirrored rows cannot disagree -- and the dual-write
  parity tests cover both at once.
* **It is idempotent.** Every write is a keyed put, so a re-run overwrites
  rather than duplicating. Interrupt it and run it again.

Enumeration is deliberately kept out of the request-path repository port. The
production port exposes scoped reads (by owner, by author, by recipient) on
purpose; adding "list everything" there would invite a full-table scan into a
request handler. A migration is the one place a scan is correct, so the sources
below reach past the port instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from social_api.domain.feed_mirror import FeedMirror
from social_api.domain.models import (
    FeedEvent,
    FollowRecord,
    Notification,
    PostRecord,
    Room,
    RoomMembership,
)


LOGGER = logging.getLogger(__name__)


class BackfillSource(Protocol):
    """Enumerates every feed row currently held by seagulls."""

    def iter_posts(self) -> Iterable[PostRecord]:
        ...

    def iter_follows(self) -> Iterable[FollowRecord]:
        ...

    def iter_rooms(self) -> Iterable[Room]:
        ...

    def iter_room_memberships(self) -> Iterable[RoomMembership]:
        ...

    def iter_feed_events(self) -> Iterable[FeedEvent]:
        ...

    def iter_notifications(self) -> Iterable[Notification]:
        ...


class InMemoryBackfillSource:
    """Enumerate an ``InMemorySocialRepository``.

    Used by tests and by local runs against the in-memory adapter.
    """

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    def iter_posts(self) -> Iterable[PostRecord]:
        return tuple(self._repository._posts.values())  # noqa: SLF001 - migration

    def iter_follows(self) -> Iterable[FollowRecord]:
        return tuple(self._repository._follows.values())  # noqa: SLF001 - migration

    def iter_rooms(self) -> Iterable[Room]:
        return tuple(self._repository._rooms.values())  # noqa: SLF001 - migration

    def iter_room_memberships(self) -> Iterable[RoomMembership]:
        return tuple(self._repository._memberships.values())  # noqa: SLF001 - migration

    def iter_feed_events(self) -> Iterable[FeedEvent]:
        return tuple(self._repository._feed_events.values())  # noqa: SLF001 - migration

    def iter_notifications(self) -> Iterable[Notification]:
        return tuple(self._repository._notifications.values())  # noqa: SLF001 - migration


class DynamoDbBackfillSource:
    """Scan the six seagulls feed tables.

    Reuses the repository's own item decoders, so a row that the service can
    read is a row the backfill can read -- no second parsing implementation to
    drift.
    """

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    @staticmethod
    def _scan(table) -> Iterable[dict]:
        kwargs: dict[str, Any] = {}
        while True:
            result = table.scan(**kwargs)
            for item in result.get("Items", []):
                yield item
            key = result.get("LastEvaluatedKey")
            if not key:
                return
            kwargs["ExclusiveStartKey"] = key

    def _decoded(self, table, decoder_name: str) -> Iterable[Any]:
        from social_api.storage import dynamodb as codecs

        decoder = getattr(codecs, decoder_name)
        for item in self._scan(table):
            yield decoder(item)

    def iter_posts(self) -> Iterable[PostRecord]:
        return self._decoded(self._repository._posts_table, "item_to_post")  # noqa: SLF001

    def iter_follows(self) -> Iterable[FollowRecord]:
        return self._decoded(self._repository._follows_table, "item_to_follow")  # noqa: SLF001

    def iter_rooms(self) -> Iterable[Room]:
        return self._decoded(self._repository._rooms_table, "item_to_room")  # noqa: SLF001

    def iter_room_memberships(self) -> Iterable[RoomMembership]:
        return self._decoded(
            self._repository._room_memberships_table, "item_to_room_membership"  # noqa: SLF001
        )

    def iter_feed_events(self) -> Iterable[FeedEvent]:
        return self._decoded(self._repository._feed_events_table, "item_to_feed_event")  # noqa: SLF001

    def iter_notifications(self) -> Iterable[Notification]:
        return self._decoded(
            self._repository._notifications_table, "item_to_notification"  # noqa: SLF001
        )


@dataclass
class BackfillReport:
    """What crossed over, and what refused to.

    ``failures`` is the number that matters: a backfill reporting copies but
    also failures has *not* finished, and the seagulls tables must not be
    dropped on the strength of it.
    """

    copied: dict[str, int] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False

    @property
    def total_copied(self) -> int:
        return sum(self.copied.values())

    @property
    def total_failures(self) -> int:
        return sum(self.failures.values())

    @property
    def complete(self) -> bool:
        return self.total_failures == 0

    def summary(self) -> str:
        mode = "would copy" if self.dry_run else "copied"
        # Every kind is reported even at zero: it distinguishes "enumerated and
        # found nothing" from "never looked", which is the difference between a
        # finished migration and a silently skipped one.
        parts = [f"{kind}={count}" for kind, count in sorted(self.copied.items())]
        line = f"backfill {mode}: {' '.join(parts)} (total {self.total_copied})"
        if self.total_failures:
            failed = " ".join(f"{k}={v}" for k, v in sorted(self.failures.items()))
            line += f" | FAILURES: {failed} (total {self.total_failures})"
        return line


def backfill_feed(
    source: BackfillSource,
    mirror: FeedMirror,
    *,
    dry_run: bool = False,
) -> BackfillReport:
    """Copy every seagulls feed row into gulls through ``mirror``.

    Pass a ``StrictFeedMirror``, not a ``BestEffortFeedMirror``: a migration
    wants failures counted, not swallowed. Swallowing is correct for a live
    request that must not fail a human's post; it is exactly wrong for a
    one-shot whose whole purpose is to prove completeness.
    """
    report = BackfillReport(dry_run=dry_run)

    steps = (
        ("posts", source.iter_posts, mirror.mirror_post),
        ("follows", source.iter_follows, mirror.mirror_follow),
        ("rooms", source.iter_rooms, mirror.mirror_room),
        ("room_memberships", source.iter_room_memberships, mirror.mirror_room_membership),
        ("feed_events", source.iter_feed_events, mirror.mirror_feed_event),
        ("notifications", source.iter_notifications, mirror.mirror_notification),
    )

    for kind, read, write in steps:
        copied = 0
        failed = 0
        for record in read():
            if dry_run:
                copied += 1
                continue
            try:
                write(record)
            except Exception:
                failed += 1
                LOGGER.warning("backfill failed for one %s row", kind, exc_info=True)
            else:
                copied += 1
        report.copied[kind] = copied
        if failed:
            report.failures[kind] = failed

    return report


__all__ = [
    "BackfillReport",
    "BackfillSource",
    "DynamoDbBackfillSource",
    "InMemoryBackfillSource",
    "backfill_feed",
]
