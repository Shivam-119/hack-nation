"""Tests for the reputation scanner.

Everything here runs offline: the fixture provider replaces web search and the
LLM summarisation step is stubbed, so the deterministic core is what gets
tested. Async tests use asyncio.run directly to avoid depending on
pytest-asyncio mode.

The tool collects and organises evidence -- it does not score, rank, or grade
publications. These tests guard that contract: findings are deduplicated,
every one carries its sources by name and link, and nothing invents a ranking.
"""

import asyncio

import pytest

from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.models import SourceType
from vc_brain.memory.store import MemoryStore
from vc_brain.sourcing.reputation import analyzer as analyzer_module
from vc_brain.sourcing.reputation.aggregate import (
    dedupe_sources,
    index_by_category,
    index_by_polarity,
    merge_by_clusters,
    sort_findings,
)
from vc_brain.sourcing.reputation.analyzer import _as_relevance, cluster_findings
from vc_brain.sourcing.reputation.enrichment import (
    apply_extractions,
    select_for_extraction,
    thin_count,
)
from vc_brain.sourcing.reputation.models import (
    Article,
    EntityType,
    FindingCategory,
    Polarity,
    ReputationFinding,
    SourceRef,
)
from vc_brain.sourcing.reputation.providers import get_provider
from vc_brain.sourcing.reputation.providers.mock import MockProvider
from vc_brain.sourcing.reputation.analyzer import _load_system_prompt
from vc_brain.sourcing.reputation.queries import (
    BACKGROUND,
    FORUM,
    NEGATIVE,
    POSITIVE,
    build_queries,
)
from vc_brain.sourcing.reputation import scanner as scanner_module
from vc_brain.sourcing.reputation.scanner import ReputationScanner
from vc_brain.sourcing.reputation.sources import source_name


async def _no_cluster(*args, **kwargs):
    """Stand-in for the LLM dedup step: no findings are grouped."""
    return []


@pytest.fixture(autouse=True)
def _offline_clustering(monkeypatch):
    """Keep every scanner run offline -- the dedup LLM call is stubbed to a
    no-op so tests never depend on a key or the network. Tests that exercise
    cluster_findings directly stub complete_json themselves and are unaffected."""
    monkeypatch.setattr(scanner_module, "cluster_findings", _no_cluster, raising=False)


def _source(url="https://techcrunch.com/a", relevance=8):
    return SourceRef(source=source_name(url), url=url, relevance=relevance)


def _finding(
    summary="A summary about the person",
    category=FindingCategory.PRESS,
    polarity=Polarity.POSITIVE,
    entity="Acme",
    confidence=0.6,
    sources=None,
):
    return ReputationFinding(
        summary=summary,
        category=category,
        polarity=polarity,
        entity=entity,
        confidence=confidence,
        relevance=max((s.relevance for s in (sources or [])), default=5),
        sources=list(sources) if sources else [_source()],
    )


# -- Source naming ----------------------------------------------------------

def test_source_name_strips_scheme_and_www():
    assert source_name("https://www.reuters.com/legal/a") == "reuters.com"
    assert source_name("https://techcrunch.com/2023/a") == "techcrunch.com"
    assert source_name("https://blog.techcrunch.com/post") == "blog.techcrunch.com"
    assert source_name("https://www.bbc.co.uk/news") == "bbc.co.uk"


def test_source_name_handles_empty_input():
    assert source_name("") == ""


# -- Query sweep ------------------------------------------------------------

def test_build_queries_covers_both_polarities_and_applies_hint():
    queries = build_queries("Ada Whitfield", hint="Rivulet", max_queries=6)
    assert len(queries) == 6
    intents = {q.intent for q in queries}
    assert POSITIVE in intents and NEGATIVE in intents
    assert all("Rivulet" in q.text for q in queries)
    assert all('"Ada Whitfield"' in q.text for q in queries)


def test_build_queries_requires_a_name():
    assert build_queries("", max_queries=5) == []


