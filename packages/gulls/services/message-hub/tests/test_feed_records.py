"""Feed is a gulls network capability, so its records live here.

Covers the base Feed source of truth the concept docs assign to gulls:
durable one-to-many publishing and subscription. seagulls keeps ranking and
projections on top of these records, not a second copy of the truth
(packages/gulls/docs/terminology.md).

The DynamoDB item codecs are pure functions, so their round-trips run without
boto3 or moto -- only the repository query paths need emulated AWS.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import TestCase

from seagull_protocol.base import MessageIntent, MessageRef, Visibility

from message_hub.domain.models import (
    FeedEventRecord,
    FollowRecord,
    NotificationRecord,
    PostRecord,
    RoomMembershipRecord,
    RoomRecord,
    normalize_visibility,
)
from message_hub.storage.dynamodb import (
    feed_event_to_item,
    follow_to_item,
    item_to_feed_event,
    item_to_follow,
    item_to_notification,
    item_to_post,
    item_to_room,
    item_to_room_membership,
    notification_to_item,
    post_to_item,
    room_membership_to_item,
    room_to_item,
)
from message_hub.storage.memory import InMemoryMessageHubRepository


BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def at(offset_seconds: int) -> datetime:
    return BASE + timedelta(seconds=offset_seconds)


class FeedModelTest(TestCase):
    def test_post_intent_uses_the_protocol_vocabulary(self) -> None:
        plain = PostRecord(post_id="p1", author_agent_id="a1", content="c", text="c")
        reply = PostRecord(
            post_id="p2", author_agent_id="a1", content="c", text="c", reply_to_post_id="p1"
        )
        mention = PostRecord(
            post_id="p3",
            author_agent_id="a1",
            content="c",
            text="c",
            mention_agent_ids=("a2",),
        )
        # A reply that also mentions someone is still a reply.
        reply_with_mention = PostRecord(
            post_id="p4",
            author_agent_id="a1",
            content="c",
            text="c",
            reply_to_post_id="p1",
            mention_agent_ids=("a2",),
        )

        self.assertEqual(MessageIntent.POST, plain.intent)
        self.assertEqual(MessageIntent.REPLY, reply.intent)
        self.assertEqual(MessageIntent.MENTION, mention.intent)
        self.assertEqual(MessageIntent.REPLY, reply_with_mention.intent)
        self.assertEqual(MessageIntent.FOLLOW, FollowRecord("a1", "a2").intent)

    def test_visibility_normalizes_but_tolerates_unknown_values(self) -> None:
        self.assertEqual(Visibility.PUBLIC, normalize_visibility("public"))
        self.assertEqual(Visibility.PUBLIC, normalize_visibility("  PUBLIC "))
        self.assertEqual(Visibility.DIRECT, normalize_visibility(Visibility.DIRECT))
        # seagulls never constrained this field, so an unrecognized stored value
        # must survive the migration rather than fail the write.
        self.assertEqual("followers-only", normalize_visibility("followers-only"))

        post = PostRecord(
            post_id="p1", author_agent_id="a1", content="c", text="c", visibility="LIMITED"
        )
        self.assertEqual(Visibility.LIMITED, post.visibility)

    def test_feed_event_type_maps_onto_message_intent(self) -> None:
        self.assertEqual(
            MessageIntent.FOLLOW,
            FeedEventRecord(event_id="e1", event_type="follow").intent,
        )
        # Unknown event types pass through as plain strings.
        self.assertEqual(
            "room_created",
            FeedEventRecord(event_id="e2", event_type="room_created").intent,
        )


class FeedMemoryRepositoryTest(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMessageHubRepository()

    def test_posts_round_trip_and_list_newest_first(self) -> None:
        for index in range(3):
            self.repository.put_post(
                PostRecord(
                    post_id=f"post_{index}",
                    author_agent_id="agent_1" if index < 2 else "agent_2",
                    content=f"c{index}",
                    text=f"t{index}",
                    created_at=at(index),
                )
            )

        self.assertEqual("t1", self.repository.get_post("post_1").text)
        self.assertEqual(
            ["post_2", "post_1", "post_0"],
            [post.post_id for post in self.repository.list_posts()],
        )
        self.assertEqual(
            ["post_1", "post_0"],
            [post.post_id for post in self.repository.list_posts_by_author("agent_1")],
        )
        self.assertEqual(
            ["post_2"],
            [post.post_id for post in self.repository.list_posts(limit=1)],
        )
        self.assertIsNone(self.repository.get_post("missing"))

    def test_reput_of_the_same_post_does_not_duplicate_the_author_index(self) -> None:
        post = PostRecord(post_id="post_1", author_agent_id="agent_1", content="c", text="t")
        self.repository.put_post(post)
        self.repository.put_post(post)

        self.assertEqual(1, len(self.repository.list_posts_by_author("agent_1")))

    def test_follow_edges_are_queryable_from_both_directions(self) -> None:
        self.repository.put_follow(FollowRecord("agent_1", "agent_2", created_at=at(0)))
        self.repository.put_follow(FollowRecord("agent_1", "agent_3", created_at=at(1)))
        self.repository.put_follow(FollowRecord("agent_3", "agent_2", created_at=at(2)))

        self.assertIsNotNone(self.repository.get_follow("agent_1", "agent_2"))
        self.assertIsNone(self.repository.get_follow("agent_2", "agent_1"))
        self.assertEqual(
            ["agent_2", "agent_3"],
            [f.followed_agent_id for f in self.repository.list_follows_by_follower("agent_1")],
        )
        self.assertEqual(
            ["agent_1", "agent_3"],
            [f.follower_agent_id for f in self.repository.list_follows_by_followed("agent_2")],
        )

    def test_rooms_are_addressable_by_id_and_slug(self) -> None:
        self.repository.put_room(RoomRecord(room_id="room_1", slug="general", name="General"))
        self.repository.put_room_membership(RoomMembershipRecord("room_1", "agent_1"))

        self.assertEqual("General", self.repository.get_room("room_1").name)
        self.assertEqual("room_1", self.repository.get_room_by_slug("general").room_id)
        self.assertIsNone(self.repository.get_room_by_slug("missing"))
        self.assertEqual("member", self.repository.get_room_membership("room_1", "agent_1").role)
        self.assertEqual(
            ["room_1"],
            [m.room_id for m in self.repository.list_room_memberships_by_agent("agent_1")],
        )
        self.assertEqual((), self.repository.list_room_memberships_by_agent("agent_2"))

    def test_feed_events_and_notifications_list_newest_first(self) -> None:
        for index in range(3):
            self.repository.put_feed_event(
                FeedEventRecord(event_id=f"event_{index}", event_type="post", created_at=at(index))
            )
            self.repository.put_notification(
                NotificationRecord(
                    notification_id=f"note_{index}",
                    recipient_agent_id="agent_1" if index < 2 else "agent_2",
                    notification_type="mention",
                    created_at=at(index),
                )
            )

        self.assertEqual(
            ["event_2", "event_1", "event_0"],
            [event.event_id for event in self.repository.list_feed_events()],
        )
        self.assertEqual(
            ["note_1", "note_0"],
            [
                note.notification_id
                for note in self.repository.list_notifications_by_recipient("agent_1")
            ],
        )


class FeedItemCodecTest(TestCase):
    """Round-trips for the stored DynamoDB shapes (no boto3 needed)."""

    def test_post_round_trip_preserves_refs_and_mentions(self) -> None:
        post = PostRecord(
            post_id="post_1",
            author_agent_id="agent_1",
            content="Look at this",
            text="Look at this",
            refs=(MessageRef(type="url", url="https://example.com", remember_as="spec"),),
            visibility=Visibility.LIMITED,
            room_id="room_1",
            reply_to_post_id="post_0",
            mention_agent_ids=("agent_2", "agent_3"),
            created_at=at(0),
        )

        item = post_to_item(post)
        # Enum fields must store their value, not "Visibility.LIMITED".
        self.assertEqual("limited", item["visibility"])

        self.assertEqual(post, item_to_post(item))

    def test_post_round_trip_tolerates_an_unknown_visibility(self) -> None:
        post = PostRecord(
            post_id="post_1",
            author_agent_id="agent_1",
            content="c",
            text="t",
            visibility="followers-only",
            created_at=at(0),
        )

        self.assertEqual("followers-only", post_to_item(post)["visibility"])
        self.assertEqual(post, item_to_post(post_to_item(post)))

    def test_follow_room_and_membership_round_trip(self) -> None:
        follow = FollowRecord("agent_1", "agent_2", created_at=at(0))
        room = RoomRecord(
            room_id="room_1",
            slug="general",
            name="General",
            description="Everything",
            created_by_user_id="user_1",
            created_at=at(0),
            updated_at=at(5),
        )
        membership = RoomMembershipRecord("room_1", "agent_1", role="owner", created_at=at(0))

        self.assertEqual(follow, item_to_follow(follow_to_item(follow)))
        self.assertEqual(room, item_to_room(room_to_item(room)))
        self.assertEqual(membership, item_to_room_membership(room_membership_to_item(membership)))

    def test_room_without_updated_at_falls_back_to_created_at(self) -> None:
        item = room_to_item(RoomRecord(room_id="room_1", slug="s", name="n", created_at=at(0)))
        del item["updated_at"]

        self.assertEqual(at(0), item_to_room(item).updated_at)

    def test_feed_event_and_notification_round_trip(self) -> None:
        event = FeedEventRecord(
            event_id="event_1",
            event_type="mention",
            actor_agent_id="agent_1",
            object_id="post_1",
            target_agent_ids=("agent_2",),
            room_id="room_1",
            created_at=at(0),
        )
        read = NotificationRecord(
            notification_id="note_1",
            recipient_agent_id="agent_2",
            notification_type="mention",
            owner_user_id="user_1",
            actor_agent_id="agent_1",
            post_id="post_1",
            read_at=at(9),
            created_at=at(0),
        )
        unread = NotificationRecord(
            notification_id="note_2",
            recipient_agent_id="agent_2",
            notification_type="mention",
            created_at=at(0),
        )

        self.assertEqual(event, item_to_feed_event(feed_event_to_item(event)))
        self.assertEqual(read, item_to_notification(notification_to_item(read)))
        # An unread notification stores no read_at at all rather than a null.
        self.assertNotIn("read_at", notification_to_item(unread))
        self.assertEqual(unread, item_to_notification(notification_to_item(unread)))
