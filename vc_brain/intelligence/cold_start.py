"""Cold-start founder handling — explicit path for zero-history applicants.

A cold-start founder has minimal verifiable data (no GitHub, no LinkedIn, new profile).
Rather than auto-rejecting them with low scores, the system:
- Detects the cold-start condition
- Does not penalize for missing data — only for confirmed negatives
- Emits a data-request list of what would move confidence to 0.6+
- Returns passes_screen=None to indicate deferred decision, not a rejection
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from vc_brain.memory.models import Application, Company, Founder

# How many data points a founder needs to NOT be cold-start
_MIN_DATA_POINTS = 2
# Minimum score for cold-start path — we don't penalize below this floor
_COLD_START_SCORE_FLOOR = 30.0


class ColdStartReport(BaseModel):
    is_cold_start: bool
    reasons: list[str] = Field(default_factory=list)
    data_requests: list[str] = Field(default_factory=list)
    confidence: float = 0.2
    score_floor: float = _COLD_START_SCORE_FLOOR


def detect_cold_start(
    founders: list[Founder], application: Application, company: Company
) -> ColdStartReport:
    """Determine if this is a cold-start case and what data would help.

    Cold-start = not enough external signals to make an evidence-backed assessment.
    This is NOT a rejection — it is a request for more data.
    """
    if not founders:
        return ColdStartReport(
            is_cold_start=True,
            reasons=["No founder information provided"],
            data_requests=[
                "Founder full name and email",
                "LinkedIn profile URL",
                "GitHub username",
                "Brief bio (50–200 words)",
                "Previous companies or projects",
            ],
            confidence=0.1,
        )

    reasons: list[str] = []
    data_requests: list[str] = []

    # Check each founder for data richness
    all_have_enough = all(
        len(f.data_points) >= _MIN_DATA_POINTS for f in founders
    )

    for founder in founders:
        if not founder.github_url:
            data_requests.append(f"GitHub profile for {founder.name or 'founder'}")
        if not founder.linkedin_url:
            data_requests.append(f"LinkedIn profile for {founder.name or 'founder'}")
        if not founder.bio or len(founder.bio) < 30:
            data_requests.append(f"Bio/background for {founder.name or 'founder'}")
        if not founder.skills:
            data_requests.append(f"Skills / technical background for {founder.name or 'founder'}")
        if not founder.work_history:
            data_requests.append(f"Work history for {founder.name or 'founder'}")

        if founder.score.overall == 0.0:
            reasons.append(f"{founder.name}: no computed score yet")
        if len(founder.data_points) < _MIN_DATA_POINTS:
            reasons.append(
                f"{founder.name}: only {len(founder.data_points)} data point(s) — insufficient evidence"
            )

    # Company-level checks
    if not company.description or len(company.description) < 20:
        reasons.append("Company description missing or too brief")
        data_requests.append("Company description (what you do and for whom, 1–3 sentences)")
    if not company.sector:
        data_requests.append("Target sector / market")
    if not application.deck_text:
        data_requests.append("Pitch deck or executive summary (PDF)")

    is_cold = bool(reasons) or not all_have_enough
    confidence = 0.1 if is_cold else 0.5

    # De-duplicate requests
    data_requests = list(dict.fromkeys(data_requests))

    return ColdStartReport(
        is_cold_start=is_cold,
        reasons=reasons,
        data_requests=data_requests,
        confidence=confidence,
    )


def cold_start_founder_score(founder: Founder) -> float:
    """Return a score for a cold-start founder that doesn't punish missing data.

    We apply the score floor so the founder isn't immediately below any
    minimum threshold purely because of absent data rather than confirmed problems.
    """
    raw = founder.score.overall
    if raw == 0.0 and not founder.data_points:
        # Truly zero-data: use the floor
        return _COLD_START_SCORE_FLOOR
    # Otherwise use the actual score but no lower than floor when data is sparse
    if len(founder.data_points) < _MIN_DATA_POINTS and raw < _COLD_START_SCORE_FLOOR:
        return _COLD_START_SCORE_FLOOR
    return raw
