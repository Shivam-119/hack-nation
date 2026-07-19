"""Reputation scanner -- web-article background check on a person.

Given a name, sweeps the open web from opposed angles (flattering and
damaging), summarises what each article says, merges duplicates, and returns a
categorised list of findings with the proof links attached.

It collects evidence; it does not score or rank. Every finding carries a
category, a polarity label, a relevance tag (how much the article is actually
about this person) and every source supporting it.

    scanner = ReputationScanner(pipeline)
    report = await scanner.analyze("Ada Whitfield", hint="Rivulet")
    for finding in report.findings:
        print(finding.category, finding.relevance, finding.summary)
        for source in finding.sources:
            print("   ", source.url)
    scanner.ingest(report)
"""

from vc_brain.sourcing.reputation.aggregate import (
    index_by_category,
    index_by_polarity,
    merge_findings,
)
from vc_brain.sourcing.reputation.models import (
    RELEVANCE_DEFAULT,
    RELEVANCE_DIRECT,
    RELEVANCE_INCIDENTAL,
    Article,
    EntityType,
    FindingCategory,
    Polarity,
    ReputationFinding,
    ReputationReport,
    SourceRef,
)
from vc_brain.sourcing.reputation.providers import get_provider
from vc_brain.sourcing.reputation.scanner import ReputationScanner

__all__ = [
    "RELEVANCE_DEFAULT",
    "RELEVANCE_DIRECT",
    "RELEVANCE_INCIDENTAL",
    "Article",
    "EntityType",
    "FindingCategory",
    "Polarity",
    "ReputationFinding",
    "ReputationReport",
    "ReputationScanner",
    "SourceRef",
    "get_provider",
    "index_by_category",
    "index_by_polarity",
    "merge_findings",
]
