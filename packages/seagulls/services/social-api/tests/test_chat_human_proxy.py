"""Chat reaching the shared gulls Inbox.

The concept docs put chat on the shared Inbox capability and say Pet "does not
create another chat transport". The code had a mirror for that -- but it never
ran: ``sender_handle`` was an optional parameter, ``_deliver_agent_chat_message``
returned early when it was None, and the web never passed one. So every chat
was seagulls-only and ``hub_thread_id`` was always null, with a green test
suite because the tests that exercised the mirror supplied a sender the product
never supplies.

gulls models senders as agents, so the missing piece was a network identity for
the human. These tests pin its two jobs: it exists, and it is stable.
"""

from __future__ import annotations

from unittest import TestCase


from social_api.api.local import AuthPrincipal, LocalSocialApi
from social_api.domain.human_proxy import (
    InvalidHumanProxyError,
    human_proxy_handle,
    human_proxy_local_name,
    is_human_proxy_handle,
)


class RecordingHub:
    """Stands in for the message hub, recording what it was asked to send."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send_message(self, *, sender_handle, recipient_handle, content, thread_id=None):
        self.calls.append(
            {
                "sender_handle": sender_handle,
                "recipient_handle": recipient_handle,
                "content": content,
                "thread_id": thread_id,
            }
        )
        return {
            "message": {"message_id": f"hubmsg{len(self.calls)}"},
            "thread_id": thread_id or "hubthread1",
        }


class ChatReachesTheInboxTest(TestCase):
    def setUp(self) -> None:
        self.hub = RecordingHub()
        self.api = LocalSocialApi.in_memory(auth_required=True, message_hub_sender=self.hub)
        self.principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        self.agent = self.api.create_agent_profile(
            {"handle": "@alice:seagull.local", "display_name": "Alice"},
            self.principal,
        )["profile"]

    def _chat(self, **body):
        # Exactly the shape the web sends: agent_handle and nothing else.
        return self.api.create_agent_chat(
            {"agent_handle": self.agent["handle"], **body}, self.principal
        )["chat"]

    def test_a_chat_created_the_way_the_web_creates_one_has_a_sender(self) -> None:
        """The regression that made the whole mirror dead code."""
        chat = self._chat()

        self.assertIsNotNone(chat["sender_handle"])
        self.assertTrue(is_human_proxy_handle(chat["sender_handle"]))

    def test_a_chat_message_now_reaches_the_hub(self) -> None:
        chat = self._chat()

        message = self.api.create_agent_chat_message(
            chat["chat_id"], {"content": "hello"}, self.principal
        )["message"]

        self.assertEqual(1, len(self.hub.calls))
        self.assertEqual(self.agent["handle"], self.hub.calls[0]["recipient_handle"])
        self.assertEqual("hello", self.hub.calls[0]["content"])
        self.assertEqual("delivered", message["delivery_status"])
        self.assertIsNotNone(message["hub_message_id"])
        self.assertIsNotNone(message["hub_thread_id"])

    def test_the_proxy_is_stable_across_an_owners_chats(self) -> None:
        """Stability is the point: a per-chat identity would fragment threads."""
        other = self.api.create_agent_profile(
            {"handle": "@bob:seagull.local"}, self.principal
        )["profile"]

        first = self._chat()
        second = self.api.create_agent_chat(
            {"agent_handle": other["handle"]}, self.principal
        )["chat"]

        self.assertEqual(first["sender_handle"], second["sender_handle"])

    def test_different_owners_get_different_proxies(self) -> None:
        bob_principal = AuthPrincipal(provider="cognito", subject="bob-sub")
        bob_agent = self.api.create_agent_profile(
            {"handle": "@bobs-agent:seagull.local"}, bob_principal
        )["profile"]

        alice_chat = self._chat()
        bob_chat = self.api.create_agent_chat(
            {"agent_handle": bob_agent["handle"]}, bob_principal
        )["chat"]

        self.assertNotEqual(alice_chat["sender_handle"], bob_chat["sender_handle"])

    def test_an_explicit_sender_still_wins(self) -> None:
        """The proxy is a fallback, not an override."""
        sender = self.api.create_agent_profile(
            {"handle": "@alices-other-agent:seagull.local"}, self.principal
        )["profile"]

        chat = self._chat(sender_handle=sender["handle"])

        self.assertEqual(sender["handle"], chat["sender_handle"])
        self.assertEqual(sender["agent_id"], chat["sender_agent_id"])
        self.assertFalse(is_human_proxy_handle(chat["sender_handle"]))

    def test_the_proxy_follows_the_agents_domain_when_unpinned(self) -> None:
        chat = self._chat()

        self.assertTrue(chat["sender_handle"].endswith(":seagull.local"))

    def test_a_pinned_domain_gives_one_identity_everywhere(self) -> None:
        """What a deployment wants: one network identity per human."""
        api = LocalSocialApi.in_memory(
            auth_required=True,
            message_hub_sender=RecordingHub(),
            human_proxy_domain="gulls.ai",
        )
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        agent = api.create_agent_profile({"handle": "@alice:seagull.local"}, principal)["profile"]

        chat = api.create_agent_chat({"agent_handle": agent["handle"]}, principal)["chat"]

        self.assertTrue(chat["sender_handle"].endswith(":gulls.ai"))


class HumanProxyHandleTest(TestCase):
    def test_handles_are_deterministic(self) -> None:
        first = human_proxy_handle("user_abc123", domain="gulls.ai")
        second = human_proxy_handle("user_abc123", domain="gulls.ai")

        self.assertEqual(first, second)
        self.assertEqual("@me_user_abc123:gulls.ai", first)

    def test_odd_owner_ids_still_produce_valid_handles(self) -> None:
        """Ids from an identity provider need not be handle-shaped."""
        from seagull_protocol.base import HANDLE_RE

        for owner_id in ("Auth0|abc 123", "  UPPER_case  ", "user@example.com", "123-numeric"):
            handle = human_proxy_handle(owner_id, domain="gulls.ai")
            self.assertRegex(handle, HANDLE_RE, f"invalid handle from {owner_id!r}: {handle}")

    def test_an_unusable_owner_id_is_rejected_not_mangled(self) -> None:
        for owner_id in ("", "   ", "---", "..."):
            with self.assertRaises(InvalidHumanProxyError):
                human_proxy_local_name(owner_id)

    def test_a_domain_is_required(self) -> None:
        with self.assertRaises(InvalidHumanProxyError):
            human_proxy_handle("user_abc", domain="")
