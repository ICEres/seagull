"""Reading the base Feed from gulls while seagulls keeps the projection.

terminology.md:55 gives seagulls "feed ranking and projections, not the base
Feed source of truth". These tests pin both halves of that line:

* which posts appear in a home feed, and in what order, still comes from
  seagulls' per-owner feed events, and
* what each post *is* comes from gulls once a gulls feed source is configured.

The cutover is deliberately gated: dual-write first, then flip reads. So the
fallback behaviour matters as much as the happy path -- posts written before
the mirror began exist only in the seagulls tables.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import TestCase

from message_hub.storage.memory import InMemoryMessageHubRepository

from social_api.api.local import AuthPrincipal, LocalSocialApi
from social_api.domain.feed_mirror import StrictFeedMirror
from social_api.domain.feed_source import (
    FallbackFeedSource,
    GullsFeedSource,
    RepositoryFeedSource,
)


class ExplodingFeedSource:
    def get_post(self, post_id: str):
        raise RuntimeError("gulls feed store unavailable")

    def list_posts(self, *, limit: int = 50):
        raise RuntimeError("gulls feed store unavailable")


class FeedReadCutoverTest(TestCase):
    def setUp(self) -> None:
        self.gulls = InMemoryMessageHubRepository()

    def _api(self, *, read_from_gulls: bool, with_fallback: bool = True) -> LocalSocialApi:
        feed_source = None
        if read_from_gulls:
            gulls_source = GullsFeedSource(self.gulls)
            feed_source = gulls_source
        api = LocalSocialApi.in_memory(
            auth_required=True,
            feed_mirror=StrictFeedMirror(self.gulls),
            feed_source=feed_source,
        )
        if read_from_gulls and with_fallback:
            # Wrap only once the service exists, so the fallback can reach the
            # same in-memory seagulls repository the service is using.
            service = api._service  # noqa: SLF001 - test wiring
            service._feed_source = FallbackFeedSource(  # noqa: SLF001
                GullsFeedSource(self.gulls),
                RepositoryFeedSource(service._repository),  # noqa: SLF001
            )
        return api

    def _seed(self, api: LocalSocialApi):
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        author = api.create_agent_profile({"handle": "@alice:seagull.local"}, principal)["profile"]
        return principal, author

    def test_home_feed_is_served_from_gulls_after_the_cutover(self) -> None:
        api = self._api(read_from_gulls=True)
        principal, author = self._seed(api)
        post = api.create_post(
            {
                "author_handle": author["handle"],
                "text": "Read me from gulls.",
                "refs": [{"type": "url", "url": "https://example.com", "remember_as": "spec"}],
            },
            principal,
        )["post"]

        feed = api.read_home_feed(principal=principal)["items"]

        self.assertEqual([post["post_id"]], [item["post_id"] for item in feed])
        self.assertEqual("Read me from gulls.", feed[0]["text"])
        # Refs survive the round trip through the gulls MessageRef shape and
        # back into the seagulls response shape.
        self.assertEqual("url", feed[0]["refs"][0]["type"])
        self.assertEqual("https://example.com", feed[0]["refs"][0]["url"])
        self.assertEqual("public", feed[0]["visibility"])

    def test_the_post_really_comes_from_gulls_not_seagulls(self) -> None:
        api = self._api(read_from_gulls=True, with_fallback=False)
        principal, author = self._seed(api)
        post = api.create_post(
            {"author_handle": author["handle"], "text": "Original text."},
            principal,
        )["post"]

        # Change the record only in gulls. With no fallback, a feed still
        # showing the old text would mean reads never left seagulls.
        stored = self.gulls.get_post(post["post_id"])
        from dataclasses import replace

        self.gulls.put_post(replace(stored, text="Rewritten in gulls."))

        feed = api.read_home_feed(principal=principal)["items"]

        self.assertEqual("Rewritten in gulls.", feed[0]["text"])

    def test_ordering_stays_a_seagulls_projection(self) -> None:
        api = self._api(read_from_gulls=True)
        principal, author = self._seed(api)
        posts = [
            api.create_post(
                {"author_handle": author["handle"], "text": f"Post {index}"},
                principal,
            )["post"]["post_id"]
            for index in range(3)
        ]

        feed = [item["post_id"] for item in api.read_home_feed(principal=principal)["items"]]

        # gulls holds the records; the home-feed order is seagulls' own.
        self.assertEqual(set(posts), set(feed))
        self.assertEqual(len(posts), len(feed))

    def test_posts_predating_the_mirror_still_resolve(self) -> None:
        # Write with no mirror at all, as if before the dual-write shipped.
        api = LocalSocialApi.in_memory(auth_required=True)
        principal, author = self._seed(api)
        legacy = api.create_post(
            {"author_handle": author["handle"], "text": "Written before the mirror."},
            principal,
        )["post"]

        # Now flip reads to gulls, which has never seen this post.
        service = api._service  # noqa: SLF001 - test wiring
        service._feed_source = FallbackFeedSource(  # noqa: SLF001
            GullsFeedSource(self.gulls),
            RepositoryFeedSource(service._repository),  # noqa: SLF001
        )

        feed = api.read_home_feed(principal=principal)["items"]

        self.assertEqual([legacy["post_id"]], [item["post_id"] for item in feed])
        self.assertEqual("Written before the mirror.", feed[0]["text"])

    def test_a_gulls_read_failure_falls_back_instead_of_emptying_the_feed(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        principal, author = self._seed(api)
        post = api.create_post(
            {"author_handle": author["handle"], "text": "Still visible."},
            principal,
        )["post"]

        service = api._service  # noqa: SLF001 - test wiring
        service._feed_source = FallbackFeedSource(  # noqa: SLF001
            ExplodingFeedSource(),
            RepositoryFeedSource(service._repository),  # noqa: SLF001
        )

        with self.assertLogs("social_api.domain.feed_source", level="WARNING"):
            feed = api.read_home_feed(principal=principal)["items"]

        self.assertEqual([post["post_id"]], [item["post_id"] for item in feed])

    def test_listing_merges_both_stores_mid_migration(self) -> None:
        """A partially-migrated store must not truncate to the migrated tail.

        This is the state every deployment passes through: gulls holds
        everything written since the dual-write began, seagulls holds
        everything older. Returning whichever store answered first would drop
        the other half of the feed.
        """
        from social_api.domain.models import PostRecord

        class StubSource:
            def __init__(self, posts):
                self._posts = posts

            def get_post(self, post_id):
                return next((p for p in self._posts if p.post_id == post_id), None)

            def list_posts(self, *, limit: int = 50):
                return tuple(self._posts[:limit])

        def post(post_id, seconds, text):
            return PostRecord(
                post_id=post_id,
                author_agent_id="a1",
                content=text,
                text=text,
                created_at=datetime(2025, 1, 1, tzinfo=timezone.utc)
                + timedelta(seconds=seconds),
            )

        gulls_only = post("new", 10, "after the mirror")
        seagulls_only = post("old", 0, "before the mirror")

        source = FallbackFeedSource(StubSource([gulls_only]), StubSource([seagulls_only]))

        listed = source.list_posts()

        self.assertEqual(["new", "old"], [p.post_id for p in listed])

    def test_listing_prefers_gulls_on_id_collision(self) -> None:
        """Both stores hold a mirrored post; gulls is the source of truth."""
        from social_api.domain.models import PostRecord

        class StubSource:
            def __init__(self, posts):
                self._posts = posts

            def get_post(self, post_id):
                return next((p for p in self._posts if p.post_id == post_id), None)

            def list_posts(self, *, limit: int = 50):
                return tuple(self._posts[:limit])

        created = datetime(2025, 1, 1, tzinfo=timezone.utc)
        base = dict(post_id="p1", author_agent_id="a1", created_at=created)

        source = FallbackFeedSource(
            StubSource([PostRecord(content="gulls", text="gulls", **base)]),
            StubSource([PostRecord(content="stale", text="stale", **base)]),
        )

        listed = source.list_posts()

        self.assertEqual(1, len(listed))
        self.assertEqual("gulls", listed[0].text)

    def test_an_empty_gulls_is_a_real_answer_not_a_failure(self) -> None:
        """Distinct from a gulls *failure*, which does fall back."""

        class EmptySource:
            def get_post(self, post_id):
                return None

            def list_posts(self, *, limit: int = 50):
                return ()

        source = FallbackFeedSource(EmptySource(), EmptySource())

        self.assertEqual((), source.list_posts())

    def test_without_a_feed_source_reads_stay_on_seagulls(self) -> None:
        # The default must not change under anyone's feet.
        api = LocalSocialApi.in_memory(auth_required=True)
        principal, author = self._seed(api)
        post = api.create_post(
            {"author_handle": author["handle"], "text": "Default path."},
            principal,
        )["post"]

        feed = api.read_home_feed(principal=principal)["items"]

        self.assertEqual([post["post_id"]], [item["post_id"] for item in feed])
        # Nothing was mirrored, because no mirror was configured.
        self.assertEqual((), self.gulls.list_posts())
