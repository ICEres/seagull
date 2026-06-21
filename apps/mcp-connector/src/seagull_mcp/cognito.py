from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib import request

from seagull_mcp.auth import (
    PermissionDeniedError,
    Principal,
    TokenVerificationError,
    normalize_handles,
    normalize_scopes,
    required_string,
)


SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class CognitoIdentityProvider(Protocol):
    def admin_get_user(self, *, UserPoolId: str, Username: str) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(slots=True)
class CognitoJwtVerifier:
    user_pool_id: str
    app_client_id: str
    region: str
    jwks_url: str | None = None
    _jwks_cache: dict[str, Any] | None = field(default=None, init=False, repr=False)

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    def verify(self, token: str, *, now_epoch: int | None = None) -> dict[str, Any]:
        header, payload, signature, signed_part = split_jwt(token)
        if header.get("alg") != "RS256":
            raise TokenVerificationError("Cognito token must use RS256")
        kid = required_string(str(header.get("kid") or ""), "kid")
        key = self._key_for_kid(kid)
        if not verify_rs256_signature(signed_part.encode("ascii"), signature, key):
            raise TokenVerificationError("Cognito token signature is invalid")
        self.validate_claims(payload, now_epoch=now_epoch)
        return payload

    def validate_claims(self, claims: dict[str, Any], *, now_epoch: int | None = None) -> None:
        if claims.get("iss") != self.issuer:
            raise TokenVerificationError("Cognito token issuer is invalid")
        if claims.get("token_use") != "access":
            raise TokenVerificationError("Cognito token must be an access token")
        if claims.get("client_id") != self.app_client_id:
            raise TokenVerificationError("Cognito token client_id is invalid")
        expires_at = int_claim(claims, "exp")
        if expires_at <= (now_epoch or int(time.time())):
            raise TokenVerificationError("Cognito token is expired")

    def _key_for_kid(self, kid: str) -> dict[str, Any]:
        for key in self._jwks().get("keys", []):
            if key.get("kid") == kid:
                return key
        self._jwks_cache = None
        for key in self._jwks().get("keys", []):
            if key.get("kid") == kid:
                return key
        raise TokenVerificationError("Cognito signing key not found")

    def _jwks(self) -> dict[str, Any]:
        if self._jwks_cache is None:
            url = self.jwks_url or f"{self.issuer}/.well-known/jwks.json"
            with request.urlopen(url, timeout=5) as response:
                self._jwks_cache = json.loads(response.read().decode("utf-8"))
        return self._jwks_cache


@dataclass(slots=True)
class CognitoPrincipalResolver:
    verifier: CognitoJwtVerifier
    user_pool_id: str
    identity_provider: CognitoIdentityProvider

    def principal_from_token(self, token: str) -> Principal:
        claims = self.verifier.verify(token)
        username = required_string(str(claims.get("username") or ""), "username")
        attributes = self._user_attributes(username)
        owner_user_id = first_text_value(
            claims,
            attributes,
            ("custom:seagull_owner_user_id", "custom:sg_owner_id"),
        ) or username
        agent_handles = split_csv(
            first_text_value(
                claims,
                attributes,
                ("custom:seagull_agent_handles", "custom:sg_handles"),
            )
            or ""
        )
        scopes = split_csv(
            first_text_value(
                claims,
                attributes,
                ("custom:seagull_scopes", "custom:sg_scopes"),
            )
            or ""
        )
        if not scopes:
            raise PermissionDeniedError("Cognito user is missing Seagull scopes")
        try:
            normalized_scopes = normalize_scopes(scopes)
            normalized_handles = normalize_handles(agent_handles)
        except ValueError as exc:
            raise PermissionDeniedError(str(exc)) from exc
        return Principal(
            owner_user_id=required_string(owner_user_id, "owner_user_id"),
            scopes=frozenset(normalized_scopes),
            agent_handles=frozenset(normalized_handles),
            token_id=str(claims.get("jti") or claims.get("sub") or username),
            source="cognito",
        )

    def _user_attributes(self, username: str) -> dict[str, str]:
        try:
            result = self.identity_provider.admin_get_user(UserPoolId=self.user_pool_id, Username=username)
        except Exception as exc:
            raise TokenVerificationError("Cognito user lookup failed") from exc
        return {
            item["Name"]: item["Value"]
            for item in result.get("UserAttributes", [])
            if item.get("Name") and item.get("Value") is not None
        }


def split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def first_text_value(
    claims: dict[str, Any],
    attributes: dict[str, str],
    names: tuple[str, ...],
) -> str | None:
    for source in (claims, attributes):
        for name in names:
            value = source.get(name)
            if value is None:
                continue
            if not isinstance(value, str):
                raise PermissionDeniedError(f"{name} must be a string")
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def split_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, str]:
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenVerificationError("Cognito token has invalid JWT format")
    header = json_b64url_decode(parts[0])
    payload = json_b64url_decode(parts[1])
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise TokenVerificationError("Cognito token has invalid JWT payload")
    return header, payload, b64url_decode(parts[2]), f"{parts[0]}.{parts[1]}"


def json_b64url_decode(value: str) -> Any:
    try:
        return json.loads(b64url_decode(value).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenVerificationError("Cognito token contains invalid JSON") from exc


def b64url_decode(value: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}")
    except (ValueError, binascii.Error) as exc:
        raise TokenVerificationError("Cognito token contains invalid base64url") from exc


def int_claim(claims: dict[str, Any], name: str) -> int:
    value = claims.get(name)
    if not isinstance(value, int):
        raise TokenVerificationError(f"Cognito token {name} claim is invalid")
    return value


def verify_rs256_signature(signed_part: bytes, signature: bytes, key: dict[str, Any]) -> bool:
    if key.get("kty") != "RSA":
        raise TokenVerificationError("Cognito signing key must be RSA")
    modulus = int.from_bytes(b64url_decode(required_string(str(key.get("n") or ""), "n")), "big")
    exponent = int.from_bytes(b64url_decode(required_string(str(key.get("e") or ""), "e")), "big")
    key_size = (modulus.bit_length() + 7) // 8
    if len(signature) != key_size:
        return False
    encoded = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(key_size, "big")
    digest = hashlib.sha256(signed_part).digest()
    expected_suffix = SHA256_DIGEST_INFO_PREFIX + digest
    if not encoded.startswith(b"\x00\x01"):
        return False
    separator_index = encoded.find(b"\x00", 2)
    if separator_index < 10:
        return False
    padding = encoded[2:separator_index]
    return (
        bool(padding)
        and all(byte == 0xFF for byte in padding)
        and encoded[separator_index + 1:] == expected_suffix
    )
