#!/usr/bin/env python3
"""Copy pre-existing seagulls feed rows into the gulls Feed store.

The mirror only catches new writes. This is the one-shot for everything older,
and it must finish before the seagulls feed tables can be dropped.

Reads the same environment variables the social-api Lambda uses, so a shell
that can run the service can run this with no extra configuration:

    POSTS_TABLE, FOLLOWS_TABLE, ROOMS_TABLE, ROOM_MEMBERSHIPS_TABLE,
    FEED_EVENTS_TABLE, NOTIFICATIONS_TABLE          (seagulls, source)
    GULLS_POSTS_TABLE, GULLS_FOLLOWS_TABLE, GULLS_ROOMS_TABLE,
    GULLS_ROOM_MEMBERSHIPS_TABLE, GULLS_FEED_EVENTS_TABLE,
    GULLS_NOTIFICATIONS_TABLE                       (gulls, destination)

Usage:
    scripts/backfill-feed.py --dry-run     # count without writing
    scripts/backfill-feed.py               # copy

Re-running is safe: every write is a keyed put, so a second run overwrites
rather than duplicating. Exits non-zero if any row failed, so it can gate the
decision to drop the old tables.
"""

from __future__ import annotations

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for relative in (
    "packages/seagulls/services/social-api/src",
    "packages/gulls/services/message-hub/src",
    "packages/gulls/packages/protocol/src",
    "packages/gulls/packages/policy/src",
    "packages/gulls/packages/common/src",
    "packages/pet/packages/assets/src",
):
    sys.path.insert(0, os.path.join(REPO_ROOT, relative))


SEAGULLS_TABLES = (
    "POSTS_TABLE",
    "FOLLOWS_TABLE",
    "ROOMS_TABLE",
    "ROOM_MEMBERSHIPS_TABLE",
    "FEED_EVENTS_TABLE",
    "NOTIFICATIONS_TABLE",
)

GULLS_TABLES = tuple(f"GULLS_{name}" for name in SEAGULLS_TABLES)


def _require(names):
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise SystemExit(f"missing required environment variables: {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count what would be copied without writing anything",
    )
    args = parser.parse_args()

    _require(SEAGULLS_TABLES)
    if not args.dry_run:
        _require(GULLS_TABLES)

    import boto3

    from message_hub.storage.dynamodb import DynamoDbMessageHubRepository
    from social_api.domain.feed_backfill import DynamoDbBackfillSource, backfill_feed
    from social_api.domain.feed_mirror import StrictFeedMirror
    from social_api.storage.dynamodb import DynamoDbSocialRepository

    dynamodb = boto3.resource("dynamodb")

    def table(name: str):
        return dynamodb.Table(os.environ[name])

    # Only the feed tables are needed to enumerate; the rest of the social
    # repository is irrelevant to this migration.
    source_repository = DynamoDbSocialRepository(
        identities_table=None,
        profiles_table=None,
        personal_agent_assets_table=None,
        agent_asset_bindings_table=None,
        agent_chats_table=None,
        agent_chat_messages_table=None,
        nodes_table=None,
        pair_tokens_table=None,
        rooms_table=table("ROOMS_TABLE"),
        room_memberships_table=table("ROOM_MEMBERSHIPS_TABLE"),
        follows_table=table("FOLLOWS_TABLE"),
        posts_table=table("POSTS_TABLE"),
        feed_events_table=table("FEED_EVENTS_TABLE"),
        notifications_table=table("NOTIFICATIONS_TABLE"),
        moderation_table=None,
    )

    if args.dry_run:
        # Nothing is written, so the destination is never touched.
        mirror = _CountingMirror()
    else:
        destination = DynamoDbMessageHubRepository(
            agents_table=None,
            messages_table=None,
            threads_table=None,
            deliveries_table=None,
            idempotency_table=None,
            thread_summaries_table=None,
            posts_table=table("GULLS_POSTS_TABLE"),
            follows_table=table("GULLS_FOLLOWS_TABLE"),
            rooms_table=table("GULLS_ROOMS_TABLE"),
            room_memberships_table=table("GULLS_ROOM_MEMBERSHIPS_TABLE"),
            feed_events_table=table("GULLS_FEED_EVENTS_TABLE"),
            notifications_table=table("GULLS_NOTIFICATIONS_TABLE"),
        )
        # Strict, not best-effort: a migration counts failures rather than
        # swallowing them, because its output gates dropping the old tables.
        mirror = StrictFeedMirror(destination)

    report = backfill_feed(
        DynamoDbBackfillSource(source_repository),
        mirror,
        dry_run=args.dry_run,
    )

    print(report.summary())

    if not report.complete:
        print(
            "backfill did NOT finish cleanly -- do not drop the seagulls feed tables",
            file=sys.stderr,
        )
        return 1
    return 0


class _CountingMirror:
    """Dry-run stand-in; backfill_feed never calls it when dry_run is set."""

    def __getattr__(self, _name):
        def _unreachable(*_args, **_kwargs):  # pragma: no cover - defensive
            raise AssertionError("dry run must not write")

        return _unreachable


if __name__ == "__main__":
    raise SystemExit(main())
