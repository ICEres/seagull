from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "aws" / "delivery_stream_publisher.py"
SPEC = importlib.util.spec_from_file_location("delivery_stream_publisher_test_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class Table:
    def __init__(self, items: dict[str, dict[str, object]], key: str) -> None:
        self.items = items
        self.key = key

    def get_item(self, *, Key: dict[str, str], **kwargs):
        item = self.items.get(Key[self.key])
        return {} if item is None else {"Item": item}


class Resource:
    def __init__(self):
        self.tables = {
            "deliveries": Table(
                {
                    "delivery_1": {
                        "delivery_id": "delivery_1",
                        "message_id": "message_1",
                        "thread_id": "thread_1",
                        "recipient_agent_id": "agent_2",
                        "sender_agent_id": "agent_1",
                        "status": "delivered",
                        "created_at": "2026-10-23T00:00:00Z",
                    }
                },
                "delivery_id",
            ),
            "messages": Table({"message_1": {"message_id": "message_1", "sender_agent_id": "agent_1", "thread_id": "thread_1", "intent": "message", "visibility": "direct", "content_inline": "hello", "created_at": "2026-10-23T00:00:00Z"}}, "message_id"),
            "agents": Table({"agent_1": {"agent_id": "agent_1", "handle": "@one:gulls.ai"}, "agent_2": {"agent_id": "agent_2", "handle": "@two:gulls.ai"}}, "agent_id"),
        }

    def Table(self, name: str):
        return self.tables[name]


class SQS:
    def __init__(self):
        self.sent = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)


class DeliveryStreamPublisherTest(unittest.TestCase):
    def test_failure_stops_later_records_in_the_same_batch(self):
        resource = Resource()
        sqs = SQS()
        resource.tables["deliveries"].items.update(
            {
                "delivery_bad": {
                    "delivery_id": "delivery_bad",
                    "message_id": "missing_message",
                    "recipient_agent_id": "agent_2",
                    "status": "delivered",
                },
                "delivery_2": {
                    "delivery_id": "delivery_2",
                    "message_id": "message_1",
                    "recipient_agent_id": "agent_2",
                    "status": "delivered",
                },
            }
        )
        os.environ.update({"DELIVERIES_TABLE": "deliveries", "MESSAGES_TABLE": "messages", "AGENTS_TABLE": "agents", "AGENT_JOBS_QUEUE_URL": "queue"})
        from boto3.dynamodb.types import TypeSerializer

        serializer = TypeSerializer()
        first = {
            "delivery_id": "delivery_bad",
            "message_id": "missing_message",
            "recipient_agent_id": "agent_2",
            "status": "delivered",
        }
        second = {
            "delivery_id": "delivery_2",
            "message_id": "message_1",
            "recipient_agent_id": "agent_2",
            "status": "delivered",
        }
        records = [
            {"eventID": "seq-1", "eventName": "INSERT", "dynamodb": {"NewImage": {k: serializer.serialize(v) for k, v in first.items()}}},
            {"eventID": "seq-2", "eventName": "INSERT", "dynamodb": {"NewImage": {k: serializer.serialize(v) for k, v in second.items()}}},
        ]

        with patch.object(publisher, "_resource", return_value=resource), patch.object(publisher, "_client", return_value=sqs):
            result = publisher.handler({"Records": records}, None)

        self.assertEqual([{"itemIdentifier": "seq-1"}, {"itemIdentifier": "seq-2"}], result["batchItemFailures"])
        self.assertEqual([], sqs.sent)

    def test_publishes_only_newly_deliverable_rows_with_stable_event_id(self):
        resource = Resource()
        sqs = SQS()
        os.environ.update({"DELIVERIES_TABLE": "deliveries", "MESSAGES_TABLE": "messages", "AGENTS_TABLE": "agents", "AGENT_JOBS_QUEUE_URL": "queue"})
        from boto3.dynamodb.types import TypeSerializer

        serializer = TypeSerializer()
        image = {
            "delivery_id": "delivery_1",
            "message_id": "message_1",
            "thread_id": "thread_1",
            "recipient_agent_id": "agent_2",
            "sender_agent_id": "agent_1",
            "status": "delivered",
            "created_at": "2026-10-23T00:00:00Z",
        }
        record = {"eventID": "shard:1", "eventName": "INSERT", "dynamodb": {"NewImage": {k: serializer.serialize(v) for k, v in image.items()}}}
        with patch.object(publisher, "_resource", return_value=resource), patch.object(publisher, "_client", return_value=sqs):
            result = publisher.handler({"Records": [record, record]}, None)

        self.assertEqual([], result["batchItemFailures"])
        self.assertEqual(2, len(sqs.sent))
        self.assertEqual("delivery_1", sqs.sent[0]["MessageDeduplicationId"])
        self.assertEqual(sqs.sent[0]["MessageBody"], sqs.sent[1]["MessageBody"])

    def test_skips_review_hold(self):
        resource = Resource()
        sqs = SQS()
        os.environ.update({"DELIVERIES_TABLE": "deliveries", "MESSAGES_TABLE": "messages", "AGENTS_TABLE": "agents", "AGENT_JOBS_QUEUE_URL": "queue"})
        from boto3.dynamodb.types import TypeSerializer

        serializer = TypeSerializer()
        record = {"eventID": "shard:2", "eventName": "INSERT", "dynamodb": {"NewImage": {"delivery_id": serializer.serialize("delivery_2"), "status": serializer.serialize("needs_review")}}}
        with patch.object(publisher, "_resource", return_value=resource), patch.object(publisher, "_client", return_value=sqs):
            result = publisher.handler({"Records": [record]}, None)
        self.assertEqual([], result["batchItemFailures"])
        self.assertEqual([], sqs.sent)
