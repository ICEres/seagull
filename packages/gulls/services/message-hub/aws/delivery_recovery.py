"""Recover delivery publication after a stream outage.

This module is intentionally separate from the stream Lambda.  It replays the
original Lambda failure envelope from S3 or scans a bounded delivery window,
then re-reads each delivery before publishing.  The default is a dry run so an
operator must opt in to sending FIFO messages.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

try:  # Lambda zip files place both modules at the root.
    from .delivery_stream_publisher import _event, _image
except ImportError:  # pragma: no cover - exercised by the standalone CLI/tests.
    from delivery_stream_publisher import _event, _image


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class RecoveryReport:
    planned: int = 0
    published: int = 0
    skipped: int = 0
    unresolved: int = 0
    incomplete: bool = False
    failures: list[dict[str, str]] = field(default_factory=list)
    objects: int = 0
    pages: int = 0


class S3CheckpointStore:
    """Small durable checkpoint adapter backed by one S3 object."""

    def __init__(self, client: Any, bucket: str, key: str) -> None:
        self.client = client
        self.bucket = bucket
        self.key = key

    def load(self) -> dict[str, Any]:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=self.key)["Body"].read()
            value = json.loads(body)
            return value if isinstance(value, dict) else {}
        except KeyError:
            return {}
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = str(response.get("Error", {}).get("Code", "")) if isinstance(response, dict) else ""
            if code in {"NoSuchKey", "404", "NotFound"}:
                return {}
            raise

    def save(self, value: dict[str, Any]) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )


class DeliveryRecovery:
    def __init__(
        self,
        *,
        deliveries: Any,
        messages: Any,
        agents: Any,
        queue: Any,
        queue_url: str,
        dry_run: bool = True,
        checkpoint: S3CheckpointStore | None = None,
        target_identity: str | None = None,
    ) -> None:
        self.deliveries = deliveries
        self.messages = messages
        self.agents = agents
        self.queue = queue
        self.queue_url = queue_url
        self.dry_run = dry_run
        self.checkpoint = checkpoint
        self.target_identity = target_identity or queue_url
        self._seen: set[str] = set()

    def _checkpoint_state(
        self,
        mode: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        source_identity: str | None = None,
    ) -> dict[str, Any]:
        if not self.checkpoint:
            return {}
        state = self.checkpoint.load()
        if not state:
            return {}
        if state.get("mode") != mode or state.get("target") != self.target_identity:
            raise ValueError("checkpoint does not match the recovery mode or target")
        if mode == "replay" and state.get("source") != source_identity:
            raise ValueError("checkpoint does not match the failure archive source")
        if mode == "reconcile":
            if state.get("start") != start.isoformat() or state.get("end") != end.isoformat():
                raise ValueError("checkpoint does not match the requested outage window")
        return state

    def _save_checkpoint(self, value: dict[str, Any]) -> None:
        if self.checkpoint and not self.dry_run:
            self.checkpoint.save({**value, "target": self.target_identity, "updated_at": _now()})

    def replay_objects(
        self,
        objects: Iterable[tuple[str, bytes]],
        report: RecoveryReport | None = None,
        *,
        source_identity: str | None = None,
    ) -> RecoveryReport:
        report = report or RecoveryReport()
        state = self._checkpoint_state("replay", source_identity=source_identity)
        completed = set(state.get("completed_objects") or [])
        for object_key, raw in objects:
            report.objects += 1
            if object_key in completed:
                continue
            object_failed = False
            try:
                envelope = json.loads(raw)
                records = _archive_records(envelope)
                for record in records:
                    try:
                        delivery_id = _record_delivery_id(record)
                        if delivery_id:
                            outcome = self.publish_delivery(delivery_id, report)
                            if outcome == "unresolved":
                                object_failed = True
                    except Exception as exc:
                        object_failed = True
                        report.failures.append({"object": object_key, "error": str(exc)})
                if not object_failed:
                    completed.add(object_key)
                    self._save_checkpoint({"mode": "replay", "source": source_identity, "completed_objects": sorted(completed)})
            except Exception as exc:
                report.failures.append({"object": object_key, "error": str(exc)})
        return report

    def reconcile(self, start: datetime, end: datetime, *, page_size: int = 100, max_pages: int = 1000) -> RecoveryReport:
        report = RecoveryReport()
        state = self._checkpoint_state("reconcile", start=start, end=end)
        exclusive_key = state.get("last_evaluated_key")
        completed = set(state.get("completed_delivery_ids") or [])
        for _ in range(max_pages):
            kwargs: dict[str, Any] = {"Limit": page_size}
            if exclusive_key:
                kwargs["ExclusiveStartKey"] = exclusive_key
            page = self.deliveries.scan(**kwargs)
            report.pages += 1
            page_failed = False
            for delivery in page.get("Items") or []:
                delivery_id = str(delivery.get("delivery_id") or "")
                created_at = _parse_time(delivery.get("created_at"))
                updated_at = _parse_time(delivery.get("updated_at"))
                in_window = any(stamp is not None and start <= stamp <= end for stamp in (created_at, updated_at))
                if not delivery_id or delivery_id in completed or not in_window:
                    continue
                if delivery.get("status") != "delivered":
                    report.skipped += 1
                    continue
                try:
                    outcome = self.publish_delivery(delivery_id, report)
                except Exception as exc:
                    page_failed = True
                    report.failures.append({"delivery": delivery_id, "error": str(exc)})
                    continue
                if outcome == "unresolved":
                    page_failed = True
                elif outcome == "completed":
                    completed.add(delivery_id)
            next_key = None if page_failed else page.get("LastEvaluatedKey")
            if page_failed:
                report.incomplete = True
                report.failures.append({"page": str(exclusive_key), "error": "page retained for retry"})
            self._save_checkpoint({
                    "mode": "reconcile",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "last_evaluated_key": next_key if not page_failed else exclusive_key,
                    "completed_delivery_ids": sorted(completed),
                })
            exclusive_key = next_key if not page_failed else exclusive_key
            if page_failed:
                break
            if not exclusive_key:
                break
        if exclusive_key:
            report.incomplete = True
        return report

    def publish_delivery(self, delivery_id: str, report: RecoveryReport) -> str:
        if delivery_id in self._seen:
            report.skipped += 1
            return "completed"
        delivery = self.deliveries.get_item(Key={"delivery_id": delivery_id}, ConsistentRead=True).get("Item")
        if not delivery or delivery.get("status") != "delivered":
            report.unresolved += 1
            return "unresolved"
        message_id = str(delivery.get("message_id") or "")
        recipient_id = str(delivery.get("recipient_agent_id") or "")
        message = self.messages.get_item(Key={"message_id": message_id}, ConsistentRead=True).get("Item")
        recipient = self.agents.get_item(Key={"agent_id": recipient_id}, ConsistentRead=True).get("Item")
        sender_id = str((message or {}).get("sender_agent_id") or delivery.get("sender_agent_id") or "")
        sender = self.agents.get_item(Key={"agent_id": sender_id}, ConsistentRead=True).get("Item")
        if not message or not recipient or not sender:
            raise RuntimeError(f"delivery {delivery_id} references missing message or agent")
        payload = _event(delivery, message, sender, recipient)
        report.planned += 1
        if self.dry_run:
            self._seen.add(delivery_id)
            return "completed"
        self.queue.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(payload, separators=(",", ":"), sort_keys=True),
            MessageGroupId=str(delivery.get("thread_id") or message.get("thread_id") or delivery_id),
            MessageDeduplicationId=delivery_id,
        )
        report.published += 1
        self._seen.add(delivery_id)
        return "completed"


def _archive_records(envelope: Any) -> list[dict[str, Any]]:
    if isinstance(envelope, dict):
        for key in ("requestPayload", "request_payload", "event"):
            candidate = envelope.get(key)
            if isinstance(candidate, str):
                try:
                    candidate = json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"failure envelope field {key} is not valid JSON") from exc
            if isinstance(candidate, dict) and isinstance(candidate.get("Records"), list):
                return [record for record in candidate["Records"] if isinstance(record, dict)]
        if isinstance(envelope.get("Records"), list):
            return [record for record in envelope["Records"] if isinstance(record, dict)]
    raise ValueError("S3 failure object does not contain a DynamoDB stream Records payload")


def _record_delivery_id(record: dict[str, Any]) -> str | None:
    image = _image(record)
    value = image.get("delivery_id")
    if value:
        return str(value)
    keys = record.get("dynamodb", {}).get("Keys") or {}
    value = _image({"dynamodb": {"NewImage": keys}}).get("delivery_id")
    return str(value) if value else None


def _list_objects(s3: Any, bucket: str, prefix: str, *, exclude_key: str | None = None) -> Iterable[tuple[str, bytes]]:
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        for item in page.get("Contents") or []:
            key = str(item.get("Key") or "")
            if key and key != exclude_key:
                body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
                yield key, body
        token = page.get("NextContinuationToken")
        if not token:
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay or reconcile message-hub delivery publication.")
    parser.add_argument("mode", choices=("replay", "reconcile"))
    parser.add_argument("--bucket", required=True, help="S3 failure archive bucket")
    parser.add_argument("--prefix", default="", help="S3 failure archive prefix for replay")
    parser.add_argument("--checkpoint-key", required=True, help="S3 object key for the operator checkpoint")
    parser.add_argument("--start", help="Inclusive UTC ISO-8601 outage start for reconcile")
    parser.add_argument("--end", help="Inclusive UTC ISO-8601 outage end for reconcile")
    parser.add_argument("--execute", action="store_true", help="Publish to FIFO; default is dry-run")
    args = parser.parse_args(argv)

    import boto3

    ddb = boto3.resource("dynamodb")
    s3 = boto3.client("s3")
    recovery = DeliveryRecovery(
        deliveries=ddb.Table(os.environ["DELIVERIES_TABLE"]),
        messages=ddb.Table(os.environ["MESSAGES_TABLE"]),
        agents=ddb.Table(os.environ["AGENTS_TABLE"]),
        queue=boto3.client("sqs"),
        queue_url=os.environ["AGENT_JOBS_QUEUE_URL"],
        dry_run=not args.execute,
        checkpoint=S3CheckpointStore(s3, args.bucket, args.checkpoint_key),
        target_identity="|".join(
            [os.environ["DELIVERIES_TABLE"], os.environ["MESSAGES_TABLE"],
             os.environ["AGENTS_TABLE"], os.environ["AGENT_JOBS_QUEUE_URL"]]
        ),
    )
    if args.mode == "replay":
        report = recovery.replay_objects(
            _list_objects(s3, args.bucket, args.prefix, exclude_key=args.checkpoint_key),
            source_identity=f"s3://{args.bucket}/{args.prefix}",
        )
    else:
        if not args.start or not args.end:
            parser.error("reconcile requires --start and --end")
        start = _parse_time(args.start)
        end = _parse_time(args.end)
        if start is None or end is None or start > end:
            parser.error("--start and --end must be valid ordered UTC timestamps")
        report = recovery.reconcile(start, end)
    print(json.dumps(report.__dict__, sort_keys=True))
    return 1 if report.failures or report.unresolved or report.incomplete else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
