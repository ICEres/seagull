from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "aws" / "delivery_recovery.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("delivery_recovery_test_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
recovery = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = recovery
SPEC.loader.exec_module(recovery)


class Body:
    def __init__(self, value: bytes):
        self.value = value

    def read(self):
        return self.value


class Table:
    def __init__(self, items: dict[str, dict[str, object]], key: str):
        self.items = items
        self.key = key

    def get_item(self, *, Key, **kwargs):
        item = self.items.get(Key[self.key])
        return {} if item is None else {"Item": item}

    def scan(self, *, Limit=100, ExclusiveStartKey=None, **kwargs):
        keys = list(self.items)
        start = 0
        if ExclusiveStartKey:
            start = keys.index(ExclusiveStartKey[self.key]) + 1
        selected = keys[start : start + Limit]
        result = {"Items": [self.items[key] for key in selected]}
        if start + Limit < len(keys):
            result["LastEvaluatedKey"] = {self.key: selected[-1]}
        return result


class Queue:
    def __init__(self):
        self.sent = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)


class FlakyQueue(Queue):
    def __init__(self):
        super().__init__()
        self.fail = True

    def send_message(self, **kwargs):
        if self.fail:
            self.fail = False
            raise RuntimeError("temporary SQS outage")
        super().send_message(**kwargs)


class S3:
    def __init__(self):
        self.values = {}
        self.saved = []

    def get_object(self, *, Bucket, Key):
        return {"Body": Body(self.values[(Bucket, Key)])}

    def put_object(self, **kwargs):
        self.saved.append(kwargs)
        self.values[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]


