"""Exercise the Feed repository query paths against emulated DynamoDB.

``test_feed_records.py`` covers the models, the in-memory repository, and the
item codecs -- all of which run without AWS. None of that touches the part most
likely to break in production: the ``query`` calls, which name a GSI that only
exists because Terraform declares it.

That pairing is the real risk. ``terraform validate`` proves the HCL is
well-formed, not that ``IndexName="author-created-at-index"`` matches the index
the module actually creates. A typo on either side type-checks cleanly, passes
every non-moto test, and fails on the first feed read after deploy.

So the table definitions below are written to mirror
``infra/terraform/modules/message-hub/main.tf`` exactly -- same key schema, same
index names, same key types. A drift on either side fails here.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

try:
    import boto3
    from moto import mock_aws

    HAS_MOTO = True
except ImportError:  # pragma: no cover - exercised by the skip below
    HAS_MOTO = False

from message_hub.domain.models import (
    FeedEventRecord,
    FollowRecord,
    NotificationRecord,
    PostRecord,
    RoomMembershipRecord,
    RoomRecord,
)
from message_hub.storage.dynamodb import DynamoDbMessageHubRepository


REGION = "ap-southeast-2"
BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def at(offset_seconds: int) -> datetime:
    return BASE + timedelta(seconds=offset_seconds)


def _table(dynamodb, name, *, hash_key, range_key=None, gsis=()):
    attributes = {hash_key}
    if range_key:
        attributes.add(range_key)
    for _, gsi_hash, gsi_range in gsis:
        attributes.add(gsi_hash)
        if gsi_range:
            attributes.add(gsi_range)

    kwargs = {
        "TableName": name,
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": hash_key, "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": attribute, "AttributeType": "S"} for attribute in sorted(attributes)
        ],
    }
    if range_key:
        kwargs["KeySchema"].append({"AttributeName": range_key, "KeyType": "RANGE"})
    if gsis:
        kwargs["GlobalSecondaryIndexes"] = [
            {
                "IndexName": index_name,
                "KeySchema": (
                    [{"AttributeName": gsi_hash, "KeyType": "HASH"}]
                    + ([{"AttributeName": gsi_range, "KeyType": "RANGE"}] if gsi_range else [])
                ),
                "Projection": {"ProjectionType": "ALL"},
            }
            for index_name, gsi_hash, gsi_range in gsis
        ]
    dynamodb.create_table(**kwargs)
    return dynamodb.Table(name)


@unittest.skipUnless(HAS_MOTO, "moto and boto3 are required for Feed DynamoDB tests")
class FeedDynamoDbRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
        os.environ.setdefault("AWS_DEFAULT_REGION", REGION)
        self._mock = mock_aws()
        self._mock.start()
        self.addCleanup(self._mock.stop)

        dynamodb = boto3.resource("dynamodb", region_name=REGION)

        # Mirrors infra/terraform/modules/message-hub/main.tf.
        self.posts = _table(
            dynamodb,
            "posts",
            hash_key="post_id",
            gsis=(("author-created-at-index", "author_agent_id", "created_at"),),
        )
        self.follows = _table(
            dynamodb,
            "follows",
            hash_key="follower_agent_id",
            range_key="followed_agent_id",
            gsis=(("followed-index", "followed_agent_id", "follower_agent_id"),),
        )
        self.rooms = _table(
            dynamodb, "rooms", hash_key="room_id", gsis=(("slug-index", "slug", None),)
        )
        self.room_memberships = _table(
            dynamodb,
            "room-memberships",
            hash_key="room_id",
            range_key="agent_id",
            gsis=(("agent-index", "agent_id", "room_id"),),
        )
        self.feed_events = _table(dynamodb, "feed-events", hash_key="event_id")
        self.notifications = _table(
            dynamodb,
            "notifications",
            hash_key="notification_id",
            gsis=(("recipient-created-at-index", "recipient_agent_id", "created_at"),),
        )

        # The repository requires its core tables even when a caller only
        # touches Feed, so create the minimum it asks for.
        core = {
            "agents_table": _table(dynamodb, "agents", hash_key="agent_id"),
            "messages_table": _table(dynamodb, "messages", hash_key="message_id"),
            "threads_table": _table(dynamodb, "threads", hash_key="thread_id"),
            "deliveries_table": _table(dynamodb, "deliveries", hash_key="delivery_id"),
            "idempotency_table": _table(
                dynamodb, "idempotency", hash_key="sender_agent_id", range_key="idempotency_key"
            ),
            "thread_summaries_table": _table(
                dynamodb, "thread-summaries", hash_key="thread_id", range_key="created_at"
            ),
        }

        self.repository = DynamoDbMessageHubRepository(
            posts_table=self.posts,
            follows_table=self.follows,
            rooms_table=self.rooms,
            room_memberships_table=self.room_memberships,
            feed_events_table=self.feed_events,
            notifications_table=self.notifications,
            **core,
        )
        self._core = core

    # -- posts

    def test_post_round_trip_preserves_refs_and_visibility(self) -> None:
        from seagull_protocol.base import MessageRef, Visibility

        post = PostRecord(
            post_id="p1",
            author_agent_id="a1",
            content="hello",
            text="hello",
            refs=(MessageRef(type="url", url="https://example.com", find="f", remember_as="r"),),
            visibility=Visibility.PUBLIC,
            mention_agent_ids=("a2",),
            created_at=at(0),
        )
        self.repository.put_post(post)

        loaded = self.repository.get_post("p1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.text, "hello")
        self.assertEqual(loaded.mention_agent_ids, ("a2",))
        self.assertEqual(len(loaded.refs), 1)
        self.assertEqual(loaded.refs[0].url, "https://example.com")
        self.assertEqual(loaded.refs[0].remember_as, "r")
        self.assertEqual(loaded.created_at, at(0))

    def test_get_post_returns_none_when_absent(self) -> None:
        self.assertIsNone(self.repository.get_post("missing"))

    def test_list_posts_by_author_uses_the_gsi_newest_first(self) -> None:
        for index in range(3):
            self.repository.put_post(
                PostRecord(
                    post_id=f"p{index}",
                    author_agent_id="author",
                    content=f"c{index}",
                    text=f"c{index}",
                    created_at=at(index),
                )
            )
        self.repository.put_post(
            PostRecord(
                post_id="other",
                author_agent_id="someone-else",
                content="x",
                text="x",
                created_at=at(99),
            )
        )

        posts = self.repository.list_posts_by_author("author")

        # Newest first, and scoped to the requested author.
        self.assertEqual([post.post_id for post in posts], ["p2", "p1", "p0"])

    def test_list_posts_by_author_honours_limit(self) -> None:
        for index in range(5):
            self.repository.put_post(
                PostRecord(
                    post_id=f"p{index}",
                    author_agent_id="author",
                    content="c",
                    text="c",
                    created_at=at(index),
                )
            )

        self.assertEqual(len(self.repository.list_posts_by_author("author", limit=2)), 2)

    def test_list_posts_sorts_newest_first_across_authors(self) -> None:
        self.repository.put_post(
            PostRecord(post_id="old", author_agent_id="a1", content="c", text="c", created_at=at(0))
        )
        self.repository.put_post(
            PostRecord(post_id="new", author_agent_id="a2", content="c", text="c", created_at=at(10))
        )

        self.assertEqual([post.post_id for post in self.repository.list_posts()], ["new", "old"])

    # -- follows

    def test_follow_round_trip_and_both_directions(self) -> None:
        self.repository.put_follow(FollowRecord("f1", "t1", created_at=at(0)))
        self.repository.put_follow(FollowRecord("f1", "t2", created_at=at(1)))
        self.repository.put_follow(FollowRecord("f2", "t1", created_at=at(2)))

        self.assertIsNotNone(self.repository.get_follow("f1", "t1"))
        self.assertIsNone(self.repository.get_follow("f1", "nobody"))

        # Table key: who f1 follows.
        following = self.repository.list_follows_by_follower("f1")
        self.assertEqual(sorted(f.followed_agent_id for f in following), ["t1", "t2"])

        # followed-index: who follows t1.
        followers = self.repository.list_follows_by_followed("t1")
        self.assertEqual(sorted(f.follower_agent_id for f in followers), ["f1", "f2"])

    # -- rooms and membership

    def test_room_round_trip_and_slug_lookup(self) -> None:
        self.repository.put_room(
            RoomRecord(room_id="r1", slug="weather", name="Weather", created_at=at(0))
        )

        self.assertEqual(self.repository.get_room("r1").name, "Weather")
        self.assertEqual(self.repository.get_room_by_slug("weather").room_id, "r1")
        self.assertIsNone(self.repository.get_room_by_slug("nope"))

    def test_room_membership_round_trip_and_agent_index(self) -> None:
        self.repository.put_room_membership(RoomMembershipRecord("r1", "a1", created_at=at(0)))
        self.repository.put_room_membership(RoomMembershipRecord("r2", "a1", created_at=at(1)))
        self.repository.put_room_membership(RoomMembershipRecord("r1", "a2", created_at=at(2)))

        self.assertIsNotNone(self.repository.get_room_membership("r1", "a1"))
        self.assertIsNone(self.repository.get_room_membership("r2", "a2"))

        memberships = self.repository.list_room_memberships_by_agent("a1")
        self.assertEqual(sorted(m.room_id for m in memberships), ["r1", "r2"])

    # -- feed events and notifications

    def test_feed_events_round_trip(self) -> None:
        self.repository.put_feed_event(
            FeedEventRecord(
                event_id="e1",
                event_type="post_created",
                actor_agent_id="a1",
                object_id="p1",
                target_agent_ids=("a2",),
                created_at=at(0),
            )
        )

        events = self.repository.list_feed_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "post_created")
        self.assertEqual(events[0].target_agent_ids, ("a2",))

    def test_notifications_by_recipient_use_the_gsi_newest_first(self) -> None:
        for index in range(3):
            self.repository.put_notification(
                NotificationRecord(
                    notification_id=f"n{index}",
                    recipient_agent_id="a1",
                    notification_type="mention",
                    created_at=at(index),
                )
            )
        self.repository.put_notification(
            NotificationRecord(
                notification_id="other",
                recipient_agent_id="a2",
                notification_type="mention",
                created_at=at(99),
            )
        )

        notifications = self.repository.list_notifications_by_recipient("a1")

        self.assertEqual([n.notification_id for n in notifications], ["n2", "n1", "n0"])

    # -- configuration

    def test_missing_feed_table_raises_a_clear_error(self) -> None:
        """A repository built without feed tables should say which one is missing.

        Feed tables are optional constructor arguments, so a deployment that
        forgets to wire one gets this error rather than an AttributeError.
        """
        repository = DynamoDbMessageHubRepository(**self._core)
        with self.assertRaises(Exception) as caught:
            repository.get_post("p1")
        self.assertIn("posts_table", str(caught.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
