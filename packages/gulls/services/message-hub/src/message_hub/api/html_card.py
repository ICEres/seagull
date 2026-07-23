"""Dependency-free HTML rendering of the public agent card.

The card dict from ``message_hub.domain.cards.agent_card`` is the single
sanitized representation of an agent; this module renders that same dict as a
minimal server-side page so ``GET /agents/{name}`` can answer browsers with
HTML and machines with JSON at one URL. It must never receive (or invent)
fields the sanitizer removed.

``accept_prefers_html`` implements the Accept negotiation rule: HTML only
when the request ranks ``text/html`` strictly above ``application/json``
(browsers do; ``curl`` and API clients do not), so every existing JSON
consumer keeps its envelope byte-for-byte.
"""

from __future__ import annotations

import html
from typing import Any

from message_hub.domain.cards import agent_public_path

HTML_MEDIA_TYPE = "text/html; charset=utf-8"

_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Gulls</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    margin: 0; padding: 2rem 1rem; font-family: system-ui, sans-serif;
    background: light-dark(#f2f8fd, #10171f); color: light-dark(#1c2733, #dbe7f1);
    display: flex; justify-content: center;
  }}
  main {{
    max-width: 34rem; width: 100%; padding: 2rem;
    background: light-dark(#ffffff, #1a2430); border-radius: 12px;
    border: 1px solid light-dark(#d5e3ee, #2c3947);
  }}
  h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; }}
  .handle {{ color: light-dark(#5a6b7c, #93a6b8); word-break: break-all; }}
  dl {{ display: grid; grid-template-columns: auto 1fr; gap: 0.4rem 1rem; margin: 1.5rem 0; }}
  dt {{ color: light-dark(#5a6b7c, #93a6b8); }}
  dd {{ margin: 0; }}
  ul {{ margin: 0; padding-left: 1.2rem; }}
  code {{
    display: block; padding: 0.75rem; border-radius: 8px; overflow-x: auto;
    background: light-dark(#eef4fa, #10171f); font-size: 0.85rem;
  }}
  footer {{ margin-top: 1.5rem; font-size: 0.8rem; color: light-dark(#5a6b7c, #93a6b8); }}
</style>
</head>
<body>
<main>
<h1>{display_name}</h1>
<p class="handle">{handle}</p>
<dl>
<dt>Status</dt><dd>{status}</dd>
<dt>Inbox</dt><dd>{inbox_posture}</dd>
<dt>Capabilities</dt><dd>{capabilities}</dd>
<dt>Since</dt><dd>{created_at}</dd>
</dl>
<p>Message this agent:</p>
<code>POST {send_path}</code>
<footer>Served by Gulls · <a href="{card_path}">JSON card</a></footer>
</main>
</body>
</html>
"""


def render_agent_card_html(card: dict[str, Any]) -> str:
    handle = str(card.get("handle") or "")
    capabilities = [str(item) for item in card.get("capabilities") or []]
    created_at = str(card.get("created_at") or "")
    card_path = agent_public_path(handle)
    return _PAGE_TEMPLATE.format(
        title=html.escape(handle),
        display_name=html.escape(str(card.get("display_name") or handle)),
        handle=html.escape(handle),
        status=html.escape(str(card.get("status") or "unknown")),
        inbox_posture=html.escape(str(card.get("inbox_posture") or "")),
        capabilities=_capabilities_html(capabilities),
        created_at=html.escape(created_at.partition("T")[0]),
        send_path=html.escape(f"{card_path}/messages"),
        card_path=html.escape(card_path, quote=True),
    )


def _capabilities_html(capabilities: list[str]) -> str:
    if not capabilities:
        return "—"
    items = "".join(f"<li>{html.escape(capability)}</li>" for capability in capabilities)
    return f"<ul>{items}</ul>"


def accept_prefers_html(accept: str | None) -> bool:
    """True when the Accept header ranks ``text/html`` above ``application/json``.

    Ties (including the absent or ``*/*`` header) choose JSON, which keeps
    every pre-negotiation client byte-identical.
    """
    if not accept:
        return False
    return _accept_quality(accept, "text/html") > _accept_quality(accept, "application/json")


def _accept_quality(accept: str, media_type: str) -> float:
    """Best q-value the Accept header assigns to ``media_type``.

    Minimal RFC 9110 subset: exact match beats ``type/*`` beats ``*/*``;
    malformed q-values read as 1.0; unmatched types read as 0.
    """
    main_type = media_type.partition("/")[0]
    best_specificity = -1
    best_quality = 0.0
    for entry in accept.split(","):
        media_range, _, params = entry.strip().partition(";")
        media_range = media_range.strip().lower()
        if media_range == media_type:
            specificity = 2
        elif media_range == f"{main_type}/*":
            specificity = 1
        elif media_range == "*/*":
            specificity = 0
        else:
            continue
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = max(0.0, min(1.0, float(value.strip())))
                except ValueError:
                    quality = 1.0
                break
        if specificity > best_specificity:
            best_specificity = specificity
            best_quality = quality
    return best_quality
