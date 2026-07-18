"""Outbound sourcing: scan Hacker News for Show HN / Launch HN posts."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.models import Founder, SourceType


@dataclass
class HNLaunch:
    title: str
    url: str
    author: str
    score: int
    hn_url: str


class HackerNewsScanner:
    """Scan Hacker News for Show HN and Launch HN posts indicating builder activity."""

    HN_API = "https://hacker-news.firebaseio.com/v0"

    def __init__(self, pipeline: IngestionPipeline):
        self.pipeline = pipeline

    async def scan_show_hn(self, limit: int = 20) -> list[HNLaunch]:
        """Fetch recent Show HN stories."""
        launches = []
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.HN_API}/showstories.json", timeout=15)
            if resp.status_code != 200:
                return launches

            story_ids = resp.json()[:limit]
            for sid in story_ids:
                item_resp = await client.get(f"{self.HN_API}/item/{sid}.json", timeout=10)
                if item_resp.status_code != 200:
                    continue
                item = item_resp.json()
                if not item:
                    continue
                launches.append(HNLaunch(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    author=item.get("by", ""),
                    score=item.get("score", 0),
                    hn_url=f"https://news.ycombinator.com/item?id={sid}",
                ))
        return launches

    async def ingest_launches(self, launches: list[HNLaunch]) -> list[Founder]:
        """Store HN launchers as founder candidates."""
        founders = []
        for launch in launches:
            if launch.score < 5:  # Skip very low traction
                continue
            founder = self.pipeline.ingest_founder_from_source(
                source=SourceType.HACKER_NEWS,
                data={
                    "name": launch.author,
                    "bio": f"Show HN: {launch.title}",
                    "profile_url": launch.hn_url,
                    "product_url": launch.url,
                    "hn_score": launch.score,
                    "launches": 1,
                    "confidence": 0.4,
                },
            )
            founders.append(founder)
        return founders
