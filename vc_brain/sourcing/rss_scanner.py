"""Outbound sourcing: scan tech news RSS feeds for startup launches."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.models import Founder, SourceType


@dataclass
class RSSLaunch:
    title: str
    summary: str
    article_url: str
    author: str
    source: str  # e.g. "TechCrunch", "VentureBeat"
    company_name: str = ""
    funding_amount: str = ""
    tags: list[str] = field(default_factory=list)


# Feeds to scan and how to classify them
RSS_FEEDS: list[dict] = [
    {
        "name": "TechCrunch Startups",
        "url": "https://techcrunch.com/category/startups/feed/",
        "source": "TechCrunch",
    },
    {
        "name": "TechCrunch Venture",
        "url": "https://techcrunch.com/category/venture/feed/",
        "source": "TechCrunch",
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
        "source": "VentureBeat",
    },
]

# Signals that an article is about a new startup / raise
LAUNCH_SIGNALS = [
    "raises", "launch", "seed", "series a", "series b", "pre-seed",
    "funding", "debuts", "unveils", "announces", "startup", "founded",
    "stealth", "emerges", "secures", "$",
]

# Patterns to extract company name from title
_RAISES_RE = re.compile(
    r"^(?P<company>[^,]+?)\s+(?:raises?|secures?|lands?|closes?)\s",
    re.IGNORECASE,
)
_FUNDING_AMOUNT_RE = re.compile(r"\$[\d,.]+[MBK]?", re.IGNORECASE)


def _is_launch_article(title: str, summary: str) -> bool:
    text = (title + " " + summary).lower()
    return any(sig in text for sig in LAUNCH_SIGNALS)


def _extract_company(title: str) -> str:
    m = _RAISES_RE.match(title)
    if m:
        return m.group("company").strip()
    # Fallback: first segment before comma or dash
    for sep in (",", " - ", " – ", ":"):
        if sep in title:
            return title.split(sep)[0].strip()
    return ""


def _extract_funding(title: str, summary: str) -> str:
    for text in (title, summary):
        m = _FUNDING_AMOUNT_RE.search(text)
        if m:
            return m.group(0)
    return ""


class TechRSSScanner:
    """Scan tech news RSS feeds for startup launch and funding articles."""

    def __init__(self, pipeline: IngestionPipeline, feeds: list[dict] | None = None):
        self.pipeline = pipeline
        self.feeds = feeds if feeds is not None else RSS_FEEDS

    async def scan_feeds(self, limit_per_feed: int = 15) -> list[RSSLaunch]:
        """Fetch and parse all configured RSS feeds, return launch articles."""
        launches: list[RSSLaunch] = []
        async with httpx.AsyncClient(timeout=20) as client:
            for feed in self.feeds:
                items = await self._fetch_feed(client, feed, limit_per_feed)
                launches.extend(items)
        return launches

    async def _fetch_feed(
        self, client: httpx.AsyncClient, feed: dict, limit: int
    ) -> list[RSSLaunch]:
        launches = []
        try:
            resp = await client.get(feed["url"])
            if resp.status_code != 200:
                return launches

            root = ET.fromstring(resp.text)
            channel = root.find("channel")
            if channel is None:
                # Atom feed fallback
                channel = root

            ns = {
                "dc": "http://purl.org/dc/elements/1.1/",
                "content": "http://purl.org/rss/1.0/modules/content/",
            }
            items = channel.findall("item")[:limit]

            for item in items:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                description = (item.findtext("description") or "").strip()
                author = (item.findtext("dc:creator", namespaces=ns) or "").strip()
                # strip HTML tags from description for signal matching
                plain_desc = re.sub(r"<[^>]+>", " ", description)

                if not _is_launch_article(title, plain_desc):
                    continue

                launches.append(RSSLaunch(
                    title=title,
                    summary=plain_desc[:300],
                    article_url=link,
                    author=author,
                    source=feed["source"],
                    company_name=_extract_company(title),
                    funding_amount=_extract_funding(title, plain_desc),
                ))
        except Exception:
            pass
        return launches

    async def ingest_launches(self, launches: list[RSSLaunch]) -> list[Founder]:
        """Store company founders discovered via tech press as candidates."""
        founders = []
        for launch in launches:
            company = launch.company_name or "Unknown startup"
            bio = f"{launch.source}: {launch.title}"
            if launch.funding_amount:
                bio += f" ({launch.funding_amount})"

            founder = self.pipeline.ingest_founder_from_source(
                source=SourceType.TECH_PRESS,
                data={
                    "name": launch.author or f"Founder of {company}",
                    "bio": bio,
                    "profile_url": launch.article_url,
                    "company_name": company,
                    "article_url": launch.article_url,
                    "press_source": launch.source,
                    "funding_amount": launch.funding_amount,
                    "confidence": 0.35,
                },
            )
            founders.append(founder)
        return founders