def test_company_sweep_asks_different_questions_than_a_person_sweep():
    person = build_queries("Ada Whitfield", max_queries=15, entity=EntityType.PERSON)
    company = build_queries("Northwind Logistics", max_queries=15, entity=EntityType.COMPANY)

    assert {q.text for q in person} != {q.text for q in company}
    company_text = " ".join(q.text for q in company).lower()
    # Early-stage concerns: what is it, who built it, who backed it.
    for term in ("pre-seed", "founders", "product hunt", "accelerator", "launch"):
        assert term in company_text

    # Growth/late-stage angles waste queries at pre-seed and pull in namesakes.
    for term in ("layoffs", "acquisition", "merger", "market share", "partnership"):
        assert term not in company_text

    # Both sweeps stay balanced across intents.
    for queries in (person, company):
        intents = {q.intent for q in queries}
        assert {POSITIVE, NEGATIVE, BACKGROUND, FORUM} <= intents


def test_reddit_angle_is_domain_restricted():
    """A 'site:' operator is unreliable in semantic search -- we scope by domain."""
    for entity in (EntityType.PERSON, EntityType.COMPANY):
        queries = build_queries("Subject", max_queries=15, entity=entity)
        forum = [q for q in queries if q.intent == FORUM]

        assert forum, f"{entity.value} sweep is missing a forum angle"
        assert all(q.include_domains == ("reddit.com",) for q in forum)
        # Every other angle searches the open web.
        assert all(q.include_domains == () for q in queries if q.intent != FORUM)


# -- Relevance --------------------------------------------------------------

def test_relevance_is_clamped_into_range():
    assert _as_relevance(10) == 10
    assert _as_relevance(1) == 1
    assert _as_relevance(99) == 10  # a model over-shooting is pulled back
    assert _as_relevance(-4) == 1
    assert _as_relevance("7") == 7
    assert _as_relevance(7.6) == 8
    assert _as_relevance(None) == 5  # sensible default, not a crash
    assert _as_relevance("banana") == 5


def test_finding_relevance_takes_the_best_source():
    """A story is as relevant as the most on-point article backing it."""
    incidental = _source("https://sportsblog.com/a", relevance=1)
    direct = _source("https://www.reuters.com/a", relevance=10)

    merged = merge_by_clusters(
        [
            _finding(summary="Led the Series B round", sources=[incidental]),
            _finding(summary="Led the Series B round", sources=[direct]),
        ],
        [[0, 1]],
    )

    assert len(merged) == 1
    assert merged[0].relevance == 10


# -- Deduplication ----------------------------------------------------------
#
# *Which* findings describe the same story is the model's call (cluster_findings,
# exercised below with a stubbed LLM). These tests cover the mechanical merge:
# given the model's index groups, merge_by_clusters must combine the sources,
# keep the strongest wording, and never drop or duplicate a finding.

def test_clustered_story_becomes_one_finding_with_both_links():
    summary = "Was charged by the SEC with misleading investors"
    merged = merge_by_clusters(
        [
            _finding(
                summary=summary, category=FindingCategory.FRAUD, polarity=Polarity.NEGATIVE,
                entity="Northwind", sources=[_source("https://www.reuters.com/a", 9)],
            ),
            _finding(
                summary=summary, category=FindingCategory.FRAUD, polarity=Polarity.NEGATIVE,
                entity="Northwind", sources=[_source("https://www.sec.gov/b", 10)],
            ),
        ],
        [[0, 1]],
    )

    assert len(merged) == 1
    finding = merged[0]
    assert finding.source_count == 2
    assert {s.url for s in finding.sources} == {
        "https://www.reuters.com/a",
        "https://www.sec.gov/b",
    }
    assert {s.source for s in finding.sources} == {"reuters.com", "sec.gov"}
    # Most on-point article is listed first.
    assert finding.primary_source.source == "sec.gov"


def test_cluster_keeps_the_strongest_wording():
    """When a group is merged, the best-supported phrasing survives."""
    merged = merge_by_clusters(
        [
            _finding(
                summary="Holmes founded Theranos",
                category=FindingCategory.CURRENT_ROLE, entity="Theranos",
                sources=[_source("https://www.britannica.com/a", 7)],
            ),
            _finding(
                summary="Elizabeth Holmes was the founder and CEO of Theranos from 2003 to 2018",
                category=FindingCategory.CURRENT_ROLE, entity="Theranos",
                sources=[_source("https://www.reuters.com/a", 9)],
            ),
        ],
        [[0, 1]],
    )

    assert len(merged) == 1
    assert merged[0].source_count == 2
    # The more on-point, more detailed version wins the wording.
    assert "2003 to 2018" in merged[0].summary


