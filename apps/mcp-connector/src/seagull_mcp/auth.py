from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


TOKEN_PREFIX = "sgc"
ALL_SCOPES = frozenset({"agents:read", "messages:read", "messages:write", "messages:ack"})


class TokenVerificationError(Exception):
    """Raised when connector authentication fails."""


class PermissionDeniedError(Exception):
    """Raised when an authenticated connector lacks a requested permission."""


@dataclass(frozen=True, slots=True)
class ConnectorTokenRecord:
    token_id: str
    token_hash: str
    name: str
    owner_user_id: str
    scopes: tuple[str, ...]
    agent_handles: tuple[str, ...]
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= utc_now():
            return False
        return True


@dataclass(frozen=True, slots=True)
class IssuedConnectorToken:
    token: str
    record: ConnectorTokenRecord


@dataclass(frozen=True, slots=True)
class Principal:
    owner_user_id: str
    scopes: frozenset[str]
    agent_handles: frozenset[str]
    token_id: str = "dev"
    source: str = "connector_token"

    def require_scope(self, scope: str) -> None:
        if scope not in self.scopes:
            raise PermissionDeniedError(f"missing connector scope: {scope}")

    def require_agent(self, handle: str) -> None:
        normalized = normalize_handle(handle)
        if normalized not in self.agent_handles:
            raise PermissionDeniedError(f"connector token cannot access agent: {normalized}")


class ConnectorTokenStore:
    def put_token(self, record: ConnectorTokenRecord) -> None:
        raise NotImplementedError

    def get_token(self, token_id: str) -> ConnectorTokenRecord | None:
        raise NotImplementedError

    def mark_used(self, token_id: str, used_at: datetime) -> None:
        raise NotImplementedError

    def revoke_token(self, token_id: str, revoked_at: datetime) -> ConnectorTokenRecord | None:
        raise NotImplementedError

    def list_tokens(self, owner_user_id: str) -> tuple[ConnectorTokenRecord, ...]:
        raise NotImplementedError


@dataclass(slots=True)
class InMemoryConnectorTokenStore(ConnectorTokenStore):
    _records: dict[str, ConnectorTokenRecord] = field(default_factory=dict)

    def put_token(self, record: ConnectorTokenRecord) -> None:
        self._records[record.token_id] = record

    def get_token(self, token_id: str) -> ConnectorTokenRecord | None:
        return self._records.get(token_id)

    def mark_used(self, token_id: str, used_at: datetime) -> None:
        record = self._records.get(token_id)
        if record is not None:
            self._records[token_id] = ConnectorTokenRecord(
                token_id=record.token_id,
                token_hash=record.token_hash,
                name=record.name,
                owner_user_id=record.owner_user_id,
                scopes=record.scopes,
                agent_handles=record.agent_handles,
                created_at=record.created_at,
                expires_at=record.expires_at,
                last_used_at=used_at,
                revoked_at=record.revoked_at,
            )

    def revoke_token(self, token_id: str, revoked_at: datetime) -> ConnectorTokenRecord | None:
        record = self._records.get(token_id)
        if record is None:
            return None
        updated = ConnectorTokenRecord(
            token_id=record.token_id,
            token_hash=record.token_hash,
            name=record.name,
            owner_user_id=record.owner_user_id,
            scopes=record.scopes,
            agent_handles=record.agent_handles,
            created_at=record.created_at,
            expires_at=record.expires_at,
            last_used_at=record.last_used_at,
            revoked_at=revoked_at,
        )
        self._records[token_id] = updated
        return updated

    def list_tokens(self, owner_user_id: str) -> tuple[ConnectorTokenRecord, ...]:
        return tuple(
            sorted(
                (record for record in self._records.values() if record.owner_user_id == owner_user_id),
                key=lambda record: record.created_at,
                reverse=True,
            )
        )


