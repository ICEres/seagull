"""Backfilling the rows that predate the mirror.

The mirror only catches new writes, so everything older lives solely in the
seagulls tables. Until those rows cross over, ``FallbackFeedSource`` has to keep
reading both stores and the seagulls tables cannot be dropped -- which means
gulls is not yet the source of truth the concept docs assign it.

These tests pin the properties that make the backfill safe to trust: it copies
everything, it can be re-run, and it reports honestly when it did not finish.
"""

from __future__ import annotations

from unittest import TestCase

from message_hub.storage.memory import InMemoryMessageHubRepository

from social_api.api.local import AuthPrincipal, LocalSocialApi
from social_api.domain.feed_backfill import (
    InMemoryBackfillSource,
    backfill_feed,
)
from social_api.domain.feed_mirror import StrictFeedMirror
from social_api.domain.feed_source import (
    FallbackFeedSource,
    GullsFeedSource,
    RepositoryFeedSource,
)


class FeedBackfillTest(TestCase):
    def setUp(self) -> None:
        # An API with no mirror at all: exactly the pre-dual-write world.
        self.api = LocalSocialApi.in_memory(auth_required=True)
        self.principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        self.author = self.api.create_agent_profile(
            {"handle": "@alice:seagull.local", "display_name": "Alice"},
            self.principal,
        )["profile"]
        self.gulls = InMemoryMessageHubRepository()

    def _repository(self):
        return self.api._service._repository  # noqa: SLF001 - test wiring

    def _run(self, *, dry_run: bool = False):
        return backfill_feed(
            InMemoryBackfillSource(self._repository()),
            StrictFeedMirror(self.gulls),
            dry_run=dry_run,
        )

    def _post(self, text: str):
        return self.api.create_post(
            {"author_handle": self.author["handle"], "text": text},
            self.principal,
        )["post"]

    def test_posts_written_before_the_mirror_cross_over(self) -> None:
        self._post("Written before the mirror.")
        self.assertEqual((), self.gulls.list_posts())

        report = self._run()

        self.assertEqual(1, report.copied["posts"])
        self.assertTrue(report.complete)
        self.assertEqual(1, len(self.gulls.list_posts()))
        self.assertEqual("Written before the mirror.", self.gulls.list_posts()[0].text)

    def test_dry_run_counts_without_writing(self) -> None:
        self._post("Nothing should move.")

        report = self._run(dry_run=True)

        self.assertTrue(report.dry_run)
        self.assertEqual(1, report.copied["posts"])
        self.assertEqual((), self.gulls.list_posts())

    def test_rerunning_is_idempotent(self) -> None:
        self._post("Only once.")

        first = self._run()
        second = self._run()

        # Both runs report the same row, but the store holds it once.
        self.assertEqual(first.copied["posts"], second.copied["posts"])
        self.assertEqual(1, len(self.gulls.list_posts()))

    def test_follows_and_rooms_cross_over_too(self) -> None:
        other = self.api.create_agent_profile(
            {"handle": "@bob:seagull.local"}, self.principal
        )["profile"]
        self.api.follow_agent(
            {"follower_handle": self.author["handle"], "followed_handle": other["handle"]},
            self.principal,
        )
        self.api.create_room({"slug": "weather", "name": "Weather"}, self.principal)
        self.api.join_room("weather", {"agent_handle": self.author["handle"]}, self.principal)

        report = self._run()

        self.assertEqual(1, report.copied["follows"])
        self.assertEqual(1, report.copied["rooms"])
        self.assertEqual(1, report.copied["room_memberships"])
        self.assertTrue(report.complete)

        self.assertEqual(1, len(self.gulls.list_follows_by_follower(self.author["agent_id"])))
        self.assertIsNotNone(self.gulls.get_room_by_slug("weather"))

    def test_a_failing_write_is_reported_not_swallowed(self) -> None:
        """A migration must not report success it did not achieve.

        BestEffortFeedMirror swallowing is right for a live request; here it
        would hide an incomplete copy and invite dropping the seagulls tables
        on false evidence. So the backfill counts failures and says so.
        """
        self._post("Will not make it.")

        class ExplodingMirror:
            def mirror_post(self, post):
                raise RuntimeError("gulls unavailable")

            def mirror_follow(self, follow):
                return None

            def mirror_room(self, room):
                return None

            def mirror_room_membership(self, membership):
                return None

            def mirror_feed_event(self, event):
                return None

            def mirror_notification(self, notification):
                return None

        with self.assertLogs("social_api.domain.feed_backfill", level="WARNING"):
            report = backfill_feed(
                InMemoryBackfillSource(self._repository()), ExplodingMirror()
            )

        self.assertFalse(report.complete)
        self.assertEqual(1, report.failures["posts"])
        self.assertEqual(0, report.copied["posts"])
        self.assertIn("FAILURES", report.summary())

    def test_after_backfill_gulls_alone_serves_the_feed(self) -> None:
        """The point of the exercise: fallback becomes unnecessary.

        Reading with no seagulls fallback at all is what proves the migration
        actually finished. While any row is still missing, this is the test
        that fails -- not a production feed after the tables are dropped.
        """
        self._post("Historic post.")
        self._run()

        service = self.api._service  # noqa: SLF001 - test wiring
        service._feed_source = GullsFeedSource(self.gulls)  # noqa: SLF001

        feed = self.api.read_home_feed(principal=self.principal)["items"]

        self.assertEqual(["Historic post."], [item["text"] for item in feed])

    def test_backfill_plus_mirror_agree_on_shape(self) -> None:
        """Backfilled and live-mirrored rows must be indistinguishable.

        They share one translation by construction; this asserts the property
        that sharing exists to guarantee.
        """
        historic = self._post("Before.")
        self._run()

        mirrored_api = LocalSocialApi.in_memory(
            auth_required=True, feed_mirror=StrictFeedMirror(self.gulls)
        )
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        author = mirrored_api.create_agent_profile(
            {"handle": "@alice:seagull.local", "display_name": "Alice"}, principal
        )["profile"]
        live = mirrored_api.create_post(
            {"author_handle": author["handle"], "text": "After."}, principal
        )["post"]

        backfilled_record = self.gulls.get_post(historic["post_id"])
        mirrored_record = self.gulls.get_post(live["post_id"])

        self.assertEqual(type(backfilled_record), type(mirrored_record))
        self.assertEqual(
            {f for f in backfilled_record.__slots__},
            {f for f in mirrored_record.__slots__},
        )
        self.assertEqual(backfilled_record.visibility, mirrored_record.visibility)

    def test_per_owner_fan_out_is_not_backfilled(self) -> None:
        """The backfill must select exactly what the live mirror selects.

        seagulls fans a post out into one feed-event row per follower, next to
        the single base event. Those copies are a projection the mirror does
        not carry (see test_feed_dual_write.py), so a backfill that enumerated
        them would leave gulls holding duplicates of every post.
        """
        other = self.api.create_agent_profile(
            {"handle": "@bob:seagull.local"}, self.principal
        )["profile"]
        self.api.follow_agent(
            {"follower_handle": other["handle"], "followed_handle": self.author["handle"]},
            self.principal,
        )
        self._post("One post.")

        report = self._run()

        self.assertEqual(1, report.copied["feed_events"])
        self.assertTrue(report.complete)
        self.assertEqual(1, len(self.gulls.list_feed_events()))

    def test_summary_reports_every_kind_even_at_zero(self) -> None:
        """Zeros are the evidence a kind was enumerated rather than skipped."""
        report = self._run()

        self.assertTrue(report.complete)
        self.assertEqual(0, report.total_copied)

        summary = report.summary()
        for kind in ("posts", "follows", "rooms", "room_memberships", "feed_events", "notifications"):
            self.assertIn(f"{kind}=0", summary)
        self.assertNotIn("FAILURES", summary)
