"""Tests for github_evaluator — pure functions and mocked evaluate()."""

from __future__ import annotations

import pytest

from vc_brain.sourcing.github_evaluator import (
    BuilderEvaluation,
    _is_tutorial,
    _score_readme,
    evaluate,
)


# ── _is_tutorial ─────────────────────────────────────────────────────────────

def test_is_tutorial_matches_tutorial_names():
    assert _is_tutorial({"name": "react-tutorial", "description": ""})
    assert _is_tutorial({"name": "homework-3", "description": ""})
    assert _is_tutorial({"name": "bootcamp-exercises", "description": ""})


def test_is_tutorial_matches_description():
    assert _is_tutorial({"name": "my-project", "description": "Learning Python basics"})


def test_is_tutorial_false_for_real_project():
    assert not _is_tutorial({"name": "vector-db", "description": "Fast similarity search"})
    assert not _is_tutorial({"name": "fastapi-server", "description": "Production API server"})


# ── _score_readme ─────────────────────────────────────────────────────────────

def test_score_readme_empty_returns_zero():
    score, signals = _score_readme("")
    assert score == 0.0
    assert signals == []


def test_score_readme_detects_ci():
    readme = "See .github/workflows for CI configuration."
    score, signals = _score_readme(readme)
    assert "ci" in signals
    assert score > 0


def test_score_readme_detects_code_example():
    readme = "```python\nimport my_lib\nmy_lib.run()\n```"
    score, signals = _score_readme(readme)
    assert "code_example" in signals


def test_score_readme_detects_license():
    readme = "## License\nMIT License"
    score, signals = _score_readme(readme)
    assert "license" in signals


def test_score_readme_length_bonus():
    # 200+ word README gets a length bonus
    readme = ("word " * 250) + "## Install\n```bash\nnpm install\n```"
    score_short, _ = _score_readme("## Install\n```bash\nnpm install\n```")
    score_long, _ = _score_readme(readme)
    assert score_long > score_short


def test_score_readme_max_100():
    # A README with all 8 signals should cap at 100
    readme = """
    ![badge](badge-url) CI: .github/workflows
    ## Install\n```python\nimport lib\n```
    Demo: https://demo.example.com screenshot.gif
    ## License MIT License
    ## Contributing pull request welcome
    docs/ documentation API reference
    """
    score, signals = _score_readme(readme * 10)  # long enough for length bonus
    assert score <= 100.0


# ── evaluate() with mocked HTTP ──────────────────────────────────────────────

class _MockResponse:
    def __init__(self, data, status_code: int = 200):
        self._data = data
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._data


