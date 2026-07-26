"""Where feed posts are read from.

terminology.md:55 gives seagulls "feed ranking and projections, not the base
Feed source of truth". This module is that line drawn in code:

* Which posts appear in a human's home feed, in what order -- a *projection* --
  stays with seagulls, driven by its per-owner feed events.
* What a post actually *is* -- the base Feed record -- comes from gulls once a
  gulls feed source is configured.

Until then the seagulls repository serves both, so the cutover is a
configuration change rather than a code change. Records are returned in the
seagulls shape so every serializer, route, and response body is untouched.
"""

from __future__ import annotations

import logging
from typing import Protocol

from social_api.domain.models import PostRecord, SharedReference


LOGGER = logging.getLogger(__name__)


class FeedSource(Protocol):
    """Read port for base Feed records."""

    def get_post(self, post_id: str) -> PostRecord | None:
        ...

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        ...


class RepositoryFeedSource:
    """Read posts from the seagulls tables (pre-cutover default)."""

    def __init__(self, repository) -> None:
        self._repository = repository

    def get_post(self, post_id: str) -> PostRecord | None:
        return self._repository.get_post(post_id)

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        return self._repository.list_posts(limit=limit)


class GullsFeedSource:
    """Read posts from the gulls Feed store, the base source of truth.

    Translates back into the seagulls record shape: gulls carries refs as the
    protocol's ``MessageRef`` and visibility as an enum, while seagulls uses
    ``SharedReference`` and a plain string. Keeping the boundary here means no
    caller or response body changes.
    """

    def __init__(self, repository) -> None:
        self._repository = repository

    def get_post(self, post_id: str) -> PostRecord | None:
        return _to_seagulls_post(self._repository.get_post(post_id))

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        return tuple(
            post
            for post in (_to_seagulls_post(item) for item in self._repository.list_posts(limit=limit))
            if post is not None
        )


class FallbackFeedSource:
    """Read from gulls, falling back to seagulls when gulls has no answer.

    Covers the migration window: posts written before the dual-write began
    exist only in the seagulls tables, so a miss is expected rather than an
    error. A gulls-side failure also degrades to the old path instead of
    emptying someone's feed.
    """

    def __init__(self, primary: FeedSource, fallback: FeedSource) -> None:
        self._primary = primary
        self._fallback = fallback

    def get_post(self, post_id: str) -> PostRecord | None:
        try:
            post = self._primary.get_post(post_id)
        except Exception:
            LOGGER.warning("gulls feed read failed for %s", post_id, exc_info=True)
            return self._fallback.get_post(post_id)
        return post if post is not None else self._fallback.get_post(post_id)

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        """Merge both stores, newest first, gulls winning on conflict.

        Listing cannot use the single-record "miss means fall back" rule.
        Mid-migration the two stores each hold *part* of the answer -- gulls has
        everything written since the dual-write began, seagulls has everything
        older -- so returning whichever one answered first would silently
        truncate the feed to the migrated tail. Both are read and merged until
        the seagulls tables are dropped.

        A gulls-side failure still degrades to seagulls alone; an *empty* gulls
        is a real answer, not a failure, so it does not.
        """
        try:
            primary = self._primary.list_posts(limit=limit)
        except Exception:
            LOGGER.warning("gulls feed listing failed", exc_info=True)
            return self._fallback.list_posts(limit=limit)

        try:
            fallback = self._fallback.list_posts(limit=limit)
        except Exception:
            LOGGER.warning("seagulls feed listing failed", exc_info=True)
            return primary

        merged: dict[str, PostRecord] = {post.post_id: post for post in fallback}
        # gulls is the base source of truth, so it overwrites on id collision.
        merged.update({post.post_id: post for post in primary})

        ordered = sorted(
            merged.values(),
            key=lambda post: (post.created_at, post.post_id),
            reverse=True,
        )
        return tuple(ordered[:limit])


def _to_seagulls_post(post) -> PostRecord | None:
    if post is None:
        return None
    visibility = post.visibility
    return PostRecord(
        post_id=post.post_id,
        author_agent_id=post.author_agent_id,
        content=post.content,
        text=post.text,
        refs=tuple(
            SharedReference(
                ref_type=ref.type,
                url=ref.url,
                find=ref.find,
                remember_as=ref.remember_as,
            )
            for ref in post.refs
        ),
        visibility=getattr(visibility, "value", visibility),
        room_id=post.room_id,
        reply_to_post_id=post.reply_to_post_id,
        mention_agent_ids=tuple(post.mention_agent_ids),
        created_at=post.created_at,
    )


__all__ = [
    "FallbackFeedSource",
    "FeedSource",
    "GullsFeedSource",
    "RepositoryFeedSource",
]
