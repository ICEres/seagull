from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count
from unittest import TestCase

from social_api.api import ApiError, AuthPrincipal, LocalSocialApi
from social_api.domain import (
    AgentProfileRecord,
    InvalidSocialRequestError,
    Notification,
    PermissionDeniedError,
    PostRecord,
    SocialApiService,
)
from social_api.storage import InMemorySocialRepository
from social_api.storage.repository import AgentProfilePage


class DeterministicIds:
    def __init__(self) -> None:
        self._counts: dict[str, count] = {}

    def __call__(self, prefix: str) -> str:
        if prefix not in self._counts:
            self._counts[prefix] = count(1)
        return f"{prefix}_{next(self._counts[prefix])}"


class DeterministicClock:
    def __init__(self) -> None:
        self._base = datetime(2026, 6, 13, tzinfo=timezone.utc)
        self._ticks = count()

    def __call__(self) -> datetime:
        return self._base + timedelta(seconds=next(self._ticks))


class ManualClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 6, 13, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class FakeMessageHubSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handle: str,
        content: str,
        thread_id: str | None = None,
    ) -> dict[str, object]:
        self.sent.append(
            {
                "sender_handle": sender_handle,
                "recipient_handle": recipient_handle,
                "content": content,
                "thread_id": thread_id,
            }
        )
        return {
            "thread_id": thread_id or "thread_1",
            "message": {
                "message_id": f"message_{len(self.sent)}",
                "thread_id": thread_id or "thread_1",
            },
        }


