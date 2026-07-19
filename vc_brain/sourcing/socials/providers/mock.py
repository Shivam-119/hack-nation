"""Mock provider — serves bundled fixtures so the whole tool runs keyless at $0.

This is the DEFAULT backend. It reads ``fixtures/{network}_{handle}.json`` and
falls back to ``fixtures/{network}_default.json`` so any handle yields demo data.
Used both for offline tests and for a zero-cost demo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vc_brain.sourcing.socials.models import (
    Connection,
    Network,
    SocialComment,
    SocialPost,
    SocialProfile,
)
from vc_brain.sourcing.socials.notable import normalize_handle

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class MockProvider:
    def __init__(self, network: Network):
        self.network = network

    # -- public surface -----------------------------------------------------
    async def get_profile(self, handle: str) -> SocialProfile | None:
        data = self._load(handle)
        p = data.get("profile")
        if not p:
            return None
        return SocialProfile(network=self.network, handle=normalize_handle(handle), **p)

    async def get_posts(self, handle: str, limit: int = 50) -> list[SocialPost]:
        data = self._load(handle)
        h = normalize_handle(handle)
        posts = [
            SocialPost(
                network=self.network,
                author_handle=h,
                **_clean(post, SocialPost, drop={"author_handle"}),
            )
            for post in data.get("posts", [])
        ]
        return posts[:limit]

    async def get_comments(
        self, posts: list[SocialPost], limit_per_post: int = 20
    ) -> list[SocialComment]:
        # Fixtures carry comments per seed handle; match to posts by url when present.
        handle = posts[0].author_handle if posts else ""
        data = self._load(handle)
        post_urls = {p.url for p in posts}
        out: list[SocialComment] = []
        for c in data.get("comments", []):
            comment = SocialComment(network=self.network, **_clean(c, SocialComment))
            if not post_urls or not comment.post_url or comment.post_url in post_urls:
                out.append(comment)
        return out

    async def get_connections(self, handle: str, limit: int = 200) -> list[Connection]:
        data = self._load(handle)
        h = normalize_handle(handle)
        conns = [
            Connection(
                network=self.network,
                source_handle=c.get("source_handle", h),
                **_clean(c, Connection, drop={"source_handle"}),
            )
            for c in data.get("connections", [])
        ]
        return conns[:limit]

    # -- internals ----------------------------------------------------------
    def _load(self, handle: str) -> dict[str, Any]:
        h = normalize_handle(handle)
        for name in (f"{self.network}_{h}.json", f"{self.network}_default.json"):
            path = _FIXTURES / name
            if path.exists():
                try:
                    return json.loads(path.read_text())
                except (json.JSONDecodeError, OSError):
                    return {}
        return {}


def _clean(raw: dict[str, Any], model: type, drop: set[str] | None = None) -> dict[str, Any]:
    """Keep only keys the model accepts (fixtures may carry extra/renamed fields).

    ``network`` is always set explicitly by the caller; pass ``drop`` for any
    other field the caller sets itself (e.g. author_handle on posts).
    """
    allowed = set(model.model_fields) - {"network"} - (drop or set())
    return {k: v for k, v in raw.items() if k in allowed}
