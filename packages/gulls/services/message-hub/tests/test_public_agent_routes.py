"""Contract tests for the public agent URL routes.

Every agent handle maps to a public URL resource; these tests pin the exact
wire envelopes (card GET, send 202, replay 200, sender-visible status GET) in
``tests/fixtures/public-agents/*.json`` and assert BOTH transports produce
them:

* ``LocalMessageHubApi`` driven directly, and
* the Lambda handler driven through its ``build_service`` injection seam with
  ``InMemoryMessageHubRepository``.

Volatile fields (generated ids, timestamps) are replaced with placeholders by
``canonicalize`` before comparing against the fixtures.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import types
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import quote

from message_hub.api import ApiError, LocalMessageHubApi
from message_hub.domain import DeliveryStatus, LocalSafetyEvaluator, MessageHubService
from message_hub.domain.cards import agent_card
from message_hub.storage import InMemoryMessageHubRepository

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "public-agents"
LAMBDA_PATH = Path(__file__).resolve().parents[1] / "aws" / "lambda_function.py"

SENDER_HANDLE = "@caller:gulls.ai"
RECIPIENT_HANDLE = "@weather-jp:gulls.ai"
BYSTANDER_HANDLE = "@bystander:gulls.ai"

RECIPIENT_REGISTRATION = {
    "handle": RECIPIENT_HANDLE,
    "display_name": "Weather JP",
    # The private capability and the api_key trigger must be sanitized out of
    # the public card by the one sanitizer in message_hub.domain.cards.
    "capabilities": ["weather.forecast", "mcp://weather-tool.internal"],
    "response_rules": {
        "persona": "cheerful weather reporter",
        "style": "concise",
        "ask_human_triggers": ["storm warnings", "api_key rotation"],
    },
    "scopes": ["agent:read", "agent:inbox", "agent:post", "agent:ack"],
}

VOLATILE_ID_PATTERN = re.compile(r"(agent|delivery|message|thread)_[0-9a-f]{32}")
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


def canonicalize(value: object) -> object:
    """Replace volatile ids and timestamps with stable fixture placeholders."""
    if isinstance(value, dict):
        return {key: canonicalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    if isinstance(value, str):
        return TIMESTAMP_PATTERN.sub("TIMESTAMP", VOLATILE_ID_PATTERN.sub(r"\1_ID", value))
    return value


def fixture(name: str) -> object:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def load_lambda_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_message_hub_lambda_public_agents_test", LAMBDA_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load message-hub Lambda module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAMBDA = load_lambda_module()


class PublicAgentRouteContractMixin:
    """Transport-agnostic contract tests.

    Subclasses provide the transport primitives (``register``, ``get_card``,
    ``send``, ``get_status``, ``decide_reply``) plus ``self.repository`` and
    call ``install_agents`` from ``setUp``. Every operation returns
    ``(status_code, parsed_body)`` with 202/200 signalling created/replayed
    sends, so both transports run the identical assertions.
    """

    maxDiff = None

    def install_agents(self) -> None:
        self.sender_token = self.register({"handle": SENDER_HANDLE, "scopes": ["agent:read", "agent:post"]})
        self.recipient_token = self.register(dict(RECIPIENT_REGISTRATION))
        self.bystander_token = self.register({"handle": BYSTANDER_HANDLE, "scopes": ["agent:read", "agent:post"]})

    def force_delivery_status(self, delivery_id: str, status: DeliveryStatus) -> None:
        # The send flow cannot park deliveries in every state the coarse
        # mapping covers (e.g. legacy ``queued`` rows), so simulate them
        # directly on the repository.
        delivery = self.repository.get_delivery(delivery_id)
        assert delivery is not None
        self.repository.update_delivery(replace(delivery, status=status))

    def send_hello(self, **kwargs: object) -> dict[str, object]:
        status_code, envelope = self.send(self.sender_token, RECIPIENT_HANDLE, {"content": "Hello"}, **kwargs)
        assert status_code == 202, envelope
        return envelope

    # -- card

    def test_card_matches_fixture(self) -> None:
        status_code, card = self.get_card(RECIPIENT_HANDLE)
        self.assertEqual(200, status_code)
        self.assertEqual(fixture("card.json"), canonicalize(card))

    def test_card_uses_the_single_sanitizer(self) -> None:
        status_code, card = self.get_card(RECIPIENT_HANDLE)
        self.assertEqual(200, status_code)
        agent = self.repository.get_agent_by_handle(RECIPIENT_HANDLE)
        self.assertEqual({"agent": agent_card(agent)}, card)

    # -- POST /agents/{name}/messages

    def test_send_matches_fixture_and_binds_sender_to_token(self) -> None:
        status_code, envelope = self.send(
            self.sender_token,
            RECIPIENT_HANDLE,
            # A spoofed body sender must be ignored: the sender is the token's
            # agent, never taken from the body.
            {"content": "Hello", "sender_handle": BYSTANDER_HANDLE},
        )
        self.assertEqual(202, status_code)
        self.assertEqual(fixture("send-202.json"), canonicalize(envelope))

        message = self.repository.get_message(str(envelope["message_id"]))
        sender = self.repository.get_agent_by_handle(SENDER_HANDLE)
        recipient = self.repository.get_agent_by_handle(RECIPIENT_HANDLE)
        self.assertEqual(sender.agent_id, message.sender_agent_id)
        delivery = self.repository.get_delivery(str(envelope["delivery_id"]))
        self.assertEqual(recipient.agent_id, delivery.recipient_agent_id)
        self.assertEqual("direct", message.visibility)

    def test_send_accepts_handle_with_or_without_at_prefix(self) -> None:
        for name in (RECIPIENT_HANDLE, RECIPIENT_HANDLE.removeprefix("@")):
            status_code, envelope = self.send(self.sender_token, name, {"content": "Hi"})
            self.assertEqual(202, status_code, envelope)
            # status_url always uses the canonical stored handle, URL-encoded.
            self.assertTrue(
                str(envelope["status_url"]).startswith(f"/agents/{quote(RECIPIENT_HANDLE, safe='')}/messages/"),
                envelope["status_url"],
            )

        # A bare name only resolves when the hub stores the hostless handle;
        # this instance stores host-qualified handles, so it is a 404.
        status_code, _ = self.send(self.sender_token, "weather-jp", {"content": "Hi"})
        self.assertEqual(404, status_code)

    def test_send_requires_auth(self) -> None:
        status_code, _ = self.send(None, RECIPIENT_HANDLE, {"content": "Hi"})
        self.assertEqual(401, status_code)

    def test_send_requires_post_scope(self) -> None:
        reader_token = self.register({"handle": "@reader-only:gulls.ai", "scopes": ["agent:read"]})
        status_code, _ = self.send(reader_token, RECIPIENT_HANDLE, {"content": "Hi"})
        self.assertEqual(403, status_code)

    def test_send_without_content_is_bad_request(self) -> None:
        status_code, body = self.send(self.sender_token, RECIPIENT_HANDLE, {})
        self.assertEqual(400, status_code)
        self.assertEqual("bad_request", body["error"])

    def test_replay_returns_the_original_envelope(self) -> None:
        first = self.send_hello(idempotency_key="send-1")

        replay_status, replay = self.send(
            self.sender_token, RECIPIENT_HANDLE, {"content": "Hello"}, idempotency_key="send-1"
        )
        self.assertEqual(200, replay_status)
        self.assertEqual(first, replay)
        self.assertEqual(fixture("send-replay-200.json"), canonicalize(replay))

        # The body field is the fallback for the Idempotency-Key header.
        fallback_status, fallback = self.send(
            self.sender_token, RECIPIENT_HANDLE, {"content": "Hello", "idempotency_key": "send-1"}
        )
        self.assertEqual(200, fallback_status)
        self.assertEqual(first, fallback)

    # -- GET /agents/{name}/messages/{delivery_id}

    def test_status_envelopes_match_fixtures(self) -> None:
        envelope = self.send_hello()
        delivery_id = str(envelope["delivery_id"])

        self.force_delivery_status(delivery_id, DeliveryStatus.QUEUED)
        status_code, body = self.get_status(self.sender_token, RECIPIENT_HANDLE, delivery_id)
        self.assertEqual(200, status_code)
        self.assertEqual(fixture("status-accepted.json"), canonicalize(body))

        self.force_delivery_status(delivery_id, DeliveryStatus.NEEDS_REVIEW)
        _, body = self.get_status(self.sender_token, RECIPIENT_HANDLE, delivery_id)
        self.assertEqual(fixture("status-quarantined.json"), canonicalize(body))

        self.force_delivery_status(delivery_id, DeliveryStatus.PENDING_ACTION)
        _, body = self.get_status(self.sender_token, RECIPIENT_HANDLE, delivery_id)
        self.assertEqual("quarantined", body["status"])

        self.force_delivery_status(delivery_id, DeliveryStatus.FAILED)
        _, body = self.get_status(self.sender_token, RECIPIENT_HANDLE, delivery_id)
        self.assertEqual("blocked", body["status"])

        # A real recipient reply, not a forced row: replied stays observable.
        self.force_delivery_status(delivery_id, DeliveryStatus.DELIVERED)
        self.decide_reply(self.recipient_token, delivery_id, "Sunny tomorrow.")
        _, body = self.get_status(self.sender_token, RECIPIENT_HANDLE, delivery_id)
        self.assertEqual(fixture("status-replied.json"), canonicalize(body))

    def test_recipient_decisions_are_not_sender_visible(self) -> None:
        envelope = self.send_hello()
        delivery_id = str(envelope["delivery_id"])

        _, before = self.get_status(self.sender_token, RECIPIENT_HANDLE, delivery_id)
        self.assertEqual("delivered", before["status"])

        for hidden in (DeliveryStatus.READ, DeliveryStatus.ACKED, DeliveryStatus.IGNORED):
            self.force_delivery_status(delivery_id, hidden)
            _, after = self.get_status(self.sender_token, RECIPIENT_HANDLE, delivery_id)
            self.assertEqual(before, after)

    def test_status_requires_auth(self) -> None:
        envelope = self.send_hello()
        status_code, _ = self.get_status(None, RECIPIENT_HANDLE, str(envelope["delivery_id"]))
        self.assertEqual(401, status_code)

    def test_status_is_readable_only_by_the_sender(self) -> None:
        envelope = self.send_hello()
        delivery_id = str(envelope["delivery_id"])

        status_code, _ = self.get_status(self.bystander_token, RECIPIENT_HANDLE, delivery_id)
        self.assertEqual(403, status_code)
        # Even the recipient cannot use the sender-facing status route.
        status_code, _ = self.get_status(self.recipient_token, RECIPIENT_HANDLE, delivery_id)
        self.assertEqual(403, status_code)

    def test_status_unknown_delivery_or_recipient_mismatch_is_404(self) -> None:
        envelope = self.send_hello()

        status_code, _ = self.get_status(self.sender_token, RECIPIENT_HANDLE, "delivery_" + "0" * 32)
        self.assertEqual(404, status_code)
        # The delivery exists but is not addressed to the path agent.
        status_code, _ = self.get_status(self.sender_token, BYSTANDER_HANDLE, str(envelope["delivery_id"]))
        self.assertEqual(404, status_code)
        # Unknown path agent.
        status_code, _ = self.get_status(self.sender_token, "@nobody:gulls.ai", str(envelope["delivery_id"]))
        self.assertEqual(404, status_code)


class LocalApiPublicAgentRoutesTest(PublicAgentRouteContractMixin, TestCase):
    """Drives LocalMessageHubApi directly (no HTTP transport, no kill switch)."""

    def setUp(self) -> None:
        self.repository = InMemoryMessageHubRepository()
        self.api = LocalMessageHubApi(
            MessageHubService(self.repository, safety_evaluator=LocalSafetyEvaluator())
        )
        self.install_agents()

    @staticmethod
    def authorization(token: str | None) -> str | None:
        return None if token is None else f"Bearer {token}"

    def register(self, body: dict[str, object]) -> str:
        return str(self.api.agent_registration(body)["token"])

    def get_card(self, name: str) -> tuple[int, dict[str, object]]:
        return self.call(lambda: self.api.read_agent(name))

    def send(
        self,
        token: str | None,
        name: str,
        body: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        def invoke() -> tuple[int, dict[str, object]]:
            result = self.api.public_agent_send(
                self.authorization(token), name, body, idempotency_key=idempotency_key
            )
            replayed = result.pop("replayed")
            return (200 if replayed else 202), result

        return self.call(invoke)

    def get_status(self, token: str | None, name: str, delivery_id: str) -> tuple[int, dict[str, object]]:
        return self.call(
            lambda: self.api.public_agent_message_status(self.authorization(token), name, delivery_id)
        )

    def decide_reply(self, recipient_token: str, delivery_id: str, content: str) -> None:
        self.api.agent_decide_delivery(
            self.authorization(recipient_token), delivery_id, {"decision": "reply", "content": content}
        )

    @staticmethod
    def call(invoke):
        try:
            result = invoke()
        except ApiError as exc:
            return exc.status_code, {"error": exc.error, "message": exc.message}
        if isinstance(result, tuple):
            return result
        return 200, result


class LambdaPublicAgentRoutesTest(PublicAgentRouteContractMixin, TestCase):
    """Drives the Lambda handler via build_service with the in-memory repository."""

    def setUp(self) -> None:
        env = patch.dict(os.environ, {"APP_NAME": "message-hub-test"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(LAMBDA.reset_runtime)

        self.repository = InMemoryMessageHubRepository()
        service = LAMBDA.build_service(
            repository=self.repository,
            safety_evaluator=LocalSafetyEvaluator(),
        )
        self.api = LocalMessageHubApi(service)
        LAMBDA.configure_api(self.api)
        self.install_agents()

    def handle(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        request: dict[str, object] = {
            "rawPath": path,
            "requestContext": {"http": {"method": method, "path": path}},
        }
        if headers is not None:
            request["headers"] = headers
        if body is not None:
            request["body"] = json.dumps(body)
        response = LAMBDA.handler(request, None)
        return int(response["statusCode"]), json.loads(response["body"])

    def register(self, body: dict[str, object]) -> str:
        status_code, result = self.handle("POST", "/agent-registrations", body)
        assert status_code == 201, result
        return str(result["token"])

    def get_card(self, name: str) -> tuple[int, dict[str, object]]:
        return self.handle("GET", f"/agents/{quote(name, safe='')}")

    def send(
        self,
        token: str | None,
        name: str,
        body: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        headers: dict[str, str] = {}
        if token is not None:
            headers["authorization"] = f"Bearer {token}"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return self.handle(
            "POST", f"/agents/{quote(name, safe='')}/messages", body, headers=headers or None
        )

    def get_status(self, token: str | None, name: str, delivery_id: str) -> tuple[int, dict[str, object]]:
        headers = None if token is None else {"authorization": f"Bearer {token}"}
        return self.handle(
            "GET",
            f"/agents/{quote(name, safe='')}/messages/{quote(delivery_id, safe='')}",
            headers=headers,
        )

    def decide_reply(self, recipient_token: str, delivery_id: str, content: str) -> None:
        status_code, body = self.handle(
            "POST",
            f"/agent/deliveries/{quote(delivery_id, safe='')}/decision",
            {"decision": "reply", "content": content},
            headers={"authorization": f"Bearer {recipient_token}"},
        )
        assert status_code == 200, body

    # -- Lambda-only behavior

    def test_card_body_is_byte_identical_to_read_agent(self) -> None:
        raw = LAMBDA.handler(
            {
                "rawPath": f"/agents/{quote(RECIPIENT_HANDLE, safe='')}",
                "requestContext": {"http": {"method": "GET", "path": f"/agents/{quote(RECIPIENT_HANDLE, safe='')}"}},
            },
            None,
        )["body"]
        expected = LAMBDA.response(200, self.api.read_agent(RECIPIENT_HANDLE))["body"]
        self.assertEqual(expected, raw)

    def test_status_url_round_trips_through_the_lambda(self) -> None:
        envelope = self.send_hello()
        status_code, body = self.handle(
            "GET",
            str(envelope["status_url"]),
            headers={"authorization": f"Bearer {self.sender_token}"},
        )
        self.assertEqual(200, status_code)
        self.assertEqual(envelope["delivery_id"], body["delivery_id"])

    def test_kill_switch_disables_only_the_new_routes(self) -> None:
        envelope = self.send_hello()
        delivery_id = str(envelope["delivery_id"])

        for disabled in ("false", "0"):
            with patch.dict(os.environ, {"PUBLIC_AGENT_URLS_ENABLED": disabled}):
                status_code, body = self.send(self.sender_token, RECIPIENT_HANDLE, {"content": "Hi"})
                self.assertEqual(404, status_code)
                self.assertEqual("not_found", body["error"])
                status_code, body = self.get_status(self.sender_token, RECIPIENT_HANDLE, delivery_id)
                self.assertEqual(404, status_code)
                self.assertEqual("not_found", body["error"])

                # Existing routes keep working while the switch is off.
                status_code, _ = self.get_card(RECIPIENT_HANDLE)
                self.assertEqual(200, status_code)
                status_code, _ = self.handle(
                    "GET", "/agent/me", headers={"authorization": f"Bearer {self.sender_token}"}
                )
                self.assertEqual(200, status_code)

        for enabled in ("true", "1", ""):
            with patch.dict(os.environ, {"PUBLIC_AGENT_URLS_ENABLED": enabled}):
                status_code, _ = self.get_status(self.sender_token, RECIPIENT_HANDLE, delivery_id)
                self.assertEqual(200, status_code)
