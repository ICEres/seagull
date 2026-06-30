from __future__ import annotations

import json
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ai_provider.domain.models import ProviderRequest, ProviderResponse, ProviderUsage


ApiKeyResolver = Callable[[str], str]
UrlOpen = Callable[..., Any]


class OpenAIProviderAdapter:
    """OpenAI Responses API adapter."""

    def __init__(
        self,
        *,
        api_key_resolver: ApiKeyResolver,
        endpoint: str = "https://api.openai.com/v1/responses",
        timeout_seconds: int = 30,
        opener: UrlOpen = urlopen,
    ) -> None:
        self._api_key_resolver = api_key_resolver
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        api_key = self._api_key_resolver(request.provider).strip()
        if not api_key:
            raise RuntimeError("OpenAI API key is not configured")

        body = {
            "model": request.model,
            "input": openai_input_text(request),
            "max_output_tokens": request.max_output_tokens,
        }
        http_request = Request(
            self._endpoint,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with self._opener(http_request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = exc.reason or f"HTTP {exc.code}"
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                message = error_payload.get("error", {}).get("message") or message
            except Exception:
                pass
            raise RuntimeError(f"OpenAI request failed: {message}") from exc

        usage = payload.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        input_token_details = usage.get("input_tokens_details")
        if not isinstance(input_token_details, dict):
            input_token_details = {}
        return ProviderResponse(
            output_text=openai_output_text(payload),
            provider_run_id=string_value(payload.get("id")),
            finish_reason=string_value(payload.get("status")) or "stop",
            usage=ProviderUsage(
                input_tokens=int_value(usage.get("input_tokens")),
                output_tokens=int_value(usage.get("output_tokens")),
                cached_tokens=int_value(input_token_details.get("cached_tokens")),
            ),
        )


def openai_input_text(request: ProviderRequest) -> str:
    parts: list[str] = []
    if request.system_instructions:
        parts.append(f"System:\n{request.system_instructions}")
    if request.system_instructions_ref:
        parts.append(f"System instructions ref:\n{request.system_instructions_ref}")
    for message in request.input_messages:
        parts.append(f"{message.role}:\n{message.content}")
    if request.context_refs:
        parts.append("Context refs:\n" + "\n".join(request.context_refs))
    if request.content_ref:
        parts.append(f"Content ref:\n{request.content_ref}")
    return "\n\n".join(parts)


def openai_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text

    texts: list[str] = []
    output = payload.get("output")
    if not isinstance(output, list):
        return ""

    for item in output:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "\n".join(texts)


def int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
