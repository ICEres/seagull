from __future__ import annotations

from unittest import TestCase

from ai_provider.domain.models import ProviderMessage, ProviderRequest
from ai_provider.providers.bedrock import BedrockConverseProviderAdapter


class RecordingBedrockClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(kwargs)
        return self.response


class BedrockConverseProviderAdapterTest(TestCase):
    def test_generate_calls_converse_and_maps_response(self) -> None:
        client = RecordingBedrockClient(
            {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "Hello from Bedrock."}],
                    }
                },
                "stopReason": "end_turn",
                "usage": {
                    "inputTokens": 7,
                    "outputTokens": 9,
                    "totalTokens": 16,
                },
                "metrics": {"latencyMs": 1234},
                "ResponseMetadata": {"RequestId": "bedrock_request_1"},
            }
        )
        adapter = BedrockConverseProviderAdapter(client=client)

        response = adapter.generate(
            ProviderRequest(
                provider="bedrock",
                model="anthropic.claude-3-5-sonnet-20240620-v1:0",
                actor_agent_id="agent_1",
                owner_user_id="user_1",
                input_messages=(ProviderMessage(role="user", content="Hello"),),
                system_instructions="Be concise.",
                context_refs=("payload://context/1",),
                content_ref="payload://input/1",
                max_output_tokens=64,
                temperature=0.4,
                task_id="task_1",
                message_id="message_1",
                trace_id="trace_1",
                idempotency_key="idem_1",
            )
        )

        self.assertEqual("Hello from Bedrock.", response.output_text)
        self.assertEqual("bedrock_request_1", response.provider_run_id)
        self.assertEqual("end_turn", response.finish_reason)
        self.assertEqual(7, response.usage.input_tokens)
        self.assertEqual(9, response.usage.output_tokens)
        self.assertEqual(16, response.usage.total_tokens)
        self.assertEqual(1234, response.latency_ms)

        request = client.requests[0]
        self.assertEqual("anthropic.claude-3-5-sonnet-20240620-v1:0", request["modelId"])
        self.assertEqual({"maxTokens": 64, "temperature": 0.4}, request["inferenceConfig"])
        self.assertEqual([{"text": "Be concise."}], request["system"])
        self.assertEqual(
            [
                {"role": "user", "content": [{"text": "Hello"}]},
                {
                    "role": "user",
                    "content": [{"text": "Context refs:\npayload://context/1\n\nContent ref:\npayload://input/1"}],
                },
            ],
            request["messages"],
        )
        self.assertEqual(
            {
                "trace_id": "trace_1",
                "task_id": "task_1",
                "message_id": "message_1",
                "idempotency_key": "idem_1",
            },
            request["requestMetadata"],
        )

    def test_generate_joins_multiple_text_blocks(self) -> None:
        client = RecordingBedrockClient(
            {
                "output": {
                    "message": {
                        "content": [
                            {"text": "First paragraph."},
                            {"text": "Second paragraph."},
                        ],
                    }
                },
                "usage": {},
            }
        )
        adapter = BedrockConverseProviderAdapter(client=client)

        response = adapter.generate(
            ProviderRequest(
                provider="bedrock",
                model="model",
                actor_agent_id="agent_1",
                owner_user_id="user_1",
                input_messages=(ProviderMessage(role="assistant", content="Previous answer."),),
            )
        )

        self.assertEqual("First paragraph.\nSecond paragraph.", response.output_text)
        self.assertEqual("assistant", client.requests[0]["messages"][0]["role"])

    def test_client_factory_is_lazy(self) -> None:
        calls: list[str] = []

        def client_factory() -> RecordingBedrockClient:
            calls.append("created")
            return RecordingBedrockClient({"output": {"message": {"content": [{"text": "Done."}]}}, "usage": {}})

        adapter = BedrockConverseProviderAdapter(client_factory=client_factory)
        self.assertEqual([], calls)

        response = adapter.generate(
            ProviderRequest(
                provider="bedrock",
                model="model",
                actor_agent_id="agent_1",
                owner_user_id="user_1",
                input_messages=(ProviderMessage(role="user", content="Hello"),),
            )
        )

        self.assertEqual("Done.", response.output_text)
        self.assertEqual(["created"], calls)
