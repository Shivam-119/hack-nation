"""Decide which articles deserve a full-text extraction.

Extraction costs credits and latency, so we do not pull every result. Which
pages to fetch is deterministic policy, not a model call -- and it makes no
judgement about publications, only about how much text we already have.

The rule is simply: read the pages we know least about. A short snippet is
where information gets silently lost, because the summariser can only report
what the text actually says. Fetching the body is how we recover it.
"""

from __future__ import annotations

from vc_brain.sourcing.reputation.models import Article

# Snippets shorter than this rarely say much on their own.
THIN_SNIPPET_CHARS = 400


def select_for_extraction(articles: list[Article], limit: int) -> list[Article]:
    """Pick the articles we currently know least about, thinnest first.

    Only genuinely thin articles are eligible. Without that floor, a wide sweep
    with a generous limit would spend credits re-reading pages whose snippet
    already says plenty -- paying for text we effectively have.
    """
    if limit <= 0:
        return []

    candidates = [
        a for a in articles
        if a.url and not a.extracted and len(a.snippet) < THIN_SNIPPET_CHARS
    ]
    # Thinnest snippet first; URL as a tie-break so the order is stable.
    candidates.sort(key=lambda a: (len(a.snippet), a.url))
    return candidates[:limit]


def apply_extractions(articles: list[Article], extracted: dict[str, str]) -> int:
    """Attach extracted page text to its article. Returns how many landed."""
    applied = 0
    for article in articles:
        text = extracted.get(article.url)
        if text:
            article.full_text = text
            article.extracted = True
            applied += 1
    return applied


def thin_count(articles: list[Article]) -> int:
    """How many articles still rest on a snippet too thin to say much."""
    return sum(
        1 for a in articles
        if not a.extracted and len(a.snippet) < THIN_SNIPPET_CHARS
    )
