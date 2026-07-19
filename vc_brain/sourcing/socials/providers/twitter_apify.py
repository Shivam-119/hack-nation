"""Twitter/X via an Apify actor — posts + reply/comment scraping.

Uses a free-tier-friendly pay-per-result actor (default
`kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest`, verified to
run on Apify's $5 credit and return likes/retweets/replies/views). It takes
Twitter search operators, so:
- a user's posts  -> searchTerms ["from:<handle>"]
- replies/comments -> searchTerms ["conversation_id:<tweet id>"] (SAME actor,
  no separate paid reply actor).

Runs via `run-sync-get-dataset-items`; fails soft; the factory only reaches here
when `APIFY_TOKEN` is set and the twitter provider is "apify".
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

_POSTS_FOR_COMMENTS = 5  # cost cap: fetch replies for at most this many posts


class ApifyTwitterProvider:
    network = "twitter"
    BASE = "https://api.apify.com/v2"

    def __init__(self) -> None:
        self._token = config.apify_token
        self._actor = config.apify_twitter_actor
        self._followers_actor = config.apify_twitter_followers_actor
        self._post_limit = config.socials_post_limit

    # -- public surface -----------------------------------------------------
    async def get_profile(self, handle: str) -> SocialProfile | None:
        h = normalize_handle(handle)
        items = _valid(await self._run(self._actor, {"searchTerms": [f"from:{h}"], "maxItems": 1}))
        author = (items[0].get("author") if items else None) or {}
        if not isinstance(author, dict) or not author:
            return SocialProfile(network="twitter", handle=h, url=f"https://twitter.com/{h}")
        return SocialProfile(
            network="twitter",
            handle=h,
            name=pick(author, "name", default=""),
            bio=pick(author, "description", "bio", default=""),
            url=pick(author, "url", "profileUrl", default=f"https://twitter.com/{h}"),
            followers=_int(pick(author, "followers", "followersCount", default=0)),
            following=_int(pick(author, "following", "followingCount", default=0)),
            verified=bool(pick(author, "isVerified", "isBlueVerified", "verified", default=False)),
            raw=author,
        )

    async def get_posts(self, handle: str, limit: int = 50) -> list[SocialPost]:
        limit = min(limit, self._post_limit)
        h = normalize_handle(handle)
        items = _valid(await self._run(self._actor, {"searchTerms": [f"from:{h}"], "maxItems": limit}))
        return [self._to_post(it, h) for it in items[:limit]]

    async def get_comments(
        self, posts: list[SocialPost], limit_per_post: int = 20
    ) -> list[SocialComment]:
        limit_per_post = min(limit_per_post, config.socials_comment_limit)
        out: list[SocialComment] = []
        for p in posts[:_POSTS_FOR_COMMENTS]:
            cid = _conversation_id(p)
            if not cid:
                continue
            items = _valid(
                await self._run(
                    self._actor,
                    {"searchTerms": [f"conversation_id:{cid}"], "maxItems": limit_per_post + 1},
                )
            )
            author_h = normalize_handle(p.author_handle)
            for it in items:
                au = it.get("author") if isinstance(it.get("author"), dict) else {}
                ah = normalize_handle(str(pick(it, "userName", default=au.get("userName", ""))))
                if not ah or ah == author_h:  # skip the root tweet / the founder's own
                    continue
                out.append(
                    SocialComment(
                        network="twitter",
                        post_url=p.url,
                        author_handle=ah,
                        author_name=str(au.get("name", "")),
                        text=pick(it, "text", "full_text", default=""),
                        likes=_int(pick(it, "likeCount", "favoriteCount", default=0)),
                        created_at=str(pick(it, "createdAt", "created_at", default="")),
                        raw=it,
                    )
                )
                if len([c for c in out if c.post_url == p.url]) >= limit_per_post:
                    break
        return out

    async def get_connections(self, handle: str, limit: int = 200) -> list[Connection]:
        # Connection edges are sourced from the (mock) graph provider, not here.
        return []

    # -- internals ----------------------------------------------------------
    def _to_post(self, it: dict[str, Any], h: str) -> SocialPost:
        text = pick(it, "text", "full_text", default="")
        return SocialPost(
            network="twitter",
            author_handle=h,
            text=text,
            created_at=str(pick(it, "createdAt", "created_at", default="")),
            url=pick(it, "url", "twitterUrl", default=""),
            likes=_int(pick(it, "likeCount", "favoriteCount", default=0)),
            reposts=_int(pick(it, "retweetCount", default=0)),
            replies=_int(pick(it, "replyCount", default=0)),
            is_repost=bool(pick(it, "isRetweet", "isRepost", default=False)),
            mentions=_mentions_of(it, text),
            hashtags=_hashtags_of(it),
            raw=it,
        )

    async def _run(self, actor: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
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
    """Drop the actor's placeholder rows ({"noResults":true}) and error rows (id=-1)."""
    return [it for it in items if isinstance(it, dict) and "noResults" not in it and it.get("id") != -1]


def _conversation_id(post: SocialPost) -> str:
    raw = post.raw or {}
    cid = raw.get("conversationId") or raw.get("id")
    if cid and str(cid) != "-1":
        return str(cid)
    tail = post.url.rstrip("/").split("/")[-1].split("?")[0]
    return tail if tail.isdigit() else ""


def _mentions_of(item: dict[str, Any], text: str) -> list[str]:
    entities = item.get("entities") if isinstance(item.get("entities"), dict) else {}
    ums = entities.get("user_mentions") if isinstance(entities, dict) else None
    if isinstance(ums, list) and ums:
        return [normalize_handle(str(m.get("screen_name") or m.get("userName")))
                for m in ums if isinstance(m, dict) and (m.get("screen_name") or m.get("userName"))]
    return extract_mentions(text)


def _hashtags_of(item: dict[str, Any]) -> list[str]:
    entities = item.get("entities") if isinstance(item.get("entities"), dict) else {}
    tags = entities.get("hashtags") if isinstance(entities, dict) else None
    if isinstance(tags, list):
        return [str(t.get("text", t) if isinstance(t, dict) else t).lstrip("#") for t in tags]
    return []


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
