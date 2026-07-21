"""Reputation scanner: collect what the open web says about a person.

Sweeps a set of deliberately opposed query angles (the flattering and the
damaging), summarises what each article says, merges duplicates, and returns a
categorised list of findings with the proof links attached.

It does not score, rank or judge -- that is a downstream concern. What it
guarantees is coverage from both directions, a source for every statement, and
an explicit list of what it could not establish.

Same shape as the other sourcing scanners (`GitHubScanner`,
`HackerNewsScanner`): construct with an `IngestionPipeline`, await the gather
method, then `ingest()` the report.
"""

from __future__ import annotations

import asyncio

from vc_brain.config import config
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.models import Company, DataPoint, Founder, SourceType
from vc_brain.sourcing.reputation.aggregate import (
    index_by_category,
    index_by_polarity,
    merge_by_clusters,
)
from vc_brain.sourcing.reputation.analyzer import cluster_findings, extract_findings
from vc_brain.sourcing.reputation.enrichment import (
    apply_extractions,
    select_for_extraction,
    thin_count,
)
from vc_brain.sourcing.reputation.models import (
    Article,
    EntityType,
    ReputationFinding,
    ReputationReport,
)
from vc_brain.sourcing.reputation.providers import SearchProvider, get_provider
from vc_brain.sourcing.reputation.queries import (
    BACKGROUND,
    FORUM,
    NEGATIVE,
    POSITIVE,
    Query,
    build_queries,
)

_INTENT_LABELS = {
    POSITIVE: "positive-signal",
    NEGATIVE: "adverse-media",
    BACKGROUND: "background",
    FORUM: "forum/community",
}