def issue_connector_token(
    store: ConnectorTokenStore,
    *,
    name: str,
    owner_user_id: str,
    scopes: Iterable[str],
    agent_handles: Iterable[str],
    expires_in_days: int | None = 90,
    now: datetime | None = None,
) -> IssuedConnectorToken:
    issued_at = now or utc_now()
    token_id = secrets.token_hex(12)
    secret = secrets.token_hex(32)
    token = f"{TOKEN_PREFIX}_{token_id}_{secret}"
    normalized_scopes = normalize_scopes(scopes)
    normalized_handles = normalize_handles(agent_handles)
    expires_at = None if expires_in_days is None else issued_at + timedelta(days=expires_in_days)
    record = ConnectorTokenRecord(
        token_id=token_id,
        token_hash=hash_token_parts(token_id, secret),
        name=required_string(name, "name"),
        owner_user_id=required_string(owner_user_id, "owner_user_id"),
        scopes=normalized_scopes,
        agent_handles=normalized_handles,
        created_at=issued_at,
        expires_at=expires_at,
    )
    store.put_token(record)
    return IssuedConnectorToken(token=token, record=record)


def verify_bearer_token(
    store: ConnectorTokenStore,
    token: str,
    *,
    now: datetime | None = None,
) -> Principal:
    token_id, secret = parse_connector_token(token)
    record = store.get_token(token_id)
    if record is None:
        raise TokenVerificationError("connector token not found")
    expected = hash_token_parts(token_id, secret)
    if not secrets.compare_digest(expected, record.token_hash):
        raise TokenVerificationError("connector token is invalid")
    checked_at = now or utc_now()
    if record.revoked_at is not None:
        raise TokenVerificationError("connector token is revoked")
    if record.expires_at is not None and record.expires_at <= checked_at:
        raise TokenVerificationError("connector token is expired")
    store.mark_used(token_id, checked_at)
    return Principal(
        owner_user_id=record.owner_user_id,
        scopes=frozenset(record.scopes),
        agent_handles=frozenset(record.agent_handles),
        token_id=record.token_id,
    )


def dev_principal_from_token(
    provided_token: str,
    *,
    expected_token: str | None,
    owner_user_id: str,
    agent_handles: Iterable[str],
    scopes: Iterable[str] = ALL_SCOPES,
) -> Principal | None:
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        return None
    return Principal(
        owner_user_id=required_string(owner_user_id, "owner_user_id"),
        scopes=frozenset(normalize_scopes(scopes)),
        agent_handles=frozenset(normalize_handles(agent_handles)),
        source="dev_token",
    )


def parse_authorization_header(value: str | None) -> str:
    if not value:
        raise TokenVerificationError("missing authorization header")
    parts = value.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise TokenVerificationError("authorization header must be bearer token")
    return parts[1].strip()


def parse_connector_token(token: str) -> tuple[str, str]:
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX or not parts[1] or not parts[2]:
        raise TokenVerificationError("connector token has invalid format")
    return parts[1], parts[2]


def hash_token_parts(token_id: str, secret: str) -> str:
    return hashlib.sha256(f"{token_id}.{secret}".encode("utf-8")).hexdigest()


def normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    normalized = sorted({required_string(scope, "scope") for scope in scopes})
    unknown = [scope for scope in normalized if scope not in ALL_SCOPES]
    if unknown:
        raise ValueError(f"unknown connector scopes: {', '.join(unknown)}")
    return tuple(normalized)


def normalize_handles(handles: Iterable[str]) -> tuple[str, ...]:
    normalized = []
    seen = set()
    for handle in handles:
        value = normalize_handle(handle)
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    if not normalized:
        raise ValueError("agent_handles must include at least one handle")
    return tuple(normalized)


def normalize_handle(handle: str) -> str:
    value = required_string(handle, "handle").lower()
    if not value.startswith("@") or ":" not in value:
        raise ValueError("agent handle must look like @name:domain")
    return value


def required_string(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} is required")
    return stripped


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def datetime_from_string(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def record_to_dict(record: ConnectorTokenRecord, *, include_hash: bool = False) -> dict[str, object]:
    body: dict[str, object] = {
        "token_id": record.token_id,
        "name": record.name,
        "owner_user_id": record.owner_user_id,
        "scopes": list(record.scopes),
        "agent_handles": list(record.agent_handles),
        "active": record.active,
        "created_at": datetime_to_string(record.created_at),
        "expires_at": datetime_to_string(record.expires_at),
        "last_used_at": datetime_to_string(record.last_used_at),
        "revoked_at": datetime_to_string(record.revoked_at),
    }
    if include_hash:
        body["token_hash"] = record.token_hash
    return body
