"""Reading chat content back from the gulls Inbox.

The same split the Feed cutover draws: which messages a chat holds and in what
order stays a seagulls projection; what each one *says* comes from gulls.

Chat cannot copy the Feed's whole-record approach. The Feed mirror controls the
record and passes ``post_id`` through unchanged, so identity survives. Chat is
mirrored via ``send_message``, which mints its own id -- rebuilding
``AgentChatMessage`` from hub records alone would change every
``chat_message_id`` the UI holds and lose ``ai_run_id``, ``ai_run_state`` and
``delivery_status``, none of which have a hub equivalent.
"""

from __future__ import annotations

from unittest import TestCase

from message_hub.domain.service import MessageHubService
from message_hub.storage.memory import InMemoryMessageHubRepository

from social_api.api.local import AuthPrincipal, LocalSocialApi
from social_api.domain.chat_source import GullsChatSource, SafeChatSource


class HubBackedSender:
    """A message hub sender wired to a real in-memory hub.

    Using the real service rather than a stub means a mapping mistake fails
    here instead of in production -- the same reason the feed parity tests run
    against InMemoryMessageHubRepository.
    """

    def __init__(self, service: MessageHubService) -> None:
        self._service = service

    def send_message(self, *, sender_handle, recipient_handle, content, thread_id=None):
        for handle in (sender_handle, recipient_handle):
            if self._service._repository.get_agent_by_handle(handle) is None:  # noqa: SLF001
                if handle.startswith("@me_"):
                    self._service.ensure_human_proxy(handle)
                else:
                    self._service.register_agent(handle)
        result = self._service.send_message(
            sender_handle=sender_handle,
            recipient_handles=[recipient_handle],
            content=content,
            intent="direct_message",
            visibility="direct",
            thread_id=thread_id,
        )
        return {
            "message": {"message_id": result.message.message_id},
            "thread_id": result.thread.thread_id,
        }


class EchoAi:
    def create_run(self, request):
        return {"run_id": "r1", "state": "completed", "output_text": "reply from the agent"}


class ChatReadCutoverTest(TestCase):
    def setUp(self) -> None:
        self.gulls_repository = InMemoryMessageHubRepository()
        self.hub = MessageHubService(self.gulls_repository)
        self.sender = HubBackedSender(self.hub)

    def _api(self, *, read_from_gulls: bool):
        return LocalSocialApi.in_memory(
            auth_required=True,
            message_hub_sender=self.sender,
            ai_run_client=EchoAi(),
            chat_source=(
                SafeChatSource(GullsChatSource(self.gulls_repository)) if read_from_gulls else None
            ),
        )

    def _seed(self, api):
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        agent = api.create_agent_profile({"handle": "@alice:seagull.local"}, principal)["profile"]
        chat = api.create_agent_chat({"agent_handle": agent["handle"]}, principal)["chat"]
        return principal, chat

    def _hub_thread_id(self, api, chat_id, principal):
        """The thread both sides of the chat share, as the session records it."""
        chat = api.read_agent_chat(chat_id, principal=principal)["chat"]
        self.assertIsNotNone(chat["hub_thread_id"], "chat never reached gulls")
        return chat["hub_thread_id"]

    def test_both_sides_of_the_conversation_reach_gulls(self) -> None:
        """The human's message and the agent's reply, in one thread.

        Mirroring only the human side would leave gulls holding half a
        conversation, and reading from gulls would then surface exactly that.
        """
        api = self._api(read_from_gulls=False)
        principal, chat = self._seed(api)

        api.create_agent_chat_message(chat["chat_id"], {"content": "hello"}, principal)

        thread_id = self._hub_thread_id(api, chat["chat_id"], principal)
        messages = self.gulls_repository.list_thread_messages(thread_id)

        self.assertEqual(
            ["hello", "reply from the agent"],
            [m.content_inline for m in messages],
        )

    def test_content_is_served_from_gulls_after_the_cutover(self) -> None:
        api = self._api(read_from_gulls=True)
        principal, chat = self._seed(api)
        api.create_agent_chat_message(chat["chat_id"], {"content": "hello"}, principal)

        # Mutate only in gulls, so a read served from seagulls would still show
        # the original text and fail. Written through the id map because
        # put_message deliberately refuses to overwrite -- right for the hub,
        # inconvenient for exactly this assertion.
        thread_id = self._hub_thread_id(api, chat["chat_id"], principal)
        stored = self.gulls_repository.list_thread_messages(thread_id)[0]
        from dataclasses import replace

        self.gulls_repository._messages_by_id[stored.message_id] = replace(  # noqa: SLF001
            stored, content_inline="rewritten in gulls"
        )

        messages = api.list_agent_chat_messages(chat["chat_id"], principal=principal)["items"]

        self.assertEqual("rewritten in gulls", messages[0]["content"])

    def test_identity_and_audit_state_survive_the_cutover(self) -> None:
        """What the hub has no equivalent for must not be lost."""
        api = self._api(read_from_gulls=True)
        principal, chat = self._seed(api)
        created = api.create_agent_chat_message(
            chat["chat_id"], {"content": "hello"}, principal
        )["message"]

        messages = api.list_agent_chat_messages(chat["chat_id"], principal=principal)["items"]

        self.assertEqual(created["chat_message_id"], messages[0]["chat_message_id"])
        self.assertEqual("human", messages[0]["sender_type"])
        self.assertEqual("delivered", messages[0]["delivery_status"])
        self.assertEqual("r1", messages[1]["ai_run_id"])

    def test_messages_predating_the_mirror_still_read(self) -> None:
        """No hub_message_id means the seagulls copy is all there is."""
        plain = LocalSocialApi.in_memory(auth_required=True)
        principal, chat = self._seed(plain)
        plain.create_agent_chat_message(chat["chat_id"], {"content": "before the mirror"}, principal)

        # Flip reads on for a store gulls has never seen.
        plain._service._chat_source = SafeChatSource(  # noqa: SLF001 - test wiring
            GullsChatSource(self.gulls_repository)
        )

        messages = plain.list_agent_chat_messages(chat["chat_id"], principal=principal)["items"]

        self.assertEqual("before the mirror", messages[0]["content"])

    def test_a_gulls_failure_degrades_to_the_stored_copy(self) -> None:
        class Exploding:
            def content_for(self, hub_message_id):
                raise RuntimeError("gulls unavailable")

        api = self._api(read_from_gulls=False)
        principal, chat = self._seed(api)
        api.create_agent_chat_message(chat["chat_id"], {"content": "still readable"}, principal)

        api._service._chat_source = SafeChatSource(Exploding())  # noqa: SLF001 - test wiring

        with self.assertLogs("social_api.domain.chat_source", level="WARNING"):
            messages = api.list_agent_chat_messages(chat["chat_id"], principal=principal)["items"]

        self.assertEqual("still readable", messages[0]["content"])

    def test_without_a_chat_source_reads_stay_on_seagulls(self) -> None:
        api = self._api(read_from_gulls=False)
        principal, chat = self._seed(api)
        api.create_agent_chat_message(chat["chat_id"], {"content": "default path"}, principal)

        messages = api.list_agent_chat_messages(chat["chat_id"], principal=principal)["items"]

        self.assertEqual("default path", messages[0]["content"])
