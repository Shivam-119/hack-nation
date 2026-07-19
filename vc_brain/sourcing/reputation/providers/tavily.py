"""Tavily-backed web search.

Live provider: costs credits, so it activates only when REPUTATION_PROVIDER is
set to "tavily" *and* a key is present (see providers/__init__.py).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from vc_brain.config import config
from vc_brain.sourcing.reputation.models import Article
from vc_brain.sourcing.reputation.sources import source_name


class TavilyProvider:
    """Search and page-extraction via Tavily's /search and /extract endpoints."""

    name = "tavily"
    API_URL = "https://api.tavily.com/search"
    EXTRACT_URL = "https://api.tavily.com/extract"

    # Tavily accepts at most 20 URLs per /extract call.
    EXTRACT_BATCH = 20
    # ...and hard-caps /search max_results at 20. Asking for more is an error,
    # so clamp rather than trusting the caller's config.
    MAX_RESULTS = 20

    def __init__(self, api_key: str = "", search_depth: str = "basic"):
        self.api_key = api_key or config.tavily_api_key
        # "basic" costs fewer credits than "advanced" and is enough for
        # headline + snippet, which is all the extractor reads.
        self.search_depth = search_depth

    async def search(
        self,
        query: str,
        limit: int = 5,
        include_domains: tuple[str, ...] = (),
    ) -> list[Article]:
        if not self.api_key or not query:
            return []

        payload: dict[str, Any] = {
            # Sent in the body for older keys and as a bearer token for current
            # ones -- harmless together, and works across both auth styles.
            "api_key": self.api_key,
            "query": query,
            "max_results": min(self.MAX_RESULTS, max(1, limit)),
            "search_depth": self.search_depth,
            "include_answer": False,
            "include_raw_content": False,
        }
        if include_domains:
            payload["include_domains"] = list(include_domains)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.API_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            # Fail soft: a dead query must not abort the whole sweep.
            return []

        return [self._to_article(item, query) for item in data.get("results", [])]

    async def extract(self, urls: list[str]) -> dict[str, str]:
        """Pull full page text for `urls` via /extract. Never raises."""
        wanted = [u for u in dict.fromkeys(urls) if u]
        if not self.api_key or not wanted:
            return {}

        batches = [
            wanted[i : i + self.EXTRACT_BATCH]
            for i in range(0, len(wanted), self.EXTRACT_BATCH)
        ]
        results = await asyncio.gather(
            *(self._extract_batch(batch) for batch in batches),
            return_exceptions=True,
        )

        merged: dict[str, str] = {}
        for result in results:
            if isinstance(result, dict):
                merged.update(result)
        return merged

    async def _extract_batch(self, urls: list[str]) -> dict[str, str]:
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "urls": urls,
            "extract_depth": config.reputation_extract_depth,
            "include_images": False,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.EXTRACT_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    # Extraction fetches real pages, so it is slower than search.
                    timeout=90,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            # Fail soft: callers fall back to the search snippet.
            return {}

        extracted: dict[str, str] = {}
        for item in data.get("results", []):
            url = item.get("url", "") or ""
            text = (item.get("raw_content") or "").strip()
            if url and text:
                extracted[url] = text
        return extracted

    @staticmethod
    def _to_article(item: dict[str, Any], query: str) -> Article:
        url = item.get("url", "") or ""
        return Article(
            title=item.get("title", "") or "",
            url=url,
            snippet=item.get("content", "") or "",
            source=source_name(url),
            published=item.get("published_date", "") or "",
            query=query,
            raw=item,
        )