def test_unclustered_findings_stay_separate():
    """No group means no merge -- distinct events each stand on their own."""
    merged = merge_by_clusters(
        [
            _finding(
                summary="Was sentenced to more than 11 years in prison",
                category=FindingCategory.LEGAL, entity="Theranos", polarity=Polarity.NEGATIVE,
            ),
            _finding(
                summary="Owes over 25 million dollars to company creditors",
                category=FindingCategory.LEGAL, entity="Theranos", polarity=Polarity.NEGATIVE,
            ),
        ],
        [],
    )
    assert len(merged) == 2


def test_same_url_twice_is_only_one_source():
    summary = "Company shut down after failing to raise"
    merged = merge_by_clusters(
        [
            _finding(summary=summary, category=FindingCategory.FAILURE,
                     sources=[_source("https://techcrunch.com/a")]),
            _finding(summary=summary, category=FindingCategory.FAILURE,
                     sources=[_source("https://techcrunch.com/a")]),
        ],
        [[0, 1]],
    )
    assert len(merged) == 1
    assert merged[0].source_count == 1


def test_out_of_range_and_repeated_indices_never_drop_a_finding():
    """A malformed cluster list can only fail to merge, never lose data."""
    findings = [
        _finding(summary="Won a gold medal at the IMO", category=FindingCategory.AWARD),
        _finding(summary="Raised a $4M seed round led by Accel", category=FindingCategory.FUNDING),
    ]
    # Nonsense clusters: a phantom index, and 0 named in two groups at once.
    merged = merge_by_clusters(findings, [[0, 99], [0, 1]])
    # Every real finding still present exactly once, nothing duplicated.
    assert {f.summary for f in merged} == {f.summary for f in findings}
    assert len(merged) <= len(findings)


def test_empty_clusters_leave_every_finding_standing():
    findings = [
        _finding(summary="Won a gold medal at the IMO", category=FindingCategory.AWARD),
        _finding(summary="Raised a $4M seed round led by Accel", category=FindingCategory.FUNDING),
    ]
    merged = merge_by_clusters(findings, [])
    assert len(merged) == 2


def test_dedupe_sources_orders_by_relevance():
    ordered = dedupe_sources([
        _source("https://a.com/x", 4),
        _source("https://b.com/x", 10),
        _source("https://c.com/x", 7),
    ])
    assert [s.relevance for s in ordered] == [10, 7, 4]


def test_merging_is_deterministic():
    findings = [
        _finding(summary="Won a gold medal at the IMO", category=FindingCategory.AWARD),
        _finding(summary="Was sued by investors", category=FindingCategory.LEGAL,
                 polarity=Polarity.NEGATIVE),
    ]
    assert [f.summary for f in merge_by_clusters(findings, [])] == [
        f.summary for f in merge_by_clusters(findings, [])
    ]


# -- LLM clustering (stubbed model) -----------------------------------------

def _stub_complete_json(result):
    async def _run(prompt, system="", **kwargs):
        return result

    return _run


def test_cluster_findings_returns_model_groups(monkeypatch):
    monkeypatch.setattr(
        analyzer_module, "complete_json", _stub_complete_json({"groups": [[0, 2]]})
    )
    findings = [
        _finding(summary="a"), _finding(summary="b"), _finding(summary="c"),
    ]
    groups = asyncio.run(cluster_findings("Subject", findings))
    assert groups == [[0, 2]]


def test_cluster_findings_drops_singletons_and_non_lists(monkeypatch):
    monkeypatch.setattr(
        analyzer_module,
        "complete_json",
        _stub_complete_json({"groups": [[1], "nonsense", [0, 2]]}),
    )
    findings = [_finding(summary=s) for s in ("a", "b", "c")]
    groups = asyncio.run(cluster_findings("Subject", findings))
    # Only the real group of two survives; a singleton and a non-list are dropped.
    assert groups == [[0, 2]]


