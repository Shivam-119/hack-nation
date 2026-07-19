"""Provider contract: the swappable "ways to process" a social network.

Every backend (Mock, Apify, TwitterAPI.io, ...) implements this same async
surface, so the scanner and graph builder never know which one is in use. All
methods must FAIL SOFT — return ``None`` / ``[]`` on any error or missing
credential — so a single provider failure never crashes the pipeline.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vc_brain.sourcing.socials.models import (
    Connection,
    SocialComment,
    SocialPost,
    SocialProfile,
)


@runtime_checkable
class SocialProvider(Protocol):
    network: str  # "twitter" | "linkedin"

    async def get_profile(self, handle: str) -> SocialProfile | None:
        """Return the profile for a handle, or None if unavailable."""

    async def get_posts(self, handle: str, limit: int = 50) -> list[SocialPost]:
        """Return up to ``limit`` recent posts (may be empty)."""

    async def get_comments(
        self, posts: list[SocialPost], limit_per_post: int = 20
    ) -> list[SocialComment]:
        """Return replies/comments left on the given posts (may be empty)."""

    async def get_connections(self, handle: str, limit: int = 200) -> list[Connection]:
        """Return up to ``limit`` connection edges (may be empty)."""
