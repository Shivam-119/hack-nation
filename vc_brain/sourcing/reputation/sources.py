"""Naming a source.

There is no credibility ranking here, by design. Judging how much a given
publication is worth is left to the downstream LLM that reads these findings;
all this module does is turn a URL into a readable publication name.
"""

from __future__ import annotations

from urllib.parse import urlparse


def source_name(url: str) -> str:
    """Return the publication name for a URL ('www.' stripped, lowercased).

    >>> source_name("https://www.reuters.com/legal/article")
    'reuters.com'
    """
    if not url:
        return ""
    try:
        host = urlparse(url if "//" in url else f"https://{url}").netloc.lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host
