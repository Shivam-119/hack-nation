"""Search provider interface for the reputation scanner.

Providers only fetch articles -- they never interpret them. Every provider
fails soft (returns `[]`), so one dead backend degrades the sweep instead of
crashing the pipeline.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vc_brain.sourcing.reputation.models import Article


@runtime_checkable
class SearchProvider(Protocol):
    """Anything that can turn a query string into articles."""

    name: str

    async def search(
        self,
        query: str,
        limit: int = 5,
        include_domains: tuple[str, ...] = (),
    ) -> list[Article]:
        """Return up to `limit` articles for `query`. Never raises.

        `include_domains` restricts results to those sites -- used for the
        dedicated forum sweep, where a "site:" operator is unreliable.
        """
        ...

    async def extract(self, urls: list[str]) -> dict[str, str]:
        """Fetch full page text for `urls`, returning {url: text}.

        Search snippets are often too thin to support a claim, and the
        extractor drops claims it cannot ground -- pulling the page body
        recovers those. Partial results are fine; missing URLs are simply
        absent from the mapping. Never raises.
        """
        ...
