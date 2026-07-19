"""Tests for the socials tool — deterministic core + scanner, fully offline.

No network and no API keys: the Mock provider serves fixtures and the LLM call
is monkeypatched, so these run in CI at $0.
"""

import asyncio

from vc_brain.config import config
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.store import MemoryStore
from vc_brain.sourcing.socials import (
    SocialsScanner,
    aggregate_identity_score,
    build_network_graph,
    get_graph_provider,
    get_identity_checker,
    get_provider,
    score_network,
    score_prominence,
)
from vc_brain.sourcing.socials.identity import MockIdentityChecker
from vc_brain.sourcing.socials.models import Connection, IdentityResult, SocialPost
from vc_brain.sourcing.socials.providers.mock import MockProvider
import vc_brain.sourcing.socials.post_analyzer as post_analyzer


# ---------------------------------------------------------------------------
# Mock provider / fixtures
# ---------------------------------------------------------------------------
def test_mock_provider_loads_fixtures():
    p = MockProvider("twitter")
    prof = asyncio.run(p.get_profile("janedoe"))
    posts = asyncio.run(p.get_posts("janedoe", 30))
    conns = asyncio.run(p.get_connections("janedoe", 200))
    assert prof and prof.handle == "janedoe" and prof.followers > 0
    assert len(posts) == 5
    assert any(c.target_handle == "sama" for c in conns)


def test_mock_provider_unknown_handle_uses_default_fixture():
    prof = asyncio.run(MockProvider("twitter").get_profile("totally_unknown"))
    assert prof is not None  # falls back to twitter_default.json


# ---------------------------------------------------------------------------
# Deterministic graph + score
# ---------------------------------------------------------------------------
def test_graph_detects_notable_and_scores():
    conns = [
        Connection(network="twitter", source_handle="jane", target_handle="sama",
                   source_url="https://twitter.com/jane/following"),
        Connection(network="twitter", source_handle="jane", target_handle="paulg",
                   source_url="https://twitter.com/jane/following"),
        Connection(network="twitter", source_handle="jane", target_handle="nobody_random"),
    ]
    g = build_network_graph("jane", "twitter", conns, [])
    hit_handles = {h.handle for h in g.notable_hits}
    assert "sama" in hit_handles and "paulg" in hit_handles
    assert "nobody_random" not in hit_handles
    assert 0 < score_network(g) <= 100
    # every notable hit is traceable to a source url
    assert all(h.source_url for h in g.notable_hits)


def test_score_increases_with_more_notable_connections():
    base = [Connection(network="twitter", source_handle="j", target_handle="sama")]
    more = base + [Connection(network="twitter", source_handle="j", target_handle="pmarca")]
    s1 = score_network(build_network_graph("j", "twitter", base, []))
    s2 = score_network(build_network_graph("j", "twitter", more, []))
    assert s2 >= s1


def test_mention_edges_built_from_posts():
    posts = [SocialPost(network="twitter", author_handle="jane",
                        text="great chat with @sama", mentions=["sama"])]
    g = build_network_graph("jane", "twitter", [], posts)
    assert any(e.target == "sama" and e.edge_type == "mentions" for e in g.edges)
    assert any(h.handle == "sama" for h in g.notable_hits)


def test_empty_graph_scores_zero():
    g = build_network_graph("solo", "twitter", [], [])
    assert g.node_count == 1 and g.edge_count == 0
    assert score_network(g) == 0.0


# ---------------------------------------------------------------------------
# Comments (real scraping surface; mock in tests)
# ---------------------------------------------------------------------------
def test_mock_provider_scrapes_comments():
    p = MockProvider("twitter")
    posts = asyncio.run(p.get_posts("janedoe", 30))
    comments = asyncio.run(p.get_comments(posts, 20))
    assert len(comments) >= 3
    names = {c.author_name for c in comments}
    assert "Pieter Levels" in names  # notable commenter present
    assert all(c.author_handle for c in comments)  # handles preserved (not stripped)


# ---------------------------------------------------------------------------
# Connection graph is mocked for now
# ---------------------------------------------------------------------------
def test_graph_provider_always_mock():
    assert type(get_graph_provider("twitter")).__name__ == "MockProvider"
    assert type(get_graph_provider("linkedin")).__name__ == "MockProvider"


# ---------------------------------------------------------------------------
# Identity check + deterministic prominence
# ---------------------------------------------------------------------------
def test_identity_mock_resolves_notable_and_unknown(monkeypatch):
    from vc_brain import config as config_module

    # Pin the provider: config now loads .env, so a real
    # SOCIALS_IDENTITY_PROVIDER there must not change what this test exercises.
    monkeypatch.setattr(
        config_module.config, "socials_identity_provider", "mock", raising=False
    )

    ic = get_identity_checker()
    assert isinstance(ic, MockIdentityChecker)
    notable = asyncio.run(ic.identify("Pieter Levels", "levelsio"))
    assert notable.is_notable and notable.prominence_score >= 60
    unknown = asyncio.run(ic.identify("Alex Rando", "randobuilder22"))
    assert not unknown.is_notable and unknown.prominence_score < 30


