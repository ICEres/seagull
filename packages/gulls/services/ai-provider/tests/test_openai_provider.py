from __future__ import annotations

import json
from unittest import TestCase

from ai_provider.domain.models import ProviderMessage, ProviderRequest
from ai_provider.providers.openai import OpenAIProviderAdapter


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class RecordingOpener:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[object] = []
        self.timeouts: list[int] = []

    def __call__(self, request: object, *, timeout: int) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        return FakeResponse(self.payload)


class OpenAIProviderAdapterTest(TestCase):
    def test_generate_calls_responses_api_and_maps_usage(self) -> None:
        opener = RecordingOpener(
            {
                "id": "resp_1",
                "status": "completed",
                "output_text": "Hello from OpenAI.",
                "usage": {
                    "input_tokens": 4,
                    "output_tokens": 5,
                    "input_tokens_details": {"cached_tokens": 1},
                },
            }
        )
        adapter = OpenAIProviderAdapter(
            api_key_resolver=lambda provider: "sk-test" if provider == "openai" else "",
            opener=opener,
        )

        response = adapter.generate(
            ProviderRequest(
                provider="openai",
                model="gpt-test",
                actor_agent_id="agent_1",
                owner_user_id="user_1",
                input_messages=(ProviderMessage(role="user", content="Hello"),),
                max_output_tokens=12,
            )
        )

        self.assertEqual("Hello from OpenAI.", response.output_text)
        self.assertEqual("resp_1", response.provider_run_id)
        self.assertEqual("completed", response.finish_reason)
        self.assertEqual(4, response.usage.input_tokens)
        self.assertEqual(5, response.usage.output_tokens)
        self.assertEqual(1, response.usage.cached_tokens)
        # cached_tokens is a subset of input_tokens (OpenAI's input_tokens_details
        # breakdown), not additional tokens, so total_tokens must not double-count it.
        self.assertEqual(9, response.usage.total_tokens)

        request = opener.requests[0]
        self.assertEqual("Bearer sk-test", request.headers["Authorization"])  # type: ignore[attr-defined]
        body = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        self.assertEqual("gpt-test", body["model"])
        # Role-tagged structured input, not a flattened spoofable string.
        self.assertEqual([{"role": "user", "content": "Hello"}], body["input"])
        self.assertEqual(12, body["max_output_tokens"])
        self.assertEqual(0.2, body["temperature"])

    def test_generate_passes_instructions_and_json_format(self) -> None:
        opener = RecordingOpener({"id": "resp_2", "status": "completed", "output_text": "{}"})
        adapter = OpenAIProviderAdapter(api_key_resolver=lambda provider: "sk-test", opener=opener)

        adapter.generate(
            ProviderRequest(
                provider="openai",
                model="gpt-test",
                actor_agent_id="agent_1",
                owner_user_id="user_1",
                input_messages=(ProviderMessage(role="user", content="Give me JSON"),),
                system_instructions="You are terse.",
                response_format="json",
                temperature=0.7,
            )
        )

        body = json.loads(opener.requests[0].data.decode("utf-8"))  # type: ignore[attr-defined]
        self.assertEqual("You are terse.", body["instructions"])
        self.assertEqual({"format": {"type": "json_object"}}, body["text"])
        self.assertEqual(0.7, body["temperature"])

    def test_generate_raises_when_response_status_is_not_completed(self) -> None:
        opener = RecordingOpener(
            {
                "id": "resp_3",
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output_text": "partial",
            }
        )
        adapter = OpenAIProviderAdapter(api_key_resolver=lambda provider: "sk-test", opener=opener)

        with self.assertRaisesRegex(RuntimeError, "did not complete"):
            adapter.generate(
                ProviderRequest(
                    provider="openai",
                    model="gpt-test",
                    actor_agent_id="agent_1",
                    owner_user_id="user_1",
                    input_messages=(ProviderMessage(role="user", content="Hello"),),
                )
            )

    def test_generate_requires_api_key(self) -> None:
        adapter = OpenAIProviderAdapter(api_key_resolver=lambda provider: "")

        with self.assertRaisesRegex(RuntimeError, "API key"):
            adapter.generate(
                ProviderRequest(
                    provider="openai",
                    model="gpt-test",
                    actor_agent_id="agent_1",
                    owner_user_id="user_1",
                    input_messages=(ProviderMessage(role="user", content="Hello"),),
                )
            )
