"""The human proxy namespace.

gulls models message senders as agents, but a person chatting one of their own
agents is not an agent. A human proxy is that person's network identity: one per
owner, reused across chats so threads stay coherent and every message stays
attributable to the human who sent it.

``@me_`` is reserved for the same reason ``@guest_`` is, and the reason is a
security boundary rather than a naming convention: the handle is derived from an
owner id, so letting anyone register one would let them mint another person's
proxy and receive that person's chat replies.
"""

from __future__ import annotations

from unittest import TestCase

from message_hub.domain.service import (
    HUMAN_PROXY_AGENT_STATUS,
    HUMAN_PROXY_HANDLE_PREFIX,
    InvalidMessageError,
    MessageHubService,
)
from message_hub.storage.memory import InMemoryMessageHubRepository


class HumanProxyNamespaceTest(TestCase):
    def setUp(self) -> None:
        self.service = MessageHubService(InMemoryMessageHubRepository())

    def test_users_cannot_register_into_the_reserved_namespace(self) -> None:
        with self.assertRaises(InvalidMessageError) as caught:
            self.service.register_agent("@me_user_someoneelse:gulls.ai")

        self.assertIn("reserved", str(caught.exception))
        self.assertIn(HUMAN_PROXY_HANDLE_PREFIX, str(caught.exception))

    def test_the_reservation_does_not_leak_into_ordinary_handles(self) -> None:
        """`@member:` starts with the same letters but is not the prefix."""
        agent = self.service.register_agent("@member:gulls.ai")

        self.assertEqual("@member:gulls.ai", agent.handle)

    def test_the_server_can_mint_one(self) -> None:
        agent = self.service.ensure_human_proxy("@me_user_abc:gulls.ai", display_name="Alice")

        self.assertEqual("@me_user_abc:gulls.ai", agent.handle)
        self.assertEqual(HUMAN_PROXY_AGENT_STATUS, agent.status)
        self.assertEqual("Alice", agent.display_name)

    def test_minting_is_idempotent(self) -> None:
        """Reached on every chat creation, so a second call must not duplicate."""
        first = self.service.ensure_human_proxy("@me_user_abc:gulls.ai")
        second = self.service.ensure_human_proxy("@me_user_abc:gulls.ai")

        self.assertEqual(first.agent_id, second.agent_id)
        self.assertEqual(first.handle, second.handle)

    def test_it_refuses_handles_outside_the_reserved_namespace(self) -> None:
        """Otherwise it would be a back door around register_agent's checks."""
        with self.assertRaises(InvalidMessageError):
            self.service.ensure_human_proxy("@alice:gulls.ai")

    def test_a_proxy_can_send_into_an_agents_inbox(self) -> None:
        """The whole point: chat reaches the shared Inbox."""
        recipient = self.service.register_agent("@alice:gulls.ai")
        proxy = self.service.ensure_human_proxy("@me_user_abc:gulls.ai")

        result = self.service.send_message(
            sender_handle=proxy.handle,
            recipient_handles=[recipient.handle],
            intent="direct_message",
            visibility="direct",
            content="hello",
        )

        self.assertEqual(proxy.agent_id, result.message.sender_agent_id)
        inbox = self.service.get_inbox(recipient.handle)
        self.assertEqual(1, len(inbox))
        self.assertEqual("hello", inbox[0].message.content_inline)
