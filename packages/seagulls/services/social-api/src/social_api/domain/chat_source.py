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
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from social_api.domain.models import AgentChatMessage


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HubChatReply:
    message_id: str
    content: str
    created_at: datetime


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

    def __init__(self, repository, *, read_content: bool = True) -> None:
        self._repository = repository
        self._read_content = read_content

    def content_for(self, hub_message_id: str) -> str | None:
        if not self._read_content:
            return None
        message = self._repository.get_message(hub_message_id)
        if message is None:
            return None
        return message.content_inline

    def replies_for(self, thread_id: str, agent_handle: str, human_handle: str) -> tuple[HubChatReply, ...]:
        agent = self._repository.get_agent_by_handle(agent_handle)
        human = self._repository.get_agent_by_handle(human_handle)
        if agent is None or human is None:
            return ()
        messages = self._repository.list_thread_messages(thread_id, limit=1000)
        return tuple(
            HubChatReply(message.message_id, message.content_inline, message.created_at)
            for message in messages
            if message.thread_id == thread_id
            and message.runtime_mode == "local"
            and message.sender_agent_id == agent.agent_id
            and set(message.recipient_agent_ids) == {human.agent_id}
            and message.content_inline
        )


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

    def replies_for(self, thread_id: str, agent_handle: str, human_handle: str) -> tuple[HubChatReply, ...]:
        try:
            return self._source.replies_for(thread_id, agent_handle, human_handle)
        except Exception:
            LOGGER.warning("gulls local reply read failed for %s", thread_id, exc_info=True)
            return ()


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
