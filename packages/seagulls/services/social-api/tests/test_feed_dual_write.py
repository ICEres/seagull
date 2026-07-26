"""Dual-write parity: every seagulls feed write reaches the gulls Feed store.

Feed is a gulls network capability; seagulls owns ranking and projections, not
the base Feed source of truth (packages/gulls/docs/terminology.md). During the
migration seagulls stays authoritative for reads while mirroring writes into
gulls, so this asserts the two stores agree before reads move over.

Uses the real InMemoryMessageHubRepository rather than a stub, so a mapping bug
between the two record shapes fails here instead of in production.
"""

from __future__ import annotations

from unittest import TestCase

from message_hub.storage.memory import InMemoryMessageHubRepository
from seagull_protocol.base import MessageIntent, Visibility

from social_api.api.local import AuthPrincipal, LocalSocialApi
from social_api.domain.feed_mirror import BestEffortFeedMirror, StrictFeedMirror


class FeedDualWriteTest(TestCase):
    def setUp(self) -> None:
        self.gulls = InMemoryMessageHubRepository()
        self.api = LocalSocialApi.in_memory(
            auth_required=True,
            feed_mirror=StrictFeedMirror(self.gulls),
        )
        self.principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        self.author = self.api.create_agent_profile(
            {"handle": "@alice:seagull.local", "display_name": "Alice"},
            self.principal,
        )["profile"]
        self.other = self.api.create_agent_profile(
            {"handle": "@bob:seagull.local"},
            self.principal,
        )["profile"]

    def test_post_reaches_gulls_with_the_same_content(self) -> None:
        post = self.api.create_post(
            {
                "author_handle": self.author["handle"],
                "text": "Shipping the Feed migration.",
                "refs": [{"type": "url", "url": "https://example.com", "remember_as": "spec"}],
            },
            self.principal,
        )["post"]

        mirrored = self.gulls.get_post(post["post_id"])

        self.assertIsNotNone(mirrored, "post did not reach the gulls Feed store")
        self.assertEqual(post["post_id"], mirrored.post_id)
        self.assertEqual(self.author["agent_id"], mirrored.author_agent_id)
        self.assertEqual("Shipping the Feed migration.", mirrored.text)
        self.assertEqual(Visibility.PUBLIC, mirrored.visibility)
        self.assertEqual(MessageIntent.POST, mirrored.intent)
        # seagulls names the discriminator ref_type; gulls uses MessageRef.type.
        self.assertEqual(("url",), tuple(ref.type for ref in mirrored.refs))
        self.assertEqual("https://example.com", mirrored.refs[0].url)
        self.assertEqual("spec", mirrored.refs[0].remember_as)

    def test_reply_and_mention_carry_their_protocol_intent(self) -> None:
        root = self.api.create_post(
            {"author_handle": self.author["handle"], "text": "Root post."},
            self.principal,
        )["post"]
        reply = self.api.create_post(
            {
                "author_handle": self.author["handle"],
                "text": "A reply.",
                "reply_to_post_id": root["post_id"],
            },
            self.principal,
        )["post"]
        mention = self.api.create_post(
            {"author_handle": self.author["handle"], "text": "ping @bob:seagull.local"},
            self.principal,
        )["post"]

        self.assertEqual(MessageIntent.REPLY, self.gulls.get_post(reply["post_id"]).intent)
        mirrored_mention = self.gulls.get_post(mention["post_id"])
        self.assertEqual(MessageIntent.MENTION, mirrored_mention.intent)
        self.assertEqual((self.other["agent_id"],), mirrored_mention.mention_agent_ids)

    def test_follow_reaches_gulls_and_is_queryable_both_ways(self) -> None:
        self.api.follow_agent(
            {"follower_handle": self.author["handle"], "followed_handle": self.other["handle"]},
            self.principal,
        )

        mirrored = self.gulls.get_follow(self.author["agent_id"], self.other["agent_id"])

        self.assertIsNotNone(mirrored)
        self.assertEqual(MessageIntent.FOLLOW, mirrored.intent)
        self.assertEqual(
            [self.other["agent_id"]],
            [f.followed_agent_id for f in self.gulls.list_follows_by_follower(self.author["agent_id"])],
        )
        self.assertEqual(
            [self.author["agent_id"]],
            [f.follower_agent_id for f in self.gulls.list_follows_by_followed(self.other["agent_id"])],
        )

    def test_room_and_membership_reach_gulls(self) -> None:
        room = self.api.create_room(
            {"slug": "general", "name": "General", "description": "Everything"},
            self.principal,
        )["room"]
        self.api.join_room("general", {"agent_handle": self.author["handle"]}, self.principal)

        mirrored_room = self.gulls.get_room(room["room_id"])
        mirrored_membership = self.gulls.get_room_membership(
            room["room_id"], self.author["agent_id"]
        )

        self.assertEqual("general", mirrored_room.slug)
        self.assertEqual("General", mirrored_room.name)
        self.assertEqual(room["room_id"], self.gulls.get_room_by_slug("general").room_id)
        self.assertIsNotNone(mirrored_membership)
        self.assertEqual("member", mirrored_membership.role)

    def test_feed_event_and_mention_notification_reach_gulls(self) -> None:
        post = self.api.create_post(
            {"author_handle": self.author["handle"], "text": "ping @bob:seagull.local"},
            self.principal,
        )["post"]

        events = self.gulls.list_feed_events()
        notifications = self.gulls.list_notifications_by_recipient(self.other["agent_id"])

        self.assertEqual(["post"], [event.event_type for event in events])
        self.assertEqual(post["post_id"], events[0].object_id)
        self.assertEqual(self.author["agent_id"], events[0].actor_agent_id)

        self.assertEqual(1, len(notifications))
        self.assertEqual("mention", notifications[0].notification_type)
        self.assertEqual(post["post_id"], notifications[0].post_id)
        self.assertEqual(self.author["agent_id"], notifications[0].actor_agent_id)

    def test_per_owner_fan_out_stays_a_seagulls_projection(self) -> None:
        # gulls holds one base feed event per post. The per-owner copies
        # seagulls fans out for its home feed are ranking/projection work and
        # must not be mirrored, or gulls would accumulate duplicates.
        self.api.follow_agent(
            {"follower_handle": self.other["handle"], "followed_handle": self.author["handle"]},
            self.principal,
        )
        self.api.create_post(
            {"author_handle": self.author["handle"], "text": "One post."},
            self.principal,
        )

        self.assertEqual(1, len(self.gulls.list_feed_events()))
        # seagulls still serves its own home feed from its own tables.
        self.assertEqual(1, len(self.api.read_home_feed(principal=self.principal)["items"]))

    def test_seagulls_reads_stay_authoritative_and_consistent(self) -> None:
        post = self.api.create_post(
            {"author_handle": self.author["handle"], "text": "Both stores."},
            self.principal,
        )["post"]

        seagulls_feed = self.api.read_home_feed(principal=self.principal)["items"]

        self.assertEqual([post["post_id"]], [item["post_id"] for item in seagulls_feed])
        self.assertEqual(
            [post["post_id"]],
            [mirrored.post_id for mirrored in self.gulls.list_posts()],
        )


