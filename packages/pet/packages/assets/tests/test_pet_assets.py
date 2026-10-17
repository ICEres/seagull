from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

from pet_assets import (
    InMemoryPetAssetRepository,
    InvalidPetAssetRequestError,
    PetAssetNotFoundError,
    PetAssetPermissionDeniedError,
    PetAssetService,
    agent_asset_binding_to_dict,
    personal_agent_asset_to_dict,
)


class DeterministicIds:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return f"{prefix}_{self._counts[prefix]}"


def fixed_clock() -> datetime:
    return datetime(2025, 1, 1, tzinfo=timezone.utc)


class PetAssetServiceTest(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryPetAssetRepository()
        self.service = PetAssetService(
            self.repository,
            id_factory=DeterministicIds(),
            clock=fixed_clock,
        )

    def test_creates_normalized_prompt_asset(self) -> None:
        asset = self.service.create_personal_agent_asset(
            owner_user_id="user_1",
            asset_type="  PROMPT ",
            name="  Reviewer  ",
            instructions="  Be terse.  ",
            description="   ",
            tags=["review", "review", " code ", ""],
            max_output_chars=99_000,
        )

        self.assertEqual("asset_1", asset.asset_id)
        self.assertEqual("prompt", asset.asset_type)
        self.assertEqual("Reviewer", asset.name)
        self.assertEqual("Be terse.", asset.instructions)
        # Blank-only optional strings collapse to None rather than empty text.
        self.assertIsNone(asset.description)
        # Tags are de-duplicated, stripped, and empties dropped, order preserved.
        self.assertEqual(("review", "code"), asset.tags)
        # max_output_chars is clamped into the supported range.
        self.assertEqual(4000, asset.max_output_chars)

    def test_rejects_unknown_asset_type_and_bad_max_output_chars(self) -> None:
        with self.assertRaises(InvalidPetAssetRequestError):
            self.service.create_personal_agent_asset(
                owner_user_id="user_1",
                asset_type="voice",
                name="n",
                instructions="i",
            )

        with self.assertRaises(InvalidPetAssetRequestError):
            self.service.create_personal_agent_asset(
                owner_user_id="user_1",
                asset_type="prompt",
                name="n",
                instructions="i",
                max_output_chars="lots",  # type: ignore[arg-type]
            )

    def test_lists_assets_by_owner_filtered_by_type(self) -> None:
        prompt = self.service.create_personal_agent_asset(
            owner_user_id="user_1", asset_type="prompt", name="p", instructions="i"
        )
        skill = self.service.create_personal_agent_asset(
            owner_user_id="user_1", asset_type="skill", name="s", instructions="i"
        )
        self.service.create_personal_agent_asset(
            owner_user_id="user_2", asset_type="prompt", name="other", instructions="i"
        )

        everything = self.service.list_personal_agent_assets("user_1")
        prompts = self.service.list_personal_agent_assets("user_1", asset_type="prompt")

        self.assertEqual({prompt.asset_id, skill.asset_id}, {asset.asset_id for asset in everything})
        self.assertEqual([prompt.asset_id], [asset.asset_id for asset in prompts])

    def test_get_asset_refuses_a_different_owner(self) -> None:
        asset = self.service.create_personal_agent_asset(
            owner_user_id="user_1", asset_type="prompt", name="p", instructions="i"
        )

        with self.assertRaises(PetAssetPermissionDeniedError):
            self.service.get_personal_agent_asset(owner_user_id="user_2", asset_id=asset.asset_id)

        with self.assertRaises(PetAssetNotFoundError):
            self.service.get_personal_agent_asset(owner_user_id="user_1", asset_id="asset_missing")

    def test_binding_requires_matching_asset_types(self) -> None:
        prompt = self.service.create_personal_agent_asset(
            owner_user_id="user_1", asset_type="prompt", name="p", instructions="i"
        )
        skill = self.service.create_personal_agent_asset(
            owner_user_id="user_1", asset_type="skill", name="s", instructions="i"
        )

        binding = self.service.set_agent_asset_binding(
            owner_user_id="user_1",
            agent_id="agent_1",
            prompt_asset_id=prompt.asset_id,
            skill_asset_id=skill.asset_id,
        )

        self.assertEqual("agent_1", binding.agent_id)
        self.assertEqual(prompt.asset_id, binding.prompt_asset_id)
        self.assertEqual(skill.asset_id, binding.skill_asset_id)

        # A skill cannot be bound into the prompt slot.
        with self.assertRaises(InvalidPetAssetRequestError):
            self.service.set_agent_asset_binding(
                owner_user_id="user_1",
                agent_id="agent_1",
                prompt_asset_id=skill.asset_id,
            )

        # Nor can another human's asset be bound.
        with self.assertRaises(PetAssetPermissionDeniedError):
            self.service.set_agent_asset_binding(
                owner_user_id="user_2",
                agent_id="agent_1",
                prompt_asset_id=prompt.asset_id,
            )

    def test_rebinding_preserves_created_at_and_clears_unset_slots(self) -> None:
        prompt = self.service.create_personal_agent_asset(
            owner_user_id="user_1", asset_type="prompt", name="p", instructions="i"
        )
        first = self.service.set_agent_asset_binding(
            owner_user_id="user_1", agent_id="agent_1", prompt_asset_id=prompt.asset_id
        )
        second = self.service.set_agent_asset_binding(owner_user_id="user_1", agent_id="agent_1")

        self.assertEqual(first.created_at, second.created_at)
        # Omitting a slot clears it; the binding is a full replacement.
        self.assertIsNone(second.prompt_asset_id)
        self.assertEqual(second, self.service.get_agent_asset_binding("agent_1"))

    def test_unbound_agent_has_no_binding(self) -> None:
        self.assertIsNone(self.service.get_agent_asset_binding("agent_unknown"))

    def test_agent_prompt_creates_immutable_versions_and_preserves_skill_binding(self) -> None:
        skill = self.service.create_personal_agent_asset(
            owner_user_id="user_1", asset_type="skill", name="s", instructions="skill"
        )
        self.service.set_agent_asset_binding(
            owner_user_id="user_1", agent_id="agent_1", skill_asset_id=skill.asset_id
        )

        prompt = self.service.set_agent_prompt(
            owner_user_id="user_1",
            agent_id="agent_1",
            name="Agent Reply Prompt",
            instructions="Be concise.",
        )
        self.assertIsNotNone(prompt)
        assert prompt is not None
        self.assertEqual("Be concise.", prompt.instructions)
        binding = self.service.get_agent_asset_binding("agent_1")
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(prompt.asset_id, binding.prompt_asset_id)
        self.assertEqual(skill.asset_id, binding.skill_asset_id)

        updated = self.service.set_agent_prompt(
            owner_user_id="user_1",
            agent_id="agent_1",
            name="Agent Reply Prompt",
            instructions="Ask before acting.",
        )
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertNotEqual(prompt.asset_id, updated.asset_id)
        self.assertEqual("Ask before acting.", updated.instructions)
        self.assertEqual("Be concise.", self.service.require_asset(prompt.asset_id).instructions)

        self.assertIsNone(
            self.service.set_agent_prompt(
                owner_user_id="user_1",
                agent_id="agent_1",
                name="Agent Reply Prompt",
                instructions="   ",
            )
        )
        binding = self.service.get_agent_asset_binding("agent_1")
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertIsNone(binding.prompt_asset_id)
        self.assertEqual(skill.asset_id, binding.skill_asset_id)

    def test_editing_one_agent_does_not_change_a_shared_prompt_asset(self) -> None:
        shared = self.service.create_personal_agent_asset(
            owner_user_id="user_1", asset_type="prompt", name="Shared", instructions="Original"
        )
        self.service.set_agent_asset_binding(
            owner_user_id="user_1", agent_id="agent_1", prompt_asset_id=shared.asset_id
        )
        self.service.set_agent_asset_binding(
            owner_user_id="user_1", agent_id="agent_2", prompt_asset_id=shared.asset_id
        )

        replacement = self.service.set_agent_prompt(
            owner_user_id="user_1",
            agent_id="agent_1",
            name="Agent 1 Reply Prompt",
            instructions="Agent 1 only",
        )
        self.assertIsNotNone(replacement)
        assert replacement is not None
        self.assertEqual(shared.asset_id, self.service.get_agent_asset_binding("agent_2").prompt_asset_id)
        self.assertEqual("Original", self.service.require_asset(shared.asset_id).instructions)
        self.assertEqual(replacement.asset_id, self.service.get_agent_asset_binding("agent_1").prompt_asset_id)

    def test_serializers_expose_the_public_response_shape(self) -> None:
        asset = self.service.create_personal_agent_asset(
            owner_user_id="user_1",
            asset_type="prompt",
            name="Reviewer",
            instructions="Be terse.",
            tags=["review"],
        )
        binding = self.service.set_agent_asset_binding(
            owner_user_id="user_1", agent_id="agent_1", prompt_asset_id=asset.asset_id
        )

        self.assertEqual(
            {
                "asset_id": "asset_1",
                "owner_user_id": "user_1",
                "asset_type": "prompt",
                "name": "Reviewer",
                "instructions": "Be terse.",
                "description": None,
                "style": None,
                "tags": ["review"],
                "max_output_chars": None,
                "status": "active",
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
            },
            personal_agent_asset_to_dict(asset),
        )
        self.assertEqual(
            {
                "agent_id": "agent_1",
                "owner_user_id": "user_1",
                "prompt_asset_id": "asset_1",
                "skill_asset_id": None,
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
            },
            agent_asset_binding_to_dict(binding),
        )
