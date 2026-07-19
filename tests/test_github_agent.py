"""Tests for GitHubSourcingAgent — query building, thesis fit scoring, verdict logic."""

from __future__ import annotations

import pytest

from vc_brain.sourcing.github_evaluator import BuilderEvaluation
from vc_brain.sourcing.github_agent import (
    FounderCandidate,
    GitHubSourcingAgent,
    InvestorCriteria,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def make_criteria(**overrides) -> InvestorCriteria:
    defaults = dict(
        sectors=["AI", "ML"],
        languages=["Python"],
        locations=["Berlin"],
        min_stars=10,
        min_repos=3,
        active_within_days=180,
        must_be_builder=False,
    )
    defaults.update(overrides)
    return InvestorCriteria(**defaults)


def make_evaluation(**overrides) -> BuilderEvaluation:
    defaults = dict(
        username="testuser",
        is_builder=True,
        grade="B",
        score=65.0,
        technical_ability=70.0,
        execution_ability=60.0,
        founder_product_ability=50.0,
        technical_background=55.0,
        reputation=60.0,
        growth_signals=45.0,
        signals=["10 substantial codebases", "AI/ML activity detected"],
        red_flags=[],
        not_measurable=["Revenue/business traction — needs application data"],
    )
    defaults.update(overrides)
    return BuilderEvaluation(**defaults)


# ── InvestorCriteria ──────────────────────────────────────────────────────────

def test_investor_criteria_defaults():
    c = InvestorCriteria(sectors=["AI"], languages=["Python"])
    assert c.min_stars == 10
    assert c.min_repos == 3
    assert c.active_within_days == 180
    assert c.must_be_builder is False


# ── _build_queries ────────────────────────────────────────────────────────────

def test_build_queries_generates_repo_and_user_queries():
    agent = GitHubSourcingAgent(make_criteria())
    queries = agent._build_queries()
    types = [q["type"] for q in queries]
    assert "repositories" in types
    assert "users" in types


def test_build_queries_no_location_generates_user_queries():
    agent = GitHubSourcingAgent(make_criteria(locations=[]))
    queries = agent._build_queries()
    user_queries = [q for q in queries if q["type"] == "users"]
    assert len(user_queries) >= 1
    # Should search by language + repos, not by location
    assert any("repos:" in q["q"] for q in user_queries)


def test_build_queries_contains_sector_and_language():
    agent = GitHubSourcingAgent(
        make_criteria(sectors=["robotics"], languages=["C++"])
    )
    queries = agent._build_queries()
    repo_queries = [q for q in queries if q["type"] == "repositories"]
    assert any("robotics" in q["q"] and "C++" in q["q"] for q in repo_queries)


def test_build_queries_multiple_sectors_and_langs():
    agent = GitHubSourcingAgent(
        make_criteria(sectors=["AI", "infra"], languages=["Python", "Go"])
    )
    queries = agent._build_queries()
    repo_queries = [q for q in queries if q["type"] == "repositories"]
    # 2 sectors × 2 langs = 4 repo queries
    assert len(repo_queries) == 4


# ── _score_thesis_fit ─────────────────────────────────────────────────────────

def test_score_thesis_fit_location_match():
    agent = GitHubSourcingAgent(make_criteria(locations=["Berlin"]))
    user = {"location": "Berlin, Germany", "bio": ""}
    ev = make_evaluation(score=30.0, is_builder=False)
    fit, matches, _ = agent._score_thesis_fit(user, ev)
    assert any("Location" in m for m in matches)


def test_score_thesis_fit_location_miss():
    agent = GitHubSourcingAgent(make_criteria(locations=["Berlin"]))
    user = {"location": "Tokyo, Japan", "bio": ""}
    ev = make_evaluation(score=30.0)
    _, _, misses = agent._score_thesis_fit(user, ev)
    assert any("Location" in m for m in misses)


def test_score_thesis_fit_sector_in_bio():
    agent = GitHubSourcingAgent(make_criteria(sectors=["AI"], locations=[]))
    user = {"location": "", "bio": "building AI products for healthcare"}
    ev = make_evaluation()
    fit, matches, _ = agent._score_thesis_fit(user, ev)
    assert any("sector" in m.lower() for m in matches)


def test_score_thesis_fit_strong_builder_boosts_score():
    agent = GitHubSourcingAgent(make_criteria(locations=[]))
    user = {"location": "", "bio": ""}
    weak_ev = make_evaluation(score=25.0, is_builder=False)
    strong_ev = make_evaluation(score=70.0, is_builder=True)
    fit_weak, _, _ = agent._score_thesis_fit(user, weak_ev)
    fit_strong, _, _ = agent._score_thesis_fit(user, strong_ev)
    assert fit_strong > fit_weak


def test_score_thesis_fit_red_flags_penalise():
    agent = GitHubSourcingAgent(make_criteria(locations=[]))
    user = {"location": "", "bio": ""}
    clean_ev = make_evaluation(red_flags=[])
    flagged_ev = make_evaluation(red_flags=["flag1", "flag2", "flag3"])
    fit_clean, _, _ = agent._score_thesis_fit(user, clean_ev)
    fit_flagged, _, _ = agent._score_thesis_fit(user, flagged_ev)
    assert fit_clean > fit_flagged


def test_score_thesis_fit_high_reputation_boosts():
    agent = GitHubSourcingAgent(make_criteria(locations=[]))
    user = {"location": "", "bio": ""}
    low_rep = make_evaluation(reputation=20.0)
    high_rep = make_evaluation(reputation=75.0)
    fit_low, _, _ = agent._score_thesis_fit(user, low_rep)
    fit_high, _, _ = agent._score_thesis_fit(user, high_rep)
    assert fit_high >= fit_low


def test_score_thesis_fit_capped_at_100():
    agent = GitHubSourcingAgent(make_criteria(locations=["Berlin"]))
    user = {"location": "Berlin", "bio": "building AI tools"}
    ev = make_evaluation(score=100.0, reputation=100.0, red_flags=[])
    fit, _, _ = agent._score_thesis_fit(user, ev)
    assert fit <= 100.0


# ── _decide_verdict ────────────────────────────────────────────────────────────

def test_decide_verdict_strong_match():
    agent = GitHubSourcingAgent(make_criteria())
    ev = make_evaluation(score=80.0, is_builder=True)
    verdict = agent._decide_verdict(ev, thesis_fit=70.0)
    assert verdict == "strong_match"


def test_decide_verdict_potential():
    agent = GitHubSourcingAgent(make_criteria())
    ev = make_evaluation(score=55.0, is_builder=True)
    verdict = agent._decide_verdict(ev, thesis_fit=30.0)
    assert verdict == "potential"


def test_decide_verdict_weak():
    agent = GitHubSourcingAgent(make_criteria())
    # combined = 40 * 0.6 + 30 * 0.4 = 24 + 12 = 36 >= 30, not a builder → "weak"
    ev = make_evaluation(score=40.0, is_builder=False)
    verdict = agent._decide_verdict(ev, thesis_fit=30.0)
    assert verdict == "weak"


def test_decide_verdict_pass():
    agent = GitHubSourcingAgent(make_criteria())
    ev = make_evaluation(score=10.0, is_builder=False)
    verdict = agent._decide_verdict(ev, thesis_fit=10.0)
    assert verdict == "pass"


# ── run() with mocked HTTP ────────────────────────────────────────────────────

MOCK_SEARCH_USER = {
    "login": "aibuilder",
    "name": "AI Builder",
    "bio": "Building AI tools",
    "location": "Berlin",
    "html_url": "https://github.com/aibuilder",
    "public_repos": 10,
    "followers": 100,
    "type": "User",
}

MOCK_EVAL = make_evaluation(username="aibuilder", score=65.0, is_builder=True)


@pytest.fixture
def mock_agent_http(monkeypatch):
    """Monkeypatch HTTP calls for agent run() — both search and evaluate."""
    import httpx

    class _MockResp:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code
            self.text = ""

        def json(self):
            return self._data

    async def fake_get(self, url, **kwargs):
        if "search/users" in url or "search/repositories" in url:
            return _MockResp({"items": [MOCK_SEARCH_USER]})
        if "/users/aibuilder" in url and "repos" in url:
            return _MockResp([])
        if "/users/aibuilder" in url and "events" in url:
            return _MockResp([])
        if "/users/aibuilder" in url:
            return _MockResp(MOCK_SEARCH_USER)
        r = _MockResp([], 404)
        r.text = ""
        return r

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


@pytest.mark.asyncio
async def test_run_returns_candidates(mock_agent_http):
    agent = GitHubSourcingAgent(make_criteria())
    candidates = await agent.run(max_candidates=5)
    assert isinstance(candidates, list)
    # At least one candidate from the mock search
    assert len(candidates) >= 1


@pytest.mark.asyncio
async def test_run_returns_sorted_candidates(mock_agent_http):
    agent = GitHubSourcingAgent(make_criteria())
    candidates = await agent.run(max_candidates=5)
    scores = [
        (c.evaluation.score * 0.6) + (c.thesis_fit * 0.4)
        for c in candidates
    ]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_run_must_be_builder_filters(monkeypatch):
    """must_be_builder=True should filter out non-builders."""
    import httpx

    class _MockResp:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code
            self.text = ""

        def json(self):
            return self._data

    async def fake_get(self, url, **kwargs):
        if "search" in url:
            return _MockResp({"items": [MOCK_SEARCH_USER]})
        if "/users/aibuilder" in url and "repos" in url:
            return _MockResp([])
        if "/users/aibuilder" in url and "events" in url:
            return _MockResp([])
        if "/users/aibuilder" in url:
            return _MockResp(MOCK_SEARCH_USER)
        r = _MockResp([], 404)
        r.text = ""
        return r

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    criteria = make_criteria(must_be_builder=True)
    agent = GitHubSourcingAgent(criteria)
    candidates = await agent.run(max_candidates=5)
    # All returned candidates must be builders
    for c in candidates:
        assert c.evaluation.is_builder
