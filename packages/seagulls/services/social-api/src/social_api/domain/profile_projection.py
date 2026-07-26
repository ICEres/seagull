"""Project the seagulls profile record onto the shared protocol profile.

gulls owns identity, handles, and profiles; seagulls holds a storage record
with product-layer additions (``bio``, ``node_id``, ``delivery_mode``,
``last_seen_at``, ownership, timestamps). ``seagull_protocol.AgentProfile`` is
the shared shape both layers agree on, so anything crossing the boundary
travels as one.

The hub has a matching projection (``message_hub.domain.profiles``). Both
produce the same ``AgentProfile`` for the same logical agent -- that
equivalence is what makes gulls authoritative in practice rather than only in
the docs, and it is asserted in the tests.
"""

from __future__ import annotations

from seagull_protocol.base import (
    AgentProfile,
    Handle,
    ProtocolError,
    Visibility,
)

from social_api.domain.models import AgentProfileRecord


def profile_record_to_profile(record: AgentProfileRecord) -> AgentProfile:
    """Project a stored seagulls profile onto the shared profile shape."""
    return AgentProfile(
        handle=Handle(record.handle),
        display_name=record.display_name,
        capabilities=tuple(record.capabilities),
        relationship_posture=record.relationship_posture,
        approval_required_for=tuple(record.approval_required_for),
        allowed_use_terms=tuple(record.allowed_use_terms),
        contact_explanation=record.contact_explanation,
        protocols=tuple(record.protocols),
        status=record.status,
        owner_user_id=record.owner_user_id,
        node_id=record.node_id,
        visibility=Visibility.PUBLIC,
    )


def try_profile_record_to_profile(record: AgentProfileRecord) -> AgentProfile | None:
    try:
        return profile_record_to_profile(record)
    except ProtocolError:
        return None


__all__ = ["profile_record_to_profile", "try_profile_record_to_profile"]
