"""Publish committed delivery rows from DynamoDB Streams to the agent queue.

The API transaction owns the durable message/delivery state. This Lambda is the
recoverable handoff: a delivery is acknowledged by the stream only after its
stable event has been accepted by the FIFO queue.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


def _client(name: str) -> Any:
    import boto3

    return boto3.client(name)


def _resource():
    import boto3

    return boto3.resource("dynamodb")


def _image(record: dict[str, Any]) -> dict[str, Any]:
    from boto3.dynamodb.types import TypeDeserializer

    image = record.get("dynamodb", {}).get("NewImage") or {}
    deserializer = TypeDeserializer()
    return {key: deserializer.deserialize(value) for key, value in image.items()}


def _event(delivery: dict[str, Any], message: dict[str, Any], sender: dict[str, Any], recipient: dict[str, Any]) -> dict[str, Any]:
    delivery_id = str(delivery["delivery_id"])
    message_id = str(message["message_id"])
    thread_id = str(delivery.get("thread_id") or message.get("thread_id") or "")
    created_at = str(delivery.get("created_at") or message.get("created_at") or datetime.now(timezone.utc).isoformat())
    event_id = f"event_{delivery_id}"
    return {
        "specversion": "1.0",
        "type": "seagull.delivery.created.v1",
        "source": "seagull.message-hub",
        "id": event_id,
        "event_id": event_id,
        "time": created_at,
        "subject": delivery_id,
        "datacontenttype": "application/json",
        "data": {
            "event_id": event_id,
            "delivery_id": delivery_id,
            "message_id": message_id,
            "thread_id": thread_id,
            "sender_agent_id": str(message.get("sender_agent_id") or delivery.get("sender_agent_id") or ""),
            "sender_handle": str(sender.get("handle") or ""),
            "recipient_agent_id": str(delivery.get("recipient_agent_id") or ""),
            "recipient_handle": str(recipient.get("handle") or ""),
            "intent": str(message.get("intent") or "message"),
            "visibility": str(message.get("visibility") or "direct"),
            "content_inline": message.get("content_inline"),
            "content_ref": message.get("content_ref"),
            "created_at": str(message.get("created_at") or created_at),
            "refs": delivery.get("refs") or [],
            "current_content_inline": delivery.get("current_content_inline") or message.get("content_inline"),
            "current_content_ref": delivery.get("current_content_ref") or message.get("content_ref"),
            "current_stage": delivery.get("current_stage") or "agent.wait",
        },
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    dynamodb = _resource()
    deliveries = dynamodb.Table(os.environ["DELIVERIES_TABLE"])
    messages = dynamodb.Table(os.environ["MESSAGES_TABLE"])
    agents = dynamodb.Table(os.environ["AGENTS_TABLE"])
    sqs = _client("sqs")
    queue_url = os.environ["AGENT_JOBS_QUEUE_URL"]
    failures: list[dict[str, str]] = []

    records = list(event.get("Records", []))
    for index, record in enumerate(records):
        record_id = str(
            record.get("dynamodb", {}).get("SequenceNumber")
            or record.get("eventID")
            or record.get("eventId")
            or ""
        )
        try:
            if record.get("eventName") not in {"INSERT", "MODIFY"}:
                continue
            image = _image(record)
            if image.get("status") != "delivered":
                continue
            old_image = record.get("dynamodb", {}).get("OldImage") or {}
            if record.get("eventName") == "MODIFY":
                from boto3.dynamodb.types import TypeDeserializer

                old_status = TypeDeserializer().deserialize(old_image["status"]) if "status" in old_image else None
                if old_status == "delivered":
                    continue
            delivery_id = str(image["delivery_id"])
            # Streams can deliver an older NewImage after a moderation update.
            # Read the current row strongly before publishing so a delivery
            # that is now held cannot leak into the worker queue.
            current = deliveries.get_item(
                Key={"delivery_id": delivery_id}, ConsistentRead=True
            ).get("Item")
            if current is None or current.get("status") != "delivered":
                continue
            image = current
            message_id = str(image["message_id"])
            message = messages.get_item(Key={"message_id": message_id}, ConsistentRead=True).get("Item")
            recipient_id = str(image["recipient_agent_id"])
            sender_id = str(message.get("sender_agent_id") or image.get("sender_agent_id")) if message else ""
            recipient = agents.get_item(Key={"agent_id": recipient_id}, ConsistentRead=True).get("Item")
            sender = agents.get_item(Key={"agent_id": sender_id}, ConsistentRead=True).get("Item")
            if message is None or recipient is None or sender is None:
                raise RuntimeError(f"delivery {delivery_id} references missing message or agent")
            payload = _event(image, message, sender, recipient)
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(payload, separators=(",", ":"), sort_keys=True),
                MessageGroupId=str(image.get("thread_id") or message.get("thread_id") or delivery_id),
                MessageDeduplicationId=delivery_id,
            )
        except Exception as exc:
            print(json.dumps({"level": "error", "message": str(exc), "record": record_id}))
            # DynamoDB Streams are ordered per shard. Do not publish a later
            # record after an earlier record failed, or a same-thread message
            # can overtake the retry of the earlier one.
            for pending in records[index:]:
                pending_id = str(
                    pending.get("dynamodb", {}).get("SequenceNumber")
                    or pending.get("eventID")
                    or pending.get("eventId")
                    or ""
                )
                if pending_id:
                    failures.append({"itemIdentifier": pending_id})
            break
    return {"batchItemFailures": failures}
