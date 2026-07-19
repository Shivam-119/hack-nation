"""LinkedIn via Apify no-cookie actors — public posts/activity + post comments.

Both actors are verified free-tier-friendly (run on Apify's $5 credit, no cookie,
so our accounts are never exposed):
- posts:    apimaestro/linkedin-profile-posts            -> input {username, limit}
- comments: apimaestro/linkedin-post-comments-...-no-cookies -> input {postIds:[url]}

Engagement lives under a `stats` object (reactions / comments / reposts).
`get_connections` returns [] by design — LinkedIn contributes posts + comments,
not graph edges (those come from the mock graph provider). Fails soft.
"""

from __future__ import annotations

from typing import Any

import httpx

from vc_brain.config import config
from vc_brain.sourcing.socials.models import (
    Connection,
    SocialComment,
    SocialPost,
    SocialProfile,
)
from vc_brain.sourcing.socials.notable import normalize_handle
from vc_brain.sourcing.socials.providers._util import actor_path, extract_mentions, pick

_POSTS_FOR_COMMENTS = 5  # cost cap: fetch comments for at most this many posts


class LinkedInApifyProvider:
    network = "linkedin"
    BASE = "https://api.apify.com/v2"

    def __init__(self) -> None:
        self._token = config.apify_token
        self._actor = config.apify_linkedin_actor
        self._comments_actor = config.apify_linkedin_comments_actor
        self._post_limit = config.socials_post_limit

    async def get_profile(self, handle: str) -> SocialProfile | None:
        h = normalize_handle(handle)
        items = _valid(await self._run({"username": h, "limit": 1}))
        author = (items[0].get("author") if items else None) or {}
        url = f"https://www.linkedin.com/in/{h}"
        if not isinstance(author, dict) or not author:
            return SocialProfile(network="linkedin", handle=h, url=url)
        return SocialProfile(
            network="linkedin",
            handle=pick(author, "username", default=h),
            name=_full_name(author),
            bio=pick(author, "headline", "occupation", default=""),
            url=pick(author, "profile_url", "profileUrl", "url", default=url),
            followers=_int(pick(author, "followers", "followersCount", default=0)),
            raw=author,
        )

    async def get_posts(self, handle: str, limit: int = 50) -> list[SocialPost]:
        limit = min(limit, self._post_limit)
        h = normalize_handle(handle)
        items = _valid(await self._run({"username": h, "limit": limit}))
        posts: list[SocialPost] = []
        for it in items[:limit]:
            text = pick(it, "text", "content", "commentary", default="")
            stats = it.get("stats") if isinstance(it.get("stats"), dict) else {}
            posts.append(
                SocialPost(
                    network="linkedin",
                    author_handle=h,
                    text=text,
                    created_at=_ts(it.get("posted_at")),
                    url=pick(it, "url", "postUrl", default=""),
                    likes=_int(pick(stats, "total_reactions", "like", "likes", default=0)),
                    reposts=_int(pick(stats, "reposts", "shares", default=0)),
                    replies=_int(pick(stats, "comments", default=0)),
                    mentions=extract_mentions(text),
                    hashtags=_hashtags(text),
                    raw=it,
                )
            )
        return posts

    async def get_comments(
        self, posts: list[SocialPost], limit_per_post: int = 20
    ) -> list[SocialComment]:
        limit_per_post = min(limit_per_post, config.socials_comment_limit)
        out: list[SocialComment] = []
        for p in posts[:_POSTS_FOR_COMMENTS]:
            if not p.url:
                continue
            items = _valid(
                await self._run(
                    {"postIds": [p.url], "limit": limit_per_post, "sortOrder": "most recent"},
                    actor=self._comments_actor,
                )
            )
            for it in items[:limit_per_post]:
                au = it.get("author") if isinstance(it.get("author"), dict) else {}
                stats = it.get("stats") if isinstance(it.get("stats"), dict) else {}
                out.append(
                    SocialComment(
                        network="linkedin",
                        post_url=p.url,
                        author_handle=normalize_handle(str(pick(au, "username", default=""))),
                        author_name=_full_name(au) or pick(au, "name", default=""),
                        text=pick(it, "text", "comment", default=""),
                        likes=_int(pick(stats, "total_reactions", "like", "likes", default=0)),
                        created_at=_ts(it.get("posted_at")),
                        raw=it,
                    )
                )
        return out

    async def get_connections(self, handle: str, limit: int = 200) -> list[Connection]:
        # No legal/cheap LinkedIn connection API — LinkedIn contributes posts/comments only.
        return []

    # -- internals ----------------------------------------------------------
    async def _run(
        self, payload: dict[str, Any], actor: str | None = None
    ) -> list[dict[str, Any]]:
        actor = actor or self._actor
        if not self._token or not actor:
            return []
        url = f"{self.BASE}/acts/{actor_path(actor)}/run-sync-get-dataset-items"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url, params={"token": self._token}, json=payload, timeout=280
                )
                if resp.status_code >= 300:
                    return []
                data = resp.json()
                if isinstance(data, list):
                    return data
                return data.get("items", []) if isinstance(data, dict) else []
        except (httpx.HTTPError, ValueError):
            return []


def _valid(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [it for it in items if isinstance(it, dict) and "noResults" not in it]


def _full_name(author: dict[str, Any]) -> str:
    fn = str(author.get("first_name", "")).strip()
    ln = str(author.get("last_name", "")).strip()
    return (f"{fn} {ln}".strip()) or str(author.get("fullName", ""))


def _ts(posted_at: Any) -> str:
    if isinstance(posted_at, dict):
        return str(posted_at.get("date", ""))
    return str(posted_at or "")


def _hashtags(text: str) -> list[str]:
    return [w.lstrip("#") for w in (text or "").split() if w.startswith("#")]


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
