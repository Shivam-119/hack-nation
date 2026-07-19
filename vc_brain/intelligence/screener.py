"""Multi-Axis Screening: every opportunity scored along three independent axes.

Axes (NOT averaged):
1. Founder: who they are, traits, track record
2. Market: sizing, competitors, SWOT -- rated bullish/neutral/bear
3. Idea vs. Market: does the idea survive scrutiny, or is the team strong enough to pivot?

Each axis also shows trend (improving/declining/stable).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from vc_brain.llm import complete_json
from vc_brain.memory.models import Application, Company, Founder, Trend


class MarketSentiment(str, Enum):
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEAR = "bear"


class AxisScore(BaseModel):
    score: float = 0.0  # 0-100
    sentiment: str = "neutral"
    trend: Trend = Trend.STABLE
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    strengths: list[dict[str, str]] = Field(default_factory=list)
    weaknesses: list[dict[str, str]] = Field(default_factory=list)
    opportunities: list[dict[str, str]] = Field(default_factory=list)
    threats: list[dict[str, str]] = Field(default_factory=list)


class ScreeningResult(BaseModel):
    """Three independent axes -- never averaged into one number."""
    founder_axis: AxisScore = Field(default_factory=AxisScore)
    market_axis: AxisScore = Field(default_factory=AxisScore)
    idea_vs_market_axis: AxisScore = Field(default_factory=AxisScore)
    passes_screen: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)


class Screener:
    """Run the 3-axis screening on an application."""

    SYSTEM = (
        "You are an expert VC analyst. Score each axis independently on 0-100. "
        "Be transparent about confidence and evidence gaps. "
        "Return valid JSON only."
    )

    async def screen(
        self,
        application: Application,
        company: Company,
        founders: list[Founder],
        thesis_context: str = "",
    ) -> ScreeningResult:
        """Run multi-axis screening. Uses LLM for market and idea analysis."""

        # Founder axis: computed from Founder Score + data points
        founder_axis = self._score_founder_axis(founders)

        # Market and Idea axes: LLM-assisted
        market_axis, idea_axis = await self._llm_screen(application, company, founders, thesis_context)

        # Pass/fail: all axes must be above threshold
        passes = (
            founder_axis.score >= 25
            and market_axis.score >= 25
            and idea_axis.score >= 20
        )

        reasons = []
        if founder_axis.score < 25:
            reasons.append(f"Founder axis too low ({founder_axis.score})")
        if market_axis.score < 25:
            reasons.append(f"Market axis too low ({market_axis.score})")
        if idea_axis.score < 20:
            reasons.append(f"Idea vs Market axis too low ({idea_axis.score})")

        return ScreeningResult(
            founder_axis=founder_axis,
            market_axis=market_axis,
            idea_vs_market_axis=idea_axis,
            passes_screen=passes,
            rejection_reasons=reasons,
        )

    def _score_founder_axis(self, founders: list[Founder]) -> AxisScore:
        if not founders:
            return AxisScore(
                score=10, sentiment="bear",
                evidence=["No founder information available — cold-start case"],
                confidence=0.2,
            )

        best = max(founders, key=lambda f: f.score.overall)
        evidence = [
            f"Best founder score: {best.score.overall}/100",
            f"Technical: {best.score.technical}, Execution: {best.score.execution}",
            f"Skills: {', '.join(best.skills[:5]) or 'None listed'}",
        ]
        if best.score.overall >= 60:
            sentiment = "bullish"
        elif best.score.overall >= 30:
            sentiment = "neutral"
        else:
            sentiment = "bear"

        return AxisScore(
            score=best.score.overall,
            sentiment=sentiment,
            trend=best.score.trend,
            evidence=evidence,
            confidence=min(0.3 + len(best.data_points) * 0.1, 0.95),
            strengths=[{"text": item} for item in evidence[:2]],
        )

    async def _llm_screen(
        self,
        app: Application,
        company: Company,
        founders: list[Founder],
        thesis_context: str,
    ) -> tuple[AxisScore, AxisScore]:
        prompt = (
            f"Analyze this startup for investment screening.\n\n"
            f"Company: {company.name}\n"
            f"Sector: {company.sector}\n"
            f"Stage: {company.stage}\n"
            f"Geography: {company.geography}\n"
            f"Description: {company.description}\n"
            f"Deck excerpt: {app.deck_text[:2000]}\n"
            f"Fund thesis context: {thesis_context}\n\n"
            f"Return JSON with exactly these keys:\n"
            f'{{"market_score": 0-100, "market_sentiment": "bullish|neutral|bear", '
            f'"market_evidence": ["..."], '
            f'"idea_score": 0-100, "idea_sentiment": "bullish|neutral|bear", '
            f'"idea_evidence": ["..."]}}'
        )

        try:
            result = await complete_json(prompt, system=self.SYSTEM)
            market_axis = AxisScore(
                score=float(result.get("market_score", 50)),
                sentiment=result.get("market_sentiment", "neutral"),
                evidence=result.get("market_evidence", []),
                confidence=0.5,
                strengths=[{"text": item} for item in result.get("market_evidence", [])],
            )
            idea_axis = AxisScore(
                score=float(result.get("idea_score", 50)),
                sentiment=result.get("idea_sentiment", "neutral"),
                evidence=result.get("idea_evidence", []),
                confidence=0.5,
                strengths=[{"text": item} for item in result.get("idea_evidence", [])],
            )
        except Exception:
            # Fallback if LLM fails
            market_axis = AxisScore(score=50, sentiment="neutral",
                                     evidence=["LLM analysis unavailable"], confidence=0.2)
            idea_axis = AxisScore(score=50, sentiment="neutral",
                                    evidence=["LLM analysis unavailable"], confidence=0.2)

        return market_axis, idea_axis
