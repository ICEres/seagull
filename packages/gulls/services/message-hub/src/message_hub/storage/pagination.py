"""Small, storage-neutral cursor helpers for message history pages.

The cursor deliberately includes the query scope.  A cursor copied from one
agent's inbox or one thread therefore cannot be replayed against another
scope, even when the record id happens to exist there.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar


class InvalidCursor(ValueError):
    """The supplied pagination cursor is malformed or for another query."""


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CursorPage(Generic[T]):
    items: tuple[T, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CursorPosition:
    kind: str
    scope: str
    created_at: str
    record_id: str


def encode_cursor(*, kind: str, scope: str, created_at: datetime | str, record_id: str) -> str:
    value = created_at if isinstance(created_at, str) else created_at.isoformat()
    payload = {
        "v": 1,
        "kind": str(kind),
        "scope": str(scope),
        "created_at": value,
        "id": str(record_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str | None, *, kind: str, scope: str) -> CursorPosition | None:
    if cursor is None or not str(cursor).strip():
        return None
    value = str(cursor).strip()
    if len(value) > 4096:
        raise InvalidCursor("cursor is too long")
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise InvalidCursor("cursor is invalid") from exc
    if not isinstance(payload, dict):
        raise InvalidCursor("cursor is invalid")
    if payload.get("v") != 1 or payload.get("kind") != kind or payload.get("scope") != scope:
        raise InvalidCursor("cursor does not belong to this query")
    created_at = payload.get("created_at")
    record_id = payload.get("id")
    if not isinstance(created_at, str) or not created_at or not isinstance(record_id, str) or not record_id:
        raise InvalidCursor("cursor is invalid")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidCursor("cursor timestamp is invalid") from exc
    return CursorPosition(kind=kind, scope=scope, created_at=created_at, record_id=record_id)


def cursor_after(*, kind: str, scope: str, created_at: datetime | str, record_id: str) -> str:
    return encode_cursor(kind=kind, scope=scope, created_at=created_at, record_id=record_id)
