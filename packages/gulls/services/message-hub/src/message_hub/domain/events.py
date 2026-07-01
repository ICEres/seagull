from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any

from message_hub.domain.models import Agent, Delivery, Message


DELIVERY_CREATED_EVENT_TYPE = "seagull.delivery.created.v1"
DELIVERY_EVENT_SOURCE = "seagull.message-hub"


def delivery_created_event(
    *,
    delivery: Delivery,
    message: Message,
    sender: Agent,
    recipient: Agent,
) -> dict[str, Any]:
    event_id = delivery_event_id(delivery.delivery_id)
    return {
        "specversion": "1.0",
        "type": DELIVERY_CREATED_EVENT_TYPE,
        "source": DELIVERY_EVENT_SOURCE,
        "id": event_id,
        "event_id": event_id,
        "time": datetime_to_event_time(delivery.created_at),
        "subject": delivery.delivery_id,
        "datacontenttype": "application/json",
        "data": {
            "event_id": event_id,
            "delivery_id": delivery.delivery_id,
            "message_id": message.message_id,
            "thread_id": message.thread_id,
            "sender_agent_id": sender.agent_id,
            "sender_handle": sender.handle,
            "recipient_agent_id": recipient.agent_id,
            "recipient_handle": recipient.handle,
            "intent": message.intent,
            "visibility": message.visibility,
            "content_inline": message.content_inline,
            "content_ref": message.content_ref,
            "created_at": datetime_to_event_time(message.created_at),
        },
    }


def delivery_event_id(delivery_id: str) -> str:
    return f"event_{delivery_id}"


def sign_webhook_body(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def datetime_to_event_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
