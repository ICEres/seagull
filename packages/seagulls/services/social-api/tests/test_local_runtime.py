from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count
from unittest import TestCase

from message_hub.api import LocalMessageHubApi
from message_hub.domain import MessageHubService
from message_hub.storage import InMemoryMessageHubRepository
from social_api.api import LocalSocialApi
from social_api.api.local import generate_agent_chat_reply
from social_api.domain import PermissionDeniedError, SocialApiService
from social_api.domain.chat_source import GullsChatSource
from social_api.storage import InMemorySocialRepository


class DeterministicIds:
    def __init__(self) -> None:
        self._counts: dict[str, count] = {}

    def __call__(self, prefix: str) -> str:
        self._counts.setdefault(prefix, count(1))
        return f"{prefix}_{next(self._counts[prefix])}"


class ManualClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 17, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class FakeRuntimeHub:
    def __init__(self) -> None:
        self.issued: list[dict[str, str]] = []
        self.revoked: list[str] = []
        self._counter = count(1)

    def issue_token(self, *, handle: str, owner_user_id: str, node_id: str) -> dict[str, object]:
        number = next(self._counter)
        token_id = f"token_{number}"
        record = {
            "token_id": token_id,
            "agent_handle": handle,
            "owner_user_id": owner_user_id,
            "node_id": node_id,
        }
        self.issued.append(record)
        return {"token": f"sga_test_{number}", "record": record}

    def revoke_token(self, token_id: str) -> None:
        self.revoked.append(token_id)


class HubRegistry:
    def __init__(self, hub: MessageHubService) -> None:
        self.hub = hub

    def register(self, handle: str, display_name: str | None = None) -> None:
        if self.hub._repository.get_agent_by_handle(handle) is None:  # noqa: SLF001
            self.hub.register_agent(handle, display_name=display_name)


class HubSender:
    def __init__(self, hub: MessageHubService) -> None:
        self.hub = hub

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handle: str,
        content: str,
        thread_id: str | None = None,
    ) -> dict[str, object]:
        result = self.hub.send_message(
            sender_handle=sender_handle,
            recipient_handles=[recipient_handle],
            content=content,
            thread_id=thread_id,
        )
        return {
            "thread_id": result.thread.thread_id,
            "message": {
                "message_id": result.message.message_id,
                "thread_id": result.thread.thread_id,
            },
        }


class FakeAiRunClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def create_run(self, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(request)
        return {"run_id": "run_1", "state": "completed", "output_text": "cloud reply"}


class LocalRuntimeServiceTest(TestCase):
    def setUp(self) -> None:
        self.clock = ManualClock()
        self.repository = InMemorySocialRepository()
        self.hub = FakeRuntimeHub()
        self.service = SocialApiService(
            self.repository,
            id_factory=DeterministicIds(),
            clock=self.clock,
        )
        self.owner = self.service.identify_human(provider="local", subject="owner")
        self.profile = self.service.create_agent_profile(
            owner_user_id=self.owner.user_id,
            handle="@local:gulls.ai",
        )

    def test_runtime_mode_is_owner_scoped(self) -> None:
        self.assertEqual("cloud", self.service.get_agent_runtime(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle)["mode"])
        self.service.set_agent_runtime(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle, mode="local")
        self.assertEqual("local", self.service.get_agent_runtime(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle)["mode"])
        with self.assertRaises(PermissionDeniedError):
            self.service.set_agent_runtime(owner_user_id="someone-else", agent_handle=self.profile.handle, mode="manual")

    def test_pairing_attaches_existing_agent_and_pair_token_is_single_use_and_expires(self) -> None:
        pair = self.service.create_local_pair_token(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle)
        paired = self.service.pair_local_runtime(pair_token=pair.pair_token, hub=self.hub)
        self.assertEqual(self.profile.handle, paired["agent_handle"])
        self.assertEqual("node_1", paired["node_id"])
        self.assertEqual("token_1", paired["token_id"])
        updated = self.service.get_owned_profile(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle)
        self.assertEqual("node_1", updated.node_id)
        self.assertEqual("token_1", updated.runtime_token_id)

        with self.assertRaises(Exception):
            self.service.pair_local_runtime(pair_token=pair.pair_token, hub=self.hub)

        expiring = self.service.create_local_pair_token(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle)
        self.clock.advance(timedelta(minutes=11))
        with self.assertRaises(Exception):
            self.service.pair_local_runtime(pair_token=expiring.pair_token, hub=self.hub)

    def test_repair_replaces_token_and_heartbeat_and_disconnect(self) -> None:
        first = self.service.pair_local_runtime(
            pair_token=self.service.create_local_pair_token(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle).pair_token,
            hub=self.hub,
        )
        second = self.service.pair_local_runtime(
            pair_token=self.service.create_local_pair_token(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle).pair_token,
            hub=self.hub,
        )
        self.assertEqual([first["token_id"]], self.hub.revoked)
        self.assertNotEqual(first["node_id"], second["node_id"])

        runtime = self.service.get_agent_runtime(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle)
        self.assertTrue(runtime["connected"])
        self.service.heartbeat_local_runtime({"owner_user_id": self.owner.user_id, "agent_handle": self.profile.handle, "node_id": second["node_id"], "token_id": second["token_id"]})
        self.clock.advance(timedelta(seconds=91))
        self.assertFalse(self.service.get_agent_runtime(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle)["connected"])
        with self.assertRaises(PermissionDeniedError):
            self.service.heartbeat_local_runtime({"owner_user_id": self.owner.user_id, "agent_handle": self.profile.handle, "node_id": first["node_id"], "token_id": first["token_id"]})

        disconnected = self.service.disconnect_local_runtime(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle, hub=self.hub)
        self.assertIsNone(disconnected["node_id"])
        self.assertIsNone(self.service.get_owned_profile(owner_user_id=self.owner.user_id, agent_handle=self.profile.handle).runtime_token_id)


class LocalRuntimeChatProjectionTest(TestCase):
    def setUp(self) -> None:
        self.clock = ManualClock()
        self.hub_repository = InMemoryMessageHubRepository()
        self.hub_service = MessageHubService(self.hub_repository, clock=self.clock)
        self.social_repository = InMemorySocialRepository()
        self.social_service = SocialApiService(
            self.social_repository,
            id_factory=DeterministicIds(),
            clock=self.clock,
            agent_registry=HubRegistry(self.hub_service),
            chat_source=GullsChatSource(self.hub_repository),
        )
        self.owner = self.social_service.identify_human(provider="local", subject="owner")
        self.sender = self.social_service.create_agent_profile(owner_user_id=self.owner.user_id, handle="@human:gulls.ai")
        self.agent = self.social_service.create_agent_profile(owner_user_id=self.owner.user_id, handle="@worker:gulls.ai")
        self.other = self.social_service.create_agent_profile(owner_user_id=self.owner.user_id, handle="@other:gulls.ai")

    def test_local_reply_projects_once_and_filters_sender_thread_and_recipients(self) -> None:
        api = LocalSocialApi(self.social_service, message_hub_sender=HubSender(self.hub_service))
        chat = self.social_service.create_agent_chat(
            owner_user_id=self.owner.user_id,
            agent_handle=self.agent.handle,
            sender_handle=self.sender.handle,
        )
        created = api.create_agent_chat_message(
            chat.chat_id,
            {"owner_user_id": self.owner.user_id, "content": "hello"},
        )
        inbound = created["message"]
        self.assertEqual("delivered", inbound["delivery_status"])
        hub_agent = self.hub_repository.get_agent_by_handle(self.agent.handle)
        assert hub_agent is not None
        delivery = self.hub_repository.list_deliveries_by_recipient(hub_agent.agent_id)[0]
        issued = self.hub_service.issue_agent_token(self.agent.handle, scopes=["agent:post"])
        hub_api = LocalMessageHubApi(self.hub_service)
        hub_api.agent_decide_delivery(
            f"Bearer {issued.token}",
            delivery.delivery_id,
            {"decision": "reply", "content": "local reply"},
        )

        hub_thread_id = str(inbound["hub_thread_id"])
        reply_messages = self.hub_repository.list_thread_messages(hub_thread_id)
        local_reply = next(message for message in reply_messages if message.content_inline == "local reply")
        self.assertEqual("local", local_reply.runtime_mode)
        self.hub_service.send_message(
            sender_handle=self.agent.handle,
            recipient_handles=[self.sender.handle],
            content="cloud duplicate candidate",
            thread_id=hub_thread_id,
            runtime_mode="cloud",
        )
        self.hub_service.send_message(
            sender_handle=self.agent.handle,
            recipient_handles=[self.other.handle],
            content="wrong recipient",
            thread_id=hub_thread_id,
        )
        self.hub_service.send_message(
            sender_handle=self.agent.handle,
            recipient_handles=[self.sender.handle],
            content="wrong thread",
        )
        first = self.social_service.list_agent_chat_messages(owner_user_id=self.owner.user_id, chat_id=chat.chat_id)
        second = self.social_service.list_agent_chat_messages(owner_user_id=self.owner.user_id, chat_id=chat.chat_id)
        replies = [message for message in first if message.sender_type == "agent"]
        self.assertEqual(["local reply"], [message.content for message in replies])
        self.assertEqual(len(first), len(second))

    def test_cloud_ai_reply_is_disabled_for_local_and_manual_runtime_modes(self) -> None:
        chat = self.social_service.create_agent_chat(
            owner_user_id=self.owner.user_id,
            agent_handle=self.agent.handle,
            sender_handle=self.sender.handle,
        )
        ai = FakeAiRunClient()
        for mode in ("local", "manual"):
            self.social_service.set_agent_runtime(owner_user_id=self.owner.user_id, agent_handle=self.agent.handle, mode=mode)
            message = self.social_service.create_agent_chat_message(
                owner_user_id=self.owner.user_id,
                chat_id=chat.chat_id,
                content=f"hello in {mode}",
            )
            self.assertEqual(mode, message.runtime_mode)
            _, reply = generate_agent_chat_reply(
                self.social_service,
                ai,
                owner_user_id=self.owner.user_id,
                chat=chat,
                message=message,
            )
            self.assertIsNone(reply)
        self.social_service.set_agent_runtime(owner_user_id=self.owner.user_id, agent_handle=self.agent.handle, mode="local")
        local_message = self.social_service.create_agent_chat_message(
            owner_user_id=self.owner.user_id,
            chat_id=chat.chat_id,
            content="local snapshot",
        )
        self.assertEqual("local", local_message.runtime_mode)
        self.social_service.set_agent_runtime(owner_user_id=self.owner.user_id, agent_handle=self.agent.handle, mode="cloud")
        _, reply = generate_agent_chat_reply(
            self.social_service,
            ai,
            owner_user_id=self.owner.user_id,
            chat=chat,
            message=local_message,
        )
        self.assertIsNone(reply)
        self.assertEqual([], ai.requests)
