"""Where chat message content is read from.

The same split the Feed cutover draws (terminology.md:55), applied to chat:

* Which messages belong to a chat, in what order, and their AI audit state --
  a *projection* -- stays with seagulls.
* What a message actually *says* comes from the gulls Inbox once configured.

Chat cannot use the Feed's approach of moving whole records across, because
identity does not survive the trip. The Feed mirror controls the record and
passes ``post_id`` through unchanged; chat is mirrored via ``send_message``,
which mints its own ``message_id``. Rebuilding ``AgentChatMessage`` from hub
records alone would therefore change every ``chat_message_id`` the UI holds,
and would lose ``ai_run_id``, ``ai_run_state`` and ``delivery_status``, which
have no hub equivalent.

So the seagulls record stays the index and carries ``hub_message_id``; this
module swaps in the gulls content for it. That makes gulls authoritative for
what was said while leaving the chat projection where it belongs -- and it is
honest about the limit: it does not by itself make gulls the whole source of
truth for chat.
"""

from __future__ import annotations

import logging
from typing import Protocol, Sequence

from social_api.domain.models import AgentChatMessage


LOGGER = logging.getLogger(__name__)


class ChatSource(Protocol):
    """Read port for base Inbox message content."""

    def content_for(self, hub_message_id: str) -> str | None:
        ...


class NullChatSource:
    """Pre-cutover default: the seagulls record already holds the content."""

    def content_for(self, hub_message_id: str) -> str | None:
        return None


class GullsChatSource:
    """Read message content from the gulls Inbox.

    Returns None when the hub has no such message, which the caller treats as
    "keep the seagulls copy" -- the same miss-means-fall-back rule the Feed
    cutover uses for a single record.
    """

    def __init__(self, repository) -> None:
        self._repository = repository

    def content_for(self, hub_message_id: str) -> str | None:
        message = self._repository.get_message(hub_message_id)
        if message is None:
            return None
        return message.content_inline


class SafeChatSource:
    """Degrade to the seagulls copy instead of failing a chat read.

    A gulls-side problem should cost freshness, not the conversation. Mirrors
    ``FallbackFeedSource``'s posture for the same reason.
    """

    def __init__(self, source: ChatSource) -> None:
        self._source = source

    def content_for(self, hub_message_id: str) -> str | None:
        try:
            return self._source.content_for(hub_message_id)
        except Exception:
            LOGGER.warning("gulls chat read failed for %s", hub_message_id, exc_info=True)
            return None


def apply_chat_source(
    messages: Sequence[AgentChatMessage],
    source: ChatSource,
) -> tuple[AgentChatMessage, ...]:
    """Substitute gulls content into a seagulls-indexed message list.

    Messages with no ``hub_message_id`` predate the mirror and are returned
    untouched, so a chat that started before the dual-write still reads
    correctly rather than coming back blank.
    """
    from dataclasses import replace

    resolved = []
    for message in messages:
        if not message.hub_message_id:
            resolved.append(message)
            continue
        content = source.content_for(message.hub_message_id)
        resolved.append(message if content is None else replace(message, content=content))
    return tuple(resolved)


__all__ = [
    "ChatSource",
    "GullsChatSource",
    "NullChatSource",
    "SafeChatSource",
    "apply_chat_source",
]
