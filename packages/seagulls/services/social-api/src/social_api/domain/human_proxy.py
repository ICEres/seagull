"""The network identity a signed-in human sends from.

gulls models message senders as agents (``Message.sender_agent_id``), but the
sender in an owner-to-own-agent chat is a person. Without an identity for that
person the chat cannot enter the shared Inbox at all -- which is exactly the
state this module fixes: ``sender_handle`` was an optional parameter the web
never passed, so ``_deliver_agent_chat_message`` returned early and no chat
message ever reached gulls.

One proxy per owner, derived deterministically from the owner id so it is
stable across chats, sessions, and deployments. Stability is the point: a fresh
identity per chat would fragment threads and break attribution, which is why
the guest namespace (explicitly never reused) is wrong for this.

The handle sits in the reserved ``@me_`` namespace. ``register_agent`` in the
hub refuses that prefix for everyone except the server, because the handle is
derived from an owner id -- if anyone could register one, they could mint
another person's proxy and receive that person's chat replies.
"""

from __future__ import annotations

import re


HUMAN_PROXY_HANDLE_PREFIX = "me_"

# Matches the protocol's local-name rule: a leading alphanumeric, then
# alphanumerics, underscore, dot, or hyphen.
_UNSAFE = re.compile(r"[^a-z0-9_.-]+")


class InvalidHumanProxyError(ValueError):
    """Raised when an owner id cannot produce a valid handle."""


def human_proxy_local_name(owner_user_id: str) -> str:
    """Derive the handle's local part from an owner id.

    Owner ids are already ``user_<hex>``-shaped, so this is normally a
    lowercase-and-prefix. The sanitising exists for ids that arrive from an
    identity provider in some other shape; it is deterministic, so the same
    owner always lands on the same handle.
    """
    cleaned = _UNSAFE.sub("-", (owner_user_id or "").strip().lower()).strip("-.")
    if not cleaned:
        raise InvalidHumanProxyError(f"owner_user_id yields no usable handle: {owner_user_id!r}")
    if not cleaned[0].isalnum():
        cleaned = f"u{cleaned}"
    return f"{HUMAN_PROXY_HANDLE_PREFIX}{cleaned}"


def handle_domain(handle: str) -> str:
    """Pull the domain off an ``@name:domain`` handle."""
    _, _, domain = (handle or "").partition(":")
    domain = domain.strip().lower()
    if not domain:
        raise InvalidHumanProxyError(f"handle has no domain: {handle!r}")
    return domain


def human_proxy_handle(owner_user_id: str, *, domain: str) -> str:
    """Build the full proxy handle for one owner in one domain.

    The domain is passed in rather than hardcoded so a deployment can pin every
    proxy to one namespace while tests and local runs simply follow the agent
    being chatted. A deployment that leaves it unset gets a proxy per domain
    for the same human, which is harmless but not what production wants -- see
    ``HUMAN_PROXY_DOMAIN`` in the social-api Lambda.
    """
    normalized_domain = (domain or "").strip().lower()
    if not normalized_domain:
        raise InvalidHumanProxyError("a human proxy handle needs a domain")
    return f"@{human_proxy_local_name(owner_user_id)}:{normalized_domain}"


def is_human_proxy_handle(handle: str) -> bool:
    return (handle or "").startswith(f"@{HUMAN_PROXY_HANDLE_PREFIX}")


__all__ = [
    "HUMAN_PROXY_HANDLE_PREFIX",
    "InvalidHumanProxyError",
    "handle_domain",
    "human_proxy_handle",
    "human_proxy_local_name",
    "is_human_proxy_handle",
]
