"""In-memory owned-agent asset storage."""

from __future__ import annotations

from pet_assets.models import AgentAssetBinding, PersonalAgentAsset


class InMemoryPetAssetRepository:
    def __init__(self) -> None:
        self._assets: dict[str, PersonalAgentAsset] = {}
        self._asset_ids_by_owner: dict[str, set[str]] = {}
        self._asset_bindings: dict[str, AgentAssetBinding] = {}

    def put_personal_agent_asset(self, asset: PersonalAgentAsset) -> None:
        self._assets[asset.asset_id] = asset
        self._asset_ids_by_owner.setdefault(asset.owner_user_id, set()).add(asset.asset_id)

    def get_personal_agent_asset(self, asset_id: str) -> PersonalAgentAsset | None:
        return self._assets.get(asset_id)

    def list_personal_agent_assets_by_owner(self, owner_user_id: str) -> tuple[PersonalAgentAsset, ...]:
        asset_ids = self._asset_ids_by_owner.get(owner_user_id, set())
        return tuple(sorted((self._assets[asset_id] for asset_id in asset_ids), key=lambda asset: asset.created_at))

    def put_agent_asset_binding(self, binding: AgentAssetBinding) -> None:
        self._asset_bindings[binding.agent_id] = binding

    def get_agent_asset_binding(self, agent_id: str) -> AgentAssetBinding | None:
        return self._asset_bindings.get(agent_id)


__all__ = ["InMemoryPetAssetRepository"]
