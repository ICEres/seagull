"""DynamoDB owned-agent asset storage.

Item shapes and table keys are unchanged from the social-api implementation
this was extracted from: terminology.md defers storage identifier renames to a
separate migration, so the same tables keep serving the same items.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key

from pet_assets.models import AgentAssetBinding, PersonalAgentAsset


class DynamoDbPetAssetRepository:
    def __init__(
        self,
        *,
        personal_agent_assets_table: Any,
        agent_asset_bindings_table: Any,
    ) -> None:
        self._personal_agent_assets_table = personal_agent_assets_table
        self._agent_asset_bindings_table = agent_asset_bindings_table

    def put_personal_agent_asset(self, asset: PersonalAgentAsset) -> None:
        self._personal_agent_assets_table.put_item(Item=personal_agent_asset_to_item(asset))

    def get_personal_agent_asset(self, asset_id: str) -> PersonalAgentAsset | None:
        item = self._personal_agent_assets_table.get_item(Key={"asset_id": asset_id}).get("Item")
        return None if item is None else item_to_personal_agent_asset(item)

    def list_personal_agent_assets_by_owner(self, owner_user_id: str) -> tuple[PersonalAgentAsset, ...]:
        result = self._personal_agent_assets_table.query(
            IndexName="owner-created-at-index",
            KeyConditionExpression=Key("owner_user_id").eq(owner_user_id),
            ScanIndexForward=True,
        )
        return tuple(item_to_personal_agent_asset(item) for item in result.get("Items", []))

    def put_agent_asset_binding(self, binding: AgentAssetBinding) -> None:
        self._agent_asset_bindings_table.put_item(Item=agent_asset_binding_to_item(binding))

    def get_agent_asset_binding(self, agent_id: str) -> AgentAssetBinding | None:
        item = self._agent_asset_bindings_table.get_item(Key={"agent_id": agent_id}).get("Item")
        return None if item is None else item_to_agent_asset_binding(item)


def without_none(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}


def personal_agent_asset_to_item(asset: PersonalAgentAsset) -> dict[str, Any]:
    return without_none(
        {
            "asset_id": asset.asset_id,
            "owner_user_id": asset.owner_user_id,
            "asset_type": asset.asset_type,
            "name": asset.name,
            "instructions": asset.instructions,
            "description": asset.description,
            "style": asset.style,
            "tags": list(asset.tags),
            "max_output_chars": asset.max_output_chars,
            "status": asset.status,
            "created_at": asset.created_at.isoformat(),
            "updated_at": asset.updated_at.isoformat(),
        }
    )


def item_to_personal_agent_asset(item: dict[str, Any]) -> PersonalAgentAsset:
    max_output_chars = item.get("max_output_chars")
    return PersonalAgentAsset(
        asset_id=item["asset_id"],
        owner_user_id=item["owner_user_id"],
        asset_type=item["asset_type"],
        name=item["name"],
        instructions=item["instructions"],
        description=item.get("description"),
        style=item.get("style"),
        tags=tuple(item.get("tags", [])),
        max_output_chars=None if max_output_chars is None else int(max_output_chars),
        status=item.get("status", "active"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def agent_asset_binding_to_item(binding: AgentAssetBinding) -> dict[str, Any]:
    return without_none(
        {
            "agent_id": binding.agent_id,
            "owner_user_id": binding.owner_user_id,
            "prompt_asset_id": binding.prompt_asset_id,
            "skill_asset_id": binding.skill_asset_id,
            "created_at": binding.created_at.isoformat(),
            "updated_at": binding.updated_at.isoformat(),
        }
    )


def item_to_agent_asset_binding(item: dict[str, Any]) -> AgentAssetBinding:
    return AgentAssetBinding(
        agent_id=item["agent_id"],
        owner_user_id=item["owner_user_id"],
        prompt_asset_id=item.get("prompt_asset_id"),
        skill_asset_id=item.get("skill_asset_id"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


__all__ = [
    "DynamoDbPetAssetRepository",
    "agent_asset_binding_to_item",
    "item_to_agent_asset_binding",
    "item_to_personal_agent_asset",
    "personal_agent_asset_to_item",
    "without_none",
]
