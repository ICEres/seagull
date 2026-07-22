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

import contextlib
import importlib.util
import io
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
from message_hub.domain import (
    DeliveryStatus,
    LocalSafetyEvaluator,
    MessageHubService,
    SafetyBlockedError,
)
from message_hub.domain.cards import agent_card
from message_hub.storage import InMemoryMessageHubRepository

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "public-agents"
LAMBDA_PATH = Path(__file__).resolve().parents[1] / "aws" / "lambda_function.py"

SENDER_HANDLE = "@caller:gulls.ai"
RECIPIENT_HANDLE = "@weather-jp:gulls.ai"
BYSTANDER_HANDLE = "@bystander:gulls.ai"
# Stable signing secret so guest status URLs stay verifiable across the api
# rebuilds some tests perform.
GUEST_SIGNING_SECRET = "5f" * 32

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
# The signed guest status token (hex HMAC-SHA256) is volatile per secret.
GUEST_TOKEN_PATTERN = re.compile(r"token=[0-9a-f]{64}")


def canonicalize(value: object) -> object:
    """Replace volatile ids, timestamps, and signed tokens with placeholders."""
    if isinstance(value, dict):
        return {key: canonicalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    if isinstance(value, str):
        canonical = GUEST_TOKEN_PATTERN.sub("token=SIGNED_TOKEN", value)
        return TIMESTAMP_PATTERN.sub("TIMESTAMP", VOLATILE_ID_PATTERN.sub(r"\1_ID", canonical))
    return value


def split_status_url(status_url: str) -> tuple[str, str, str]:
    """Split a guest status_url into (path, delivery_id, token)."""
    path, _, query = status_url.partition("?")
    assert query.startswith("token="), status_url
    return path, path.rsplit("/", 1)[-1], query.removeprefix("token=")


class RaisingSafetyEvaluator:
    """Gateway-style evaluator: hard-fails every send by raising."""

    def evaluate_send(self, request):  # noqa: ANN001, ANN201 - protocol duck type
        raise SafetyBlockedError("message blocked by safety policy: forced block")


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
        # Since M2 a token-less send is the guest path, so with the default
        # contacts_only posture it is refused by posture — not by auth.
        status_code, body = self.guest_send(RECIPIENT_HANDLE, {"content": "Hi"})
        self.assertEqual(403, status_code)
        self.assertEqual("posture_not_open", body["error"])
        # A present-but-invalid bearer token is still an auth failure.
        status_code, body = self.send("sga_bogus_bogus", RECIPIENT_HANDLE, {"content": "Hi"})
        self.assertEqual(401, status_code)
        self.assertEqual("unauthorized", body["error"])

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

    # -- inbox posture (M2.1)

    def set_posture(self, token: str, posture: str) -> None:
        status_code, body = self.set_posture_raw(token, posture)
        assert status_code == 200, body

    def guest_handles(self) -> list[str]:
        # Both transports run on InMemoryMessageHubRepository; enumerate the
        # reserved namespace directly to observe minted guest identities.
        return sorted(
            handle
            for handle in self.repository._agent_id_by_handle  # noqa: SLF001
            if handle.startswith("@guest_")
        )

    def test_registration_accepts_inbox_posture(self) -> None:
        self.register(
            {"handle": "@open-desk:gulls.ai", "inbox_posture": "open", "scopes": ["agent:read"]}
        )
        status_code, card = self.get_card("@open-desk:gulls.ai")
        self.assertEqual(200, status_code)
        self.assertEqual("open", card["agent"]["inbox_posture"])

        status_code, body = self.try_register(
            {"handle": "@bad-posture:gulls.ai", "inbox_posture": "sometimes"}
        )
        self.assertEqual(400, status_code)
        self.assertEqual("bad_request", body["error"])

    def test_inbox_posture_update_route(self) -> None:
        status_code, _ = self.set_posture_raw(None, "open")
        self.assertEqual(401, status_code)

        reader_token = self.register({"handle": "@posture-reader:gulls.ai", "scopes": ["agent:read"]})
        status_code, _ = self.set_posture_raw(reader_token, "open")
        self.assertEqual(403, status_code)

        status_code, body = self.set_posture_raw(self.recipient_token, "sometimes")
        self.assertEqual(400, status_code)
        self.assertEqual("bad_request", body["error"])

        status_code, body = self.set_posture_raw(self.recipient_token, "open")
        self.assertEqual(200, status_code)
        self.assertEqual("open", body["agent"]["inbox_posture"])
        # The public card reflects the change.
        _, card = self.get_card(RECIPIENT_HANDLE)
        self.assertEqual("open", card["agent"]["inbox_posture"])

    def test_posture_gates_only_the_token_less_path(self) -> None:
        for posture in ("contacts_only", "token_required", "open"):
            self.set_posture(self.recipient_token, posture)
            status_code, envelope = self.send(self.sender_token, RECIPIENT_HANDLE, {"content": "Hi"})
            self.assertEqual(202, status_code, envelope)
            # The registered (M1) envelope is unchanged by posture.
            self.assertEqual(
                {"delivery_id", "message_id", "thread_id", "status_url", "thread_url"},
                set(envelope),
            )

        # token_required is reserved for later semantics: guests are refused
        # exactly like contacts_only this slice.
        self.set_posture(self.recipient_token, "token_required")
        status_code, body = self.guest_send(RECIPIENT_HANDLE, {"content": "Hi"})
        self.assertEqual(403, status_code)
        self.assertEqual("posture_not_open", body["error"])

    # -- guest ingress (M2.2)

    def test_guest_send_requires_open_posture(self) -> None:
        status_code, body = self.guest_send(RECIPIENT_HANDLE, {"content": "Hello"})
        self.assertEqual(403, status_code)
        self.assertEqual("posture_not_open", body["error"])
        # No guest identity or message was persisted for the refusal.
        self.assertEqual([], self.guest_handles())

    def test_guest_send_matches_fixture_and_quarantines(self) -> None:
        self.set_posture(self.recipient_token, "open")
        status_code, envelope = self.guest_send(RECIPIENT_HANDLE, {"content": "Hello"})
        self.assertEqual(202, status_code, envelope)
        self.assertEqual(fixture("guest-send-202.json"), canonicalize(envelope))
        # The envelope is delivery_id + signed status_url ONLY: no message or
        # thread ids, which guests cannot use.
        self.assertEqual({"delivery_id", "status_url"}, set(envelope))

        delivery = self.repository.get_delivery(str(envelope["delivery_id"]))
        self.assertEqual(DeliveryStatus.NEEDS_REVIEW, delivery.status)
        self.assertEqual("human.review", delivery.current_stage)
        hold_entries = [entry for entry in delivery.workflow_trace if entry.actor == "guest-policy"]
        self.assertEqual(1, len(hold_entries))
        self.assertIn("safety action: allow", hold_entries[0].note)

        # The sender is a server-minted ephemeral guest agent record.
        sender = self.repository.get_agent(delivery.sender_agent_id)
        self.assertTrue(sender.handle.startswith("@guest_"))
        self.assertEqual("Guest sender", sender.display_name)
        self.assertEqual("guest", sender.status)

        # Held guest sends stay hidden from the recipient inbox until a human
        # releases them, and the recipient cannot act on them.
        self.assertEqual([], self.api.read_inbox(RECIPIENT_HANDLE)["items"])
        with self.assertRaises(ApiError) as held:
            self.api.agent_decide_delivery(
                f"Bearer {self.recipient_token}",
                delivery.delivery_id,
                {"decision": "ignore"},
            )
        self.assertEqual(403, held.exception.status_code)

        # Ephemeral per-send identity: the next send mints a different guest.
        _, second = self.guest_send(RECIPIENT_HANDLE, {"content": "Hello again"})
        second_delivery = self.repository.get_delivery(str(second["delivery_id"]))
        self.assertNotEqual(delivery.sender_agent_id, second_delivery.sender_agent_id)
        self.assertEqual(2, len(self.guest_handles()))

    def test_guest_status_poll_happy_path_and_coarse_vocabulary(self) -> None:
        self.set_posture(self.recipient_token, "open")
        _, envelope = self.guest_send(RECIPIENT_HANDLE, {"content": "Hello"})
        _, delivery_id, token = split_status_url(str(envelope["status_url"]))

        status_code, body = self.guest_status(RECIPIENT_HANDLE, delivery_id, token)
        self.assertEqual(200, status_code, body)
        self.assertEqual(fixture("guest-status-quarantined.json"), canonicalize(body))
        # delivery_id + status ONLY: no timestamps, no thread_url.
        self.assertEqual({"delivery_id", "status"}, set(body))

        expected = {
            DeliveryStatus.QUEUED: "accepted",
            DeliveryStatus.NEEDS_REVIEW: "quarantined",
            DeliveryStatus.PENDING_ACTION: "quarantined",
            # Blocked/failed is indistinguishable from review for guests.
            DeliveryStatus.FAILED: "quarantined",
            DeliveryStatus.DELIVERED: "delivered",
            DeliveryStatus.READ: "delivered",
            DeliveryStatus.ACKED: "delivered",
            DeliveryStatus.IGNORED: "delivered",
            DeliveryStatus.REPLIED: "replied",
        }
        for forced, visible in expected.items():
            self.force_delivery_status(delivery_id, forced)
            status_code, body = self.guest_status(RECIPIENT_HANDLE, delivery_id, token)
            self.assertEqual(200, status_code)
            self.assertEqual({"delivery_id": delivery_id, "status": visible}, body)

    def test_guest_send_safety_block_is_indistinguishable_from_allow(self) -> None:
        self.set_posture(self.recipient_token, "open")

        # The registered path still refuses the content outright...
        status_code, body = self.send(self.sender_token, RECIPIENT_HANDLE, {"content": "unsafe: rm -rf"})
        self.assertEqual(403, status_code)
        self.assertEqual("blocked", body["error"])

        # ...while the guest path accepts and quarantines it: same 202 shape,
        # same status vocabulary — no content-probing oracle.
        status_code, blocked = self.guest_send(RECIPIENT_HANDLE, {"content": "unsafe: rm -rf"})
        self.assertEqual(202, status_code, blocked)
        status_code, allowed = self.guest_send(RECIPIENT_HANDLE, {"content": "Hello"})
        self.assertEqual(202, status_code, allowed)
        self.assertEqual(set(allowed), set(blocked))
        self.assertEqual(canonicalize(allowed), canonicalize(blocked))

        for envelope in (blocked, allowed):
            _, delivery_id, token = split_status_url(str(envelope["status_url"]))
            _, body = self.guest_status(RECIPIENT_HANDLE, delivery_id, token)
            self.assertEqual("quarantined", body["status"])

        # The real safety action is preserved for the human reviewer.
        blocked_delivery = self.repository.get_delivery(str(blocked["delivery_id"]))
        self.assertEqual(DeliveryStatus.NEEDS_REVIEW, blocked_delivery.status)
        notes = [entry.note for entry in blocked_delivery.workflow_trace if entry.actor == "guest-policy"]
        self.assertEqual(1, len(notes))
        self.assertIn("safety action: block", notes[0])

    def test_guest_send_survives_evaluator_that_raises(self) -> None:
        # Gateway-style evaluators raise SafetyBlockedError instead of
        # returning a block decision; guests must still get 202 + quarantine.
        self.configure_safety_evaluator(RaisingSafetyEvaluator())
        self.set_posture(self.recipient_token, "open")

        status_code, body = self.send(self.sender_token, RECIPIENT_HANDLE, {"content": "Hi"})
        self.assertEqual(403, status_code)

        status_code, envelope = self.guest_send(RECIPIENT_HANDLE, {"content": "Hi"})
        self.assertEqual(202, status_code, envelope)
        delivery = self.repository.get_delivery(str(envelope["delivery_id"]))
        self.assertEqual(DeliveryStatus.NEEDS_REVIEW, delivery.status)
        notes = [entry.note for entry in delivery.workflow_trace if entry.actor == "guest-policy"]
        self.assertIn("safety action: block", notes[0])

    def test_guest_send_rate_limit_by_source_ip(self) -> None:
        self.set_posture(self.recipient_token, "open")
        self.configure_guest_limits(ip_limit=2, recipient_limit=30)

        for _ in range(2):
            status_code, _ = self.guest_send(RECIPIENT_HANDLE, {"content": "Hi"}, source_ip="203.0.113.7")
            self.assertEqual(202, status_code)

        minted_before = self.guest_handles()
        status_code, body = self.guest_send(RECIPIENT_HANDLE, {"content": "Hi"}, source_ip="203.0.113.7")
        self.assertEqual(429, status_code)
        self.assertEqual("rate_limited", body["error"])
        # 429 happens BEFORE any registration/persistence.
        self.assertEqual(minted_before, self.guest_handles())

        # Another source is unaffected.
        status_code, _ = self.guest_send(RECIPIENT_HANDLE, {"content": "Hi"}, source_ip="203.0.113.8")
        self.assertEqual(202, status_code)

    def test_guest_send_rate_limit_by_recipient(self) -> None:
        self.set_posture(self.recipient_token, "open")
        self.configure_guest_limits(ip_limit=100, recipient_limit=2)

        for source_ip in ("203.0.113.1", "203.0.113.2"):
            status_code, _ = self.guest_send(RECIPIENT_HANDLE, {"content": "Hi"}, source_ip=source_ip)
            self.assertEqual(202, status_code)

        minted_before = self.guest_handles()
        status_code, body = self.guest_send(RECIPIENT_HANDLE, {"content": "Hi"}, source_ip="203.0.113.3")
        self.assertEqual(429, status_code)
        self.assertEqual("rate_limited", body["error"])
        self.assertEqual(minted_before, self.guest_handles())

    def test_reserved_guest_namespace_is_rejected(self) -> None:
        status_code, body = self.try_register({"handle": "@guest_0123456789abcdef"})
        self.assertEqual(400, status_code)
        self.assertEqual("bad_request", body["error"])
        self.assertIn("reserved", body["message"])

        # The public URL path refuses the namespace as well, with or without
        # the leading @ and regardless of Authorization.
        for name in ("@guest_0123456789abcdef", "guest_0123456789abcdef"):
            status_code, _ = self.guest_send(name, {"content": "Hi"})
            self.assertEqual(400, status_code)
            status_code, _ = self.send(self.sender_token, name, {"content": "Hi"})
            self.assertEqual(400, status_code)

    # -- signed guest status polling (M2.3)

    def test_invalid_guest_token_is_404(self) -> None:
        self.set_posture(self.recipient_token, "open")
        _, envelope = self.guest_send(RECIPIENT_HANDLE, {"content": "Hello"})
        _, second = self.guest_send(RECIPIENT_HANDLE, {"content": "Other"})
        _, delivery_id, token = split_status_url(str(envelope["status_url"]))
        _, _, other_token = split_status_url(str(second["status_url"]))

        tampered = ("0" if token[0] != "0" else "1") + token[1:]
        for bad_token in (tampered, other_token, "not-a-token", ""):
            status_code, body = self.guest_status(RECIPIENT_HANDLE, delivery_id, bad_token)
            self.assertEqual(404, status_code, bad_token)
            self.assertEqual("not_found", body["error"])

        # A valid token for a delivery not addressed to the path agent is
        # still a 404: the route never confirms other agents' traffic.
        status_code, _ = self.guest_status(BYSTANDER_HANDLE, delivery_id, token)
        self.assertEqual(404, status_code)

        # The untampered token still works.
        status_code, body = self.guest_status(RECIPIENT_HANDLE, delivery_id, token)
        self.assertEqual(200, status_code)
        self.assertEqual("quarantined", body["status"])


class LocalApiPublicAgentRoutesTest(PublicAgentRouteContractMixin, TestCase):
    """Drives LocalMessageHubApi directly (no HTTP transport, no kill switch)."""

    def setUp(self) -> None:
        self.repository = InMemoryMessageHubRepository()
        self.make_api()
        self.install_agents()

    def make_api(
        self,
        *,
        safety_evaluator: object | None = None,
        **guest_kwargs: object,
    ) -> None:
        self.api = LocalMessageHubApi(
            MessageHubService(
                self.repository,
                safety_evaluator=safety_evaluator or LocalSafetyEvaluator(),
            ),
            guest_status_signing_secret=GUEST_SIGNING_SECRET,
            **guest_kwargs,
        )

    def configure_guest_limits(self, *, ip_limit: int, recipient_limit: int) -> None:
        # Local api: limits are constructor parameters.
        self.make_api(
            guest_send_ip_hourly_limit=ip_limit,
            guest_send_recipient_hourly_limit=recipient_limit,
        )

    def configure_safety_evaluator(self, evaluator: object) -> None:
        self.make_api(safety_evaluator=evaluator)

    @staticmethod
    def authorization(token: str | None) -> str | None:
        return None if token is None else f"Bearer {token}"

    def register(self, body: dict[str, object]) -> str:
        return str(self.api.agent_registration(body)["token"])

    def try_register(self, body: dict[str, object]) -> tuple[int, dict[str, object]]:
        return self.call(lambda: self.api.agent_registration(body))

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
            replayed = bool(result.pop("replayed", False))
            return (200 if replayed else 202), result

        return self.call(invoke)

    def guest_send(
        self,
        name: str,
        body: dict[str, object],
        *,
        source_ip: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        def invoke() -> tuple[int, dict[str, object]]:
            return 202, self.api.public_agent_send(None, name, body, source_ip=source_ip)

        return self.call(invoke)

    def get_status(self, token: str | None, name: str, delivery_id: str) -> tuple[int, dict[str, object]]:
        return self.call(
            lambda: self.api.public_agent_message_status(self.authorization(token), name, delivery_id)
        )

    def guest_status(self, name: str, delivery_id: str, token: str) -> tuple[int, dict[str, object]]:
        return self.call(
            lambda: self.api.public_agent_guest_message_status(name, delivery_id, token)
        )

    def set_posture_raw(self, token: str | None, posture: str) -> tuple[int, dict[str, object]]:
        return self.call(
            lambda: self.api.agent_set_inbox_posture(
                self.authorization(token), {"inbox_posture": posture}
            )
        )

    def decide_reply(self, recipient_token: str, delivery_id: str, content: str) -> None:
        self.api.agent_decide_delivery(
            self.authorization(recipient_token), delivery_id, {"decision": "reply", "content": content}
        )

    # -- Local-only behavior

    def test_guest_send_without_source_ip_skips_the_ip_window(self) -> None:
        # Local callers without transport-level addressing pass None and only
        # the recipient window applies.
        self.set_posture(self.recipient_token, "open")
        self.configure_guest_limits(ip_limit=1, recipient_limit=30)
        for _ in range(3):
            status_code, _ = self.guest_send(RECIPIENT_HANDLE, {"content": "Hi"}, source_ip=None)
            self.assertEqual(202, status_code)

    def test_guest_send_without_content_is_bad_request_and_mints_nothing(self) -> None:
        self.set_posture(self.recipient_token, "open")
        status_code, body = self.guest_send(RECIPIENT_HANDLE, {})
        self.assertEqual(400, status_code)
        self.assertEqual("bad_request", body["error"])
        self.assertEqual([], self.guest_handles())

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
        env = patch.dict(
            os.environ,
            {"APP_NAME": "message-hub-test", "GUEST_STATUS_SIGNING_SECRET": GUEST_SIGNING_SECRET},
            clear=True,
        )
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(LAMBDA.reset_runtime)

        self.repository = InMemoryMessageHubRepository()
        self.service = LAMBDA.build_service(
            repository=self.repository,
            safety_evaluator=LocalSafetyEvaluator(),
        )
        self.install_api()
        self.install_agents()

    def install_api(self) -> None:
        # build_api reads the guest signing secret and window limits from the
        # (patched) environment, exactly like the deployed get_api.
        self.api = LAMBDA.build_api(service=self.service)
        LAMBDA.configure_api(self.api)

    def configure_guest_limits(self, *, ip_limit: int, recipient_limit: int) -> None:
        # Lambda api: limits come from the environment.
        env = patch.dict(
            os.environ,
            {
                "GUEST_SEND_IP_HOURLY_LIMIT": str(ip_limit),
                "GUEST_SEND_RECIPIENT_HOURLY_LIMIT": str(recipient_limit),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.install_api()

    def configure_safety_evaluator(self, evaluator: object) -> None:
        self.service = LAMBDA.build_service(
            repository=self.repository,
            safety_evaluator=evaluator,
        )
        self.install_api()

    def handle(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        *,
        source_ip: str | None = None,
        query: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        http: dict[str, object] = {"method": method, "path": path}
        if source_ip is not None:
            http["sourceIp"] = source_ip
        request: dict[str, object] = {
            "rawPath": path,
            "requestContext": {"http": http},
        }
        if headers is not None:
            request["headers"] = headers
        if query is not None:
            request["queryStringParameters"] = query
        if body is not None:
            request["body"] = json.dumps(body)
        response = LAMBDA.handler(request, None)
        return int(response["statusCode"]), json.loads(response["body"])

    def register(self, body: dict[str, object]) -> str:
        status_code, result = self.handle("POST", "/agent-registrations", body)
        assert status_code == 201, result
        return str(result["token"])

    def try_register(self, body: dict[str, object]) -> tuple[int, dict[str, object]]:
        return self.handle("POST", "/agent-registrations", body)

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

    def guest_send(
        self,
        name: str,
        body: dict[str, object],
        *,
        source_ip: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        return self.handle(
            "POST",
            f"/agents/{quote(name, safe='')}/messages",
            body,
            source_ip=source_ip,
        )

    def get_status(self, token: str | None, name: str, delivery_id: str) -> tuple[int, dict[str, object]]:
        headers = None if token is None else {"authorization": f"Bearer {token}"}
        return self.handle(
            "GET",
            f"/agents/{quote(name, safe='')}/messages/{quote(delivery_id, safe='')}",
            headers=headers,
        )

    def guest_status(self, name: str, delivery_id: str, token: str) -> tuple[int, dict[str, object]]:
        return self.handle(
            "GET",
            f"/agents/{quote(name, safe='')}/messages/{quote(delivery_id, safe='')}",
            query={"token": token},
        )

    def set_posture_raw(self, token: str | None, posture: str) -> tuple[int, dict[str, object]]:
        headers = None if token is None else {"authorization": f"Bearer {token}"}
        return self.handle("POST", "/agent/inbox-posture", {"inbox_posture": posture}, headers=headers)

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

    def test_guest_status_url_round_trips_through_the_lambda(self) -> None:
        self.set_posture(self.recipient_token, "open")
        _, envelope = self.guest_send(RECIPIENT_HANDLE, {"content": "Hello"})
        path, _, token = split_status_url(str(envelope["status_url"]))

        # The signed URL works without any Authorization header.
        status_code, body = self.handle("GET", path, query={"token": token})
        self.assertEqual(200, status_code)
        self.assertEqual({"delivery_id": envelope["delivery_id"], "status": "quarantined"}, body)

        # Without the token the same GET is the authenticated route.
        status_code, _ = self.handle("GET", path)
        self.assertEqual(401, status_code)

    def test_guest_send_without_signing_secret_is_503(self) -> None:
        self.set_posture(self.recipient_token, "open")
        with patch.dict(os.environ, {"GUEST_STATUS_SIGNING_SECRET": ""}):
            # Drop the secret cached at build_api time so the route check
            # observes the unset environment, as a cold start would.
            LAMBDA._RUNTIME["secrets"].pop("GUEST_STATUS_SIGNING_SECRET", None)
            status_code, body = self.guest_send(RECIPIENT_HANDLE, {"content": "Hello"})
            self.assertEqual(503, status_code)
            self.assertEqual("config_error", body["error"])
            self.assertIn("GUEST_STATUS_SIGNING_SECRET", body["message"])
            # Registered sends are unaffected by the missing guest secret.
            status_code, _ = self.send(self.sender_token, RECIPIENT_HANDLE, {"content": "Hi"})
            self.assertEqual(202, status_code)
        LAMBDA._RUNTIME["secrets"].pop("GUEST_STATUS_SIGNING_SECRET", None)

    def test_public_send_emits_one_structured_log_line(self) -> None:
        self.set_posture(self.recipient_token, "open")

        def send_and_capture(invoke):
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                result = invoke()
            lines = [
                json.loads(line)
                for line in captured.getvalue().splitlines()
                if line.strip().startswith("{")
            ]
            return result, [line for line in lines if line.get("event") == "public_agent_send"]

        (status_code, envelope), logs = send_and_capture(
            lambda: self.guest_send(RECIPIENT_HANDLE, {"content": "Hello"}, source_ip="203.0.113.9")
        )
        self.assertEqual(202, status_code)
        self.assertEqual(1, len(logs))
        self.assertEqual(
            {
                "event": "public_agent_send",
                "route": "POST /agents/{name}/messages",
                "recipient": RECIPIENT_HANDLE,
                "posture": "open",
                "sender_class": "guest",
                "outcome": "accepted",
                "delivery_id": envelope["delivery_id"],
            },
            logs[0],
        )

        (status_code, _), logs = send_and_capture(
            lambda: self.send(self.sender_token, RECIPIENT_HANDLE, {"content": "Hi"})
        )
        self.assertEqual(202, status_code)
        self.assertEqual(1, len(logs))
        self.assertEqual("registered", logs[0]["sender_class"])
        self.assertEqual("accepted", logs[0]["outcome"])

        # Failures log their error code as the outcome.
        self.set_posture(self.recipient_token, "contacts_only")
        (status_code, _), logs = send_and_capture(
            lambda: self.guest_send(RECIPIENT_HANDLE, {"content": "Hello"})
        )
        self.assertEqual(403, status_code)
        self.assertEqual(1, len(logs))
        self.assertEqual("guest", logs[0]["sender_class"])
        self.assertEqual("posture_not_open", logs[0]["outcome"])
        self.assertEqual("contacts_only", logs[0]["posture"])
        self.assertIsNone(logs[0]["delivery_id"])

    def test_kill_switch_disables_only_the_new_routes(self) -> None:
        self.set_posture(self.recipient_token, "open")
        envelope = self.send_hello()
        delivery_id = str(envelope["delivery_id"])
        _, guest_envelope = self.guest_send(RECIPIENT_HANDLE, {"content": "Hello"})
        _, guest_delivery_id, guest_token = split_status_url(str(guest_envelope["status_url"]))

        for disabled in ("false", "0"):
            with patch.dict(os.environ, {"PUBLIC_AGENT_URLS_ENABLED": disabled}):
                status_code, body = self.send(self.sender_token, RECIPIENT_HANDLE, {"content": "Hi"})
                self.assertEqual(404, status_code)
                self.assertEqual("not_found", body["error"])
                status_code, body = self.get_status(self.sender_token, RECIPIENT_HANDLE, delivery_id)
                self.assertEqual(404, status_code)
                self.assertEqual("not_found", body["error"])
                # Guest ingress and the signed status poll are behind the same
                # switch.
                status_code, body = self.guest_send(RECIPIENT_HANDLE, {"content": "Hi"})
                self.assertEqual(404, status_code)
                self.assertEqual("not_found", body["error"])
                status_code, body = self.guest_status(RECIPIENT_HANDLE, guest_delivery_id, guest_token)
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
                status_code, _ = self.guest_status(RECIPIENT_HANDLE, guest_delivery_id, guest_token)
                self.assertEqual(200, status_code)