class FakeAiRunClient:
    def __init__(
        self,
        run: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.requests: list[dict[str, object]] = []
        self._run = run or {
            "run_id": "airun_1",
            "state": "completed",
            "output_text": "Here is the plan.",
        }
        self._error = error

    def create_run(self, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return self._run


class RecordingAgentRegistry:
    def __init__(self, error: Exception | None = None) -> None:
        self.registered: list[tuple[str, str | None]] = []
        self._error = error

    def register(self, handle: str, display_name: str | None = None) -> None:
        if self._error is not None:
            raise self._error
        self.registered.append((handle, display_name))


class NoFanoutReadRepository(InMemorySocialRepository):
    reject_fanout_reads = False

    def list_agent_profiles_by_owner(self, owner_user_id: str) -> tuple[AgentProfileRecord, ...]:
        if self.reject_fanout_reads:
            raise AssertionError("feed reads should not load every owned profile")
        return super().list_agent_profiles_by_owner(owner_user_id)

    def list_agent_profiles_by_owner_page(
        self,
        owner_user_id: str,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> AgentProfilePage:
        reject_fanout_reads = self.reject_fanout_reads
        self.reject_fanout_reads = False
        try:
            return super().list_agent_profiles_by_owner_page(owner_user_id, limit=limit, cursor=cursor)
        finally:
            self.reject_fanout_reads = reject_fanout_reads

    def list_posts(self, *, limit: int = 50) -> tuple[PostRecord, ...]:
        raise AssertionError("home feed should not use global post listing")

    def list_posts_by_author(self, author_agent_id: str, *, limit: int = 50) -> tuple[PostRecord, ...]:
        if self.reject_fanout_reads:
            raise AssertionError("home feed should use materialized owner feed events")
        return super().list_posts_by_author(author_agent_id, limit=limit)

    def list_notifications_by_recipient(self, recipient_agent_id: str, *, limit: int = 50) -> tuple[Notification, ...]:
        if self.reject_fanout_reads:
            raise AssertionError("dashboard should use owner notification reads")
        return super().list_notifications_by_recipient(recipient_agent_id, limit=limit)


class SocialApiServiceTest(TestCase):
    def setUp(self) -> None:
        self.repository = InMemorySocialRepository()
        self.service = SocialApiService(
            self.repository,
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
        )
        self.alice = self.service.identify_human(
            provider="local",
            subject="alice",
            email="alice@example.com",
            display_name="Alice",
        )
        self.bob = self.service.identify_human(
            provider="local",
            subject="bob",
            email="bob@example.com",
            display_name="Bob",
        )

    def test_identify_human_preserves_stored_profile_when_claims_are_missing(self) -> None:
        # A later sign-in whose token lacks email/name must not wipe stored values.
        again = self.service.identify_human(provider="local", subject="alice")
        self.assertEqual(self.alice.user_id, again.user_id)
        self.assertEqual("alice@example.com", again.email)
        self.assertEqual("Alice", again.display_name)

        # A fresh value still updates.
        renamed = self.service.identify_human(
            provider="local", subject="alice", display_name="Alice B."
        )
        self.assertEqual("Alice B.", renamed.display_name)
        self.assertEqual("alice@example.com", renamed.email)

    def test_human_creates_profile_agent_posts_feed_and_mention_routes(self) -> None:
        researcher = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@Researcher:Seagull.Local",
            display_name="Researcher",
            capabilities=("research", "planning"),
        )
        reviewer = self.service.create_agent_profile(
            owner_user_id=self.bob.user_id,
            handle="@reviewer:seagull.local",
            display_name="Reviewer",
            capabilities=("review",),
        )

        post = self.service.create_post(
            owner_user_id=self.alice.user_id,
            author_handle="@researcher:seagull.local",
            content="Can @reviewer:seagull.local review this social API plan?",
        )

        self.assertEqual("post_1", post.post_id)
        self.assertEqual(researcher.agent_id, post.author_agent_id)
        self.assertEqual((reviewer.agent_id,), post.mention_agent_ids)

        alice_feed = self.service.get_home_feed(self.alice.user_id)
        self.assertEqual((post,), alice_feed)

        notifications = self.service.list_notifications(
            owner_user_id=self.bob.user_id,
            agent_handle="@reviewer:seagull.local",
        )
        self.assertEqual(1, len(notifications))
        self.assertEqual("mention", notifications[0].notification_type)
        self.assertEqual(post.post_id, notifications[0].post_id)

    def test_follow_graph_adds_followed_agent_posts_to_home_feed(self) -> None:
        researcher = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@researcher:seagull.local",
        )
        reviewer = self.service.create_agent_profile(
            owner_user_id=self.bob.user_id,
            handle="@reviewer:seagull.local",
        )
        self.service.follow_agent(
            owner_user_id=self.alice.user_id,
            follower_handle=researcher.handle,
            followed_handle=reviewer.handle,
        )

        followed_post = self.service.create_post(
            owner_user_id=self.bob.user_id,
            author_handle=reviewer.handle,
            content="Public review notes.",
        )

        self.assertEqual((followed_post,), self.service.get_home_feed(self.alice.user_id))

    def test_home_feed_uses_materialized_owner_feed_reads(self) -> None:
        repository = NoFanoutReadRepository()
        service = SocialApiService(
            repository,
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
        )
        alice = service.identify_human(provider="local", subject="alice")
        bob = service.identify_human(provider="local", subject="bob")
        researcher = service.create_agent_profile(
            owner_user_id=alice.user_id,
            handle="@researcher:seagull.local",
        )
        reviewer = service.create_agent_profile(
            owner_user_id=bob.user_id,
            handle="@reviewer:seagull.local",
        )
        broadcaster = service.create_agent_profile(
            owner_user_id=bob.user_id,
            handle="@broadcaster:seagull.local",
        )

        mention = service.create_post(
            owner_user_id=bob.user_id,
            author_handle=reviewer.handle,
            content=f"Can {researcher.handle} review this?",
        )
        service.follow_agent(
            owner_user_id=alice.user_id,
            follower_handle=researcher.handle,
            followed_handle=broadcaster.handle,
        )
        followed_post = service.create_post(
            owner_user_id=bob.user_id,
            author_handle=broadcaster.handle,
            content="Public update.",
        )

        repository.reject_fanout_reads = True
        self.assertEqual((followed_post, mention), service.get_home_feed(alice.user_id))

    def test_room_membership_allows_room_post(self) -> None:
        profile = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@researcher:seagull.local",
        )
        room = self.service.create_room(
            owner_user_id=self.alice.user_id,
            slug="research",
            name="Research",
        )
        membership = self.service.join_room(
            owner_user_id=self.alice.user_id,
            room_slug="research",
            agent_handle=profile.handle,
        )
        post = self.service.create_post(
            owner_user_id=self.alice.user_id,
            author_handle=profile.handle,
            content="Room update.",
            room_slug="research",
            visibility="room",
        )

        self.assertEqual(room.room_id, membership.room_id)
        self.assertEqual(room.room_id, post.room_id)

    def test_room_post_requires_membership(self) -> None:
        self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@researcher:seagull.local",
        )
        self.service.create_room(
            owner_user_id=self.alice.user_id,
            slug="research",
            name="Research",
        )

        with self.assertRaises(PermissionDeniedError):
            self.service.create_post(
                owner_user_id=self.alice.user_id,
                author_handle="@researcher:seagull.local",
                content="Room update.",
                room_slug="research",
                visibility="room",
            )

    def test_moderation_records_are_listed_newest_first(self) -> None:
        first = self.service.create_moderation_record(
            owner_user_id=self.alice.user_id,
            target_type="agent",
            target_id="agent_1",
            action="report",
            reason="spam",
        )
        second = self.service.create_moderation_record(
            owner_user_id=self.alice.user_id,
            target_type="post",
            target_id="post_1",
            action="hide",
            reason="unsafe delegation",
        )

        self.assertEqual((second, first), self.service.list_moderation_records())

    def test_rejects_self_follow(self) -> None:
        profile = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@researcher:seagull.local",
        )

        with self.assertRaises(InvalidSocialRequestError):
            self.service.follow_agent(
                owner_user_id=self.alice.user_id,
                follower_handle=profile.handle,
                followed_handle=profile.handle,
            )

    def test_cloud_node_pair_token_registers_agent_to_owner_and_node(self) -> None:
        node = self.service.create_node(owner_user_id=self.alice.user_id)
        token = self.service.create_pair_token(owner_user_id=self.alice.user_id, node_id=node.node_id)

        profile = self.service.register_agent_with_pair_token(
            pair_token=token.pair_token,
            handle="@map-reader:gulls.ai",
            display_name="Map Reader",
            capabilities=("maps", "browser"),
            delivery_mode="pull_webhook",
        )

        updated_node = self.service.get_node(owner_user_id=self.alice.user_id, node_id=node.node_id)
        self.assertEqual(self.alice.user_id, profile.owner_user_id)
        self.assertEqual(node.node_id, profile.node_id)
        self.assertEqual("pull_webhook", profile.delivery_mode)
        self.assertEqual(1, updated_node.agent_count)
        self.assertIsNotNone(updated_node.last_seen_at)

    def test_node_ownership_is_enforced(self) -> None:
        node = self.service.create_node(owner_user_id=self.alice.user_id)

        with self.assertRaises(PermissionDeniedError):
            self.service.get_node(owner_user_id=self.bob.user_id, node_id=node.node_id)

    def test_expired_pair_token_is_rejected(self) -> None:
        clock = ManualClock()
        service = SocialApiService(
            InMemorySocialRepository(),
            id_factory=DeterministicIds(),
            clock=clock,
        )
        alice = service.identify_human(provider="local", subject="alice")
        node = service.create_node(owner_user_id=alice.user_id)
        token = service.create_pair_token(owner_user_id=alice.user_id, node_id=node.node_id, ttl_seconds=1)
        clock.advance(timedelta(seconds=2))

        with self.assertRaises(InvalidSocialRequestError):
            service.register_agent_with_pair_token(
                pair_token=token.pair_token,
                handle="@expired:gulls.ai",
            )

    def test_profile_listing_filters_by_node_status_and_query(self) -> None:
        node = self.service.create_node(owner_user_id=self.alice.user_id)
        token = self.service.create_pair_token(owner_user_id=self.alice.user_id, node_id=node.node_id)
        mapped = self.service.register_agent_with_pair_token(
            pair_token=token.pair_token,
            handle="@map-reader:gulls.ai",
            display_name="Map Reader",
            capabilities=("maps",),
        )
        self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@writer:gulls.ai",
            display_name="Writer",
            capabilities=("drafting",),
        )

        filtered = self.service.list_owned_profiles(
            self.alice.user_id,
            limit=10,
            q="map",
            status="active",
            node_id=node.node_id,
        )

        self.assertEqual((mapped,), filtered)

    def test_profile_listing_page_returns_next_cursor(self) -> None:
        profiles = [
            self.service.create_agent_profile(
                owner_user_id=self.alice.user_id,
                handle=f"@agent-{index}:gulls.ai",
                display_name=f"Agent {index}",
            )
            for index in range(1, 5)
        ]

        first_page = self.service.list_owned_profiles_page(self.alice.user_id, limit=2)
        second_page = self.service.list_owned_profiles_page(
            self.alice.user_id,
            limit=2,
            cursor=first_page.next_cursor,
        )

        self.assertEqual(profiles[:2], list(first_page.items))
        self.assertIsNotNone(first_page.next_cursor)
        self.assertEqual(profiles[2:], list(second_page.items))
        self.assertIsNone(second_page.next_cursor)

    def test_profile_listing_page_rejects_cursor_with_filters(self) -> None:
        for handle in ("@agent-one:gulls.ai", "@agent-two:gulls.ai"):
            self.service.create_agent_profile(
                owner_user_id=self.alice.user_id,
                handle=handle,
            )
        page = self.service.list_owned_profiles_page(self.alice.user_id, limit=1)

        with self.assertRaises(InvalidSocialRequestError):
            self.service.list_owned_profiles_page(
                self.alice.user_id,
                limit=1,
                cursor=page.next_cursor,
                q="agent",
            )

    def test_profile_asset_policy_fields_are_public_metadata(self) -> None:
        profile = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@reviewer:seagull.local",
            display_name="Reviewer",
            capabilities=("review",),
            relationship_posture="trusted_reviewer",
            approval_required_for=("private_context", "tool_use"),
            allowed_use_terms=("inspect_shared_context", "return_artifacts"),
            contact_explanation="Requested because this agent reviews frontend plans.",
        )
        updated = self.service.update_agent_profile(
            owner_user_id=self.alice.user_id,
            handle=profile.handle,
            relationship_posture="needs_approval",
            approval_required_for=("private_context", "tool_use", "high_cost_work"),
            allowed_use_terms=("inspect_shared_context",),
            contact_explanation="Requester matched a review capability.",
        )

        self.assertEqual("trusted_reviewer", profile.relationship_posture)
        self.assertEqual(("private_context", "tool_use"), profile.approval_required_for)
        self.assertEqual(("inspect_shared_context", "return_artifacts"), profile.allowed_use_terms)
        self.assertEqual("Requested because this agent reviews frontend plans.", profile.contact_explanation)
        self.assertEqual("needs_approval", updated.relationship_posture)
        self.assertEqual(("private_context", "tool_use", "high_cost_work"), updated.approval_required_for)
        self.assertEqual(("inspect_shared_context",), updated.allowed_use_terms)
        self.assertEqual("Requester matched a review capability.", updated.contact_explanation)
        self.assertFalse(hasattr(updated, "private_prompt"))
        self.assertFalse(hasattr(updated, "tool_credentials"))

    def test_prompt_and_skill_assets_bind_to_owned_agent(self) -> None:
        profile = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@assistant:seagull.local",
        )
        prompt = self.service.create_personal_agent_asset(
            owner_user_id=self.alice.user_id,
            asset_type="prompt",
            name="Concise assistant",
            instructions="Answer directly and ask before taking actions.",
        )
        skill = self.service.create_personal_agent_asset(
            owner_user_id=self.alice.user_id,
            asset_type="skill",
            name="Planning skill",
            instructions="Break implementation work into verifiable steps.",
            style="Pragmatic and specific.",
            tags=("planning", "implementation"),
            max_output_chars=1200,
        )

        binding = self.service.set_agent_asset_binding(
            owner_user_id=self.alice.user_id,
            agent_handle=profile.handle,
            prompt_asset_id=prompt.asset_id,
            skill_asset_id=skill.asset_id,
        )

        self.assertEqual("asset_1", prompt.asset_id)
        self.assertEqual("prompt", prompt.asset_type)
        self.assertEqual("asset_2", skill.asset_id)
        self.assertEqual("skill", skill.asset_type)
        self.assertEqual(("planning", "implementation"), skill.tags)
        self.assertEqual(1200, skill.max_output_chars)
        self.assertEqual(profile.agent_id, binding.agent_id)
        self.assertEqual(prompt.asset_id, binding.prompt_asset_id)
        self.assertEqual(skill.asset_id, binding.skill_asset_id)
        self.assertEqual((prompt,), self.service.list_personal_agent_assets(self.alice.user_id, asset_type="prompt"))
        self.assertEqual(binding, self.service.get_agent_asset_binding(owner_user_id=self.alice.user_id, agent_handle=profile.handle))

    def test_agent_asset_binding_enforces_owner_and_asset_type(self) -> None:
        profile = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@assistant:seagull.local",
        )
        alice_prompt = self.service.create_personal_agent_asset(
            owner_user_id=self.alice.user_id,
            asset_type="prompt",
            name="Prompt",
            instructions="Stay concise.",
        )
        bob_skill = self.service.create_personal_agent_asset(
            owner_user_id=self.bob.user_id,
            asset_type="skill",
            name="Other skill",
            instructions="Private behavior.",
        )

        with self.assertRaises(PermissionDeniedError):
            self.service.set_agent_asset_binding(
                owner_user_id=self.alice.user_id,
                agent_handle=profile.handle,
                skill_asset_id=bob_skill.asset_id,
            )
        with self.assertRaises(InvalidSocialRequestError):
            self.service.set_agent_asset_binding(
                owner_user_id=self.alice.user_id,
                agent_handle=profile.handle,
                skill_asset_id=alice_prompt.asset_id,
            )

    def test_agent_chat_snapshots_binding_and_stores_messages(self) -> None:
        sender = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@alice:seagull.local",
        )
        assistant = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@assistant:seagull.local",
            display_name="Assistant",
        )
        prompt = self.service.create_personal_agent_asset(
            owner_user_id=self.alice.user_id,
            asset_type="prompt",
            name="Concise assistant",
            instructions="Answer directly.",
        )
        skill = self.service.create_personal_agent_asset(
            owner_user_id=self.alice.user_id,
            asset_type="skill",
            name="Planning skill",
            instructions="Plan in steps.",
        )
        self.service.set_agent_asset_binding(
            owner_user_id=self.alice.user_id,
            agent_handle=assistant.handle,
            prompt_asset_id=prompt.asset_id,
            skill_asset_id=skill.asset_id,
        )

        chat = self.service.create_agent_chat(
            owner_user_id=self.alice.user_id,
            agent_handle=assistant.handle,
            sender_handle=sender.handle,
        )
        message = self.service.create_agent_chat_message(
            owner_user_id=self.alice.user_id,
            chat_id=chat.chat_id,
            content="Plan the MVP.",
        )
        delivered = self.service.record_agent_chat_message_delivery(
            owner_user_id=self.alice.user_id,
            chat_message_id=message.chat_message_id,
            delivery_status="delivered",
            hub_message_id="message_1",
            hub_thread_id="thread_1",
        )

        self.assertEqual("chat_1", chat.chat_id)
        self.assertEqual(assistant.agent_id, chat.agent_id)
        self.assertEqual(sender.agent_id, chat.sender_agent_id)
        self.assertEqual(prompt.asset_id, chat.prompt_asset_id)
        self.assertEqual(skill.asset_id, chat.skill_asset_id)
        self.assertEqual("Plan the MVP.", message.content)
        self.assertEqual("stored", message.delivery_status)
        self.assertEqual("delivered", delivered.delivery_status)
        self.assertEqual("message_1", delivered.hub_message_id)
        self.assertEqual((delivered,), self.service.list_agent_chat_messages(owner_user_id=self.alice.user_id, chat_id=chat.chat_id))
        self.assertEqual("thread_1", self.service.get_agent_chat(owner_user_id=self.alice.user_id, chat_id=chat.chat_id).hub_thread_id)

    def test_agent_chat_enforces_owner(self) -> None:
        assistant = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@assistant:seagull.local",
        )

        with self.assertRaises(PermissionDeniedError):
            self.service.create_agent_chat(
                owner_user_id=self.bob.user_id,
                agent_handle=assistant.handle,
            )

    def test_agent_chat_reply_records_ai_run_reference(self) -> None:
        assistant = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@assistant:seagull.local",
        )
        chat = self.service.create_agent_chat(
            owner_user_id=self.alice.user_id,
            agent_handle=assistant.handle,
        )
        message = self.service.create_agent_chat_message(
            owner_user_id=self.alice.user_id,
            chat_id=chat.chat_id,
            content="Plan the MVP.",
        )

        reply = self.service.create_agent_chat_reply(
            owner_user_id=self.alice.user_id,
            chat_id=chat.chat_id,
            content="Here is the plan.",
            ai_run_id="airun_1",
            ai_run_state="completed",
        )
        audited = self.service.record_agent_chat_message_ai_state(
            owner_user_id=self.alice.user_id,
            chat_message_id=message.chat_message_id,
            ai_run_id="airun_2",
            ai_run_state="denied",
            ai_error="insufficient credits",
        )

        self.assertEqual("agent", reply.sender_type)
        self.assertEqual("airun_1", reply.ai_run_id)
        self.assertEqual("completed", reply.ai_run_state)
        self.assertEqual("airun_2", audited.ai_run_id)
        self.assertEqual("denied", audited.ai_run_state)
        self.assertEqual("insufficient credits", audited.ai_error)
        self.assertEqual(
            [message.chat_message_id, reply.chat_message_id],
            [
                stored.chat_message_id
                for stored in self.service.list_agent_chat_messages(
                    owner_user_id=self.alice.user_id,
                    chat_id=chat.chat_id,
                )
            ],
        )
        with self.assertRaises(PermissionDeniedError):
            self.service.create_agent_chat_reply(
                owner_user_id=self.bob.user_id,
                chat_id=chat.chat_id,
                content="Not allowed.",
            )
        with self.assertRaises(PermissionDeniedError):
            self.service.record_agent_chat_message_ai_state(
                owner_user_id=self.bob.user_id,
                chat_message_id=message.chat_message_id,
                ai_error="not allowed",
            )

    def test_relationship_presets_derive_profile_policy_defaults(self) -> None:
        helper = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@summary:seagull.local",
            relationship_posture="summary_helper",
        )
        paid = self.service.update_agent_profile(
            owner_user_id=self.alice.user_id,
            handle=helper.handle,
            relationship_posture="paid_worker",
        )
        custom = self.service.update_agent_profile(
            owner_user_id=self.alice.user_id,
            handle=helper.handle,
            relationship_posture="research_helper",
            approval_required_for=("tool_use",),
            allowed_use_terms=("inspect_shared_context", "no_memory"),
        )

        self.assertEqual("summary_helper", helper.relationship_posture)
        self.assertEqual(("inspect_shared_context", "return_summary", "no_long_term_memory"), helper.allowed_use_terms)
        self.assertEqual("paid_worker", paid.relationship_posture)
        self.assertIn("paid_work", paid.approval_required_for)
        self.assertEqual(("inspect_shared_context", "return_artifacts", "metered_work"), paid.allowed_use_terms)
        self.assertEqual(("tool_use",), custom.approval_required_for)
        self.assertEqual(("inspect_shared_context", "no_memory"), custom.allowed_use_terms)

    def test_blocked_relationship_cannot_allow_use_terms(self) -> None:
        blocked = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@blocked:seagull.local",
            relationship_posture="blocked",
        )

        self.assertEqual("blocked", blocked.relationship_posture)
        self.assertIn("contact", blocked.approval_required_for)
        self.assertEqual((), blocked.allowed_use_terms)
        with self.assertRaises(InvalidSocialRequestError):
            self.service.update_agent_profile(
                owner_user_id=self.alice.user_id,
                handle=blocked.handle,
                relationship_posture="blocked",
                allowed_use_terms=("inspect_shared_context",),
            )

    def test_profile_creation_registers_normalized_handle_with_agent_registry(self) -> None:
        registry = RecordingAgentRegistry()
        service = SocialApiService(
            InMemorySocialRepository(),
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
            agent_registry=registry,
        )
        alice = service.identify_human(provider="local", subject="alice")

        service.create_agent_profile(
            owner_user_id=alice.user_id,
            handle="@Researcher:Seagull.Local",
            display_name="Researcher",
        )

        self.assertEqual([("@researcher:seagull.local", "Researcher")], registry.registered)

    def test_pair_token_agent_registration_registers_handle_with_agent_registry(self) -> None:
        registry = RecordingAgentRegistry()
        service = SocialApiService(
            InMemorySocialRepository(),
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
            agent_registry=registry,
        )
        alice = service.identify_human(provider="local", subject="alice")
        node = service.create_node(owner_user_id=alice.user_id)
        token = service.create_pair_token(owner_user_id=alice.user_id, node_id=node.node_id)

        service.register_agent_with_pair_token(
            pair_token=token.pair_token,
            handle="@Map-Reader:Gulls.AI",
            display_name="Map Reader",
        )

        self.assertEqual([("@map-reader:gulls.ai", "Map Reader")], registry.registered)

    def test_agent_registry_failure_does_not_fail_profile_creation(self) -> None:
        registry = RecordingAgentRegistry(error=RuntimeError("hub unreachable"))
        service = SocialApiService(
            InMemorySocialRepository(),
            id_factory=DeterministicIds(),
            clock=DeterministicClock(),
            agent_registry=registry,
        )
        alice = service.identify_human(provider="local", subject="alice")

        with self.assertLogs("social_api.domain.service", level="WARNING") as logs:
            profile = service.create_agent_profile(
                owner_user_id=alice.user_id,
                handle="@researcher:seagull.local",
            )

        self.assertEqual("@researcher:seagull.local", profile.handle)
        self.assertEqual(
            (profile,),
            service.list_owned_profiles(alice.user_id),
        )
        self.assertIn("hub unreachable", logs.output[0])

    def test_text_refs_post_preserves_legacy_content(self) -> None:
        profile = self.service.create_agent_profile(
            owner_user_id=self.alice.user_id,
            handle="@researcher:seagull.local",
        )

        post = self.service.create_post(
            owner_user_id=self.alice.user_id,
            author_handle=profile.handle,
            text="Meet here tomorrow?",
            refs=[
                {
                    "type": "url",
                    "url": "https://maps.google.com/example",
                    "find": "identify_place_or_route",
                    "remember_as": "possible meeting place for this thread",
                }
            ],
        )

        self.assertEqual("Meet here tomorrow?", post.content)
        self.assertEqual("Meet here tomorrow?", post.text)
        self.assertEqual("url", post.refs[0].ref_type)
        self.assertEqual("https://maps.google.com/example", post.refs[0].url)


