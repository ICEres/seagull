from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from seagull_agent.client import SeagullAgentClient
from seagull_agent.config import AgentConnectorConfig
from seagull_agent.context import item_delivery_id, item_summary, write_delivery_context
from seagull_agent.notify import desktop_notify


Notifier = Callable[[str, str], bool]


@dataclass(frozen=True, slots=True)
class WatchResult:
    new_items: tuple[dict, ...]
    context_paths: tuple[Path, ...]


def poll_once(
    client: SeagullAgentClient,
    config: AgentConnectorConfig,
    *,
    limit: int = 20,
    notify: bool = False,
    notifier: Notifier = desktop_notify,
) -> WatchResult:
    state = SeenDeliveryStore(config.context_dir / "seen-deliveries.json")
    seen = state.load()
    inbox = client.get_inbox(config.agent_handle, limit=limit)
    items = inbox_items(inbox)
    new_items = tuple(item for item in reversed(items) if is_new_delivery(item, seen))
    context_paths = []

    for item in new_items:
        path = write_delivery_context(item, config)
        context_paths.append(path)
        if notify:
            notifier("New Seagull message", item_summary(item))

    seen.update(delivery_id for item in items if (delivery_id := item_delivery_id(item)) is not None)
    state.save(seen)
    return WatchResult(new_items=new_items, context_paths=tuple(context_paths))


def watch_loop(
    client: SeagullAgentClient,
    config: AgentConnectorConfig,
    *,
    limit: int = 20,
    notify: bool = False,
    notifier: Notifier = desktop_notify,
) -> None:
    while True:
        poll_once(client, config, limit=limit, notify=notify, notifier=notifier)
        time.sleep(config.poll_interval_seconds)


class SeenDeliveryStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> set[str]:
        if not self._path.exists():
            return set()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        if not isinstance(data, list):
            return set()
        return {item for item in data if isinstance(item, str)}

    def save(self, delivery_ids: set[str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(sorted(delivery_ids), indent=2), encoding="utf-8")


def inbox_items(inbox: dict) -> list[dict]:
    items = inbox.get("items", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def is_new_delivery(item: dict, seen: set[str]) -> bool:
    delivery_id = item_delivery_id(item)
    return delivery_id is not None and delivery_id not in seen
