"""Fixture-backed search provider.

Serves the bundled JSON fixtures so the whole pipeline -- sweep, extraction,
scoring, ingest -- runs with no API key and no network. Used by the tests and
as the automatic fallback when Tavily has no key configured.

It deliberately honours the *shape* of a real sweep: an angle whose keywords
match nothing returns nothing, so "no litigation found" still surfaces as a
reported gap rather than being silently filled in.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from vc_brain.sourcing.reputation.models import Article
from vc_brain.sourcing.reputation.sources import source_name

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

_QUOTED = re.compile(r'"([^"]+)"')
_WORD = re.compile(r"[a-z0-9]+")
_OPERATORS = {"or", "and", "not"}


class MockProvider:
    """Search over bundled fixture people."""

    name = "mock"

    def __init__(self, fixtures_dir: Path | None = None):
        self._people = self._load(fixtures_dir or FIXTURES_DIR)

    @staticmethod
    def _load(directory: Path) -> dict[str, dict[str, Any]]:
        people: dict[str, dict[str, Any]] = {}
        if not directory.is_dir():
            return people
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue  # a broken fixture must not break the provider
            name = str(data.get("name", "")).strip().lower()
            if name:
                people[name] = data
        return people

    def known_people(self) -> list[str]:
        """Names available in the fixture set (used by the CLI for hints)."""
        return sorted(str(p.get("name", "")) for p in self._people.values())

    async def search(
        self,
        query: str,
        limit: int = 5,
        include_domains: tuple[str, ...] = (),
    ) -> list[Article]:
        subject = self._match_person(query)
        if not subject:
            return []

        terms = self._query_terms(query, str(subject.get("name", "")))
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in subject.get("articles", []):
            if include_domains and not self._on_domain(item, include_domains):
                continue  # mirrors Tavily's include_domains restriction
            haystack = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [self._to_article(item, query) for _, item in scored[:limit]]

    @staticmethod
    def _on_domain(item: dict[str, Any], domains: tuple[str, ...]) -> bool:
        host = source_name(item.get("url", "") or "")
        return any(host == d or host.endswith(f".{d}") for d in domains)

    async def extract(self, urls: list[str]) -> dict[str, str]:
        """Serve fixture `full_content` for the requested URLs.

        A fixture article without `full_content` is simply absent from the
        result, mirroring a real extraction that failed on that page.
        """
        wanted = {u for u in urls if u}
        if not wanted:
            return {}

        extracted: dict[str, str] = {}
        for person in self._people.values():
            for item in person.get("articles", []):
                url = item.get("url", "")
                text = (item.get("full_content") or "").strip()
                if url in wanted and text:
                    extracted[url] = text
        return extracted

    def _match_person(self, query: str) -> dict[str, Any] | None:
        """Find which fixture person a query is about."""
        lowered = (query or "").lower()

        quoted = _QUOTED.search(query or "")
        if quoted:
            candidate = quoted.group(1).strip().lower()
            if candidate in self._people:
                return self._people[candidate]

        for name, data in self._people.items():
            if name in lowered:
                return data
        return None

    @staticmethod
    def _query_terms(query: str, name: str) -> list[str]:
        """Query tokens minus the person's name and boolean operators."""
        name_tokens = set(_WORD.findall(name.lower()))
        terms: list[str] = []
        for token in _WORD.findall((query or "").lower()):
            if token in name_tokens or token in _OPERATORS or len(token) < 3:
                continue
            if token not in terms:
                terms.append(token)
        return terms

    @staticmethod
    def _to_article(item: dict[str, Any], query: str) -> Article:
        url = item.get("url", "") or ""
        return Article(
            title=item.get("title", "") or "",
            url=url,
            snippet=item.get("snippet", "") or "",
            source=source_name(url),
            published=item.get("published", "") or "",
            query=query,
            raw=item,
        )