class PagedS3:
    def __init__(self, pages):
        self.pages = pages
        self.values = {}
        self.calls = []

    def list_objects_v2(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        return self.pages[index]

    def get_object(self, *, Bucket, Key):
        return {"Body": Body(self.values[(Bucket, Key)])}


def tables(*, status="delivered"):
    deliveries = Table({
        "delivery-1": {"delivery_id": "delivery-1", "message_id": "message-1", "thread_id": "thread-1", "recipient_agent_id": "agent-2", "sender_agent_id": "agent-1", "status": status, "created_at": "2026-10-23T00:00:00Z"},
    }, "delivery_id")
    messages = Table({"message-1": {"message_id": "message-1", "thread_id": "thread-1", "sender_agent_id": "agent-1", "intent": "message", "visibility": "direct", "content_inline": "hello", "created_at": "2026-10-23T00:00:00Z"}}, "message_id")
    agents = Table({"agent-1": {"agent_id": "agent-1", "handle": "@one:gulls.ai"}, "agent-2": {"agent_id": "agent-2", "handle": "@two:gulls.ai"}}, "agent_id")
    return deliveries, messages, agents


class DeliveryRecoveryTest(unittest.TestCase):
    def test_replay_deduplicates_archive_records_and_rechecks_current_delivery(self):
        deliveries, messages, agents = tables()
        queue = Queue()
        image = {"delivery_id": "delivery-1", "status": "delivered"}
        record = {"image": image}
        runner = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=False)

        with patch.object(recovery, "_image", side_effect=lambda value: value["image"]):
            report = runner.replay_objects([("failure/a.json", json.dumps({"requestPayload": json.dumps({"Records": [record, record]})}).encode())])

        self.assertEqual(1, report.published)
        self.assertEqual(1, len(queue.sent))
        self.assertEqual("delivery-1", queue.sent[0]["MessageDeduplicationId"])
        deliveries.items["delivery-1"]["status"] = "needs_review"
        with patch.object(recovery, "_image", side_effect=lambda value: value["image"]):
            report = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=False).replay_objects([("failure/b.json", json.dumps({"Records": [record]}).encode())])
        self.assertEqual(1, report.unresolved)
        self.assertEqual(1, len(queue.sent))

    def test_replay_checkpoint_skips_completed_objects(self):
        deliveries, messages, agents = tables()
        queue = Queue()
        s3 = S3()
        checkpoint = recovery.S3CheckpointStore(s3, "archive", "checkpoints/run.json")
        checkpoint.save({"mode": "replay", "target": "queue", "source": "s3://archive/failure/", "completed_objects": ["failure/a.json"]})
        runner = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=True, checkpoint=checkpoint)
        report = runner.replay_objects([("failure/a.json", b"not-json"), ("failure/b.json", b'{"Records": []}')], source_identity="s3://archive/failure/")
        self.assertEqual(2, report.objects)
        self.assertEqual([], report.failures)
        self.assertEqual(1, len(s3.saved), "dry-run must not advance the checkpoint")

    def test_reconcile_dry_run_skips_held_and_persists_page_checkpoint(self):
        deliveries, messages, agents = tables()
        deliveries.items["delivery-2"] = {**deliveries.items["delivery-1"], "delivery_id": "delivery-2", "status": "needs_review", "created_at": "2026-10-23T00:01:00Z"}
        queue = Queue()
        s3 = S3()
        checkpoint = recovery.S3CheckpointStore(s3, "archive", "checkpoints/reconcile.json")
        runner = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=True, checkpoint=checkpoint)
        report = runner.reconcile(datetime(2026, 10, 23, tzinfo=timezone.utc), datetime(2026, 10, 23, 0, 2, tzinfo=timezone.utc), page_size=1)
        self.assertEqual(1, report.planned)
        self.assertEqual(1, report.skipped)
        self.assertEqual([], queue.sent)
        self.assertEqual([], s3.saved, "dry-run must not write a checkpoint")

    def test_dry_run_does_not_block_execute_with_same_checkpoint(self):
        deliveries, messages, agents = tables()
        queue = Queue()
        s3 = S3()
        checkpoint = recovery.S3CheckpointStore(s3, "archive", "checkpoints/replay.json")
        record = {"image": {"delivery_id": "delivery-1", "status": "delivered"}}
        with patch.object(recovery, "_image", side_effect=lambda value: value["image"]):
            dry = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=True, checkpoint=checkpoint)
            dry.replay_objects([("failure/a.json", json.dumps({"Records": [record]}).encode())])
            execute = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=False, checkpoint=checkpoint)
            report = execute.replay_objects([("failure/a.json", json.dumps({"Records": [record]}).encode())])
        self.assertEqual(1, report.published)
        self.assertEqual(1, len(queue.sent))

    def test_transient_sqs_failure_can_retry_same_delivery(self):
        deliveries, messages, agents = tables()
        queue = FlakyQueue()
        runner = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=False)
        report = recovery.RecoveryReport()
        with self.assertRaises(RuntimeError):
            runner.publish_delivery("delivery-1", report)
        self.assertEqual("completed", runner.publish_delivery("delivery-1", report))
        self.assertEqual(1, len(queue.sent))

    def test_held_archive_remains_replayable_after_release(self):
        deliveries, messages, agents = tables(status="needs_review")
        queue = Queue()
        record = {"image": {"delivery_id": "delivery-1", "status": "delivered"}}
        runner = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=False)
        with patch.object(recovery, "_image", side_effect=lambda value: value["image"]):
            first = runner.replay_objects([("failure/held.json", json.dumps({"Records": [record]}).encode())])
        self.assertEqual(1, first.unresolved)
        self.assertEqual([], queue.sent)
        deliveries.items["delivery-1"]["status"] = "delivered"
        with patch.object(recovery, "_image", side_effect=lambda value: value["image"]):
            second = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=False).replay_objects([("failure/held.json", json.dumps({"Records": [record]}).encode())])
        self.assertEqual(1, second.published)
        self.assertEqual(1, len(queue.sent))

    def test_checkpoint_window_and_target_mismatch_are_rejected(self):
        deliveries, messages, agents = tables()
        queue = Queue()
        s3 = S3()
        checkpoint = recovery.S3CheckpointStore(s3, "archive", "checkpoints/reconcile.json")
        checkpoint.save({"mode": "reconcile", "target": "other-queue", "start": "2026-10-23T00:00:00+00:00", "end": "2026-10-23T00:02:00+00:00", "last_evaluated_key": None})
        runner = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=False, checkpoint=checkpoint)
        with self.assertRaises(ValueError):
            runner.reconcile(datetime(2026, 10, 23, tzinfo=timezone.utc), datetime(2026, 10, 23, 0, 2, tzinfo=timezone.utc))

    def test_replay_checkpoint_rejects_a_different_archive_source(self):
        deliveries, messages, agents = tables()
        queue = Queue()
        s3 = S3()
        checkpoint = recovery.S3CheckpointStore(s3, "archive", "checkpoints/replay.json")
        checkpoint.save({"mode": "replay", "target": "queue", "source": "s3://archive/failure-a/", "completed_objects": []})
        runner = recovery.DeliveryRecovery(
            deliveries=deliveries,
            messages=messages,
            agents=agents,
            queue=queue,
            queue_url="queue",
            dry_run=True,
            checkpoint=checkpoint,
        )
        with self.assertRaises(ValueError):
            runner.replay_objects([], source_identity="s3://archive/failure-b/")

    def test_list_objects_excludes_checkpoint_key_on_every_page(self):
        s3 = PagedS3([
            {"Contents": [{"Key": "failure/a.json"}, {"Key": "failure/checkpoint.json"}], "NextContinuationToken": "next"},
            {"Contents": [{"Key": "failure/b.json"}, {"Key": "failure/checkpoint.json"}]},
        ])
        s3.values.update({
            ("archive", "failure/a.json"): b"a",
            ("archive", "failure/b.json"): b"b",
        })
        self.assertEqual(
            [("failure/a.json", b"a"), ("failure/b.json", b"b")],
            list(recovery._list_objects(s3, "archive", "failure/", exclude_key="failure/checkpoint.json")),
        )
        self.assertEqual("next", s3.calls[1]["ContinuationToken"])

    def test_reconcile_includes_created_or_updated_timestamp_in_window(self):
        deliveries, messages, agents = tables()
        base = deliveries.items["delivery-1"]
        deliveries.items["delivery-created"] = {
            **base,
            "delivery_id": "delivery-created",
            "created_at": "2026-10-23T00:01:00Z",
            "updated_at": "2026-10-22T23:00:00Z",
        }
        deliveries.items["delivery-updated"] = {
            **base,
            "delivery_id": "delivery-updated",
            "created_at": "2026-10-22T23:00:00Z",
            "updated_at": "2026-10-23T00:01:00Z",
        }
        queue = Queue()
        runner = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=True)
        report = runner.reconcile(
            datetime(2026, 10, 23, tzinfo=timezone.utc),
            datetime(2026, 10, 23, 0, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(3, report.planned)

    def test_reconcile_reports_incomplete_when_page_limit_leaves_cursor(self):
        deliveries, messages, agents = tables()
        deliveries.items["delivery-2"] = {
            **deliveries.items["delivery-1"],
            "delivery_id": "delivery-2",
            "created_at": "2026-10-23T00:01:00Z",
        }
        queue = Queue()
        runner = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=True)
        report = runner.reconcile(
            datetime(2026, 10, 23, tzinfo=timezone.utc),
            datetime(2026, 10, 23, 0, 2, tzinfo=timezone.utc),
            page_size=1,
            max_pages=1,
        )
        self.assertTrue(report.incomplete)

    def test_partial_archive_failure_does_not_stop_later_objects(self):
        deliveries, messages, agents = tables()
        queue = Queue()
        runner = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=False)
        report = runner.replay_objects([("failure/bad.json", b"{}"), ("failure/good.json", b'{"Records": []}')])
        self.assertEqual(1, len(report.failures))
        self.assertEqual(2, report.objects)

    def test_partial_record_failure_keeps_other_records_replayable(self):
        deliveries, messages, agents = tables()
        deliveries.items["delivery-2"] = {**deliveries.items["delivery-1"], "delivery_id": "delivery-2", "message_id": "missing-message"}
        queue = Queue()
        runner = recovery.DeliveryRecovery(deliveries=deliveries, messages=messages, agents=agents, queue=queue, queue_url="queue", dry_run=False)
        good = {"image": {"delivery_id": "delivery-1", "status": "delivered"}}
        bad = {"image": {"delivery_id": "delivery-2", "status": "delivered"}}
        with patch.object(recovery, "_image", side_effect=lambda value: value["image"]):
            report = runner.replay_objects([("failure/mixed.json", json.dumps({"Records": [bad, good]}).encode())])
        self.assertEqual(1, len(report.failures))
        self.assertEqual(1, len(queue.sent))