class FeedMirrorFailureTest(TestCase):
    """A gulls-side problem must never cost a human their post."""

    class ExplodingRepository:
        def put_post(self, post: object) -> None:
            raise RuntimeError("gulls feed store unavailable")

        def put_follow(self, follow: object) -> None:
            raise RuntimeError("gulls feed store unavailable")

        def put_room(self, room: object) -> None:
            raise RuntimeError("gulls feed store unavailable")

        def put_room_membership(self, membership: object) -> None:
            raise RuntimeError("gulls feed store unavailable")

        def put_feed_event(self, event: object) -> None:
            raise RuntimeError("gulls feed store unavailable")

        def put_notification(self, notification: object) -> None:
            raise RuntimeError("gulls feed store unavailable")

    def test_post_still_succeeds_when_the_mirror_fails(self) -> None:
        api = LocalSocialApi.in_memory(
            auth_required=True,
            feed_mirror=BestEffortFeedMirror(StrictFeedMirror(self.ExplodingRepository())),
        )
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        author = api.create_agent_profile({"handle": "@alice:seagull.local"}, principal)["profile"]

        with self.assertLogs("social_api.domain.feed_mirror", level="WARNING") as logs:
            post = api.create_post(
                {"author_handle": author["handle"], "text": "Survives a broken mirror."},
                principal,
            )["post"]

        self.assertEqual(
            [post["post_id"]],
            [item["post_id"] for item in api.read_home_feed(principal=principal)["items"]],
        )
        self.assertTrue(any("gulls feed mirror failed" in line for line in logs.output))

    def test_without_a_mirror_configured_nothing_changes(self) -> None:
        # The default NullFeedMirror keeps single-store deployments working.
        api = LocalSocialApi.in_memory(auth_required=True)
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        author = api.create_agent_profile({"handle": "@alice:seagull.local"}, principal)["profile"]

        post = api.create_post(
            {"author_handle": author["handle"], "text": "No mirror."}, principal
        )["post"]

        self.assertEqual(
            [post["post_id"]],
            [item["post_id"] for item in api.read_home_feed(principal=principal)["items"]],
        )
