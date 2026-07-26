"""API response shapes for owned-agent assets.

Response keys are unchanged from the social-api implementation this was
extracted from, so existing clients and routes see the same payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pet_assets.models import AgentAssetBinding, PersonalAgentAsset


def datetime_to_string(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def personal_agent_asset_to_dict(asset: PersonalAgentAsset) -> dict[str, Any]:
    return {
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
        "created_at": datetime_to_string(asset.created_at),
        "updated_at": datetime_to_string(asset.updated_at),
    }


def agent_asset_binding_to_dict(binding: AgentAssetBinding) -> dict[str, Any]:
    return {
        "agent_id": binding.agent_id,
        "owner_user_id": binding.owner_user_id,
        "prompt_asset_id": binding.prompt_asset_id,
        "skill_asset_id": binding.skill_asset_id,
        "created_at": datetime_to_string(binding.created_at),
        "updated_at": datetime_to_string(binding.updated_at),
    }


__all__ = [
    "agent_asset_binding_to_dict",
    "datetime_to_string",
    "personal_agent_asset_to_dict",
]
