"""Owned-agent asset records.

Pet / My Agents owns the private prompts, skills, and per-agent bindings a
human configures for the agents they own. These are product-layer records: they
never carry network state, and gulls does not need them to route, deliver, or
audit a message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


PERSONAL_AGENT_ASSET_TYPES = frozenset({"prompt", "skill"})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class PersonalAgentAsset:
    asset_id: str
    owner_user_id: str
    asset_type: str
    name: str
    instructions: str
    description: str | None = None
    style: str | None = None
    tags: tuple[str, ...] = ()
    max_output_chars: int | None = None
    status: str = "active"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AgentAssetBinding:
    agent_id: str
    owner_user_id: str
    prompt_asset_id: str | None = None
    skill_asset_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


__all__ = [
    "PERSONAL_AGENT_ASSET_TYPES",
    "AgentAssetBinding",
    "PersonalAgentAsset",
    "utc_now",
]
