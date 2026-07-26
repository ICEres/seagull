"""Agent-scoped request listing for the Agent Request product surface.

Tasks were only listable per thread, which no product surface can build a
queue from: to show "work I asked for" and "work asked of me" you need the
tasks for an agent, not for a conversation. The tasks table already carried
requester-created-at-index and recipient-created-at-index, so this is the
query path catching up with the storage.

Durable task records stay in gulls; this is a read path over them.
"""

from __future__ import annotations

import importlib.util
import os
import types
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from message_hub.api import LocalMessageHubApi
from message_hub.domain import MessageHubService, TaskState
from message_hub.domain.safety import LocalSafetyEvaluator
from message_hub.storage.memory import InMemoryMessageHubRepository


LAMBDA_PATH = Path(__file__).resolve().parents[1] / "aws" / "lambda_function.py"


def load_lambda_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_message_hub_lambda_task_queue_test", LAMBDA_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load message-hub Lambda module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAMBDA = load_lambda_module()


class AgentTaskQueueTest(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMessageHubRepository()
        self.service = MessageHubService(self.repository)
        self.api = LocalMessageHubApi(self.service)

        for handle, name in (
            ("@alice:gulls.ai", "Alice"),
            ("@worker:gulls.ai", "Worker"),
            ("@other:gulls.ai", "Other"),
        ):
            self.api.register_agent({"handle": handle, "display_name": name})

        # Alice asks Worker for two things; Other asks Alice for one.
        self.asked_by_alice = [
            self.api.create_task(
                {
                    "requester_handle": "@alice:gulls.ai",
                    "recipient_handle": "@worker:gulls.ai",
                    "objective": f"Task {index}",
                }
            )["task"]["task_id"]
            for index in range(2)
        ]
        self.asked_of_alice = self.api.create_task(
            {
                "requester_handle": "@other:gulls.ai",
                "recipient_handle": "@alice:gulls.ai",
                "objective": "Review this",
            }
        )["task"]["task_id"]

    def test_requester_role_returns_only_work_this_agent_asked_for(self) -> None:
        result = self.api.read_agent_tasks("@alice:gulls.ai", role="requester")

        self.assertEqual(
            set(self.asked_by_alice),
            {task["task_id"] for task in result["tasks"]},
        )

    def test_worker_role_returns_only_work_asked_of_this_agent(self) -> None:
        result = self.api.read_agent_tasks("@alice:gulls.ai", role="worker")

        self.assertEqual([self.asked_of_alice], [task["task_id"] for task in result["tasks"]])

    def test_all_merges_both_sides_without_duplicating(self) -> None:
        # A request where an agent is both sides must appear once.
        self_serve = self.api.create_task(
            {
                "requester_handle": "@alice:gulls.ai",
                "recipient_handle": "@alice:gulls.ai",
                "objective": "Self-directed",
            }
        )["task"]["task_id"]

        task_ids = [task["task_id"] for task in self.api.read_agent_tasks("@alice:gulls.ai")["tasks"]]

        self.assertEqual(len(task_ids), len(set(task_ids)), "a task was listed twice")
        self.assertEqual(
            {*self.asked_by_alice, self.asked_of_alice, self_serve},
            set(task_ids),
        )

    def test_listing_is_newest_first_and_respects_limit(self) -> None:
        tasks = self.api.read_agent_tasks("@alice:gulls.ai", role="requester", limit=1)["tasks"]

        self.assertEqual(1, len(tasks))
        # Newest of the two Alice requested.
        self.assertEqual(self.asked_by_alice[-1], tasks[0]["task_id"])

    def test_unknown_agent_and_bad_role_are_rejected(self) -> None:
        from message_hub.api import ApiError

        with self.assertRaises(ApiError) as missing:
            self.api.read_agent_tasks("@nobody:gulls.ai")
        self.assertEqual(404, missing.exception.status_code)

        with self.assertRaises(ApiError) as bad_role:
            self.api.read_agent_tasks("@alice:gulls.ai", role="observer")
        self.assertEqual(400, bad_role.exception.status_code)

    def test_task_state_survives_the_round_trip(self) -> None:
        tasks = self.api.read_agent_tasks("@alice:gulls.ai", role="requester")["tasks"]

        self.assertEqual(TaskState.REQUESTED.value, tasks[0]["state"])


class LambdaAgentTaskQueueRouteTest(TestCase):
    """GET /agent/tasks is the product path: the token names the agent.

    The handle-based /tasks routes sit behind the legacy-route secret, so a
    product surface authenticates as the agent instead. This also pins that
    the new GET does not shadow POST /agent/tasks.
    """

    def setUp(self) -> None:
        env = patch.dict(os.environ, {"APP_NAME": "message-hub-test"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(LAMBDA.reset_runtime)

        self.repository = InMemoryMessageHubRepository()
        self.service = LAMBDA.build_service(
            repository=self.repository,
            safety_evaluator=LocalSafetyEvaluator(),
        )
        api = LocalMessageHubApi(self.service)
        api.register_agent({"handle": "@alice:gulls.ai"})
        api.register_agent({"handle": "@worker:gulls.ai"})
        self.task_id = api.create_task(
            {
                "requester_handle": "@alice:gulls.ai",
                "recipient_handle": "@worker:gulls.ai",
                "objective": "Summarize",
            }
        )["task"]["task_id"]
        self.token = self.service.issue_agent_token(
            "@alice:gulls.ai", scopes=("agent:read", "agent:inbox", "agent:post")
        ).token

        LAMBDA.configure_api(LAMBDA.build_api(service=self.service))

    def _request(self, method: str, path: str, *, query=None, token: str | None = None) -> dict:
        import json

        headers = {} if token is None else {"authorization": f"Bearer {token}"}
        event = {
            "requestContext": {"http": {"method": method, "path": path}},
            "rawPath": path,
            "headers": headers,
            "queryStringParameters": query,
        }
        result = LAMBDA.handler(event, None)
        return {"status": result["statusCode"], "body": json.loads(result["body"] or "{}")}

    def test_lists_the_authenticated_agents_requests(self) -> None:
        result = self._request("GET", "/agent/tasks", token=self.token)

        self.assertEqual(200, result["status"])
        self.assertEqual([self.task_id], [task["task_id"] for task in result["body"]["tasks"]])
        self.assertEqual("@alice:gulls.ai", result["body"]["agent_handle"])

    def test_role_filter_is_honored(self) -> None:
        as_requester = self._request(
            "GET", "/agent/tasks", query={"role": "requester"}, token=self.token
        )
        as_worker = self._request(
            "GET", "/agent/tasks", query={"role": "worker"}, token=self.token
        )

        self.assertEqual([self.task_id], [t["task_id"] for t in as_requester["body"]["tasks"]])
        # Alice asked for this work; nobody asked it of her.
        self.assertEqual([], as_worker["body"]["tasks"])

    def test_requires_a_token(self) -> None:
        self.assertEqual(401, self._request("GET", "/agent/tasks")["status"])

    def test_does_not_shadow_posting_a_new_request(self) -> None:
        # Same path, different method: POST must still create.
        import json

        event = {
            "requestContext": {"http": {"method": "POST", "path": "/agent/tasks"}},
            "rawPath": "/agent/tasks",
            "headers": {"authorization": f"Bearer {self.token}"},
            "body": json.dumps(
                {"recipient_handle": "@worker:gulls.ai", "objective": "Another one"}
            ),
        }
        result = LAMBDA.handler(event, None)

        self.assertEqual(201, result["statusCode"])
