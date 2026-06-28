from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

from message_hub.api import LocalMessageHubApi
from seagull_sdk import DEFAULT_INLINE_CHAR_LIMIT, SendMessageClientAdapter, send_message_with_auto_payload


class RecordingPayloadClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def create_payload(self, body: dict[str, object]) -> dict[str, object]:
        self.calls.append(("create_payload", dict(body)))
        return {
            "content_ref": "payload://payload_1",
            "payload": {
                "content_ref": "payload://payload_1",
                "media_type": body["media_type"],
                "byte_length": len(str(body["content"]).encode("utf-8")),
                "hash": "sha256:payload",
                "compression": "gzip",
                "compressed_byte_length": 20,
                "compressed_hash": "sha256:compressed",
                "retention_state": "ready",
                "access_scope": body["access_scope"],
                "storage_provider": "local_node",
                "storage_ref": "payload://payload_1",
            },
        }

    def create_message(self, body: dict[str, object]) -> dict[str, object]:
        self.calls.append(("create_message", dict(body)))
        return {"thread_id": "thread_1", "message": dict(body)}


class RecordingSendMessageClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []
        self.messages: list[dict[str, object]] = []

    def create_payload(
        self,
        *,
        content: str,
        media_type: str,
        access_scope: str,
        ttl_expires_at: str | None = None,
    ) -> dict[str, object]:
        payload = {
            "content": content,
            "media_type": media_type,
            "access_scope": access_scope,
            "ttl_expires_at": ttl_expires_at,
        }
        self.payloads.append(payload)
        return {
            "content_ref": "payload://payload_1",
            "payload": {
                "content_ref": "payload://payload_1",
                "media_type": media_type,
                "hash": "sha256:payload",
                "compressed_hash": "sha256:compressed",
            },
        }

    def send_message(
        self,
        *,
        sender_handle: str,
        recipient_handles: tuple[str, ...],
        content: str | None = None,
        content_ref: str | None = None,
        refs: tuple[dict[str, object], ...] = (),
        thread_id: str | None = None,
        intent: str = "message",
        visibility: str = "direct",
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        message = {
            "sender_handle": sender_handle,
            "recipient_handles": list(recipient_handles),
            "content": content,
            "content_ref": content_ref,
            "refs": list(refs),
            "thread_id": thread_id,
            "intent": intent,
            "visibility": visibility,
            "idempotency_key": idempotency_key,
        }
        self.messages.append(message)
        return {"thread_id": "thread_1", "message": message}


class AutoPayloadHelperTest(TestCase):
    def test_small_content_stays_inline(self) -> None:
        client = RecordingPayloadClient()

        result = send_message_with_auto_payload(
            client,
            sender_handle="@researcher:seagull.local",
            recipient_handles=("@reviewer:seagull.local",),
            content="Small message.",
        )

        self.assertIsNone(result.payload)
        self.assertEqual(["create_message"], [name for name, _body in client.calls])
        message_body = client.calls[0][1]
        self.assertEqual("Small message.", message_body["content"])
        self.assertNotIn("content_ref", message_body)

    def test_existing_content_ref_sends_ref_without_payload_upload(self) -> None:
        client = RecordingPayloadClient()

        result = send_message_with_auto_payload(
            client,
            sender_handle="@researcher:seagull.local",
            recipient_handles=("@reviewer:seagull.local",),
            content="Do not copy this into the envelope.",
            content_ref="payload://payload_existing",
        )

        self.assertIsNone(result.payload)
        self.assertEqual("payload://payload_existing", result.content_ref)
        self.assertEqual(["create_message"], [name for name, _body in client.calls])
        message_body = client.calls[0][1]
        self.assertEqual("payload://payload_existing", message_body["content_ref"])
        self.assertNotIn("content", message_body)

    def test_large_content_is_stored_before_message_delivery(self) -> None:
        client = RecordingPayloadClient()
        content = "x" * (DEFAULT_INLINE_CHAR_LIMIT + 1)
        expires_at = datetime(2026, 6, 28, tzinfo=timezone.utc)

        result = send_message_with_auto_payload(
            client,
            sender_handle="@researcher:seagull.local",
            recipient_handles=("@reviewer:seagull.local",),
            content=content,
            media_type="text/markdown",
            access_scope="thread",
            ttl_expires_at=expires_at,
            refs=({"type": "url", "url": "https://example.com/context"},),
            idempotency_key="send-1",
        )

        self.assertEqual(["create_payload", "create_message"], [name for name, _body in client.calls])
        payload_body = client.calls[0][1]
        message_body = client.calls[1][1]
        self.assertEqual(content, payload_body["content"])
        self.assertEqual("text/markdown", payload_body["media_type"])
        self.assertEqual("thread", payload_body["access_scope"])
        self.assertEqual(expires_at.isoformat(), payload_body["ttl_expires_at"])
        self.assertEqual("payload://payload_1", message_body["content_ref"])
        self.assertEqual("send-1", message_body["idempotency_key"])
        self.assertNotIn("content", message_body)
        self.assertEqual("payload://payload_1", result.content_ref)
        assert result.payload_manifest is not None
        self.assertEqual("sha256:compressed", result.payload_manifest["compressed_hash"])
        self.assertEqual("local_node", result.payload_manifest["storage_provider"])
        self.assertEqual("payload://payload_1", result.payload["content_ref"])

    def test_send_message_client_adapter_hides_payload_storage_details(self) -> None:
        client = RecordingSendMessageClient()
        adapter = SendMessageClientAdapter(client)

        result = send_message_with_auto_payload(
            adapter,
            sender_handle="@researcher:seagull.local",
            recipient_handles=("@reviewer:seagull.local",),
            content="x" * (DEFAULT_INLINE_CHAR_LIMIT + 1),
            media_type="text/markdown",
            access_scope="thread",
        )

        self.assertEqual("payload://payload_1", result.content_ref)
        self.assertEqual(1, len(client.payloads))
        self.assertEqual(1, len(client.messages))
        self.assertEqual("payload://payload_1", client.messages[0]["content_ref"])
        self.assertIsNone(client.messages[0]["content"])

    def test_limit_boundary_is_inline(self) -> None:
        client = RecordingPayloadClient()

        send_message_with_auto_payload(
            client,
            sender_handle="@researcher:seagull.local",
            recipient_handles=("@reviewer:seagull.local",),
            content="x" * DEFAULT_INLINE_CHAR_LIMIT,
        )

        self.assertEqual(["create_message"], [name for name, _body in client.calls])

    def test_negative_limit_is_invalid(self) -> None:
        client = RecordingPayloadClient()

        with self.assertRaises(ValueError):
            send_message_with_auto_payload(
                client,
                sender_handle="@researcher:seagull.local",
                recipient_handles=("@reviewer:seagull.local",),
                content="small",
                inline_char_limit=-1,
            )

    def test_missing_content_and_ref_is_invalid(self) -> None:
        client = RecordingPayloadClient()

        with self.assertRaises(ValueError):
            send_message_with_auto_payload(
                client,
                sender_handle="@researcher:seagull.local",
                recipient_handles=("@reviewer:seagull.local",),
                content_ref=" ",
            )

    def test_large_content_uses_local_payload_storage_before_delivery(self) -> None:
        api = LocalMessageHubApi.in_memory()
        api.register_agent({"handle": "@researcher:seagull.local"})
        api.register_agent({"handle": "@reviewer:seagull.local"})
        content = "Large payload.\n" * 500

        result = send_message_with_auto_payload(
            api,
            sender_handle="@researcher:seagull.local",
            recipient_handles=("@reviewer:seagull.local",),
            content=content,
            media_type="text/markdown",
            access_scope="thread",
        )

        self.assertIsNotNone(result.payload)
        assert result.payload is not None
        payload_ref = result.payload["content_ref"]
        fetched_payload = api.read_payload(
            payload_ref,
            requester_handle="@reviewer:seagull.local",
        )
        inbox = api.read_inbox("@reviewer:seagull.local")
        self.assertEqual("gzip", result.payload["payload"]["compression"])
        self.assertLess(
            result.payload["payload"]["compressed_byte_length"],
            result.payload["payload"]["byte_length"],
        )
        self.assertIsNone(result.response["message"]["content_inline"])
        self.assertEqual(payload_ref, result.response["message"]["content_ref"])
        self.assertEqual(payload_ref, inbox["items"][0]["current_message"]["content_ref"])
        self.assertEqual(content, fetched_payload["content"])