def test_prominence_scoring_is_deterministic_and_bounded():
    high = score_prominence(is_notable=True, roles=["Founder"], affiliations=["Stripe"])
    low = score_prominence(is_notable=False, roles=["Engineer"], affiliations=["SomeCo"])
    assert high >= low
    assert 0 <= low <= 100 and 0 <= high <= 100
    assert high >= 60  # notable floor


def test_aggregate_identity_score_counts_only_notable():
    engagers = [
        IdentityResult(query_name="A", is_notable=True, prominence_score=60),
        IdentityResult(query_name="B", is_notable=True, prominence_score=60),
        IdentityResult(query_name="C", is_notable=False, prominence_score=15),
    ]
    assert aggregate_identity_score(engagers) == 60.0  # 2 * 60 * 0.5
    assert aggregate_identity_score([]) == 0.0


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------
def test_provider_factory_defaults_and_fallback():
    saved = (config.socials_twitter_provider, config.apify_token)
    try:
        config.socials_twitter_provider = "mock"
        assert type(get_provider("twitter")).__name__ == "MockProvider"

        config.socials_twitter_provider = "apify"
        config.apify_token = ""  # selected but no key -> must fall back to mock
        assert type(get_provider("twitter")).__name__ == "MockProvider"

        config.apify_token = "test-token"
        assert type(get_provider("twitter")).__name__ == "ApifyTwitterProvider"
    finally:
        config.socials_twitter_provider, config.apify_token = saved


# ---------------------------------------------------------------------------
# Post analyzer
# ---------------------------------------------------------------------------
def test_post_analyzer_fallback_when_llm_unavailable(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("No LLM API key configured")

    monkeypatch.setattr(post_analyzer, "complete_json", boom)
    posts = asyncio.run(MockProvider("twitter").get_posts("janedoe", 30))
    a = asyncio.run(post_analyzer.analyze_posts(posts))
    assert a.confidence <= 0.3
    assert "unavailable" in a.summary.lower()


def test_post_analyzer_coerces_and_clamps_llm_output(monkeypatch):
    async def ok(prompt, system="", **k):
        return {
            "topics": ["ai infra"],
            "sentiment": "positive",
            "confidence": 2.0,  # out of range -> clamp to 0.99
            "evidence": [{"claim": "shipped", "url": "https://x/1"}],
        }

    monkeypatch.setattr(post_analyzer, "complete_json", ok)
    posts = asyncio.run(MockProvider("twitter").get_posts("janedoe", 30))
    a = asyncio.run(post_analyzer.analyze_posts(posts))
    assert a.topics == ["ai infra"]
    assert a.sentiment == "positive"
    assert a.confidence == 0.99
    assert len(a.evidence) == 1


# ---------------------------------------------------------------------------
# Scanner end-to-end (mock provider, monkeypatched LLM) + Memory ingest
# ---------------------------------------------------------------------------
def test_scanner_analyze_ingest_and_enrich(monkeypatch, tmp_path):
    async def boom(*a, **k):
        raise RuntimeError("no key")  # force deterministic analyzer path

    monkeypatch.setattr(post_analyzer, "complete_json", boom)
    store = MemoryStore(path=str(tmp_path / "socials.json"))
    scanner = SocialsScanner(IngestionPipeline(store))

    result = asyncio.run(scanner.analyze({"twitter": "janedoe", "linkedin": "janedoe"}, name="Jane Doe"))
    assert result.network_score > 0
    assert result.graph.notable_hits
    assert result.profiles.get("twitter") and result.profiles.get("linkedin")
    # comments scraped + identity of engagers computed
    assert len(result.comments) >= 3
    assert result.founder_identity is not None
    assert any(e.is_notable for e in result.engager_identities)
    assert result.identity_score > 0

    f1 = scanner.ingest(result)
    n1 = len(f1.data_points)
    assert n1 >= 4  # 2 profiles + post_analysis + identity_network
    types = {dp.content.get("type") for dp in f1.data_points}
    assert "identity_network" in types
    assert store.get_founder(f1.id).twitter_url.endswith("janedoe")

    # re-ingest must enrich the SAME founder, not duplicate
    f2 = scanner.ingest(result)
    assert f2.id == f1.id
    assert len(f2.data_points) > n1
    assert len(store.founders) == 1
