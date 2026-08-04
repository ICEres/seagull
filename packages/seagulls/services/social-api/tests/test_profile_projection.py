"""gulls owns identity, handles, and profiles.

Three profile shapes exist for good reasons: the protocol's ``AgentProfile`` is
the shared wire shape, while seagulls and the hub each keep a storage record
carrying fields the other has no use for. terminology.md defers storage renames
to a separate migration, so the shapes stay -- but they must agree.

These tests assert the agreement: for one logical agent, the seagulls record
and the hub record project to an equal ``AgentProfile``. That equivalence is
what makes gulls authoritative in practice rather than only in the docs, and it
is what would break first if the two drifted apart.
"""

from __future__ import annotations

from unittest import TestCase

from message_hub.domain.models import Agent
from message_hub.domain.profiles import agent_to_profile, try_agent_to_profile
from seagull_protocol.base import AgentProfile, Handle, ProtocolError, Visibility

from social_api.api.local import AuthPrincipal, LocalSocialApi
from social_api.domain.models import AgentProfileRecord
from social_api.domain.profile_projection import (
    profile_record_to_profile,
    try_profile_record_to_profile,
)
from social_api.domain.service import AgentRegistryUnavailableError, SocialApiService
from social_api.storage.memory import InMemorySocialRepository


class FailingRegistry:
    def register(self, handle: str, display_name: str | None = None) -> None:
        raise RuntimeError("hub unreachable")


class RecoveringRegistry:
    """Refuses until ``recovered`` is set, like a hub that comes back up."""

    def __init__(self) -> None:
        self.recovered = False
        self.registered: list[str] = []

    def register(self, handle: str, display_name: str | None = None) -> None:
        if not self.recovered:
            raise RuntimeError("hub unreachable")
        self.registered.append(handle)


class ProfileProjectionTest(TestCase):
    def test_both_layers_project_the_same_agent_onto_one_profile(self) -> None:
        record = AgentProfileRecord(
            agent_id="agent_1",
            owner_user_id="user_1",
            handle="@researcher:gulls.ai",
            display_name="Researcher",
            capabilities=("summarize", "cite"),
            status="active",
        )
        hub_agent = Agent(
            agent_id="agent_1",
            handle="@researcher:gulls.ai",
            display_name="Researcher",
            capabilities=("summarize", "cite"),
            status="active",
        )

        from_seagulls = profile_record_to_profile(record)
        from_gulls = agent_to_profile(hub_agent)

        # The fields both layers actually store must agree exactly.
        self.assertEqual(from_gulls.handle, from_seagulls.handle)
        self.assertEqual(from_gulls.display_name, from_seagulls.display_name)
        self.assertEqual(from_gulls.capabilities, from_seagulls.capabilities)
        self.assertEqual(from_gulls.status, from_seagulls.status)
        self.assertEqual(Handle("@researcher:gulls.ai"), from_seagulls.handle)
        self.assertIsInstance(from_seagulls, AgentProfile)

    def test_projection_normalizes_the_handle(self) -> None:
        record = AgentProfileRecord(
            agent_id="agent_1",
            owner_user_id="user_1",
            handle="@Map-Reader:Gulls.AI",
        )

        self.assertEqual("@map-reader:gulls.ai", profile_record_to_profile(record).handle.value)

    def test_seagulls_projection_carries_the_relationship_policy(self) -> None:
        record = AgentProfileRecord(
            agent_id="agent_1",
            owner_user_id="user_1",
            handle="@reviewer:gulls.ai",
            relationship_posture="trusted_reviewer",
            allowed_use_terms=("return_feedback",),
            contact_explanation="Reviews drafts.",
            node_id="node_1",
        )

        profile = profile_record_to_profile(record)

        self.assertEqual("trusted_reviewer", profile.relationship_posture)
        self.assertEqual(("return_feedback",), profile.allowed_use_terms)
        self.assertEqual("Reviews drafts.", profile.contact_explanation)
        self.assertEqual("user_1", profile.owner_user_id)
        self.assertEqual("node_1", profile.node_id)
        self.assertEqual(Visibility.PUBLIC, profile.visibility)

    def test_guest_handles_are_not_profiles(self) -> None:
        # The hub mints guests as @guest_<hex> with no server part, which is
        # not a valid protocol handle. Guests are transient senders, not
        # profiles, so the tolerant projection returns None instead of raising.
        guest = Agent(agent_id="agent_guest", handle="@guest_0123456789abcdef")

        with self.assertRaises(ProtocolError):
            agent_to_profile(guest)
        self.assertIsNone(try_agent_to_profile(guest))

        bad_record = AgentProfileRecord(
            agent_id="agent_1", owner_user_id="user_1", handle="not-a-handle"
        )
        self.assertIsNone(try_profile_record_to_profile(bad_record))

    def test_a_created_profile_projects_cleanly(self) -> None:
        api = LocalSocialApi.in_memory(auth_required=True)
        principal = AuthPrincipal(provider="cognito", subject="alice-sub")
        created = api.create_agent_profile(
            {"handle": "@alice:seagull.local", "display_name": "Alice", "capabilities": ["chat"]},
            principal,
        )["profile"]

        record = AgentProfileRecord(
            agent_id=created["agent_id"],
            owner_user_id=created["owner_user_id"],
            handle=created["handle"],
            display_name=created["display_name"],
            capabilities=tuple(created["capabilities"]),
        )

        self.assertEqual("@alice:seagull.local", profile_record_to_profile(record).handle.value)


