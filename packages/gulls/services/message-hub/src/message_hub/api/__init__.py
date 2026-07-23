"""API adapters for the message hub."""

from message_hub.api.html_card import (
    HTML_MEDIA_TYPE,
    accept_prefers_html,
    render_agent_card_html,
)
from message_hub.api.local import ApiError, LocalMessageHubApi

__all__ = [
    "ApiError",
    "HTML_MEDIA_TYPE",
    "LocalMessageHubApi",
    "accept_prefers_html",
    "render_agent_card_html",
]
