from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import TestCase

from ai_provider.domain import AiRunState
from test_lambda_auth import load_lambda_module


class FakeHttpResponse:
    status = 200

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"ok":true}'


class RecordingUrlOpen:
    def __init__(self) -> None:
        self.requests: list[object] = []
        self.timeouts: list[float] = []

    def __call__(self, request: object, *, timeout: float) -> FakeHttpResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        return FakeHttpResponse()


def load_worker_module(lambda_module: object) -> object:
    sys.modules["lambda_function"] = lambda_module
    module_name = "_ai_provider_worker_for_test"
    path = Path(__file__).resolve().parents[1] / "aws" / "ai_worker.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ai-provider worker module")
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(module_name, None)
    spec.loader.exec_module(module)
    return module


class AiProviderWorkerTest(TestCase):
    def setUp(self) -> None:
        self.lambda_module = load_lambda_module()
        self.worker_module = load_worker_module(self.lambda_module)
        self.worker_module.MESSAGE_HUB_API_URL = "https://message.example.test"

    def test_worker_executes_queued_run_and_posts_message_hub_result(self) -> None:
        queued = self.lambda_module.service.create_queued_run(
            provider="fake",
            model="fake-small",
            actor_agent_id="agent_1",
            owner_user_id="user_1",
            input_messages=({"role": "user", "content": "Summarize this task."},),
            task_id="task_1",
            message_id="message_1",
            idempotency_key="worker-1",
        )
        urlopen = RecordingUrlOpen()
        self.worker_module.urlopen = urlopen

        result = self.worker_module.handler(
            {
                "Records": [
                    {
                        "messageId": "message-1",
                        "body": json.dumps(
                            {
                                "run_id": queued.run_id,
                                "request": {
                                    "provider": "fake",
                                    "model": "fake-small",
                                    "actor_agent_id": "agent_1",
                                    "owner_user_id": "user_1",
                                    "input_messages": [
                                        {"role": "user", "content": "Summarize this task."},
                                    ],
                                    "system_instructions": None,
                                    "system_instructions_ref": None,
                                    "context_refs": [],
                                    "content_ref": None,
                                    "max_output_tokens": 512,
                                    "temperature": 0.2,
                                    "response_format": "text",
                                    "tool_policy": "disabled",
                                    "task_id": "task_1",
                                    "message_id": "message_1",
                                    "trace_id": None,
                                    "idempotency_key": "worker-1",
                                },
                                "message_hub": {
                                    "responder_handle": "@reviewer:gulls.ai",
                                    "agent_token": "sga_test_secret",
                                },
                            }
                        ),
                    }
                ]
            },
            None,
        )

        completed = self.lambda_module.service.get_run(queued.run_id)
        self.assertEqual({"processed": 1, "batchItemFailures": []}, result)
        self.assertEqual(AiRunState.COMPLETED, completed.state)
        self.assertEqual(1, len(self.lambda_module.service.list_usage_by_owner("user_1")))
        self.assertEqual(1, len(urlopen.requests))

        request = urlopen.requests[0]
        self.assertEqual(
            "https://message.example.test/personal-agents/%40reviewer%3Agulls.ai/tasks/task_1/results",
            request.full_url,  # type: ignore[attr-defined]
        )
        body = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        self.assertEqual("completed", body["state"])
        self.assertIn("Fake response", body["content"])
        self.assertEqual([f"seagull://ai-runs/{queued.run_id}"], body["artifact_refs"])
