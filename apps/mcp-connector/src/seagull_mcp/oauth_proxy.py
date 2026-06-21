from __future__ import annotations

from dataclasses import dataclass
from urllib import error, parse, request


DEFAULT_COGNITO_SCOPES = ("openid", "email", "profile")
SUPPORTED_COGNITO_SCOPES = frozenset({
    "openid",
    "email",
    "profile",
    "phone",
    "aws.cognito.signin.user.admin",
})
AUTHORIZE_PARAM_NAMES = frozenset({
    "response_type",
    "redirect_uri",
    "state",
    "code_challenge",
    "code_challenge_method",
    "nonce",
    "prompt",
    "login_hint",
})


@dataclass(frozen=True, slots=True)
class OAuthProxyResult:
    status_code: int
    body: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class CognitoOAuthProxy:
    authorization_url: str
    token_url: str
    client_id: str

    def authorize(self, query: dict[str, str]) -> OAuthProxyResult:
        params = {
            key: value
            for key, value in query.items()
            if key in AUTHORIZE_PARAM_NAMES and value
        }
        params["client_id"] = self.client_id
        params["scope"] = normalize_cognito_scope(query.get("scope"))
        location = f"{self.authorization_url}?{parse.urlencode(params)}"
        return OAuthProxyResult(302, "", {"location": location})

    def token(self, raw_body: str | None) -> OAuthProxyResult:
        form = parse.parse_qs(raw_body or "", keep_blank_values=True)
        form["client_id"] = [self.client_id]
        if "scope" in form:
            form["scope"] = [normalize_cognito_scope(form["scope"][0])]
        data = parse.urlencode(form, doseq=True).encode("utf-8")
        upstream_request = request.Request(
            self.token_url,
            data=data,
            headers={
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with request.urlopen(upstream_request, timeout=10) as response:
                return OAuthProxyResult(
                    response.status,
                    response.read().decode("utf-8"),
                    {"content-type": response.headers.get("content-type", "application/json")},
                )
        except error.HTTPError as exc:
            return OAuthProxyResult(
                exc.code,
                exc.read().decode("utf-8"),
                {"content-type": exc.headers.get("content-type", "application/json")},
            )


def normalize_cognito_scope(scope: str | None) -> str:
    requested = (scope or "").replace(",", " ").split()
    allowed = [item for item in requested if item in SUPPORTED_COGNITO_SCOPES]
    if not allowed:
        allowed = list(DEFAULT_COGNITO_SCOPES)
    return " ".join(dedupe_preserving_order(allowed))


def dedupe_preserving_order(values: list[str]) -> tuple[str, ...]:
    deduped = []
    seen = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return tuple(deduped)
