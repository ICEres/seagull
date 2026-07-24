"""Loose coercion helpers shared across gull services."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def without_none(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}


def datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
