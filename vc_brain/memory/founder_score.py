"""Compute and update the persistent Founder Score.

The Founder Score lives in Memory, persists across applications, and never resets.
It follows the person across different startups over time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from vc_brain.memory.models import DataPoint, Founder, FounderScore, SourceType, Trend


def compute_founder_score(founder: Founder) -> FounderScore:
    """Produce a FounderScore from all available data points on a founder.

    Scoring dimensions (0-100 each):
    - technical: GitHub activity, patents, papers, technical skills
    - execution: shipping history, product launches, hackathon wins
    - leadership: team-building, prior founding experience, work seniority
    - domain_expertise: sector depth, years in field, publications
    """
    signals = _extract_signals(founder)

    technical = _score_technical(signals)
    execution = _score_execution(signals)
    leadership = _score_leadership(signals)
    domain_expertise = _score_domain(signals)

    overall = (
        technical * 0.30
        + execution * 0.30
        + leadership * 0.20
        + domain_expertise * 0.20
    )

    # Determine trend from history
    prev = founder.score.overall if founder.score else 0
    if overall > prev + 5:
        trend = Trend.IMPROVING
    elif overall < prev - 5:
        trend = Trend.DECLINING
    else:
        trend = Trend.STABLE

    history = list(founder.score.history) if founder.score else []
    history.append({
        "timestamp": datetime.utcnow().isoformat(),
        "overall": round(overall, 1),
        "technical": round(technical, 1),
        "execution": round(execution, 1),
    })

    return FounderScore(
        overall=round(overall, 1),
        technical=round(technical, 1),
        execution=round(execution, 1),
        leadership=round(leadership, 1),
        domain_expertise=round(domain_expertise, 1),
        trend=trend,
        history=history,
    )


# ---------------------------------------------------------------------------
# Signal extraction from data points
# ---------------------------------------------------------------------------

def _extract_signals(founder: Founder) -> dict[str, Any]:
    """Flatten data points into a signal dict for scoring."""
    signals: dict[str, Any] = {
        "github_repos": 0,
        "github_stars": 0,
        "github_contributions": 0,
        "papers_count": 0,
        "patents_count": 0,
        "product_launches": 0,
        "hackathon_wins": 0,
        "prior_startups": 0,
        "years_experience": 0,
        "has_technical_degree": False,
        "top_tier_education": False,
        "accelerator_alumni": False,
        "skills_count": len(founder.skills),
    }

    for dp in founder.data_points:
        c = dp.content
        if dp.source == SourceType.GITHUB:
            signals["github_repos"] += c.get("public_repos", 0)
            signals["github_stars"] += c.get("total_stars", 0)
            signals["github_contributions"] += c.get("contributions", 0)
        elif dp.source == SourceType.ARXIV:
            signals["papers_count"] += c.get("paper_count", 1)
        elif dp.source == SourceType.PRODUCT_HUNT:
            signals["product_launches"] += c.get("launches", 1)
        elif dp.source == SourceType.ACCELERATOR:
            signals["accelerator_alumni"] = True
        elif dp.source == SourceType.LINKEDIN:
            signals["years_experience"] += c.get("years_experience", 0)
            signals["prior_startups"] += c.get("startups_founded", 0)

    for edu in founder.education:
        inst = edu.get("institution", "").lower()
        if any(t in inst for t in ("mit", "stanford", "harvard", "cambridge", "oxford", "eth")):
            signals["top_tier_education"] = True
        degree = edu.get("degree", "").lower()
        if any(d in degree for d in ("cs", "computer", "engineering", "math", "physics")):
            signals["has_technical_degree"] = True

    return signals


def _score_technical(s: dict) -> float:
    score = 0.0
    score += min(s["github_repos"] * 2, 25)
    score += min(s["github_stars"] * 0.5, 25)
    score += min(s["papers_count"] * 8, 20)
    score += 15 if s["has_technical_degree"] else 0
    score += min(s["skills_count"] * 2, 15)
    return min(score, 100)


def _score_execution(s: dict) -> float:
    score = 0.0
    score += min(s["product_launches"] * 15, 30)
    score += min(s["hackathon_wins"] * 10, 20)
    score += min(s["github_contributions"] * 0.02, 20)
    score += min(s["prior_startups"] * 15, 30)
    return min(score, 100)


def _score_leadership(s: dict) -> float:
    score = 0.0
    score += min(s["prior_startups"] * 20, 40)
    score += min(s["years_experience"] * 5, 30)
    score += 15 if s["top_tier_education"] else 0
    score += 15 if s["accelerator_alumni"] else 0
    return min(score, 100)


def _score_domain(s: dict) -> float:
    score = 0.0
    score += min(s["years_experience"] * 8, 40)
    score += min(s["papers_count"] * 10, 30)
    score += min(s["patents_count"] * 15, 30)
    return min(score, 100)
