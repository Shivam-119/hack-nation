from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Rating = Literal["bullish", "neutral", "bear"]
Trend = Literal["improving", "declining", "stable"]
Confidence = Literal["high", "medium", "low"]


class KeyEvidencePoint(BaseModel):
    point: str
    source: str


class FounderAxisScore(BaseModel):
    axis: Literal["founder"] = "founder"
    rating: Rating
    fit_score_pct: int = Field(ge=0, le=100, description="How good a fit this founder is, 0-100, consistent with `rating`")
    trend: Trend
    rationale: str
    key_evidence: list[KeyEvidencePoint] = Field(default_factory=list)
    cold_start: bool
    confidence: Confidence
    confidence_pct: int = Field(ge=0, le=100, description="Numeric confidence, 0-100, consistent with `confidence`")
    thesis_notes: str | None = None


class MarketAxisScore(BaseModel):
    axis: Literal["market"] = "market"
    rating: Rating
    fit_score_pct: int = Field(ge=0, le=100, description="How good a fit this market is, 0-100, consistent with `rating`")
    trend: Trend
    rationale: str
    key_evidence: list[KeyEvidencePoint] = Field(default_factory=list)
    confidence: Confidence
    confidence_pct: int = Field(ge=0, le=100, description="Numeric confidence, 0-100, consistent with `confidence`")
    thesis_notes: str | None = None


class IdeaVsMarketScore(BaseModel):
    axis: Literal["idea_vs_market"] = "idea_vs_market"
    rating: Rating
    fit_score_pct: int = Field(ge=0, le=100, description="How good this idea-vs-market fit is, 0-100, consistent with `rating`")
    trend: Trend
    verdict: Literal["idea_survives_as_is", "team_strong_enough_to_pivot", "neither"]
    rationale: str
    confidence: Confidence
    confidence_pct: int = Field(ge=0, le=100, description="Numeric confidence, 0-100, consistent with `confidence`")


class ThesisFitResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class DecisionDraft(BaseModel):
    recommendation: Literal["invest", "pass", "more_diligence_needed"]
    check_size_recommended_usd: float | None = None
    rationale: str
    gaps_and_caveats: list[str] = Field(default_factory=list)


class AdversarialOutput(BaseModel):
    counter_argument: str
    counter_argument_severity: Literal["minor", "moderate", "serious"]
    targets_axis: Literal["founder", "market", "idea_vs_market", "thesis_fit"]


class FinalDecision(BaseModel):
    application_id: str
    founder_axis: dict
    market_axis: dict
    idea_vs_market_axis: dict
    thesis_fit: dict
    recommendation: Literal["invest", "pass", "more_diligence_needed"]
    check_size_recommended_usd: float | None = None
    rationale: str
    adversarial_view: str
    gaps_and_caveats: list[str] = Field(default_factory=list)
