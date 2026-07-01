from __future__ import annotations

from ai_provider.domain.models import ProviderRequest, ProviderResponse, ProviderUsage


class FakeProviderAdapter:
    """Deterministic provider adapter for local tests and smoke flows."""

    def __init__(self, *, output_text: str | None = None) -> None:
        self._output_text = output_text
        self.calls: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request)
        output_text = self._output_text if self._output_text is not None else fake_output_for(request)
        return ProviderResponse(
            output_text=output_text,
            provider_run_id=f"fake_{len(self.calls)}",
            usage=ProviderUsage(
                input_tokens=estimate_request_tokens(request),
                output_tokens=estimate_text_tokens(output_text),
            ),
        )


def fake_output_for(request: ProviderRequest) -> str:
    if request.input_messages:
        return f"Fake response to: {request.input_messages[-1].content}"
    if request.content_ref is not None:
        return f"Fake response for payload: {request.content_ref}"
    return "Fake response."


def estimate_request_tokens(request: ProviderRequest) -> int:
    token_count = estimate_text_tokens(request.system_instructions or "")
    token_count += sum(estimate_text_tokens(message.content) for message in request.input_messages)
    token_count += len(request.context_refs)
    if request.content_ref is not None:
        token_count += 1
    return token_count


def estimate_text_tokens(text: str) -> int:
    return len([part for part in text.strip().split() if part])