class ReputationScanner:
    """Collect web coverage of a person as categorised, sourced findings."""

    def __init__(
        self,
        pipeline: IngestionPipeline | None = None,
        provider: SearchProvider | None = None,
    ):
        self.pipeline = pipeline
        self.provider = provider or get_provider()

    async def analyze(
        self,
        name: str,
        hint: str = "",
        entity: EntityType = EntityType.PERSON,
    ) -> ReputationReport:
        """Run the full sweep for one person or company. Never raises."""
        name = (name or "").strip()
        if not name:
            return ReputationReport(
                name="",
                entity=entity,
                gaps=["No name supplied."],
                provider=getattr(self.provider, "name", "unknown"),
            )

        queries = build_queries(name, hint, config.reputation_max_queries, entity)
        articles, per_intent = await self._sweep(queries)
        extracted = await self._enrich(articles)
        raw = await extract_findings(name, articles, hint, entity)
        # The model decides which findings are the same story; the merge is
        # mechanical. On failure clustering returns [], so every finding stands.
        clusters = await cluster_findings(name, raw, entity)
        findings = merge_by_clusters(raw, clusters)

        return ReputationReport(
            name=name,
            hint=hint,
            entity=entity,
            findings=findings,
            by_category=index_by_category(findings),
            by_polarity=index_by_polarity(findings),
            articles_reviewed=len(articles),
            articles_extracted=extracted,
            queries_run=[q.text for q in queries],
            sources=sorted({a.url for a in articles if a.url}),
            gaps=self._gaps(articles, findings, per_intent),
            provider=getattr(self.provider, "name", "unknown"),
        )

    async def _sweep(self, queries: list[Query]) -> tuple[list[Article], dict[str, int]]:
        """Run every query angle concurrently and de-duplicate by URL."""
        limit = max(1, config.reputation_results_per_query)
        results = await asyncio.gather(
            *(
                self.provider.search(q.text, limit, q.include_domains)
                for q in queries
            ),
            return_exceptions=True,
        )

        per_intent: dict[str, int] = {q.intent: 0 for q in queries}
        articles: list[Article] = []
        seen: set[str] = set()

        for query, result in zip(queries, results):
            if isinstance(result, BaseException) or not result:
                continue
            for article in result:
                article.intent = query.intent
                # Counted before de-duplication: the question here is whether
                # this angle found anything at all.
                per_intent[query.intent] = per_intent.get(query.intent, 0) + 1

                key = article.url or f"{article.title}|{article.source}"
                if key in seen:
                    continue
                seen.add(key)
                articles.append(article)

        return articles, per_intent

    async def _enrich(self, articles: list[Article]) -> int:
        """Read the highest-value pages in full, so thin snippets stop
        costing us findings. Degrades to snippets on any failure."""
        if not config.reputation_extract or not articles:
            return 0

        extractor = getattr(self.provider, "extract", None)
        if extractor is None:
            return 0  # provider does not support extraction

        targets = select_for_extraction(articles, config.reputation_extract_limit)
        if not targets:
            return 0

        try:
            extracted = await extractor([a.url for a in targets])
        except Exception:
            return 0

        return apply_extractions(articles, extracted)

    @staticmethod
    def _gaps(
        articles: list[Article],
        findings: list[ReputationFinding],
        per_intent: dict[str, int],
    ) -> list[str]:
        """State what we could NOT establish. Silence is not a clean record."""
        if not articles:
            return [
                "No web coverage found for this name -- treat as unverified, not as clean."
            ]

        gaps: list[str] = []
        for intent, count in sorted(per_intent.items()):
            if count == 0:
                label = _INTENT_LABELS.get(intent, intent)
                gaps.append(f"No results returned by the {label} queries.")

        if not findings:
            gaps.append("Articles were retrieved but none yielded a usable summary.")

        thin = thin_count(articles)
        if thin:
            gaps.append(
                f"{thin} article(s) were summarised from a short search snippet only, "
                "not read in full -- information inside them may have been missed."
            )

        return gaps

    # -- Memory -------------------------------------------------------------
    def ingest(self, report: ReputationReport) -> Founder | Company | None:
        """Write findings into Memory, one DataPoint per citable finding.

        A company report lands on a `Company`, a person report on a `Founder`.
        Both carry the identical DataPoint shape, so downstream reads them the
        same way regardless of which entity was researched.
        """
        if self.pipeline is None or not report.name:
            return None

        if report.entity is EntityType.COMPANY:
            # upsert_company already dedupes case-insensitively on name and
            # merges data points into the existing record.
            return self.pipeline.store.upsert_company(
                Company(name=report.name, data_points=self._to_data_points(report))
            )

        store = self.pipeline.store
        target = report.name.strip().lower()
        matches = [
            f for f in store.search_founders(name=report.name)
            if f.name.strip().lower() == target
        ]

        founder = matches[0] if matches else Founder(name=report.name)
        founder.data_points.extend(self._to_data_points(report))
        return store.upsert_founder(founder)

    @staticmethod
    def _to_data_points(report: ReputationReport) -> list[DataPoint]:
        points = [
            DataPoint(
                source=SourceType.WEB,
                content={
                    "kind": "reputation_summary",
                    "name": report.name,
                    "entity": report.entity.value,
                    "findings_count": len(report.findings),
                    "by_category": report.by_category,
                    "by_polarity": report.by_polarity,
                    "articles_reviewed": report.articles_reviewed,
                    "articles_extracted": report.articles_extracted,
                    "gaps": report.gaps,
                    "provider": report.provider,
                },
                confidence=0.5,
                tags=["reputation", "summary"],
            )
        ]

        for finding in report.findings:
            primary = finding.primary_source
            points.append(
                DataPoint(
                    source=SourceType.WEB,
                    source_url=primary.url if primary else "",
                    content={
                        "kind": "reputation_finding",
                        "summary": finding.summary,
                        "category": finding.category.value,
                        "polarity": finding.polarity.value,
                        "entity": finding.entity,
                        "relevance": finding.relevance,
                        "source_count": finding.source_count,
                        "sources": [s.model_dump(mode="json") for s in finding.sources],
                    },
                    confidence=finding.confidence,
                    tags=[
                        "reputation",
                        finding.polarity.value,
                        finding.category.value,
                        f"relevance:{finding.relevance}",
                    ],
                )
            )

        return points
