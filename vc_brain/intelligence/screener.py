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

from prompts import load_system
from vc_brain.intelligence.cold_start import ColdStartReport, detect_cold_start, cold_start_founder_score
from vc_brain.intelligence.thesis_engine import FundThesis
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


class ScreeningResult(BaseModel):
    """Three independent axes -- never averaged into one number."""
    founder_axis: AxisScore = Field(default_factory=AxisScore)
    market_axis: AxisScore = Field(default_factory=AxisScore)
    idea_vs_market_axis: AxisScore = Field(default_factory=AxisScore)
    passes_screen: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)
    cold_start: bool = False
    cold_start_data_requests: list[str] = Field(default_factory=list)


class Screener:
    """Run the 3-axis screening on an application."""

    SYSTEM = load_system("screener")

    async def screen(
        self,
        application: Application,
        company: Company,
        founders: list[Founder],
        thesis_context: str = "",
        thesis: FundThesis | None = None,
    ) -> ScreeningResult:
        """Run multi-axis screening. Uses LLM for market and idea analysis.

        When a FundThesis is provided its constraints are applied to scoring:
        - min_founder_score enforced as a hard floor on the founder axis
        - preferred_signals boost founder scores; anti_signals are rejection flags
        - Thesis alignment is surfaced in rejection_reasons

        Cold-start founders (zero/minimal history) get an explicit data-request path
        rather than an automatic rejection.
        """
        # Detect cold-start before scoring so we can adjust the path
        cold = detect_cold_start(founders, application, company)

        # Founder axis: computed from Founder Score + data points
        founder_axis = self._score_founder_axis(founders, thesis, cold)

        # Market and Idea axes: LLM-assisted
        thesis_prompt = self._build_thesis_context(thesis) if thesis else thesis_context
        market_axis, idea_axis = await self._llm_screen(application, company, founders, thesis_prompt)

        # Pass/fail: enforce thesis min_founder_score if thesis provided
        min_founder = thesis.min_founder_score if thesis else 25.0
        passes = (
            founder_axis.score >= min_founder
            and market_axis.score >= 25
            and idea_axis.score >= 20
        )

        reasons = []
        if founder_axis.score < min_founder:
            reasons.append(
                f"Founder axis {founder_axis.score} below "
                f"{'thesis minimum' if thesis else 'threshold'} ({min_founder})"
            )
        if market_axis.score < 25:
            reasons.append(f"Market axis too low ({market_axis.score})")
        if idea_axis.score < 20:
            reasons.append(f"Idea vs Market axis too low ({idea_axis.score})")

        # Thesis anti-signal rejection
        if thesis:
            for anti in thesis.anti_signals:
                founder_text = " ".join(
                    f.bio + " ".join(f.skills) for f in founders
                ).lower()
                company_text = (company.description + company.sector).lower()
                if anti.lower() in founder_text or anti.lower() in company_text:
                    reasons.append(f"Anti-signal detected: '{anti}'")
                    passes = False

        # Cold-start: defer decision rather than reject when data is absent
        if cold.is_cold_start and passes is False and not reasons:
            reasons.append("Insufficient founder data — data requests emitted")

        return ScreeningResult(
            founder_axis=founder_axis,
            market_axis=market_axis,
            idea_vs_market_axis=idea_axis,
            passes_screen=passes,
            rejection_reasons=reasons,
            cold_start=cold.is_cold_start,
            cold_start_data_requests=cold.data_requests,
        )

    def _build_thesis_context(self, thesis: FundThesis) -> str:
        """Convert structured thesis into a context string for LLM prompts."""
        parts = [
            f"Fund: {thesis.name}",
            f"Target sectors: {', '.join(thesis.sectors)}",
            f"Target stages: {', '.join(thesis.stages)}",
            f"Target geographies: {', '.join(thesis.geographies)}",
            f"Check size: ${thesis.check_size_min:,}–${thesis.check_size_max:,}",
            f"Risk appetite: {thesis.risk_appetite}",
        ]
        if thesis.preferred_signals:
            parts.append(f"Preferred signals: {', '.join(thesis.preferred_signals)}")
        if thesis.anti_signals:
            parts.append(f"Anti-signals (auto-reject if found): {', '.join(thesis.anti_signals)}")
        return "\n".join(parts)

    def _score_founder_axis(
        self,
        founders: list[Founder],
        thesis: FundThesis | None = None,
        cold: ColdStartReport | None = None,
    ) -> AxisScore:
        if not founders:
            return AxisScore(
                score=cold.score_floor if cold else 10.0,
                sentiment="neutral" if cold and cold.is_cold_start else "bear",
                evidence=["No founder information — data requests emitted" if cold else "No founder information"],
                confidence=cold.confidence if cold else 0.2,
            )

        best = max(founders, key=lambda f: f.score.overall)
        # Use cold-start adjusted score to avoid penalizing absent data
        score = cold_start_founder_score(best) if (cold and cold.is_cold_start) else best.score.overall
        evidence = [
            f"Best founder score: {score}/100",
            f"Technical: {best.score.technical}, Execution: {best.score.execution}",
            f"Skills: {', '.join(best.skills[:5]) or 'None listed'}",
        ]

        # Apply thesis preferred/anti signals if provided
        if thesis:
            founder_text = (best.bio + " ".join(best.skills)).lower()
            for sig in thesis.preferred_signals:
                if sig.lower() in founder_text:
                    score = min(100, score + 5)
                    evidence.append(f"Preferred signal matched: '{sig}'")
            for sig in thesis.anti_signals:
                if sig.lower() in founder_text:
                    score = max(0, score - 10)
                    evidence.append(f"Anti-signal in founder profile: '{sig}'")

        if score >= 60:
            sentiment = "bullish"
        elif score >= 30:
            sentiment = "neutral"
        else:
            sentiment = "bear"

        return AxisScore(
            score=round(score, 1),
            sentiment=sentiment,
            trend=best.score.trend,
            evidence=evidence,
            confidence=min(0.3 + len(best.data_points) * 0.1, 0.95),
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
            )
            idea_axis = AxisScore(
                score=float(result.get("idea_score", 50)),
                sentiment=result.get("idea_sentiment", "neutral"),
                evidence=result.get("idea_evidence", []),
                confidence=0.5,
            )
        except Exception:
            # Fallback if LLM fails
            market_axis = AxisScore(score=50, sentiment="neutral",
                                     evidence=["LLM analysis unavailable"], confidence=0.2)
            idea_axis = AxisScore(score=50, sentiment="neutral",
                                    evidence=["LLM analysis unavailable"], confidence=0.2)

        return market_axis, idea_axis
