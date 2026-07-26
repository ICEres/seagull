"""Pet / My Agents owned-agent assets.

Pet is a sibling product layer over gulls. It owns what a human attaches to an
agent they own -- private prompts, skills, and per-agent bindings -- and
nothing about the network itself. Identity, handles, profiles, routing, and
delivery stay in gulls; this package never reaches for them.

The DynamoDB adapter here is intentionally constructed from the same two tables
the social-api Lambda already passes, so moving ownership of this code changes
no table, route, or environment variable.

``pet_assets.dynamodb`` is not re-exported here because it imports ``boto3``,
which is Lambda-provided and absent in tests -- the same convention
``social_api.storage`` follows. Import it directly from deployment code.
"""

from pet_assets.memory import InMemoryPetAssetRepository
from pet_assets.models import (
    PERSONAL_AGENT_ASSET_TYPES,
    AgentAssetBinding,
    PersonalAgentAsset,
    utc_now,
)
from pet_assets.repository import PetAssetRepository
from pet_assets.serializers import (
    agent_asset_binding_to_dict,
    personal_agent_asset_to_dict,
)
from pet_assets.service import (
    InvalidPetAssetRequestError,
    PetAssetError,
    PetAssetNotFoundError,
    PetAssetPermissionDeniedError,
    PetAssetService,
    normalize_optional_max_output_chars,
    normalize_personal_agent_asset_type,
)

__all__ = [
    "PERSONAL_AGENT_ASSET_TYPES",
    "AgentAssetBinding",
    "InMemoryPetAssetRepository",
    "InvalidPetAssetRequestError",
    "PersonalAgentAsset",
    "PetAssetError",
    "PetAssetNotFoundError",
    "PetAssetPermissionDeniedError",
    "PetAssetRepository",
    "PetAssetService",
    "agent_asset_binding_to_dict",
    "normalize_optional_max_output_chars",
    "normalize_personal_agent_asset_type",
    "personal_agent_asset_to_dict",
    "utc_now",
]
