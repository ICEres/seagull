from __future__ import annotations

from typing import Any


ERROR_MESSAGE = "An email address is required."


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    request = event.get("request")
    attributes = request.get("userAttributes", {}) if isinstance(request, dict) else {}
    email = attributes.get("email") if isinstance(attributes, dict) else None
    if not isinstance(email, str):
        email = event.get("userName")

    if not _has_email_address(email):
        raise ValueError(ERROR_MESSAGE)

    return event


def _has_email_address(email: object) -> bool:
    if not isinstance(email, str):
        return False
    local_part, separator, domain = email.strip().rpartition("@")
    return bool(local_part and separator and domain)
