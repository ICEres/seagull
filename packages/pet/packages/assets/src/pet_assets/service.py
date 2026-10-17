"""Owned-agent asset and binding rules.

The service is deliberately keyed by ``agent_id``, never by handle. Handles,
profiles, and ownership of an *agent* are gulls/seagulls concerns; Pet only
owns what a human attaches to an agent they already own. Callers resolve the
handle and check agent ownership first, then hand the resolved ``agent_id``
here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from pet_assets.models import (
    PERSONAL_AGENT_ASSET_TYPES,
    AgentAssetBinding,
    PersonalAgentAsset,
    utc_now,
)
from pet_assets.repository import PetAssetRepository


IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]


class PetAssetError(Exception):
    """Base error for owned-agent asset failures."""


class InvalidPetAssetRequestError(PetAssetError):
    """Raised when an asset request is invalid."""


class PetAssetNotFoundError(PetAssetError):
    """Raised when a required asset is missing."""


class PetAssetPermissionDeniedError(PetAssetError):
    """Raised when a human does not own the requested asset."""


class PetAssetService:
    def __init__(
        self,
        repository: PetAssetRepository,
        *,
        id_factory: IdFactory,
        clock: Clock = utc_now,
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory
        self._clock = clock

    def create_personal_agent_asset(
        self,
        *,
        owner_user_id: str,
        asset_type: str,
        name: str,
        instructions: str,
        description: str | None = None,
        style: str | None = None,
        tags: Sequence[str] = (),
        max_output_chars: int | None = None,
    ) -> PersonalAgentAsset:
        now = self._clock()
        asset = PersonalAgentAsset(
            asset_id=self._id_factory("asset"),
            owner_user_id=owner_user_id,
            asset_type=normalize_personal_agent_asset_type(asset_type),
            name=normalized_required(name, "name"),
            instructions=normalized_required(instructions, "instructions"),
            description=clean_optional(description),
            style=clean_optional(style),
            tags=clean_string_tuple(tags, "tags"),
            max_output_chars=normalize_optional_max_output_chars(max_output_chars),
            created_at=now,
            updated_at=now,
        )
        self._repository.put_personal_agent_asset(asset)
        return asset

    def list_personal_agent_assets(
        self,
        owner_user_id: str,
        *,
        asset_type: str | None = None,
    ) -> tuple[PersonalAgentAsset, ...]:
        assets = self._repository.list_personal_agent_assets_by_owner(owner_user_id)
        if asset_type is None:
            return assets
        normalized_type = normalize_personal_agent_asset_type(asset_type)
        return tuple(asset for asset in assets if asset.asset_type == normalized_type)

    def get_personal_agent_asset(
        self,
        *,
        owner_user_id: str,
        asset_id: str,
    ) -> PersonalAgentAsset:
        asset = self.require_asset(asset_id)
        self.require_asset_owner(owner_user_id, asset)
        return asset

    def set_agent_asset_binding(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        prompt_asset_id: str | None = None,
        skill_asset_id: str | None = None,
    ) -> AgentAssetBinding:
        prompt_asset = self.optional_owned_asset(
            owner_user_id=owner_user_id,
            asset_id=prompt_asset_id,
            expected_asset_type="prompt",
        )
        skill_asset = self.optional_owned_asset(
            owner_user_id=owner_user_id,
            asset_id=skill_asset_id,
            expected_asset_type="skill",
        )
        now = self._clock()
        existing = self._repository.get_agent_asset_binding(agent_id)
        binding = AgentAssetBinding(
            agent_id=agent_id,
            owner_user_id=owner_user_id,
            prompt_asset_id=None if prompt_asset is None else prompt_asset.asset_id,
            skill_asset_id=None if skill_asset is None else skill_asset.asset_id,
            created_at=now if existing is None else existing.created_at,
            updated_at=now,
        )
        self._repository.put_agent_asset_binding(binding)
        return binding

    def get_agent_asset_binding(self, agent_id: str) -> AgentAssetBinding | None:
        return self._repository.get_agent_asset_binding(agent_id)

    def set_agent_prompt(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        name: str,
        instructions: str,
    ) -> PersonalAgentAsset | None:
        """Replace the private prompt for one agent, preserving its skill binding."""
        if not isinstance(instructions, str):
            raise InvalidPetAssetRequestError("instructions must be a string")
        cleaned_instructions = clean_optional(instructions)
        if cleaned_instructions is not None and len(cleaned_instructions) > 12_000:
            raise InvalidPetAssetRequestError("instructions must be at most 12000 characters")

        existing_binding = self._repository.get_agent_asset_binding(agent_id)
        prompt = None
        if cleaned_instructions is not None:
            normalized_name = normalized_required(name, "name")
            prompt = self.create_personal_agent_asset(
                owner_user_id=owner_user_id,
                asset_type="prompt",
                name=normalized_name,
                instructions=cleaned_instructions,
            )

        if prompt is None and existing_binding is None:
            return None

        self.set_agent_asset_binding(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            prompt_asset_id=None if prompt is None else prompt.asset_id,
            skill_asset_id=None if existing_binding is None else existing_binding.skill_asset_id,
        )
        return prompt

    def require_asset(self, asset_id: str) -> PersonalAgentAsset:
        normalized_asset_id = normalized_required(asset_id, "asset_id")
        asset = self._repository.get_personal_agent_asset(normalized_asset_id)
        if asset is None:
            raise PetAssetNotFoundError(f"personal agent asset not found: {normalized_asset_id}")
        return asset

    def require_asset_owner(self, owner_user_id: str, asset: PersonalAgentAsset) -> None:
        if asset.owner_user_id != owner_user_id:
            raise PetAssetPermissionDeniedError("human does not own this personal agent asset")

    def optional_owned_asset(
        self,
        *,
        owner_user_id: str,
        asset_id: str | None,
        expected_asset_type: str,
    ) -> PersonalAgentAsset | None:
        if asset_id is None:
            return None
        asset = self.require_asset(asset_id)
        self.require_asset_owner(owner_user_id, asset)
        if asset.asset_type != expected_asset_type:
            raise InvalidPetAssetRequestError(
                f"{expected_asset_type}_asset_id must reference a {expected_asset_type} asset"
            )
        return asset


def normalize_personal_agent_asset_type(asset_type: str) -> str:
    normalized = normalized_required(asset_type, "asset_type").lower()
    if normalized not in PERSONAL_AGENT_ASSET_TYPES:
        raise InvalidPetAssetRequestError("asset_type must be prompt or skill")
    return normalized


def normalize_optional_max_output_chars(max_output_chars: int | None) -> int | None:
    if max_output_chars is None:
        return None
    if not isinstance(max_output_chars, int):
        raise InvalidPetAssetRequestError("max_output_chars must be an integer")
    return max(1, min(max_output_chars, 4000))


def normalized_required(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise InvalidPetAssetRequestError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise InvalidPetAssetRequestError(f"{field_name} is required")
    return stripped


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def clean_string_tuple(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise InvalidPetAssetRequestError(f"{field_name} must be a list")
    cleaned = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            raise InvalidPetAssetRequestError(f"{field_name} must contain only strings")
        stripped = value.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            cleaned.append(stripped)
    return tuple(cleaned)


__all__ = [
    "Clock",
    "IdFactory",
    "InvalidPetAssetRequestError",
    "PetAssetError",
    "PetAssetNotFoundError",
    "PetAssetPermissionDeniedError",
    "PetAssetService",
    "clean_optional",
    "clean_string_tuple",
    "normalize_optional_max_output_chars",
    "normalize_personal_agent_asset_type",
    "normalized_required",
]