class AuthoritativeRegistryTest(TestCase):
    """Opting in makes gulls the identity authority in practice."""

    def _service(self, **kwargs) -> SocialApiService:
        return SocialApiService(
            InMemorySocialRepository(),
            agent_registry=FailingRegistry(),
            **kwargs,
        )

    def test_strict_mode_refuses_a_profile_gulls_did_not_accept(self) -> None:
        service = self._service(require_agent_registry=True)
        alice = service.identify_human(provider="local", subject="alice")

        with self.assertRaises(AgentRegistryUnavailableError):
            service.create_agent_profile(
                owner_user_id=alice.user_id,
                handle="@researcher:seagull.local",
            )

        # Nothing may survive the refusal. A seagulls-only row is exactly the
        # ghost strict mode exists to prevent, and it would hold the handle
        # against every later attempt.
        repository = service._repository  # noqa: SLF001 - test wiring
        self.assertIsNone(repository.get_agent_profile_by_handle("@researcher:seagull.local"))

    def test_the_handle_is_free_again_once_the_registry_recovers(self) -> None:
        registry = RecoveringRegistry()
        service = SocialApiService(
            InMemorySocialRepository(),
            agent_registry=registry,
            require_agent_registry=True,
        )
        alice = service.identify_human(provider="local", subject="alice")

        with self.assertRaises(AgentRegistryUnavailableError):
            service.create_agent_profile(
                owner_user_id=alice.user_id,
                handle="@researcher:seagull.local",
            )

        registry.recovered = True
        profile = service.create_agent_profile(
            owner_user_id=alice.user_id,
            handle="@researcher:seagull.local",
        )

        self.assertEqual("@researcher:seagull.local", profile.handle)
        self.assertEqual(["@researcher:seagull.local"], registry.registered)

    def test_default_stays_best_effort(self) -> None:
        # Registration has been best-effort by deliberate design; the default
        # must not change under anyone's feet.
        service = self._service()
        alice = service.identify_human(provider="local", subject="alice")

        with self.assertLogs("social_api.domain.service", level="WARNING"):
            profile = service.create_agent_profile(
                owner_user_id=alice.user_id,
                handle="@researcher:seagull.local",
            )

        self.assertEqual("@researcher:seagull.local", profile.handle)
