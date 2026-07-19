"""Outbound sourcing: scan arXiv for AI/ML researchers who may be founders."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx

from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.models import Founder, SourceType


ARXIV_API = "https://export.arxiv.org/api/query"

# Namespaces used in arXiv Atom feed
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

# Default queries — recent, high-signal AI research areas
DEFAULT_QUERIES = [
    "cat:cs.AI AND ti:agent",
    "cat:cs.LG AND ti:foundation model",
    "cat:cs.CL AND ti:language model",
    "cat:cs.RO AND ti:robot learning",
    "cat:cs.CV AND ti:diffusion",
]


@dataclass
class ArXivPaper:
    arxiv_id: str
    title: str
    abstract: str
    paper_url: str
    authors: list[str]
    primary_author: str
    primary_author_url: str
    categories: list[str] = field(default_factory=list)
    published: str = ""


class ArXivScanner:
    """Find AI researchers on arXiv who author high-signal papers."""

    def __init__(self, pipeline: IngestionPipeline, queries: list[str] | None = None):
        self.pipeline = pipeline
        self.queries = queries if queries is not None else DEFAULT_QUERIES

    async def scan_papers(self, max_per_query: int = 10) -> list[ArXivPaper]:
        """Fetch recent arXiv papers matching configured queries."""
        papers: list[ArXivPaper] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=30) as client:
            for query in self.queries:
                batch = await self._fetch_query(client, query, max_per_query)
                for paper in batch:
                    if paper.arxiv_id not in seen_ids:
                        seen_ids.add(paper.arxiv_id)
                        papers.append(paper)

        return papers

    async def _fetch_query(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[ArXivPaper]:
        params = urlencode({
            "search_query": query,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        })
        papers = []
        try:
            resp = await client.get(f"{ARXIV_API}?{params}")
            if resp.status_code != 200:
                return papers
            root = ET.fromstring(resp.text)
        except Exception:
            return papers

        for entry in root.findall("atom:entry", _NS):
            arxiv_id_raw = entry.findtext("atom:id", "", _NS).strip()
            arxiv_id = arxiv_id_raw.rsplit("/", 1)[-1]  # e.g. "2401.12345v1"
            title = re.sub(r"\s+", " ", entry.findtext("atom:title", "", _NS)).strip()
            abstract = re.sub(r"\s+", " ", entry.findtext("atom:summary", "", _NS)).strip()[:500]
            published = entry.findtext("atom:published", "", _NS)[:10]

            authors = [
                a.findtext("atom:name", "", _NS).strip()
                for a in entry.findall("atom:author", _NS)
            ]
            categories = [
                c.get("term", "")
                for c in entry.findall("atom:category", _NS)
            ]
            primary = authors[0] if authors else ""

            papers.append(ArXivPaper(
                arxiv_id=arxiv_id,
                title=title,
                abstract=abstract,
                paper_url=arxiv_id_raw,
                authors=authors,
                primary_author=primary,
                primary_author_url=f"https://arxiv.org/search/?query={primary.replace(' ', '+')}&searchtype=author",
                categories=categories,
                published=published,
            ))
        return papers

    async def ingest_researchers(self, papers: list[ArXivPaper]) -> list[Founder]:
        """Store primary authors of papers as high-potential founder candidates."""
        founders = []
        seen_authors: set[str] = set()

        for paper in papers:
            author = paper.primary_author
            if not author or author in seen_authors:
                continue
            seen_authors.add(author)

            bio = f"AI researcher — published: {paper.title[:80]}"
            if paper.categories:
                bio += f" [{', '.join(paper.categories[:3])}]"

            founder = self.pipeline.ingest_founder_from_source(
                source=SourceType.ARXIV,
                data={
                    "name": author,
                    "bio": bio,
                    "profile_url": paper.primary_author_url,
                    "paper_url": paper.paper_url,
                    "paper_title": paper.title,
                    "paper_abstract": paper.abstract,
                    "co_authors": paper.authors[1:5],
                    "arxiv_categories": paper.categories,
                    "published_date": paper.published,
                    "confidence": 0.5,
                },
            )
            founders.append(founder)
        return founders
