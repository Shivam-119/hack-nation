"""Twitter/X via TwitterAPI.io — optional pay-as-you-go swap (real-time X).

Pennies per call but needs a small prepaid balance, so it is OFF unless
`SOCIALS_TWITTER_PROVIDER=twitterapi_io` and `TWITTERAPI_IO_KEY` are both set.
Same `SocialProvider` surface as the Apify/Mock backends; defensive parsing +
fail-soft. Endpoint paths/fields follow TwitterAPI.io's REST API and are read
tolerantly so minor response-shape changes don't break the pipeline.
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
from vc_brain.sourcing.socials.providers._util import extract_mentions, pick

_POSTS_FOR_COMMENTS = 5  # cost cap: fetch replies for at most this many posts


class TwitterApiIoProvider:
    network = "twitter"
    BASE = "https://api.twitterapi.io"

    def __init__(self) -> None:
        self._key = config.twitterapi_io_key
        self._post_limit = config.socials_post_limit
        self._follower_sample = config.socials_follower_sample

    async def get_profile(self, handle: str) -> SocialProfile | None:
        h = normalize_handle(handle)
        data = await self._get("/twitter/user/info", {"userName": h})
        user = _unwrap_user(data)
        if not user:
            return SocialProfile(network="twitter", handle=h, url=f"https://twitter.com/{h}")
        return SocialProfile(
            network="twitter",
            handle=h,
            name=pick(user, "name", "displayName", default=""),
            bio=pick(user, "description", "bio", default=""),
            url=pick(user, "url", "profileUrl", default=f"https://twitter.com/{h}"),
            followers=int(pick(user, "followers", "followersCount", default=0) or 0),
            following=int(pick(user, "following", "followingCount", default=0) or 0),
            verified=bool(pick(user, "isVerified", "verified", default=False)),
            raw=user,
        )

    async def get_posts(self, handle: str, limit: int = 50) -> list[SocialPost]:
        limit = min(limit, self._post_limit)
        h = normalize_handle(handle)
        data = await self._get("/twitter/user/last_tweets", {"userName": h})
        tweets = _unwrap_list(data, "tweets", "data")
        posts: list[SocialPost] = []
        for t in tweets[:limit]:
            text = pick(t, "text", "full_text", default="")
            posts.append(
                SocialPost(
                    network="twitter",
                    author_handle=h,
                    text=text,
                    created_at=str(pick(t, "createdAt", "created_at", default="")),
                    url=pick(t, "url", "twitterUrl", default=""),
                    likes=int(pick(t, "likeCount", "favoriteCount", default=0) or 0),
                    reposts=int(pick(t, "retweetCount", default=0) or 0),
                    replies=int(pick(t, "replyCount", default=0) or 0),
                    mentions=extract_mentions(text),
                    raw=t,
                )
            )
        return posts

    async def get_comments(
        self, posts: list[SocialPost], limit_per_post: int = 20
    ) -> list[SocialComment]:
        limit_per_post = min(limit_per_post, config.socials_comment_limit)
        out: list[SocialComment] = []
        for p in posts[:_POSTS_FOR_COMMENTS]:
            tid = _tweet_id(p.url)
            if not tid:
                continue
            data = await self._get("/twitter/tweet/replies", {"tweetId": tid})
            for r in _unwrap_list(data, "replies", "tweets", "data")[:limit_per_post]:
                author = r.get("author") if isinstance(r.get("author"), dict) else {}
                out.append(
                    SocialComment(
                        network="twitter",
                        post_url=p.url,
                        author_handle=normalize_handle(
                            str(pick(r, "userName", "screen_name", default="")
                                or author.get("userName", ""))
                        ),
                        author_name=str(pick(r, "name", default=author.get("name", ""))),
                        text=pick(r, "text", "full_text", default=""),
                        likes=int(pick(r, "likeCount", default=0) or 0),
                        created_at=str(pick(r, "createdAt", default="")),
                        raw=r,
                    )
                )
        return out

    async def get_connections(self, handle: str, limit: int = 200) -> list[Connection]:
        limit = min(limit, self._follower_sample)
        h = normalize_handle(handle)
        conns: list[Connection] = []

        followers = _unwrap_list(
            await self._get("/twitter/user/followers", {"userName": h}), "followers", "data"
        )
        for u in followers[:limit]:
            fh = normalize_handle(str(pick(u, "userName", "screen_name", default="")))
            if fh and fh != h:
                conns.append(
                    Connection(
                        network="twitter",
                        source_handle=fh,
                        target_handle=h,
                        edge_type="follows",
                        source_url=f"https://twitter.com/{h}/followers",
                    )
                )

        followings = _unwrap_list(
            await self._get("/twitter/user/followings", {"userName": h}), "followings", "data"
        )
        for u in followings[:limit]:
            fh = normalize_handle(str(pick(u, "userName", "screen_name", default="")))
            if fh and fh != h:
                conns.append(
                    Connection(
                        network="twitter",
                        source_handle=h,
                        target_handle=fh,
                        edge_type="follows",
                        source_url=f"https://twitter.com/{h}/following",
                    )
                )
        return conns

    # -- internals ----------------------------------------------------------
    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        if not self._key:
            return {}
        try:
            async with httpx.AsyncClient(headers={"X-API-Key": self._key}) as client:
                resp = await client.get(f"{self.BASE}{path}", params=params, timeout=60)
                if resp.status_code >= 300:
                    return {}
                return resp.json()
        except (httpx.HTTPError, ValueError):
            return {}


def _tweet_id(url: str) -> str:
    """Pull the numeric status id from a tweet URL (…/status/<id>)."""
    if not url:
        return ""
    tail = url.rstrip("/").split("/")[-1].split("?")[0]
    return tail if tail.isdigit() else ""


def _unwrap_user(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        user = data.get("data") or data.get("user") or data
        if isinstance(user, dict) and (user.get("userName") or user.get("name") or user.get("id")):
            return user
    return None


def _unwrap_list(data: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []
