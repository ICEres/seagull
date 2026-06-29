"""AI provider adapter implementations."""

from ai_provider.providers.base import AiProviderAdapter
from ai_provider.providers.fake import FakeProviderAdapter

__all__ = [
    "AiProviderAdapter",
    "FakeProviderAdapter",
]
