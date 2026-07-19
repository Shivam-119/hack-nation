"""Track sourcing channel effectiveness — which channels produce the best founder candidates.

Aggregates founder scores by their source channel (GitHub, HN, Product Hunt, arXiv, etc.)
and surfaces which channels deliver the highest-quality pipeline.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from vc_brain.memory.models import Founder, SourceType


@dataclass
class ChannelStats:
    source: str
    founder_count: int = 0
    avg_score: float = 0.0
    top_score: float = 0.0
    scored_count: int = 0  # founders with score > 0
    founder_ids: list[str] = field(default_factory=list)


def compute_channel_stats(founders: list[Founder]) -> list[ChannelStats]:
    """Compute per-source statistics from the founder pool.

    For each founder, the primary source is taken from their oldest data point
    (first ingest = how we found them). Score is the founder's overall score.
    """
    buckets: dict[str, list[Founder]] = defaultdict(list)

    for founder in founders:
        if not founder.data_points:
            buckets["unknown"].append(founder)
            continue
        # Oldest data point = discovery source
        primary_dp = sorted(founder.data_points, key=lambda dp: dp.extracted_at)[0]
        buckets[primary_dp.source.value].append(founder)

    stats: list[ChannelStats] = []
    for source, channel_founders in buckets.items():
        scores = [f.score.overall for f in channel_founders if f.score.overall > 0]
        stats.append(ChannelStats(
            source=source,
            founder_count=len(channel_founders),
            avg_score=round(sum(scores) / len(scores), 1) if scores else 0.0,
            top_score=round(max(scores), 1) if scores else 0.0,
            scored_count=len(scores),
            founder_ids=[f.id for f in channel_founders],
        ))

    # Sort by average score descending, then count as tiebreaker
    stats.sort(key=lambda s: (s.avg_score, s.founder_count), reverse=True)
    return stats


def channel_stats_to_dict(stats: list[ChannelStats]) -> list[dict[str, Any]]:
    return [
        {
            "source": s.source,
            "founder_count": s.founder_count,
            "scored_count": s.scored_count,
            "avg_score": s.avg_score,
            "top_score": s.top_score,
        }
        for s in stats
    ]