@pytest.fixture
def mock_github_responses(monkeypatch):
    """Monkeypatch httpx.AsyncClient to return canned responses."""
    import httpx

    USER = {
        "login": "testuser",
        "public_repos": 5,
        "followers": 50,
        "following": 10,
        "created_at": "2018-01-01T00:00:00Z",
    }

    REPOS = [
        {
            "name": "vector-search",
            "full_name": "testuser/vector-search",
            "fork": False,
            "size": 800,
            "stargazers_count": 45,
            "forks_count": 12,
            "language": "Python",
            "description": "Fast vector similarity search engine",
            "homepage": "https://vectorsearch.io",
            "pushed_at": "2024-11-01T00:00:00Z",
            "created_at": "2023-06-01T00:00:00Z",
            "topics": ["ai", "search", "ml"],
        },
        {
            "name": "infra-toolkit",
            "full_name": "testuser/infra-toolkit",
            "fork": False,
            "size": 1200,
            "stargazers_count": 8,
            "forks_count": 3,
            "language": "Go",
            "description": "Kubernetes deployment helpers",
            "homepage": None,
            "pushed_at": "2024-10-15T00:00:00Z",
            "created_at": "2022-03-01T00:00:00Z",
            "topics": ["kubernetes", "devops", "docker"],
        },
        {
            "name": "llm-fine-tuner",
            "full_name": "testuser/llm-fine-tuner",
            "fork": False,
            "size": 500,
            "stargazers_count": 25,
            "forks_count": 6,
            "language": "Python",
            "description": "Fine-tune LLMs on custom datasets",
            "homepage": None,
            "pushed_at": "2024-09-01T00:00:00Z",
            "created_at": "2023-01-01T00:00:00Z",
            "topics": ["llm", "ml", "fine-tuning"],
        },
    ]

    EVENTS = [
        {"type": "PushEvent", "repo": {"name": "otheruser/open-source-lib"}},
        {"type": "PushEvent", "repo": {"name": "otheruser/open-source-lib"}},
        {"type": "PushEvent", "repo": {"name": "otheruser/framework"}},
        {"type": "PullRequestReviewEvent", "repo": {"name": "otheruser/repo"}},
        {"type": "PullRequestReviewEvent", "repo": {"name": "otheruser/repo"}},
        {"type": "PullRequestReviewEvent", "repo": {"name": "otheruser/repo"}},
        {"type": "IssuesEvent", "repo": {"name": "testuser/vector-search"}},
    ]

    README_TEXT = """
    ![Build](https://github.com/testuser/vector-search/actions/badge.svg)
    ## Install
    ```bash
    pip install vector-search
    ```
    ## Demo
    Live demo: https://demo.vectorsearch.io
    ## License
    MIT License
    ## Contributing
    Pull requests welcome.
    """

    async def fake_get(self, url, **kwargs):
        if "/users/testuser/repos" in url:
            return _MockResponse(REPOS)
        if "/users/testuser/events" in url:
            return _MockResponse(EVENTS)
        if "/users/testuser" in url:
            return _MockResponse(USER)
        if "raw.githubusercontent.com" in url and "README" in url:
            r = _MockResponse(None)
            r.status_code = 200
            r.text = README_TEXT
            return r
        return _MockResponse([], status_code=404)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


@pytest.mark.asyncio
async def test_evaluate_returns_builder_evaluation(mock_github_responses):
    result = await evaluate("testuser")
    assert isinstance(result, BuilderEvaluation)
    assert result.username == "testuser"


@pytest.mark.asyncio
async def test_evaluate_scores_are_in_range(mock_github_responses):
    result = await evaluate("testuser")
    for dim in (
        result.technical_ability, result.execution_ability,
        result.founder_product_ability, result.technical_background,
        result.reputation, result.growth_signals,
    ):
        assert 0.0 <= dim <= 100.0
    assert 0.0 <= result.score <= 100.0


@pytest.mark.asyncio
async def test_evaluate_detects_ai_keywords(mock_github_responses):
    result = await evaluate("testuser")
    # REPOS contain ai/ml/llm topics — bg score should benefit
    assert result.technical_background > 0


@pytest.mark.asyncio
async def test_evaluate_grade_is_valid(mock_github_responses):
    result = await evaluate("testuser")
    assert result.grade in ("A", "B", "C", "D", "F")


@pytest.mark.asyncio
async def test_evaluate_not_measurable_populated(mock_github_responses):
    result = await evaluate("testuser")
    # Not-measurable items are always appended for certain dimensions
    assert len(result.not_measurable) > 0


@pytest.mark.asyncio
async def test_evaluate_empty_repos(monkeypatch):
    """Evaluate a user with no repos — should not crash and give low scores."""
    import httpx

    async def fake_get(self, url, **kwargs):
        if "/users/nocode/repos" in url:
            return _MockResponse([])
        if "/users/nocode/events" in url:
            return _MockResponse([])
        if "/users/nocode" in url:
            return _MockResponse({"login": "nocode", "public_repos": 0,
                                  "followers": 0, "following": 0,
                                  "created_at": "2024-01-01T00:00:00Z"})
        r = _MockResponse(None, status_code=404)
        r.text = ""
        return r

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await evaluate("nocode")
    assert result.score < 50
    assert result.is_builder is False
