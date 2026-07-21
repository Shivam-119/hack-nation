"""Merge findings that describe the same thing, and index the result.

*Which* findings describe the same underlying story is decided by the model
(see `analyzer.cluster_findings`) -- outlets phrase the same event a dozen
different ways, and string similarity cannot reliably tell "same story" from
"same topic". This module only does the mechanical merge once the model has
grouped them: combine the sources, keep the best-worded version. No weighting
happens here; corroboration is left as a raw count of distinct sources.
"""

from __future__ import annotations

from vc_brain.sourcing.reputation.models import ReputationFinding, SourceRef


def _rank(finding: ReputationFinding) -> tuple[int, float, int]:
    """How good a *version of the wording* this is -- not a judgement of the
    person or the publication. Prefers the most on-point, best-supported and
    most detailed phrasing when the same story arrives several times."""
    return (finding.relevance, finding.confidence, len(finding.summary))


def dedupe_sources(sources: list[SourceRef]) -> list[SourceRef]:
    """One entry per URL, most on-point first."""
    seen: dict[str, SourceRef] = {}
    for source in sources:
        key = source.url or f"{source.source}|{source.title}"
        if not key:
            continue
        current = seen.get(key)
        if current is None or source.relevance > current.relevance:
            seen[key] = source

    return sorted(seen.values(), key=lambda s: (-s.relevance, s.source))


def _absorb(winner: ReputationFinding, other: ReputationFinding) -> ReputationFinding:
    """Fold `other` into `winner`, keeping the strongest wording."""
    combined = list(winner.sources) + list(other.sources)
    kept = other.model_copy(deep=True) if _rank(other) > _rank(winner) else winner
    kept.sources = combined
    kept.relevance = max(winner.relevance, other.relevance)
    kept.confidence = max(winner.confidence, other.confidence)
    return kept


def merge_by_clusters(
    findings: list[ReputationFinding], clusters: list[list[int]]
) -> list[ReputationFinding]:
    """Merge findings grouped by the model into one finding per group.

    `clusters` are index groups from `analyzer.cluster_findings`. A finding
    named in no group stands on its own, and out-of-range or already-used
    indices are ignored -- so a malformed cluster list can only fail to merge,
    never drop or duplicate a finding.
    """
    n = len(findings)
    assigned: set[int] = set()
    groups: list[list[int]] = []

    for cluster in clusters:
        idxs = [i for i in cluster if isinstance(i, int) and 0 <= i < n and i not in assigned]
        if idxs:
            assigned.update(idxs)
            groups.append(idxs)
    # Every finding the model didn't cluster stands alone.
    groups.extend([i] for i in range(n) if i not in assigned)

    merged: list[ReputationFinding] = []
    for idxs in groups:
        kept = findings[idxs[0]].model_copy(deep=True)
        for j in idxs[1:]:
            kept = _absorb(kept, findings[j])
        kept.sources = dedupe_sources(kept.sources)
        if kept.sources:
            kept.relevance = max(s.relevance for s in kept.sources)
        merged.append(kept)

    return sort_findings(merged)


def sort_findings(findings: list[ReputationFinding]) -> list[ReputationFinding]:
    """Deterministic index order: grouped by category, most relevant first.

    This is an ordering for readability, not a ranking of importance.
    """
    return sorted(
        findings,
        key=lambda f: (f.category.value, -f.relevance, -f.source_count, f.summary),
    )


def index_by_category(findings: list[ReputationFinding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.category.value] = counts.get(finding.category.value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def index_by_polarity(findings: list[ReputationFinding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.polarity.value] = counts.get(finding.polarity.value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
