"""Small shared helpers for live providers (defensive parsing of vendor JSON).

Vendor payloads vary field names between actors/versions, so providers read
them through `pick()` (first non-empty key wins) and never assume a shape.
"""

from __future__ import annotations

import re
from typing import Any

_MENTION_RE = re.compile(r"@(\w{1,30})")


def pick(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def actor_path(actor: str) -> str:
    """Apify addresses actors as ``username~actorName`` in the REST path."""
    return actor.replace("/", "~")


def extract_mentions(text: str) -> list[str]:
    """Pull @-handles out of post text (lowercased, deduped, order-preserving)."""
    seen: list[str] = []
    for m in _MENTION_RE.findall(text or ""):
        h = m.lower()
        if h not in seen:
            seen.append(h)
    return seen
