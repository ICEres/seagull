from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, TextIO

from seagull_agent.client import SeagullClientError, SeagullAgentClient, SeagullHttpClient
from seagull_agent.config import AgentConnectorConfig, ConfigError
from seagull_agent.context import (
    find_inbox_item,
    item_message_id,
    item_summary,
    write_delivery_context,
)
from seagull_agent.response_rules import DraftResult, generate_draft_reply
from seagull_agent.watcher import poll_once, watch_loop


def main(
    argv: list[str] | None = None,
    *,
    client: SeagullAgentClient | None = None,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = AgentConnectorConfig.from_env(
            environ,
            api_url=args.api_url,
            agent_handle=args.agent_handle,
            context_dir=args.context_dir,
            poll_interval_seconds=args.interval if getattr(args, "interval", None) is not None else None,
        )
    except ConfigError as exc:
        print(f"config error: {exc}", file=err)
        return 2

    seagull = client or SeagullHttpClient(api_url=config.api_url, token=config.token)

    try:
        return run_command(args, config, seagull, out)
    except (SeagullClientError, ValueError) as exc:
        print(f"seagull: {exc}", file=err)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seagull")
    parser.add_argument("--api-url", help="Seagull Message Hub URL. Defaults to SEAGULL_API_URL.")
    parser.add_argument("--agent-handle", help="Local agent handle. Defaults to SEAGULL_AGENT_HANDLE.")
    parser.add_argument("--context-dir", help="Context handoff directory. Defaults to SEAGULL_AGENT_CONTEXT_DIR or .seagull/agent.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON where supported.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("whoami", help="Read the configured agent record.")

    inbox = subparsers.add_parser("inbox", help="Read recent inbox deliveries.")
    inbox.add_argument("--limit", type=bounded_limit, default=20)

    open_delivery = subparsers.add_parser("open", help="Write a local context file for an inbox delivery.")
    open_delivery.add_argument("delivery_id")
    open_delivery.add_argument("--limit", type=bounded_limit, default=100)

    thread = subparsers.add_parser("thread", help="Read a thread.")
    thread.add_argument("thread_id")
    thread.add_argument("--limit", type=bounded_limit, default=50)

    thread_context = subparsers.add_parser("context", help="Read compact thread context.")
    thread_context.add_argument("thread_id")

    reply = subparsers.add_parser("reply", help="Reply to a delivery through the agent decision flow.")
    reply.add_argument("delivery_id")
    reply.add_argument("content", nargs="+")

    draft_reply = subparsers.add_parser("draft-reply", help="Generate a reply draft without sending it.")
    draft_reply.add_argument("delivery_id")
    draft_reply.add_argument("--limit", type=bounded_limit, default=100)

    ack = subparsers.add_parser("ack", help="Acknowledge an inbox delivery.")
    ack.add_argument("delivery_id")
    ack.add_argument("--limit", type=bounded_limit, default=100)

    ignore = subparsers.add_parser("ignore", help="Mark a delivery ignored through the agent decision flow.")
    ignore.add_argument("delivery_id")

    post = subparsers.add_parser("post", help="Send a direct message as the configured agent.")
    post.add_argument("--to", action="append", required=True, dest="recipients")
    post.add_argument("--thread-id")
    post.add_argument("--intent", default="message")
    post.add_argument("content", nargs="+")

    watch = subparsers.add_parser("watch", help="Watch inbox and write context files for new deliveries.")
    watch.add_argument("--limit", type=bounded_limit, default=20)
    watch.add_argument("--interval", type=float)
    watch.add_argument("--notify", action="store_true")
    watch.add_argument("--once", action="store_true")

    return parser


def run_command(
    args: argparse.Namespace,
    config: AgentConnectorConfig,
    client: SeagullAgentClient,
    out: TextIO,
) -> int:
    if args.command == "whoami":
        result = client.get_agent(config.agent_handle)
        print_json_or_text(args.json, result, format_agent(result), out)
        return 0

    if args.command == "inbox":
        result = client.get_inbox(config.agent_handle, limit=args.limit)
        print_json_or_text(args.json, result, format_inbox(result), out)
        return 0

    if args.command == "open":
        item = require_inbox_delivery(client, config, args.delivery_id, limit=args.limit)
        path = write_delivery_context(item, config)
        if args.json:
            print(json.dumps({"context_path": str(path), "delivery": item.get("delivery")}, indent=2), file=out)
        else:
            print(f"Wrote {path}", file=out)
            print(item_summary(item), file=out)
        return 0

    if args.command == "thread":
        result = client.get_thread(args.thread_id, limit=args.limit)
        print_json_or_text(args.json, result, format_thread(result), out)
        return 0

    if args.command == "context":
        result = client.get_thread_context(args.thread_id)
        print_json_or_text(args.json, result, json.dumps(result, indent=2), out)
        return 0

    if args.command == "reply":
        content = " ".join(args.content).strip()
        result = client.decide_delivery(
            delivery_id=args.delivery_id,
            agent_handle=config.agent_handle,
            decision="reply",
            content=content,
            note="manual local agent connector reply",
        )
        print_json_or_text(args.json, result, format_decision(result, "Replied"), out)
        return 0

    if args.command == "draft-reply":
        item = require_inbox_delivery(client, config, args.delivery_id, limit=args.limit)
        thread_id = item_thread_id(item)
        thread_context = client.get_thread_context(thread_id) if thread_id is not None else None
        result = generate_draft_reply(
            config.response_rules,
            delivery_item=item,
            thread_context=thread_context,
        )
        payload = result.to_dict() | {
            "delivery_id": args.delivery_id,
            "draft_sent": False,
            "delivery_decision_submitted": False,
        }
        print_json_or_text(args.json, payload, format_draft_result(result), out)
        return 0

    if args.command == "ack":
        item = require_inbox_delivery(client, config, args.delivery_id, limit=args.limit)
        message_id = item_message_id(item)
        if message_id is None:
            raise ValueError(f"delivery has no message_id: {args.delivery_id}")
        result = client.ack_message(message_id=message_id, recipient_handle=config.agent_handle)
        print_json_or_text(args.json, result, f"Acknowledged {message_id}.", out)
        return 0

    if args.command == "ignore":
        result = client.decide_delivery(
            delivery_id=args.delivery_id,
            agent_handle=config.agent_handle,
            decision="ignore",
            note="manual local agent connector ignore",
        )
        print_json_or_text(args.json, result, format_decision(result, "Ignored"), out)
        return 0

    if args.command == "post":
        result = client.send_message(
            sender_handle=config.agent_handle,
            recipient_handles=tuple(args.recipients),
            content=" ".join(args.content).strip(),
            thread_id=args.thread_id,
            intent=args.intent,
        )
        print_json_or_text(args.json, result, f"Sent {result.get('message_id')} in {result.get('thread_id')}.", out)
        return 0

    if args.command == "watch":
        if args.once:
            result = poll_once(client, config, limit=args.limit, notify=args.notify)
            if args.json:
                print(json.dumps({"new_count": len(result.new_items), "context_paths": [str(path) for path in result.context_paths]}, indent=2), file=out)
            elif result.new_items:
                print(f"{len(result.new_items)} new delivery item(s).", file=out)
                for path in result.context_paths:
                    print(f"Wrote {path}", file=out)
            else:
                print("No new deliveries.", file=out)
            return 0

        print(f"Watching {config.agent_handle} every {config.poll_interval_seconds:g}s.", file=out)
        watch_loop(client, config, limit=args.limit, notify=args.notify)
        return 0

    raise ValueError(f"unknown command: {args.command}")


def require_inbox_delivery(
    client: SeagullAgentClient,
    config: AgentConnectorConfig,
    delivery_id: str,
    *,
    limit: int,
) -> dict[str, Any]:
    inbox = client.get_inbox(config.agent_handle, limit=limit)
    item = find_inbox_item(inbox_items(inbox), delivery_id)
    if item is None:
        raise ValueError(f"delivery not found in inbox: {delivery_id}")
    return item


def format_agent(result: dict[str, Any]) -> str:
    agent = result.get("agent") if isinstance(result.get("agent"), dict) else result
    handle = agent.get("handle", "unknown")
    status = agent.get("status", "unknown")
    trigger_mode = agent.get("trigger_mode", "manual")
    return f"{handle} [{status}], trigger_mode={trigger_mode}"


def format_inbox(result: dict[str, Any]) -> str:
    items = inbox_items(result)
    if not items:
        return "Inbox is empty."
    lines = [f"{len(items)} inbox item(s):"]
    lines.extend(f"- {item_summary(item)}" for item in items)
    return "\n".join(lines)


def format_thread(result: dict[str, Any]) -> str:
    messages = result.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return "Thread has no messages."
    lines = [f"{len(messages)} message(s):"]
    for message in messages:
        if not isinstance(message, dict):
            continue
        message_id = message.get("message_id", "unknown")
        sender = message.get("sender_handle") or message.get("sender_agent_id") or "unknown"
        content = " ".join(str(message.get("content_inline") or "").split())
        lines.append(f"- {message_id} from {sender}: {content or '(no inline content)'}")
    return "\n".join(lines)


def format_decision(result: dict[str, Any], verb: str) -> str:
    delivery = result.get("delivery", {})
    delivery_id = delivery.get("delivery_id", "unknown") if isinstance(delivery, dict) else "unknown"
    status = delivery.get("status", "unknown") if isinstance(delivery, dict) else "unknown"
    reply = result.get("reply")
    if isinstance(reply, dict):
        return f"{verb} {delivery_id}; status={status}; reply={reply.get('message_id')}."
    return f"{verb} {delivery_id}; status={status}."


def format_draft_result(result: DraftResult) -> str:
    rules = result.applied_rules
    lines = [
        f"Outcome: {result.outcome}",
        f"Reason: {result.reason}",
        (
            "Rules: "
            f"source={rules.get('source')}; "
            f"schema_version={rules.get('schema_version')}; "
            f"reply_posture={rules.get('reply_posture')}; "
            f"max_reply_chars={rules.get('max_reply_chars')}"
        ),
    ]
    if result.trigger_labels:
        lines.append(f"Triggers: {', '.join(result.trigger_labels)}")
    if result.draft is None:
        lines.extend(["", "No draft generated. No reply sent."])
    else:
        lines.extend(["", "Draft (not sent):", result.draft])
    lines.append("No delivery decision was submitted.")
    return "\n".join(lines)


def print_json_or_text(as_json: bool, result: dict[str, Any], text: str, out: TextIO) -> None:
    if as_json:
        print(json.dumps(result, indent=2), file=out)
    else:
        print(text, file=out)


def inbox_items(inbox: dict[str, Any]) -> list[dict[str, Any]]:
    items = inbox.get("items", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def item_thread_id(item: dict[str, Any]) -> str | None:
    delivery = item.get("delivery") or {}
    message = item.get("message") or {}
    value = delivery.get("thread_id") or message.get("thread_id")
    return value if isinstance(value, str) and value else None


def bounded_limit(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 100:
        raise argparse.ArgumentTypeError("limit must be between 1 and 100")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
