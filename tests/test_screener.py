"""Tests for Screener — founder axis scoring, thesis context, pass/fail logic."""

from __future__ import annotations

import pytest

from vc_brain.intelligence.screener import AxisScore, Screener, ScreeningResult
from vc_brain.intelligence.thesis_engine import FundThesis
from vc_brain.memory.models import Application, Company, DataPoint, Founder, FounderScore, SourceType, Trend


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_founder(
    score: float = 60.0,
    bio: str = "",
    skills: list[str] | None = None,
    data_points: int = 2,
) -> Founder:
    fs = FounderScore(overall=score, technical=score * 0.8, execution=score * 0.7)
    dps = [
        DataPoint(source=SourceType.GITHUB, content={"repos": 5})
        for _ in range(data_points)
    ]
    return Founder(
        name="Test Founder",
        bio=bio,
        skills=skills or ["python", "ml"],
        score=fs,
        data_points=dps,
    )


def make_company(sector: str = "AI", stage: str = "seed", description: str = "") -> Company:
    return Company(name="Test Co", sector=sector, stage=stage, description=description)


def make_application() -> Application:
    return Application(company_id="testco", deck_text="We are building an AI product.")


def make_thesis(**overrides) -> FundThesis:
    defaults = dict(
        name="Test Fund",
        sectors=["AI"],
        stages=["seed"],
        geographies=["Europe"],
        check_size_min=250_000,
        check_size_max=2_000_000,
        target_ownership_pct=10.0,
        risk_appetite="moderate",
        min_founder_score=30.0,
        preferred_signals=[],
        anti_signals=[],
    )
    defaults.update(overrides)
    return FundThesis(**defaults)


# ── _score_founder_axis ───────────────────────────────────────────────────────

def test_score_founder_axis_no_founders_returns_low_score():
    screener = Screener()
    result = screener._score_founder_axis([])
    assert result.score <= 15.0
    assert result.sentiment == "bear"


def test_score_founder_axis_with_strong_founder():
    screener = Screener()
    founder = make_founder(score=75.0)
    result = screener._score_founder_axis([founder])
    assert result.score >= 60.0
    assert result.sentiment == "bullish"


def test_score_founder_axis_with_weak_founder():
    screener = Screener()
    founder = make_founder(score=20.0)
    result = screener._score_founder_axis([founder])
    assert result.score < 30.0
    assert result.sentiment == "bear"


def test_score_founder_axis_picks_best_founder():
    screener = Screener()
    weak = make_founder(score=20.0)
    strong = make_founder(score=80.0)
    result = screener._score_founder_axis([weak, strong])
    assert result.score >= 70.0


def test_score_founder_axis_thesis_preferred_signal_boosts():
    screener = Screener()
    thesis = make_thesis(preferred_signals=["open source"])
    founder = make_founder(score=50.0, bio="I love open source projects")
    result_without = screener._score_founder_axis([make_founder(score=50.0)], thesis)
    result_with = screener._score_founder_axis([founder], thesis)
    assert result_with.score >= result_without.score


def test_score_founder_axis_thesis_anti_signal_reduces():
    screener = Screener()
    thesis = make_thesis(anti_signals=["b2c only"])
    founder = make_founder(score=70.0, bio="building b2c only consumer apps")
    result = screener._score_founder_axis([founder], thesis)
    # Anti-signal should deduct from the score
    clean_result = screener._score_founder_axis([make_founder(score=70.0)], make_thesis())
    assert result.score <= clean_result.score


def test_score_founder_axis_confidence_grows_with_data_points():
    screener = Screener()
    sparse_founder = make_founder(data_points=1)
    rich_founder = make_founder(data_points=8)
    sparse_result = screener._score_founder_axis([sparse_founder])
    rich_result = screener._score_founder_axis([rich_founder])
    assert rich_result.confidence > sparse_result.confidence


# ── _build_thesis_context ─────────────────────────────────────────────────────

def test_build_thesis_context_contains_fund_name():
    screener = Screener()
    thesis = make_thesis(name="Maschmeyer Fund I")
    context = screener._build_thesis_context(thesis)
    assert "Maschmeyer Fund I" in context


