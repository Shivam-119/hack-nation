"""Outbound sourcing: scan Product Hunt for new launches."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

from vc_brain.config import config
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.models import Founder, SourceType


@dataclass
class PHLaunch:
    name: str
    tagline: str
    ph_url: str
    product_url: str
    maker_name: str
    maker_profile_url: str
    votes: int
    topics: list[str]


class ProductHuntScanner:
    """Scan Product Hunt for new product launches and their makers."""

    RSS_URL = "https://www.producthunt.com/feed"
    GQL_URL = "https://api.producthunt.com/v2/api/graphql"

    def __init__(self, pipeline: IngestionPipeline):
        self.pipeline = pipeline

    async def scan_launches(self, limit: int = 20) -> list[PHLaunch]:
        """Fetch recent Product Hunt launches.

        Uses GraphQL API when a token is configured, otherwise falls back to RSS.
        """
        if config.producthunt_token:
            return await self._scan_via_api(limit)
        return await self._scan_via_rss(limit)

    async def _scan_via_api(self, limit: int) -> list[PHLaunch]:
        """Fetch launches via Product Hunt GraphQL API."""
        query = """
        query($first: Int!) {
          posts(first: $first, order: VOTES) {
            edges {
              node {
                name
                tagline
                url
                website
                votesCount
                topics {
                  edges {
                    node { name }
                  }
                }
                makers {
                  name
                  username
                  profileUrl
                }
              }
            }
          }
        }
        """
        headers = {
            "Authorization": f"Bearer {config.producthunt_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        launches = []
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    self.GQL_URL,
                    json={"query": query, "variables": {"first": limit}},
                    headers=headers,
                )
                if resp.status_code != 200:
                    return await self._scan_via_rss(limit)

                data = resp.json()
                edges = data.get("data", {}).get("posts", {}).get("edges", [])
                for edge in edges:
                    node = edge.get("node", {})
                    makers = node.get("makers", [])
                    maker = makers[0] if makers else {}
                    topics = [
                        t["node"]["name"]
                        for t in node.get("topics", {}).get("edges", [])
                    ]
                    launches.append(PHLaunch(
                        name=node.get("name", ""),
                        tagline=node.get("tagline", ""),
                        ph_url=node.get("url", ""),
                        product_url=node.get("website", ""),
                        maker_name=maker.get("name", "") or maker.get("username", ""),
                        maker_profile_url=maker.get("profileUrl", ""),
                        votes=node.get("votesCount", 0),
                        topics=topics,
                    ))
        except Exception:
            return await self._scan_via_rss(limit)
        return launches

    async def _scan_via_rss(self, limit: int) -> list[PHLaunch]:
        """Fetch launches from Product Hunt RSS feed (no auth required)."""
        launches = []
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(self.RSS_URL)
                if resp.status_code != 200:
                    return launches

                root = ET.fromstring(resp.text)
                channel = root.find("channel")
                if channel is None:
                    return launches

                ns = {"dc": "http://purl.org/dc/elements/1.1/"}
                for item in list(channel.findall("item"))[:limit]:
                    title = (item.findtext("title") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    description = (item.findtext("description") or "").strip()
                    creator = (item.findtext("dc:creator", namespaces=ns) or "").strip()

                    # RSS title format: "Product Name — Tagline"
                    if " — " in title:
                        name, tagline = title.split(" — ", 1)
                    elif " - " in title:
                        name, tagline = title.split(" - ", 1)
                    else:
                        name, tagline = title, description[:100]

                    # Extract product URL from description HTML
                    product_url_match = re.search(r'href="(https?://[^"]+)"', description)
                    product_url = product_url_match.group(1) if product_url_match else ""
                    # Avoid self-referencing PH links as product URL
                    if "producthunt.com" in product_url:
                        product_url = ""

                    launches.append(PHLaunch(
                        name=name.strip(),
                        tagline=tagline.strip(),
                        ph_url=link,
                        product_url=product_url,
                        maker_name=creator,
                        maker_profile_url="",
                        votes=0,  # not in RSS
                        topics=[],
                    ))
        except Exception:
            pass
        return launches

    async def ingest_launches(self, launches: list[PHLaunch]) -> list[Founder]:
        """Store PH makers as founder candidates."""
        founders = []
        for launch in launches:
            if not launch.maker_name:
                continue
            founder = self.pipeline.ingest_founder_from_source(
                source=SourceType.PRODUCT_HUNT,
                data={
                    "name": launch.maker_name,
                    "bio": f"Launched on Product Hunt: {launch.name} — {launch.tagline}",
                    "profile_url": launch.maker_profile_url or launch.ph_url,
                    "product_url": launch.product_url,
                    "ph_url": launch.ph_url,
                    "product_name": launch.name,
                    "product_tagline": launch.tagline,
                    "ph_votes": launch.votes,
                    "topics": launch.topics,
                    "confidence": 0.45,
                },
            )
            founders.append(founder)
        return founders
