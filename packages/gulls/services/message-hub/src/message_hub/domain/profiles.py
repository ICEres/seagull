"""Project the hub's agent record onto the shared protocol profile.

gulls owns identity, handles, and profiles (packages/gulls/docs/terminology.md),
and ``seagull_protocol.AgentProfile`` is the shared shape that ownership is
expressed in. The hub keeps its own ``Agent`` storage record -- it carries
delivery concerns (``inbox_posture``, ``webhook_url``, ``trigger_mode``) that do
not belong in a protocol type, and terminology.md defers storage renames to a
separate migration -- but anything crossing a layer boundary travels as an
``AgentProfile``.

Guest handles are the one shape that will not project: the hub mints them as
``@guest_<hex>`` with no server part, which is not a valid protocol handle.
Guests are transient senders rather than profiles, so ``try_agent_to_profile``
returns None for them instead of raising.
"""

from __future__ import annotations

from seagull_protocol.base import (
    AgentProfile,
    Handle,
    ProtocolError,
    Visibility,
)

from message_hub.domain.models import Agent


def agent_to_profile(agent: Agent) -> AgentProfile:
    """Project a stored hub agent onto the shared profile shape.

    Raises ``ProtocolError`` when the handle is not a valid protocol handle.
    """
    return AgentProfile(
        handle=Handle(agent.handle),
        display_name=agent.display_name,
        capabilities=tuple(agent.capabilities),
        status=agent.status,
        visibility=Visibility.PUBLIC,
    )


def try_agent_to_profile(agent: Agent) -> AgentProfile | None:
    """Same projection, but None for handles that are not profiles (guests)."""
    try:
        return agent_to_profile(agent)
    except ProtocolError:
        return None


__all__ = ["agent_to_profile", "try_agent_to_profile"]
