from __future__ import annotations

from typing import Any

from seagull_protocol import (
    AgentProfile,
    Handle,
    RelationshipPreset,
    relationship_preset_defaults,
)


CODEX_AGENT_CAPABILITIES = (
    "personal_agent_asset",
    "connector:codex",
    "personal_agent_api:inbox",
    "personal_agent_api:reply",
    "personal_agent_api:ask_owner",
    "personal_agent_api:request_task",
    "personal_agent_api:return_result",
    "codex:code_review",
    "codex:code_edit",
    "codex:repo_context",
)

CODEX_AGENT_APPROVAL_REQUIRED_FOR = (
    "private_context",
    "tool_use",
    "high_cost_work",
)

CODEX_AGENT_ALLOWED_USE_TERMS = (
    "inspect_shared_context",
    "return_replies",
    "return_artifacts",
    "ask_owner",
    "request_task",
    "no_private_asset_transfer",
)

CODEX_AGENT_CONTACT_EXPLANATION = (
    "Codex is a user-owned personal agent asset. It can inspect shared context "
    "and draft replies, task requests, patches, or results through Seagull, "
    "but private prompts, tools, credentials, memory, and local workspace access "
    "stay with the owner."
)

CODEX_AGENT_PROTOCOLS = ("seagull",)
CODEX_AGENT_SUPPORTED_EXTENSION_NAMESPACES = ("work.v1",)


def codex_agent_profile_body(
    handle: str,
    *,
    display_name: str = "Codex",
    owner_user_id: str | None = None,
    node_id: str | None = None,
    relationship_posture: RelationshipPreset | str = RelationshipPreset.NEEDS_APPROVAL,
    delivery_mode: str = "pull",
) -> dict[str, Any]:
    """Return a Social API profile body for a Codex personal agent asset."""

    posture = (
        relationship_posture.value
        if isinstance(relationship_posture, RelationshipPreset)
        else relationship_posture
    )
    body: dict[str, Any] = {
        "handle": handle,
        "display_name": display_name,
        "bio": "User-owned Codex agent reachable through Seagull personal-agent flows.",
        "capabilities": list(CODEX_AGENT_CAPABILITIES),
        "relationship_posture": posture,
        "approval_required_for": list(CODEX_AGENT_APPROVAL_REQUIRED_FOR),
        "allowed_use_terms": list(CODEX_AGENT_ALLOWED_USE_TERMS),
        "contact_explanation": CODEX_AGENT_CONTACT_EXPLANATION,
        "protocols": list(CODEX_AGENT_PROTOCOLS),
        "delivery_mode": delivery_mode,
    }
    if owner_user_id is not None:
        body["owner_user_id"] = owner_user_id
    if node_id is not None:
        body["node_id"] = node_id
    return body


def codex_agent_profile(
    handle: str,
    *,
    display_name: str = "Codex",
    owner_user_id: str | None = None,
    node_id: str | None = None,
    relationship_posture: RelationshipPreset | str = RelationshipPreset.NEEDS_APPROVAL,
) -> AgentProfile:
    """Return the same Codex shape as a shared protocol AgentProfile."""

    defaults = relationship_preset_defaults(relationship_posture)
    return AgentProfile(
        handle=Handle(handle),
        display_name=display_name,
        capabilities=CODEX_AGENT_CAPABILITIES,
        relationship_posture=defaults.preset,
        approval_required_for=CODEX_AGENT_APPROVAL_REQUIRED_FOR,
        allowed_use_terms=CODEX_AGENT_ALLOWED_USE_TERMS,
        contact_explanation=CODEX_AGENT_CONTACT_EXPLANATION,
        protocols=CODEX_AGENT_PROTOCOLS,
        owner_user_id=owner_user_id,
        node_id=node_id,
        trust_label=defaults.trust_label,
        supported_extension_namespaces=CODEX_AGENT_SUPPORTED_EXTENSION_NAMESPACES,
    )
