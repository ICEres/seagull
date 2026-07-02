from __future__ import annotations

from typing import Any, Callable

from ai_provider.domain.models import ProviderRequest, ProviderResponse, ProviderUsage


BedrockClientFactory = Callable[[], Any]


class BedrockConverseProviderAdapter:
    """Amazon Bedrock Converse API adapter."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        client_factory: BedrockClientFactory | None = None,
        region_name: str | None = None,
    ) -> None:
        if client is not None and client_factory is not None:
            raise ValueError("provide client or client_factory, not both")
        self._client = client
        self._client_factory = client_factory
        self._region_name = region_name

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        response = self._bedrock_client().converse(**bedrock_converse_request(request))
        usage = dict_value(response.get("usage"))
        metrics = dict_value(response.get("metrics"))
        response_metadata = dict_value(response.get("ResponseMetadata"))
        return ProviderResponse(
            output_text=bedrock_output_text(response),
            provider_run_id=string_value(response_metadata.get("RequestId")),
            finish_reason=string_value(response.get("stopReason")) or "stop",
            usage=ProviderUsage(
                input_tokens=int_value(usage.get("inputTokens")),
                output_tokens=int_value(usage.get("outputTokens")),
            ),
            latency_ms=optional_int_value(metrics.get("latencyMs")),
        )

    def _bedrock_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory()
            return self._client

        import boto3

        kwargs = {}
        if self._region_name is not None:
            kwargs["region_name"] = self._region_name
        self._client = boto3.client("bedrock-runtime", **kwargs)
        return self._client


def bedrock_converse_request(request: ProviderRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "modelId": request.model,
        "messages": bedrock_messages(request),
        "inferenceConfig": {
            "maxTokens": request.max_output_tokens,
            "temperature": request.temperature,
        },
    }
    system = bedrock_system(request)
    if system:
        body["system"] = system
    metadata = bedrock_request_metadata(request)
    if metadata:
        body["requestMetadata"] = metadata
    return body


def bedrock_system(request: ProviderRequest) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    if request.system_instructions:
        blocks.append({"text": request.system_instructions})
    if request.system_instructions_ref:
        blocks.append({"text": f"System instructions ref:\n{request.system_instructions_ref}"})
    return blocks


def bedrock_messages(request: ProviderRequest) -> list[dict[str, Any]]:
    messages = [
        {
            "role": bedrock_role(message.role),
            "content": bedrock_content_blocks(message.content, message.content_ref),
        }
        for message in request.input_messages
    ]
    ref_text = bedrock_ref_text(request)
    if ref_text:
        messages.append({"role": "user", "content": [{"text": ref_text}]})
    return messages


def bedrock_role(role: str) -> str:
    return "assistant" if role.strip().casefold() == "assistant" else "user"


def bedrock_content_blocks(content: str, content_ref: str | None = None) -> list[dict[str, str]]:
    blocks = [{"text": content}]
    if content_ref:
        blocks.append({"text": f"Content ref:\n{content_ref}"})
    return blocks


def bedrock_ref_text(request: ProviderRequest) -> str | None:
    parts: list[str] = []
    if request.context_refs:
        parts.append("Context refs:\n" + "\n".join(request.context_refs))
    if request.content_ref:
        parts.append(f"Content ref:\n{request.content_ref}")
    return "\n\n".join(parts) or None


def bedrock_request_metadata(request: ProviderRequest) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if request.trace_id:
        metadata["trace_id"] = request.trace_id[:256]
    if request.task_id:
        metadata["task_id"] = request.task_id[:256]
    if request.message_id:
        metadata["message_id"] = request.message_id[:256]
    if request.idempotency_key:
        metadata["idempotency_key"] = request.idempotency_key[:256]
    return metadata


def bedrock_output_text(response: dict[str, Any]) -> str:
    output = dict_value(response.get("output"))
    message = dict_value(output.get("message"))
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for block in content:
        block_dict = dict_value(block)
        text = block_dict.get("text")
        if isinstance(text, str):
            texts.append(text)
    return "\n".join(texts)


def dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def optional_int_value(value: object) -> int | None:
    parsed = int_value(value)
    return parsed if parsed > 0 else None


def string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
