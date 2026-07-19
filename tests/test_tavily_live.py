"""Live integration tests against the real Tavily API.

Skipped by default. They hit the network and spend credits, so they only run
when you opt in explicitly:

    RUN_LIVE_TESTS=1 .venv/bin/python -m pytest tests/test_tavily_live.py -v

Assertions target structural invariants -- a result came back, the URL parses,
extraction returned a real body, every cited URL came from the sweep -- rather
than specific wording. Live search results drift constantly, and a test that
asserts today's headline is a test that fails next week for no useful reason.

The one semantic assertion is the Elizabeth Holmes case: a fraud conviction of
public record is about as stable as web data gets, and if our pipeline ever
stops flagging it, that is a genuine failure worth hearing about.
"""

import asyncio
import os

import pytest

from vc_brain.config import config
from vc_brain.sourcing.reputation.enrichment import apply_extractions
from vc_brain.sourcing.reputation.models import EntityType, FindingCategory, Polarity
from vc_brain.sourcing.reputation.providers import get_provider
from vc_brain.sourcing.reputation.providers.tavily import TavilyProvider
from vc_brain.sourcing.reputation.scanner import ReputationScanner
from vc_brain.sourcing.reputation.sources import source_name

_OPT_IN = os.getenv("RUN_LIVE_TESTS", "").strip().lower() in ("1", "true", "yes")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not _OPT_IN, reason="live API test -- set RUN_LIVE_TESTS=1 to enable"),
    pytest.mark.skipif(not config.tavily_api_key, reason="TAVILY_API_KEY not configured"),
]

# A topic with deep, stable coverage, so the sweep reliably returns something.
STABLE_QUERY = '"Elizabeth Holmes" Theranos SEC charges'
# A page that stays put and extracts cleanly.
STABLE_URL = "https://en.wikipedia.org/wiki/Theranos"


@pytest.fixture
def cheap_sweep(monkeypatch):
    """Shrink the sweep so the end-to-end test costs pennies."""
    monkeypatch.setattr(config, "reputation_max_queries", 4, raising=False)
    monkeypatch.setattr(config, "reputation_results_per_query", 3, raising=False)
    monkeypatch.setattr(config, "reputation_extract_limit", 3, raising=False)


# -- /search ----------------------------------------------------------------

def test_live_search_returns_wellformed_articles():
    articles = asyncio.run(TavilyProvider().search(STABLE_QUERY, limit=3))

    assert articles, "live search returned nothing for a heavily covered topic"
    assert len(articles) <= 3
    for article in articles:
        assert article.url.startswith("http")
        assert article.source
        assert article.title or article.snippet
        assert article.raw, "raw provider payload should be retained"
        assert article.query == STABLE_QUERY


def test_live_search_results_are_named_consistently():
    articles = asyncio.run(TavilyProvider().search(STABLE_QUERY, limit=5))
    assert articles

    for article in articles:
        # The source name must be derivable from the URL, never invented.
        assert article.source == source_name(article.url)
        assert "/" not in article.source
        assert not article.source.startswith("www.")


def test_live_reddit_search_is_domain_restricted():
    """The dedicated forum sweep must actually stay on Reddit."""
    articles = asyncio.run(
        TavilyProvider().search("Theranos blood testing", 5, ("reddit.com",))
    )

    if not articles:
        pytest.skip("Tavily returned no Reddit results for this query on this run")
    for article in articles:
        assert article.source == "reddit.com" or article.source.endswith(".reddit.com")


def test_live_search_is_failsoft_on_a_junk_query():
    # Nonsense query: may return nothing, but must never raise.
    articles = asyncio.run(TavilyProvider().search("zzzqqq nonexistent person xyzzy 9f8s7", limit=3))
    assert isinstance(articles, list)


# -- /extract ---------------------------------------------------------------

def test_live_extract_returns_page_body():
    extracted = asyncio.run(TavilyProvider().extract([STABLE_URL]))

    assert STABLE_URL in extracted, "extraction failed on a stable public page"
    body = extracted[STABLE_URL]
    assert len(body) > 500, "extracted body suspiciously short"
    assert "Theranos" in body


def test_live_extract_is_failsoft_on_unreachable_url():
    bad = "https://example.invalid/definitely-not-a-page"
    extracted = asyncio.run(TavilyProvider().extract([bad]))

    # Absent from the mapping, and crucially: no exception.
    assert isinstance(extracted, dict)
    assert bad not in extracted


def test_live_extract_handles_empty_input():
    assert asyncio.run(TavilyProvider().extract([])) == {}