class LocalSocialApiTest(TestCase):
    def test_local_api_phase3_loop(self) -> None:
        api = LocalSocialApi.in_memory()

        self.assertEqual({"ok": True, "app": "social-api", "storage": "memory"}, api.health())

        alice = api.identify_human(
            {
                "provider": "local",
                "subject": "alice",
                "email": "alice@example.com",
                "display_name": "Alice",
            }
        )["identity"]
        bob = api.identify_human(
            {
                "provider": "local",
                "subject": "bob",
                "email": "bob@example.com",
                "display_name": "Bob",
            }
        )["identity"]

        researcher = api.create_agent_profile(
            {
                "owner_user_id": alice["user_id"],
                "handle": "@researcher:seagull.local",
                "display_name": "Researcher",
                "capabilities": ["research"],
            }
        )["profile"]
        reviewer = api.create_agent_profile(
            {
                "owner_user_id": bob["user_id"],
                "handle": "@reviewer:seagull.local",
                "display_name": "Reviewer",
            }
        )["profile"]

        post = api.create_post(
            {
                "owner_user_id": alice["user_id"],
                "author_handle": researcher["handle"],
                "content": "Please review this, @reviewer:seagull.local.",
            }
        )["post"]

        self.assertEqual([reviewer["agent_id"]], post["mention_agent_ids"])
        self.assertEqual(post["post_id"], api.read_home_feed(alice["user_id"])["items"][0]["post_id"])

        notifications = api.read_notifications(
            reviewer["handle"],
            owner_user_id=bob["user_id"],
        )
        self.assertEqual(post["post_id"], notifications["items"][0]["post_id"])

    def test_local_api_maps_duplicate_handle_to_conflict(self) -> None:
        api = LocalSocialApi.in_memory()
        identity = api.identify_human({"provider": "local", "subject": "alice"})["identity"]
        body = {
            "owner_user_id": identity["user_id"],
            "handle": "@researcher:seagull.local",
        }
        api.create_agent_profile(body)

        with self.assertRaises(ApiError) as error:
            api.create_agent_profile(body)

        self.assertEqual(409, error.exception.status_code)

    def test_local_api_exposes_profile_asset_policy_fields(self) -> None:
        api = LocalSocialApi.in_memory()
        identity = api.identify_human({"provider": "local", "subject": "alice"})["identity"]

        profile = api.create_agent_profile(
            {
                "owner_user_id": identity["user_id"],
                "handle": "@reviewer:seagull.local",
                "display_name": "Reviewer",
                "capabilities": ["review"],
                "relationship_posture": "trusted_reviewer",
                "approval_required_for": ["private_context", "tool_use"],
                "allowed_use_terms": ["inspect_shared_context", "return_artifacts"],
                "contact_explanation": "Requested because this agent reviews frontend plans.",
            }
        )["profile"]

        self.assertEqual("trusted_reviewer", profile["relationship_posture"])
        self.assertEqual(["private_context", "tool_use"], profile["approval_required_for"])
        self.assertEqual(["inspect_shared_context", "return_artifacts"], profile["allowed_use_terms"])
        self.assertEqual("Requested because this agent reviews frontend plans.", profile["contact_explanation"])
        self.assertNotIn("private_prompt", profile)
        self.assertNotIn("tool_credentials", profile)

    def test_local_api_derives_profile_policy_from_relationship_preset(self) -> None:
        api = LocalSocialApi.in_memory()
        identity = api.identify_human({"provider": "local", "subject": "alice"})["identity"]

        profile = api.create_agent_profile(
            {
                "owner_user_id": identity["user_id"],
                "handle": "@summary:seagull.local",
                "relationship_posture": "summary_helper",
            }
        )["profile"]

        self.assertEqual("summary_helper", profile["relationship_posture"])
        self.assertEqual(
            ["inspect_shared_context", "return_summary", "no_long_term_memory"],
            profile["allowed_use_terms"],
        )

    def test_local_api_creates_and_binds_prompt_and_skill_assets(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        principal = AuthPrincipal(provider="cognito", subject="alice-sub", email="alice@example.com")
        profile = api.create_agent_profile(
            {
                "handle": "@assistant:seagull.local",
                "display_name": "Assistant",
            },
            principal,
        )["profile"]
        prompt = api.create_personal_agent_asset(
            {
                "asset_type": "prompt",
                "name": "Concise assistant",
                "instructions": "Answer directly and ask before taking actions.",
            },
            principal,
        )["asset"]
        skill = api.create_personal_agent_asset(
            {
                "asset_type": "skill",
                "name": "Planning skill",
                "instructions": "Break implementation work into verifiable steps.",
                "style": "Pragmatic and specific.",
                "tags": ["planning", "implementation"],
                "max_output_chars": 1200,
            },
            principal,
        )["asset"]

        binding = api.set_agent_asset_binding(
            profile["handle"],
            {
                "prompt_asset_id": prompt["asset_id"],
                "skill_asset_id": skill["asset_id"],
            },
            principal,
        )["binding"]
        prompt_assets = api.list_personal_agent_assets(asset_type="prompt", principal=principal)["items"]
        read_binding = api.read_agent_asset_binding(profile["handle"], principal=principal)["binding"]

        self.assertEqual("prompt", prompt["asset_type"])
        self.assertEqual("skill", skill["asset_type"])
        self.assertEqual(["planning", "implementation"], skill["tags"])
        self.assertEqual(1200, skill["max_output_chars"])
        self.assertEqual(prompt["asset_id"], binding["prompt_asset_id"])
        self.assertEqual(skill["asset_id"], binding["skill_asset_id"])
        self.assertEqual([prompt["asset_id"]], [asset["asset_id"] for asset in prompt_assets])
        self.assertEqual(binding, read_binding)

    def test_local_api_prompt_editor_is_owner_scoped_and_preserves_skill(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        alice = AuthPrincipal(provider="cognito", subject="alice-sub", email="alice@example.com")
        bob = AuthPrincipal(provider="cognito", subject="bob-sub", email="bob@example.com")
        profile = api.create_agent_profile({"handle": "@assistant:seagull.local"}, alice)["profile"]
        skill = api.create_personal_agent_asset(
            {"asset_type": "skill", "name": "Skill", "instructions": "Keep steps clear."}, alice
        )["asset"]
        api.set_agent_asset_binding(profile["handle"], {"skill_asset_id": skill["asset_id"]}, alice)

        with self.assertRaises(ApiError) as missing:
            api.set_agent_prompt(profile["handle"], {}, alice)
        self.assertEqual(400, missing.exception.status_code)
        with self.assertRaises(ApiError) as malformed:
            api.set_agent_prompt(profile["handle"], {"instructions": 123}, alice)
        self.assertEqual(400, malformed.exception.status_code)
        with self.assertRaises(ApiError) as too_long:
            api.set_agent_prompt(profile["handle"], {"instructions": "x" * 12001}, alice)
        self.assertEqual(400, too_long.exception.status_code)
        self.assertIsNone(api.read_agent_prompt(profile["handle"], principal=alice)["prompt"])

        saved = api.set_agent_prompt(
            profile["handle"], {"instructions": "Reply in a calm voice."}, alice
        )["prompt"]
        self.assertEqual("Reply in a calm voice.", saved["instructions"])
        self.assertEqual(saved, api.read_agent_prompt(profile["handle"], principal=alice)["prompt"])
        self.assertEqual(
            skill["asset_id"],
            api.read_agent_asset_binding(profile["handle"], principal=alice)["binding"]["skill_asset_id"],
        )

        with self.assertRaises(ApiError) as denied:
            api.read_agent_prompt(profile["handle"], principal=bob)
        self.assertEqual(403, denied.exception.status_code)

        self.assertIsNone(api.set_agent_prompt(profile["handle"], {"instructions": "   "}, alice)["prompt"])
        binding = api.read_agent_asset_binding(profile["handle"], principal=alice)["binding"]
        self.assertIsNone(binding["prompt_asset_id"])
        self.assertEqual(skill["asset_id"], binding["skill_asset_id"])

    def test_local_api_chat_message_can_deliver_through_message_hub_sender(self) -> None:
        hub = FakeMessageHubSender()
        api = LocalSocialApi.in_memory(auth_required=True, message_hub_sender=hub)
        principal = AuthPrincipal(provider="cognito", subject="alice-sub", email="alice@example.com")
        sender = api.create_agent_profile(
            {
                "handle": "@alice:seagull.local",
            },
            principal,
        )["profile"]
        assistant = api.create_agent_profile(
            {
                "handle": "@assistant:seagull.local",
                "display_name": "Assistant",
            },
            principal,
        )["profile"]
        chat = api.create_agent_chat(
            {
                "agent_handle": assistant["handle"],
                "sender_handle": sender["handle"],
            },
            principal,
        )["chat"]

        message = api.create_agent_chat_message(
            chat["chat_id"],
            {"content": "Plan the MVP."},
            principal,
        )["message"]
        messages = api.list_agent_chat_messages(chat["chat_id"], principal=principal)["items"]
        updated_chat = api.read_agent_chat(chat["chat_id"], principal=principal)["chat"]

        self.assertEqual(
            [
                {
                    "sender_handle": "@alice:seagull.local",
                    "recipient_handle": "@assistant:seagull.local",
                    "content": "Plan the MVP.",
                    "thread_id": None,
                }
            ],
            hub.sent,
        )
        self.assertEqual("delivered", message["delivery_status"])
        self.assertEqual("message_1", message["hub_message_id"])
        self.assertEqual("thread_1", message["hub_thread_id"])
        self.assertEqual([message["chat_message_id"]], [item["chat_message_id"] for item in messages])
        self.assertEqual("thread_1", updated_chat["hub_thread_id"])

    def test_local_api_registers_profiles_at_creation_and_not_on_chat_send(self) -> None:
        hub = FakeMessageHubSender()
        registry = RecordingAgentRegistry()
        api = LocalSocialApi.in_memory(
            auth_required=True,
            message_hub_sender=hub,
            agent_registry=registry,
        )
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        sender = api.create_agent_profile({"handle": "@alice:seagull.local"}, principal)["profile"]
        assistant = api.create_agent_profile(
            {"handle": "@assistant:seagull.local", "display_name": "Assistant"},
            principal,
        )["profile"]

        self.assertEqual(
            [("@alice:seagull.local", None), ("@assistant:seagull.local", "Assistant")],
            registry.registered,
        )

        registry.registered.clear()
        chat = api.create_agent_chat(
            {"agent_handle": assistant["handle"], "sender_handle": sender["handle"]},
            principal,
        )["chat"]
        message = api.create_agent_chat_message(
            chat["chat_id"],
            {"content": "Plan the MVP."},
            principal,
        )["message"]

        # The chat-send path relies on creation-time registration; it must not
        # re-register handles with the hub on every send.
        self.assertEqual([], registry.registered)
        self.assertEqual(1, len(hub.sent))
        self.assertEqual("delivered", message["delivery_status"])

    def test_local_api_chat_message_generates_provider_backed_reply(self) -> None:
        ai_client = FakeAiRunClient()
        api = LocalSocialApi.in_memory(auth_required=True, ai_run_client=ai_client)
        principal = AuthPrincipal(provider="cognito", subject="alice-sub", email="alice@example.com")
        assistant = api.create_agent_profile(
            {
                "handle": "@assistant:seagull.local",
                "display_name": "Assistant",
                "bio": "Owned planning agent.",
            },
            principal,
        )["profile"]
        prompt = api.create_personal_agent_asset(
            {
                "asset_type": "prompt",
                "name": "Concise assistant",
                "instructions": "Answer directly.",
            },
            principal,
        )["asset"]
        skill = api.create_personal_agent_asset(
            {
                "asset_type": "skill",
                "name": "Planning skill",
                "instructions": "Plan in steps.",
            },
            principal,
        )["asset"]
        api.set_agent_asset_binding(
            assistant["handle"],
            {"prompt_asset_id": prompt["asset_id"], "skill_asset_id": skill["asset_id"]},
            principal,
        )
        chat = api.create_agent_chat({"agent_handle": assistant["handle"]}, principal)["chat"]

        result = api.create_agent_chat_message(
            chat["chat_id"],
            {"content": "Plan the MVP."},
            principal,
        )
        messages = api.list_agent_chat_messages(chat["chat_id"], principal=principal)["items"]

        reply = result["reply"]
        self.assertIsNotNone(reply)
        self.assertEqual("agent", reply["sender_type"])
        self.assertEqual("Here is the plan.", reply["content"])
        self.assertEqual("airun_1", reply["ai_run_id"])
        self.assertEqual("completed", reply["ai_run_state"])
        self.assertIsNone(result["message"]["ai_error"])
        self.assertEqual(
            [result["message"]["chat_message_id"], reply["chat_message_id"]],
            [item["chat_message_id"] for item in messages],
        )

        self.assertEqual(1, len(ai_client.requests))
        request = ai_client.requests[0]
        self.assertEqual(assistant["agent_id"], request["actor_agent_id"])
        self.assertEqual([{"role": "user", "content": "Plan the MVP."}], request["input_messages"])
        self.assertEqual(f"chat-reply:{result['message']['chat_message_id']}", request["idempotency_key"])
        system_instructions = request["system_instructions"]
        self.assertIn("Platform rules", system_instructions)
        self.assertIn("@assistant:seagull.local", system_instructions)
        self.assertIn("Answer directly.", system_instructions)
        self.assertIn("Plan in steps.", system_instructions)

        # Prompt edits apply to the next reply in an existing chat, while the
        # chat's skill snapshot remains unchanged.
        api.set_agent_prompt(
            assistant["handle"],
            {"instructions": "Ask one clarifying question first."},
            principal,
        )
        api.create_agent_chat_message(chat["chat_id"], {"content": "Continue."}, principal)
        self.assertEqual(2, len(ai_client.requests))
        next_system = ai_client.requests[1]["system_instructions"]
        self.assertIn("Ask one clarifying question first.", next_system)
        self.assertNotIn("Answer directly.", next_system)
        self.assertIn("Plan in steps.", next_system)

        api.set_agent_prompt(assistant["handle"], {"instructions": ""}, principal)
        api.create_agent_chat_message(chat["chat_id"], {"content": "Use the default behavior."}, principal)
        self.assertEqual(3, len(ai_client.requests))
        reset_system = ai_client.requests[2]["system_instructions"]
        self.assertNotIn("Ask one clarifying question first.", reset_system)
        self.assertNotIn("Answer directly.", reset_system)
        self.assertIn("Plan in steps.", reset_system)

    def test_local_api_chat_reply_failure_keeps_message_and_records_ai_state(self) -> None:
        denied_client = FakeAiRunClient(
            run={"run_id": "airun_9", "state": "denied", "denial_reason": "insufficient credits"}
        )
        api = LocalSocialApi.in_memory(auth_required=True, ai_run_client=denied_client)
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        assistant = api.create_agent_profile({"handle": "@assistant:seagull.local"}, principal)["profile"]
        chat = api.create_agent_chat({"agent_handle": assistant["handle"]}, principal)["chat"]

        denied = api.create_agent_chat_message(chat["chat_id"], {"content": "Plan."}, principal)

        self.assertIsNone(denied["reply"])
        self.assertEqual("stored", denied["message"]["delivery_status"])
        self.assertEqual("airun_9", denied["message"]["ai_run_id"])
        self.assertEqual("denied", denied["message"]["ai_run_state"])
        self.assertEqual("insufficient credits", denied["message"]["ai_error"])

        error_client = FakeAiRunClient(error=RuntimeError("provider unreachable"))
        error_api = LocalSocialApi.in_memory(auth_required=True, ai_run_client=error_client)
        error_assistant = error_api.create_agent_profile({"handle": "@assistant:seagull.local"}, principal)["profile"]
        error_chat = error_api.create_agent_chat({"agent_handle": error_assistant["handle"]}, principal)["chat"]

        failed = error_api.create_agent_chat_message(error_chat["chat_id"], {"content": "Plan."}, principal)

        self.assertIsNone(failed["reply"])
        self.assertEqual("stored", failed["message"]["delivery_status"])
        self.assertEqual("provider unreachable", failed["message"]["ai_error"])
        self.assertEqual(
            [failed["message"]["chat_message_id"]],
            [
                item["chat_message_id"]
                for item in error_api.list_agent_chat_messages(error_chat["chat_id"], principal=principal)["items"]
            ],
        )

    def test_local_api_chat_message_without_ai_client_returns_no_reply(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        assistant = api.create_agent_profile({"handle": "@assistant:seagull.local"}, principal)["profile"]
        chat = api.create_agent_chat({"agent_handle": assistant["handle"]}, principal)["chat"]

        result = api.create_agent_chat_message(chat["chat_id"], {"content": "Plan."}, principal)

        self.assertIsNone(result["reply"])
        self.assertEqual("stored", result["message"]["delivery_status"])
        self.assertIsNone(result["message"]["ai_run_id"])

    def test_social_surface_works_with_no_provider_and_no_message_hub(self) -> None:
        # Regression guard for the concept doc's hardest guarantee: "Feed, Inbox,
        # Live, delivery, tasks, safety, and audit must continue to work when no AI
        # provider is configured" (packages/gulls/docs/concept.md). The shared AI
        # Provider and the message hub are both optional infrastructure, so a
        # deployment with neither configured must still store and read everything.
        api = LocalSocialApi.in_memory(
            auth_required=True,
            message_hub_sender=None,
            ai_run_client=None,
        )
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        author = api.create_agent_profile({"handle": "@alice:seagull.local"}, principal)["profile"]
        assistant = api.create_agent_profile({"handle": "@assistant:seagull.local"}, principal)["profile"]

        # Feed: publish and follow still work with no infrastructure configured.
        post = api.create_post(
            {"author_handle": author["handle"], "text": "Provider-free post."},
            principal,
        )["post"]
        api.follow_agent(
            {"follower_handle": author["handle"], "followed_handle": assistant["handle"]},
            principal,
        )
        feed = api.read_home_feed(principal=principal)["items"]

        # Inbox: the chat is stored durably and is readable back.
        chat = api.create_agent_chat({"agent_handle": assistant["handle"]}, principal)["chat"]
        result = api.create_agent_chat_message(chat["chat_id"], {"content": "Plan the MVP."}, principal)
        message = result["message"]
        stored = api.list_agent_chat_messages(chat["chat_id"], principal=principal)["items"]

        self.assertEqual([post["post_id"]], [item["post_id"] for item in feed])
        self.assertEqual("Provider-free post.", feed[0]["text"])

        # Stored, not delivered: no hub means no delivery, but never a lost message.
        self.assertEqual("stored", message["delivery_status"])
        self.assertIsNone(message["delivery_error"])
        self.assertIsNone(message["hub_message_id"])
        self.assertIsNone(message["hub_thread_id"])

        # No provider means no reply and no AI run reference, not an error.
        self.assertIsNone(result["reply"])
        self.assertIsNone(message["ai_run_id"])
        self.assertIsNone(message["ai_run_state"])
        self.assertIsNone(message["ai_error"])

        self.assertEqual([message["chat_message_id"]], [item["chat_message_id"] for item in stored])
        self.assertEqual("Plan the MVP.", stored[0]["content"])

    def test_authenticated_principal_maps_to_identity_and_lists_owned_profiles(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        principal = AuthPrincipal(
            provider="cognito",
            subject="alice-sub",
            email="alice@example.com",
            display_name="Alice",
        )

        identity = api.me(principal)["identity"]
        profile = api.create_agent_profile(
            {
                "handle": "@researcher:seagull.local",
                "display_name": "Researcher",
            },
            principal,
        )["profile"]

        self.assertEqual("cognito", identity["provider"])
        self.assertEqual(identity["user_id"], profile["owner_user_id"])
        self.assertEqual([profile["agent_id"]], [item["agent_id"] for item in api.list_owned_profiles(principal=principal)["items"]])

    def test_authenticated_profile_listing_returns_next_cursor(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        first = api.create_agent_profile({"handle": "@first:gulls.ai"}, principal)["profile"]
        second = api.create_agent_profile({"handle": "@second:gulls.ai"}, principal)["profile"]

        first_page = api.list_owned_profiles(principal=principal, limit=1)
        second_page = api.list_owned_profiles(
            principal=principal,
            limit=1,
            cursor=first_page["next_cursor"],
        )

        self.assertEqual([first["agent_id"]], [item["agent_id"] for item in first_page["items"]])
        self.assertEqual([second["agent_id"]], [item["agent_id"] for item in second_page["items"]])
        self.assertIsNotNone(first_page["next_cursor"])
        self.assertIsNone(second_page["next_cursor"])

    def test_authenticated_node_pair_token_and_agent_registration_flow(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        principal = AuthPrincipal(provider="cognito", subject="alice-sub", email="alice@example.com")

        node = api.create_node({}, principal)["node"]
        token = api.create_pair_token(node["node_id"], {}, principal)["pair_token"]
        profile = api.register_agent(
            {
                "pair_token": token["pair_token"],
                "handle": "@map-reader:gulls.ai",
                "display_name": "Map Reader",
                "capabilities": ["maps", "browser"],
                "delivery_mode": "pull_webhook",
            }
        )["profile"]
        nodes = api.list_nodes(principal=principal)["items"]
        filtered_profiles = api.list_owned_profiles(
            principal=principal,
            node_id=node["node_id"],
            q="map",
            status="active",
            limit=50,
        )["items"]

        self.assertEqual(node["node_id"], profile["node_id"])
        self.assertEqual("pull_webhook", profile["delivery_mode"])
        self.assertEqual(1, nodes[0]["agent_count"])
        self.assertEqual([profile["agent_id"]], [item["agent_id"] for item in filtered_profiles])

    def test_authenticated_user_cannot_read_another_users_node(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        alice = AuthPrincipal(provider="cognito", subject="alice-sub")
        bob = AuthPrincipal(provider="cognito", subject="bob-sub")
        node = api.create_node({}, alice)["node"]

        with self.assertRaises(ApiError) as error:
            api.get_node(node["node_id"], bob)

        self.assertEqual(403, error.exception.status_code)

    def test_agent_registration_rejects_invalid_pair_token(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)

        with self.assertRaises(ApiError) as error:
            api.register_agent(
                {
                    "pair_token": "pair_missing",
                    "handle": "@missing:gulls.ai",
                }
            )

        self.assertEqual(400, error.exception.status_code)
        self.assertEqual("bad_request", error.exception.error)

    def test_local_api_accepts_text_refs_posts_and_legacy_content_posts(self) -> None:
        api = LocalSocialApi.in_memory()
        identity = api.identify_human({"provider": "local", "subject": "alice"})["identity"]
        profile = api.create_agent_profile(
            {
                "owner_user_id": identity["user_id"],
                "handle": "@researcher:seagull.local",
            }
        )["profile"]

        ref_post = api.create_post(
            {
                "owner_user_id": identity["user_id"],
                "author_handle": profile["handle"],
                "text": "Meet here tomorrow?",
                "refs": [
                    {
                        "type": "url",
                        "url": "https://maps.google.com/example",
                        "find": "identify_place_or_route",
                        "remember_as": "possible meeting place for this thread",
                    }
                ],
            }
        )["post"]
        legacy_post = api.create_post(
            {
                "owner_user_id": identity["user_id"],
                "author_handle": profile["handle"],
                "content": "Legacy content still works.",
            }
        )["post"]

        self.assertEqual(ref_post["content"], ref_post["text"])
        self.assertEqual("url", ref_post["refs"][0]["type"])
        self.assertEqual([], legacy_post["refs"])
        self.assertEqual("Legacy content still works.", legacy_post["text"])

    def test_dashboard_summary_is_scoped_to_authenticated_identity(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        alice = AuthPrincipal(provider="cognito", subject="alice-sub", email="alice@example.com")
        bob = AuthPrincipal(provider="cognito", subject="bob-sub", email="bob@example.com")
        alice_profile = api.create_agent_profile(
            {
                "handle": "@researcher:seagull.local",
                "display_name": "Researcher",
                "capabilities": ["research"],
            },
            alice,
        )["profile"]
        bob_profile = api.create_agent_profile(
            {
                "handle": "@reviewer:seagull.local",
                "display_name": "Reviewer",
            },
            bob,
        )["profile"]

        mention = api.create_post(
            {
                "author_handle": bob_profile["handle"],
                "content": f"Can {alice_profile['handle']} review this?",
            },
            bob,
        )["post"]
        api.create_moderation_record(
            {
                "target_type": "post",
                "target_id": mention["post_id"],
                "action": "review",
                "reason": "Needs human review",
            },
            alice,
        )

        alice_dashboard = api.dashboard(alice)
        bob_dashboard = api.dashboard(bob)

        self.assertEqual(["@researcher:seagull.local"], [profile["handle"] for profile in alice_dashboard["profiles"]["items"]])
        self.assertEqual(["@reviewer:seagull.local"], [profile["handle"] for profile in bob_dashboard["profiles"]["items"]])
        self.assertEqual(1, alice_dashboard["profiles"]["count"])
        self.assertIsNone(alice_dashboard["profiles"]["next_cursor"])
        self.assertEqual(mention["post_id"], alice_dashboard["feed"]["items"][0]["post_id"])
        self.assertEqual(1, alice_dashboard["notifications"]["unread_count"])
        self.assertEqual(0, bob_dashboard["notifications"]["unread_count"])
        self.assertEqual(1, alice_dashboard["moderation"]["count"])
        self.assertEqual({"ok": True, "app": "social-api", "storage": "memory"}, alice_dashboard["health"])

    def test_dashboard_summary_returns_bounded_profile_page(self) -> None:
        repository = NoFanoutReadRepository()
        api = LocalSocialApi(
            SocialApiService(
                repository,
                id_factory=DeterministicIds(),
                clock=DeterministicClock(),
            ),
            auth_required=True,
        )
        alice = AuthPrincipal(provider="cognito", subject="alice-sub")
        bob = AuthPrincipal(provider="cognito", subject="bob-sub")
        off_page_profile = None

        for index in range(12):
            off_page_profile = api.create_agent_profile(
                {
                    "handle": f"@agent-{index}:gulls.ai",
                    "display_name": f"Agent {index}",
                },
                alice,
            )["profile"]
        self.assertIsNotNone(off_page_profile)
        bob_profile = api.create_agent_profile({"handle": "@reviewer:gulls.ai"}, bob)["profile"]
        mention = api.create_post(
            {
                "author_handle": bob_profile["handle"],
                "content": f"Can {off_page_profile['handle']} review this?",
            },
            bob,
        )["post"]

        repository.reject_fanout_reads = True
        dashboard = api.dashboard(alice)

        self.assertEqual(12, dashboard["profiles"]["count"])
        self.assertEqual(10, len(dashboard["profiles"]["items"]))
        self.assertIsNotNone(dashboard["profiles"]["next_cursor"])
        self.assertEqual(mention["post_id"], dashboard["feed"]["items"][0]["post_id"])
        self.assertEqual(1, dashboard["notifications"]["unread_count"])
        self.assertEqual(mention["post_id"], dashboard["notifications"]["items"][0]["post_id"])
        self.assertNotIn("profile_scope", dashboard["notifications"])

    def test_authenticated_owner_mismatch_is_forbidden(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")

        with self.assertRaises(ApiError) as error:
            api.create_agent_profile(
                {
                    "owner_user_id": "user_other",
                    "handle": "@researcher:seagull.local",
                },
                principal,
            )

        self.assertEqual(403, error.exception.status_code)

    def test_auth_required_rejects_missing_principal(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        identity = api.identify_human({"provider": "local", "subject": "alice"})["identity"]

        with self.assertRaises(ApiError) as error:
            api.create_agent_profile(
                {
                    "owner_user_id": identity["user_id"],
                    "handle": "@researcher:seagull.local",
                }
            )

        self.assertEqual(401, error.exception.status_code)
        self.assertEqual("unauthorized", error.exception.error)

    def test_dashboard_rejects_missing_principal_when_auth_required(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)

        with self.assertRaises(ApiError) as error:
            api.dashboard()

        self.assertEqual(401, error.exception.status_code)
        self.assertEqual("unauthorized", error.exception.error)
