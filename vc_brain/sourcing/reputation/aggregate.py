"""Merge findings that describe the same thing, and index the result.

No weighting happens here. This stage only removes duplication and attaches
every supporting article to the finding it belongs to. Corroboration is left
as a raw count of distinct sources -- deciding what that is worth is a
downstream concern, deliberately not ours.

Pure functions, no I/O, no LLM: same input, same output.
"""

from __future__ import annotations

import re

from vc_brain.sourcing.reputation.models import (
    ReputationFinding,
    SourceRef,
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with",
    "his", "her", "their", "was", "were", "is", "are", "be", "been", "by",
    "that", "this", "it", "as", "from", "after", "over", "into", "has", "had",
}


# Two summaries in the same category and about the same entity are treated as
# the same story when this much of the smaller one is contained in the larger.
# Overlap (rather than Jaccard) is used deliberately: outlets routinely report
# the same fact at very different lengths, and a detailed write-up should still
# absorb the one-line version of itself.
MERGE_THRESHOLD = 0.55

_SUFFIXES = ("ing", "ed", "er", "s")


def _normalize(text: str) -> str:
    return " ".join(_WORD_RE.findall((text or "").lower()))


def _stem(token: str) -> str:
    """Crude suffix trim so 'founded', 'founder' and 'founding' agree."""
    for suffix in _SUFFIXES:
        if len(token) > 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _tokens(summary: str) -> frozenset[str]:
    """Content words of a summary, stemmed, for similarity comparison."""
    return frozenset(
        _stem(t) for t in _normalize(summary).split() if t not in _STOPWORDS
    )


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Overlap coefficient: |A n B| / min(|A|, |B|)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _group_key(finding: ReputationFinding) -> tuple[str, str]:
    """Only findings of the same kind, about the same entity, may merge."""
    return (finding.category.value, _normalize(finding.entity))


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


def _absorb(
    winner: ReputationFinding, other: ReputationFinding
) -> ReputationFinding:
    """Fold `other` into `winner`, keeping the strongest wording."""
    combined = list(winner.sources) + list(other.sources)

    kept = other.model_copy(deep=True) if _rank(other) > _rank(winner) else winner

    kept.sources = combined
    kept.relevance = max(winner.relevance, other.relevance)
    kept.confidence = max(winner.confidence, other.confidence)
    return kept


def merge_findings(findings: list[ReputationFinding]) -> list[ReputationFinding]:
    """Collapse findings about the same thing into one, keeping every source.

    Outlets rarely phrase a story identically, so matching is by similarity
    rather than exact wording -- "founded Theranos in 2003" and "was the
    founder and CEO of Theranos from 2003" are one finding with two sources,
    not two findings.
    """
    groups: dict[tuple[str, str], list[ReputationFinding]] = {}
    for finding in findings:
        groups.setdefault(_group_key(finding), []).append(finding)

    merged: list[ReputationFinding] = []
    for group in groups.values():
        # Each cluster is (tokens of the representative summary, the finding).
        clusters: list[tuple[frozenset[str], ReputationFinding]] = []

        for finding in group:
            tokens = _tokens(finding.summary)
            target = next(
                (
                    i
                    for i, (cluster_tokens, _) in enumerate(clusters)
                    if _overlap(tokens, cluster_tokens) >= MERGE_THRESHOLD
                ),
                None,
            )

            if target is None:
                clusters.append((tokens, finding.model_copy(deep=True)))
                continue

            _, existing = clusters[target]
            kept = _absorb(existing, finding)
            # Track the representative's own tokens, so the cluster does not
            # drift wider with every absorption.
            clusters[target] = (_tokens(kept.summary), kept)

        for _, finding in clusters:
            finding.sources = dedupe_sources(finding.sources)
            if finding.sources:
                finding.relevance = max(s.relevance for s in finding.sources)
            merged.append(finding)

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