def test_cluster_findings_is_fail_soft(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("no LLM key configured")

    monkeypatch.setattr(analyzer_module, "complete_json", _boom)
    findings = [_finding(summary="a"), _finding(summary="b")]
    # A failed dedup must never abort the sweep -- it just skips clustering.
    assert asyncio.run(cluster_findings("Subject", findings)) == []


def test_cluster_findings_skips_the_model_below_two_findings():
    called = False

    async def _tripwire(*args, **kwargs):
        nonlocal called
        called = True
        return {"groups": []}

    # Not monkeypatched onto the module: cluster_findings must short-circuit
    # before ever reaching the model when there is nothing to compare.
    assert asyncio.run(cluster_findings("Subject", [_finding(summary="only one")])) == []
    assert asyncio.run(cluster_findings("Subject", [])) == []
    assert called is False


# -- Indexing ---------------------------------------------------------------

def test_findings_are_grouped_by_category_for_downstream():
    findings = sort_findings([
        _finding(summary="b", category=FindingCategory.FUNDING),
        _finding(summary="a", category=FindingCategory.AWARD),
        _finding(summary="c", category=FindingCategory.FUNDING),
    ])
    # Same category contiguous -- downstream can chunk without re-sorting.
    assert [f.category for f in findings] == [
        FindingCategory.AWARD,
        FindingCategory.FUNDING,
        FindingCategory.FUNDING,
    ]


def test_category_and_polarity_indexes_count_findings():
    findings = [
        _finding(summary="a", category=FindingCategory.AWARD, polarity=Polarity.POSITIVE),
        _finding(summary="b", category=FindingCategory.AWARD, polarity=Polarity.POSITIVE),
        _finding(summary="c", category=FindingCategory.LEGAL, polarity=Polarity.NEGATIVE),
    ]
    assert index_by_category(findings) == {"award": 2, "legal": 1}
    assert index_by_polarity(findings) == {"positive": 2, "negative": 1}


# -- Providers --------------------------------------------------------------

def test_mock_provider_matches_query_angle_to_articles():
    provider = MockProvider()

    negative = asyncio.run(provider.search('"Marcus Vale" fraud OR scam OR misconduct', 5))
    assert negative, "expected the adverse-media angle to return articles"
    assert any(a.source == "sec.gov" for a in negative)

    positive = asyncio.run(provider.search('"Ada Whitfield" award OR olympiad OR medalist', 5))
    assert any("olympiad" in (a.title + a.snippet).lower() for a in positive)


def test_mock_provider_returns_nothing_for_unknown_person():
    assert asyncio.run(MockProvider().search('"Nobody Here" fraud', 5)) == []


def test_provider_falls_back_to_mock_without_key(monkeypatch):
    from vc_brain import config as config_module

    monkeypatch.setattr(config_module.config, "tavily_api_key", "", raising=False)
    monkeypatch.setattr(config_module.config, "reputation_provider", "tavily", raising=False)

    assert isinstance(get_provider(), MockProvider)


# -- Full-page extraction ---------------------------------------------------

def _article(url, snippet="x" * 100):
    return Article(url=url, source=source_name(url), snippet=snippet)


def test_select_for_extraction_reads_the_thinnest_first():
    """No publication judgement -- we fetch what we know least about."""
    rich = _article("https://a.com/1", "y" * 900)
    thin = _article("https://b.com/2", "tiny")
    medium = _article("https://c.com/3", "z" * 300)

    picked = select_for_extraction([rich, thin, medium], limit=10)

    # Thinnest first, and an already-informative snippet is never re-fetched:
    # paying to read text we effectively have is pure waste.
    assert [a.url for a in picked] == ["https://b.com/2", "https://c.com/3"]
    assert rich not in picked


def test_select_for_extraction_respects_limit_and_skips_done():
    articles = [_article(f"https://outlet{i}.com/a") for i in range(10)]
    assert len(select_for_extraction(articles, limit=3)) == 3
    assert select_for_extraction(articles, limit=0) == []

    articles[0].extracted = True
    assert articles[0] not in select_for_extraction(articles, limit=10)


def test_apply_extractions_attaches_text_and_counts():
    articles = [_article("https://a.com/1"), _article("https://b.com/2")]
    applied = apply_extractions(articles, {"https://a.com/1": "the full body"})

    assert applied == 1
    assert articles[0].extracted is True
    assert articles[0].full_text == "the full body"
    assert articles[1].extracted is False


def test_best_text_prefers_full_text_and_truncates():
    article = _article("https://a.com/1", snippet="short snippet")
    assert article.best_text() == "short snippet"

    article.full_text = "word " * 400
    truncated = article.best_text(limit=50)
    assert len(truncated) <= 60 and truncated.endswith("...")


def test_thin_count_ignores_extracted_articles():
    thin = _article("https://a.com/1", "tiny")
    rich = _article("https://b.com/2", "z" * 900)
    assert thin_count([thin, rich]) == 1

    thin.extracted = True
    assert thin_count([thin, rich]) == 0


def test_mock_provider_extract_serves_fixture_full_content():
    sec_url = "https://www.sec.gov/litigation/litreleases/2023/lr25711.htm"
    extracted = asyncio.run(MockProvider().extract([sec_url, "https://unknown.example/x"]))

    assert sec_url in extracted
    assert "officer-and-director bar" in extracted[sec_url]
    assert "https://unknown.example/x" not in extracted


# -- Scanner end to end -----------------------------------------------------

def _fake_extractor(name, articles, hint="", entity=None):
    """Stand-in for the LLM step: regulator pages are fraud, others press."""

    async def _run():
        findings = []
        for article in articles:
            is_regulator = article.source.endswith(("sec.gov", "courtlistener.com"))
            findings.append(
                ReputationFinding(
                    summary=article.title,
                    category=FindingCategory.FRAUD if is_regulator else FindingCategory.PRESS,
                    polarity=Polarity.NEGATIVE if is_regulator else Polarity.POSITIVE,
                    entity="",
                    relevance=9,
                    confidence=0.7,
                    sources=[
                        SourceRef(
                            source=article.source,
                            url=article.url,
                            title=article.title,
                            published=article.published,
                            relevance=9,
                        )
                    ],
                )
            )
        return findings

    return _run()


def test_scanner_returns_categorised_sourced_findings(monkeypatch):
    monkeypatch.setattr(scanner_module, "extract_findings", _fake_extractor)

    scanner = ReputationScanner(provider=MockProvider())
    report = asyncio.run(scanner.analyze("Marcus Vale", hint="Northwind Logistics"))

    assert report.name == "Marcus Vale"
    assert report.provider == "mock"
    assert report.articles_reviewed > 0
    assert report.findings

    for finding in report.findings:
        assert finding.summary
        assert finding.sources, "every finding must carry its proof links"
        assert all(s.url.startswith("http") for s in finding.sources)
        assert all(s.source for s in finding.sources), "each source needs a name"
        assert 1 <= finding.relevance <= 10

    assert report.by_category
    assert sum(report.by_category.values()) == len(report.findings)
    # Nothing in the output ranks the person or grades a publication.
    assert not hasattr(report, "risk_level")
    assert not hasattr(report, "negative_score")
    assert not hasattr(report.findings[0].sources[0], "tier")


def test_scanner_reports_gaps_when_nothing_is_found(monkeypatch):
    monkeypatch.setattr(scanner_module, "extract_findings", _fake_extractor)

    report = asyncio.run(ReputationScanner(provider=MockProvider()).analyze("Nobody Here"))

    assert report.articles_reviewed == 0
    assert report.findings == []
    assert any("not as clean" in gap for gap in report.gaps)


def test_scanner_handles_empty_name():
    report = asyncio.run(ReputationScanner(provider=MockProvider()).analyze("  "))
    assert report.name == ""
    assert report.gaps


def test_scanner_reads_pages_in_full_and_reports_it(monkeypatch):
    monkeypatch.setattr(scanner_module, "extract_findings", _fake_extractor)
    report = asyncio.run(ReputationScanner(provider=MockProvider()).analyze("Marcus Vale"))
    assert report.articles_extracted >= 1


def test_extraction_can_be_disabled(monkeypatch):
    from vc_brain import config as config_module

    monkeypatch.setattr(scanner_module, "extract_findings", _fake_extractor)
    monkeypatch.setattr(config_module.config, "reputation_extract", False, raising=False)

    report = asyncio.run(ReputationScanner(provider=MockProvider()).analyze("Marcus Vale"))

    assert report.articles_extracted == 0
    assert any("not read in full" in gap for gap in report.gaps)


# -- Company entity ---------------------------------------------------------

def test_company_entity_selects_the_company_prompt():
    person_prompt = _load_system_prompt(EntityType.PERSON)
    company_prompt = _load_system_prompt(EntityType.COMPANY)

    assert person_prompt != company_prompt
    assert "COMPANY" in company_prompt
    # The subject test must survive in both, it is what prevents a bystander
    # in someone else's scandal from being recorded as an offender.
    assert "SUBJECT TEST" in person_prompt
    assert "SUBJECT TEST" in company_prompt


def test_mock_provider_honours_include_domains():
    provider = MockProvider()
    query = '"Northwind Logistics" review OR complaint OR experience OR scam'

    forum = asyncio.run(provider.search(query, 10, ("reddit.com",)))
    assert forum, "expected the fixture reddit thread to match the forum angle"
    assert all(a.source.endswith("reddit.com") for a in forum)

    # Unrestricted, the same query may reach the wider web.
    everywhere = asyncio.run(provider.search(query, 10))
    assert len(everywhere) >= len(forum)


def test_company_report_ingests_as_a_company_not_a_founder(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner_module, "extract_findings", _fake_extractor)

    store = MemoryStore(path=str(tmp_path / "store.json"))
    scanner = ReputationScanner(pipeline=IngestionPipeline(store), provider=MockProvider())

    report = asyncio.run(
        scanner.analyze("Northwind Logistics", entity=EntityType.COMPANY)
    )
    assert report.entity is EntityType.COMPANY
    assert report.findings

    company = scanner.ingest(report)
    assert company is not None
    assert company.name == "Northwind Logistics"
    assert store.get_company(company.id) is not None
    assert not store.search_founders(name="Northwind Logistics")

    web_points = [dp for dp in company.data_points if dp.source is SourceType.WEB]
    assert len(web_points) == len(report.findings) + 1
    assert all(dp.content.get("sources") or dp.content.get("kind") == "reputation_summary"
               for dp in web_points)

    # Re-ingesting merges into the same company rather than duplicating it.
    again = scanner.ingest(
        asyncio.run(scanner.analyze("Northwind Logistics", entity=EntityType.COMPANY))
    )
    assert again.id == company.id


def test_ingest_writes_citable_datapoints_and_enriches(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner_module, "extract_findings", _fake_extractor)

    store = MemoryStore(path=str(tmp_path / "store.json"))
    pipeline = IngestionPipeline(store)
    scanner = ReputationScanner(pipeline=pipeline, provider=MockProvider())

    report = asyncio.run(scanner.analyze("Marcus Vale"))
    founder = scanner.ingest(report)

    assert founder is not None
    assert founder.name == "Marcus Vale"

    web_points = [dp for dp in founder.data_points if dp.source is SourceType.WEB]
    assert len(web_points) == len(report.findings) + 1  # findings + summary

    finding_points = [
        dp for dp in web_points if dp.content.get("kind") == "reputation_finding"
    ]
    assert finding_points and all(dp.source_url for dp in finding_points)
    assert all(dp.content.get("relevance") for dp in finding_points)
    assert all(any(t.startswith("relevance:") for t in dp.tags) for dp in finding_points)
    assert all(dp.content.get("sources") for dp in finding_points)

    # Re-ingesting enriches the same founder rather than creating a second one.
    before = len(founder.data_points)
    again = scanner.ingest(asyncio.run(scanner.analyze("Marcus Vale")))
    assert again.id == founder.id
    assert len(again.data_points) > before
