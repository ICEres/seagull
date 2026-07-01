"""API adapters for the message hub."""

from message_hub.api.local import ApiError, LocalMessageHubApi

__all__ = [
    "ApiError",
    "LocalMessageHubApi",
]