def test_live_extract_yields_more_text_than_the_snippet():
    """The whole justification for spending credits on /extract.

    Extracts specific URLs directly rather than going through
    `select_for_extraction`, which deliberately returns nothing when every
    snippet is already rich -- that policy has its own offline test.
    """
    provider = TavilyProvider()
    articles = asyncio.run(provider.search(STABLE_QUERY, limit=5))
    assert articles

    extracted = asyncio.run(provider.extract([a.url for a in articles[:3]]))
    if not extracted:
        pytest.skip("every extraction target was blocked (paywall/403) on this run")

    applied = apply_extractions(articles, extracted)
    assert applied >= 1

    enriched = [a for a in articles if a.extracted]
    assert any(len(a.full_text) > len(a.snippet) for a in enriched)
    assert all(a.best_text() == a.full_text for a in enriched)


# -- Wiring -----------------------------------------------------------------

def test_live_factory_selects_tavily_when_key_present():
    assert isinstance(get_provider("tavily"), TavilyProvider)


# -- Full pipeline ----------------------------------------------------------

@pytest.mark.skipif(not config.openai_api_key, reason="OPENAI_API_KEY not configured")
def test_live_scanner_end_to_end(cheap_sweep):
    scanner = ReputationScanner(provider=TavilyProvider())
    report = asyncio.run(scanner.analyze("Elizabeth Holmes", hint="Theranos"))

    assert report.provider == "tavily"
    assert report.articles_reviewed > 0
    assert report.sources
    assert report.queries_run
    assert report.findings, "no findings extracted from live coverage"

    swept = set(report.sources)
    for finding in report.findings:
        assert finding.summary
        assert finding.sources, "every finding must carry its proof links"
        assert 1 <= finding.relevance <= 10
        assert 0.0 <= finding.confidence <= 0.95  # a trust label, never certainty
        assert isinstance(finding.category, FindingCategory)
        assert isinstance(finding.polarity, Polarity)

        # Integrity: the model cites articles by index, so every source must
        # trace back to a URL the sweep actually retrieved. A citation outside
        # this set would mean a hallucinated source reached the evidence chain.
        for source in finding.sources:
            assert source.url.startswith("http")
            assert source.url in swept

    # Index counts must agree with the findings themselves.
    assert sum(report.by_category.values()) == len(report.findings)
    assert sum(report.by_polarity.values()) == len(report.findings)

    # Semantic check on a matter of public record: coverage this heavy should
    # surface fraud/legal material, and it should read as unfavourable.
    categories = {f.category for f in report.findings}
    assert categories & {FindingCategory.FRAUD, FindingCategory.LEGAL}
    assert any(f.polarity is Polarity.NEGATIVE for f in report.findings)
    # A person this heavily covered should yield direct, on-topic articles.
    assert max(f.relevance for f in report.findings) >= 8


@pytest.mark.skipif(not config.openai_api_key, reason="OPENAI_API_KEY not configured")
def test_live_company_scanner_end_to_end(cheap_sweep):
    """The company variant must produce company-shaped findings, not person ones."""
    scanner = ReputationScanner(provider=TavilyProvider())
    report = asyncio.run(scanner.analyze("Theranos", entity=EntityType.COMPANY))

    assert report.entity is EntityType.COMPANY
    assert report.articles_reviewed > 0
    assert report.findings, "no findings extracted from live company coverage"

    swept = set(report.sources)
    for finding in report.findings:
        assert finding.summary
        assert finding.sources
        assert 1 <= finding.relevance <= 10
        for source in finding.sources:
            assert source.url in swept  # no hallucinated citations

    # Coverage this heavy should yield company-shaped categories.
    company_shaped = {
        FindingCategory.PRODUCT,
        FindingCategory.TEAM,
        FindingCategory.ACCELERATOR,
        FindingCategory.FUNDING,
        FindingCategory.LEGAL,
        FindingCategory.FAILURE,
        FindingCategory.FRAUD,
    }
    assert {f.category for f in report.findings} & company_shaped


@pytest.mark.skipif(not config.openai_api_key, reason="OPENAI_API_KEY not configured")
def test_live_scanner_reports_gaps_for_an_unknown_person(cheap_sweep):
    """An obscure name must yield an honest empty result, not invented signal."""
    scanner = ReputationScanner(provider=TavilyProvider())
    report = asyncio.run(scanner.analyze("Qwertyuiop Zxcvbnm Fakename"))

    # Nothing may be attributed to a person the web has never heard of.
    assert not [f for f in report.findings if f.polarity is Polarity.NEGATIVE]
    assert report.gaps, "absence of coverage must be reported as a gap"