def test_build_thesis_context_contains_sectors():
    screener = Screener()
    thesis = make_thesis(sectors=["AI", "Deep Tech"])
    context = screener._build_thesis_context(thesis)
    assert "AI" in context and "Deep Tech" in context


def test_build_thesis_context_includes_anti_signals():
    screener = Screener()
    thesis = make_thesis(anti_signals=["gambling", "crypto"])
    context = screener._build_thesis_context(thesis)
    assert "gambling" in context
    assert "crypto" in context


def test_build_thesis_context_omits_empty_preferred_signals():
    screener = Screener()
    thesis = make_thesis(preferred_signals=[])
    context = screener._build_thesis_context(thesis)
    assert "Preferred signals" not in context


# ── screen() with mocked LLM ─────────────────────────────────────────────────

@pytest.fixture
def mock_llm(monkeypatch):
    """Patch complete_json to return predictable market/idea scores."""
    import vc_brain.intelligence.screener as screener_mod

    async def fake_complete_json(prompt: str, system: str = "") -> dict:
        return {
            "market_score": 70,
            "market_sentiment": "bullish",
            "market_evidence": ["Large TAM"],
            "idea_score": 65,
            "idea_sentiment": "bullish",
            "idea_evidence": ["Strong differentiation"],
        }

    monkeypatch.setattr(screener_mod, "complete_json", fake_complete_json)


@pytest.mark.asyncio
async def test_screen_returns_screening_result(mock_llm):
    screener = Screener()
    app = make_application()
    company = make_company()
    founders = [make_founder(score=60.0)]
    result = await screener.screen(app, company, founders)
    assert isinstance(result, ScreeningResult)


@pytest.mark.asyncio
async def test_screen_passes_strong_founder(mock_llm):
    screener = Screener()
    founders = [make_founder(score=70.0)]
    result = await screener.screen(make_application(), make_company(), founders)
    assert result.passes_screen is True
    assert result.rejection_reasons == []


@pytest.mark.asyncio
async def test_screen_fails_weak_founder(mock_llm):
    screener = Screener()
    founders = [make_founder(score=5.0)]
    result = await screener.screen(make_application(), make_company(), founders)
    assert result.passes_screen is False
    assert len(result.rejection_reasons) > 0


@pytest.mark.asyncio
async def test_screen_thesis_min_score_enforced(mock_llm):
    screener = Screener()
    thesis = make_thesis(min_founder_score=60.0)
    founders = [make_founder(score=45.0)]
    result = await screener.screen(make_application(), make_company(), founders, thesis=thesis)
    assert result.passes_screen is False
    assert any("45" in r or "below" in r.lower() for r in result.rejection_reasons)


@pytest.mark.asyncio
async def test_screen_anti_signal_causes_rejection(mock_llm):
    screener = Screener()
    thesis = make_thesis(anti_signals=["gambling"])
    founders = [make_founder(score=80.0, bio="gambling app for sports betting")]
    result = await screener.screen(
        make_application(), make_company(description="online gambling"), founders, thesis=thesis
    )
    assert result.passes_screen is False
    assert any("gambling" in r for r in result.rejection_reasons)


@pytest.mark.asyncio
async def test_screen_cold_start_detected_for_no_founders(mock_llm):
    screener = Screener()
    result = await screener.screen(make_application(), make_company(), founders=[])
    assert result.cold_start is True


@pytest.mark.asyncio
async def test_screen_no_founders_no_data_requests_appended(mock_llm):
    screener = Screener()
    result = await screener.screen(make_application(), make_company(), founders=[])
    # cold_start_data_requests is populated by detect_cold_start
    assert isinstance(result.cold_start_data_requests, list)


@pytest.mark.asyncio
async def test_screen_llm_failure_falls_back_gracefully(monkeypatch):
    """Even when LLM explodes, screen() returns a ScreeningResult with fallback axes."""
    import vc_brain.intelligence.screener as screener_mod

    async def failing_llm(prompt: str, system: str = "") -> dict:
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(screener_mod, "complete_json", failing_llm)

    screener = Screener()
    result = await screener.screen(make_application(), make_company(), [make_founder(score=60.0)])
    # Should still return a result with fallback values, not raise
    assert isinstance(result, ScreeningResult)
    assert result.market_axis.score == 50
    assert result.idea_vs_market_axis.score == 50
