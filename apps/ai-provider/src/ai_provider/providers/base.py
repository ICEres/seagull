from __future__ import annotations

from typing import Protocol

from ai_provider.domain.models import ProviderRequest, ProviderResponse


class AiProviderAdapter(Protocol):
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        """Generate a model response for a normalized provider request."""
