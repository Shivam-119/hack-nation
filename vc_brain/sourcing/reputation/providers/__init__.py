"""Search provider selection for the reputation scanner.

Tavily is the default backend. If it is selected but no key is configured we
fall back to the fixture provider rather than returning nothing -- the tool
always produces a result, and the result records which provider produced it.
"""

from __future__ import annotations

from vc_brain.config import config
from vc_brain.sourcing.reputation.providers.base import SearchProvider
from vc_brain.sourcing.reputation.providers.mock import MockProvider
from vc_brain.sourcing.reputation.providers.tavily import TavilyProvider

__all__ = ["SearchProvider", "MockProvider", "TavilyProvider", "get_provider"]


def get_provider(name: str | None = None) -> SearchProvider:
    """Return the configured provider, falling back to fixtures when keyless."""
    choice = (name or config.reputation_provider or "tavily").strip().lower()

    if choice == "tavily":
        return TavilyProvider() if config.tavily_api_key else MockProvider()
    return MockProvider()
