"""AI provider storage implementations."""

from ai_provider.storage.memory import InMemoryAiProviderRepository
from ai_provider.storage.repository import AiProviderRepository

try:
    from ai_provider.storage.dynamodb import DynamoDbAiProviderRepository
except ImportError:  # pragma: no cover - boto3 is optional for local tests.
    DynamoDbAiProviderRepository = None  # type: ignore[assignment]

__all__ = [
    "AiProviderRepository",
    "DynamoDbAiProviderRepository",
    "InMemoryAiProviderRepository",
]
