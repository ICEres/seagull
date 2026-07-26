"""Storage port for owned-agent assets.

Structural (``Protocol``) typing means an existing repository that already
implements these five methods satisfies the port without inheriting from it.
"""

from __future__ import annotations

from typing import Protocol

from pet_assets.models import AgentAssetBinding, PersonalAgentAsset


class PetAssetRepository(Protocol):
    def put_personal_agent_asset(self, asset: PersonalAgentAsset) -> None:
        ...

    def get_personal_agent_asset(self, asset_id: str) -> PersonalAgentAsset | None:
        ...

    def list_personal_agent_assets_by_owner(self, owner_user_id: str) -> tuple[PersonalAgentAsset, ...]:
        ...

    def put_agent_asset_binding(self, binding: AgentAssetBinding) -> None:
        ...

    def get_agent_asset_binding(self, agent_id: str) -> AgentAssetBinding | None:
        ...


__all__ = ["PetAssetRepository"]
