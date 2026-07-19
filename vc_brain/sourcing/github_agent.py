"""GitHub sourcing agent

Flow:
1. Investor sets requirements (sector, languages, location, signals they care about)
2. Agent builds GitHub search queries from those requirements
3. Finds candidate profiles
4. Evaluates each of investor's specific criteria
5. Returns ranked list with clear good/bad for each
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from vc_brain.config import config
from vc_brain.sourcing.github_evaluator import BuilderEvaluation, GitHubRateLimitError, _check_rate_limit, evaluate


# ── Investor criteria ─────────────────────────────────────────────────

@dataclass
class InvestorCriteria:
    """What the investor is looking for. No defaults, investor must specify."""
    sectors: list[str]
    languages: list[str]
    locations: list[str] = field(default_factory=list)
    min_stars: int = 10
    min_repos: int = 3
    active_within_days: int = 180
    must_be_builder: bool = False  # investor decides — not us


# ── Candidate result ──────────────────────────────────────────────────

@dataclass
class FounderCandidate:
    username: str
    name: str
    bio: str
    location: str
    profile_url: str
    evaluation: BuilderEvaluation
    thesis_fit: float  # 0-100, how well they match investor criteria
    thesis_match: list[str]  # why they match
    thesis_miss: list[str]  # why they don't
    verdict: str  # "strong_match" | "potential" | "weak" | "pass"


# ── Agent ─────────────────────────────────────────────────────────────

class GitHubSourcingAgent:
    """Finds and evaluates founders on GitHub based on investor criteria."""

    def __init__(self, criteria: InvestorCriteria):
        self.criteria = criteria
        self._headers = {"Accept": "application/vnd.github+json"}
        if config.github_token:
            self._headers["Authorization"] = f"Bearer {config.github_token}"

    async def run(self, max_candidates: int = 20) -> list[FounderCandidate]:
        """Search → evaluate → rank → return."""
        # Step 1: Build search queries from investor criteria
        queries = self._build_queries()

        # Step 2: Search GitHub, collect unique users
        users = await self._search(queries, max_candidates)

        # Step 3: Evaluate each user as builder + thesis fit
        candidates = []
        for user in users:
            username = user.get("login", "")
            if not username:
                continue

            # Builder evaluation (shipping, consistency, validation, communication)
            evaluation = await evaluate(username)

            # Skip non-builders early if investor requires it
            if self.criteria.must_be_builder and not evaluation.is_builder:
                continue

            # Thesis fit (does this person match what the investor wants?)
            fit_score, matches, misses = self._score_thesis_fit(user, evaluation)

            verdict = self._decide_verdict(evaluation, fit_score)

            candidates.append(FounderCandidate(
                username=username,
                name=user.get("name") or username,
                bio=user.get("bio") or "",
                location=user.get("location") or "",
                profile_url=user.get("html_url", ""),
                evaluation=evaluation,
                thesis_fit=fit_score,
                thesis_match=matches,
                thesis_miss=misses,
                verdict=verdict,
            ))

        # Step 4: Rank by combined score (builder quality + thesis fit)
        candidates.sort(
            key=lambda c: (c.evaluation.score * 0.6) + (c.thesis_fit * 0.4),
            reverse=True,
        )

        return candidates

    # ── Query building ────────────────────────────────────────────────

    def _build_queries(self) -> list[dict]:
        """Turn investor criteria into GitHub API search parameters."""
        queries = []

        # Search repos by sector keywords + language
        for sector in self.criteria.sectors:
            for lang in self.criteria.languages:
                created_after = (
                    datetime.utcnow() - timedelta(days=self.criteria.active_within_days)
                ).strftime("%Y-%m-%d")
                queries.append({
                    "type": "repositories",
                    "q": f"{sector} language:{lang} stars:>={self.criteria.min_stars} pushed:>{created_after}",
                    "sort": "stars",
                })

        # Search users directly by location + activity
        for location in self.criteria.locations:
            for lang in self.criteria.languages:
                queries.append({
                    "type": "users",
                    "q": f"location:{location} language:{lang} repos:>={self.criteria.min_repos}",
                    "sort": "followers",
                })

        # If no location specified, search users by language + repo count
        if not self.criteria.locations:
            for lang in self.criteria.languages:
                queries.append({
                    "type": "users",
                    "q": f"language:{lang} repos:>={self.criteria.min_repos} followers:>=5",
                    "sort": "repositories",
                })

        return queries

    # ── Search execution ──────────────────────────────────────────────

    async def _search(self, queries: list[dict], limit: int) -> list[dict]:
        """Execute search queries and return unique user profiles."""
        seen = set()
        users = []

        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=20) as client:
                for query in queries:
                    if len(users) >= limit:
                        break

                    search_type = query["type"]
                    if search_type == "repositories":
                        results = await self._search_repos(client, query, limit - len(users))
                    else:
                        results = await self._search_users(client, query, limit - len(users))

                    for user in results:
                        username = user.get("login", "")
                        if username and username not in seen:
                            seen.add(username)
                            # Fetch full profile if we only have partial data
                            if "public_repos" not in user:
                                full = await client.get(f"https://api.github.com/users/{username}")
                                _check_rate_limit(full)
                                if full.status_code == 200:
                                    user = full.json()
                            users.append(user)
        except GitHubRateLimitError:
            pass  # Return whatever we collected before hitting the limit

        return users[:limit]

    async def _search_repos(self, client: httpx.AsyncClient, query: dict, limit: int) -> list[dict]:
        """Search repos, return their owners."""
        resp = await client.get(
            "https://api.github.com/search/repositories",
            params={"q": query["q"], "sort": query["sort"], "per_page": min(limit * 2, 30)},
        )
        _check_rate_limit(resp)
        if resp.status_code != 200:
            return []
        owners = []
        seen = set()
        for repo in resp.json().get("items", []):
            owner = repo.get("owner", {})
            login = owner.get("login", "")
            if login and login not in seen and owner.get("type") == "User":
                seen.add(login)
                owners.append(owner)
        return owners

    async def _search_users(self, client: httpx.AsyncClient, query: dict, limit: int) -> list[dict]:
        """Search users directly."""
        resp = await client.get(
            "https://api.github.com/search/users",
            params={"q": query["q"], "sort": query["sort"], "per_page": min(limit, 20)},
        )
        _check_rate_limit(resp)
        if resp.status_code != 200:
            return []
        return resp.json().get("items", [])

    # ── Thesis fit scoring ────────────────────────────────────────────

    def _score_thesis_fit(
        self, user: dict, evaluation: BuilderEvaluation
    ) -> tuple[float, list[str], list[str]]:
        """Score how well a candidate matches what the investor wants."""
        fit = 0.0
        matches = []
        misses = []

        # Location match
        user_location = (user.get("location") or "").lower()
        if self.criteria.locations:
            if any(loc.lower() in user_location for loc in self.criteria.locations):
                fit += 25
                matches.append(f"Location: {user.get('location')}")
            else:
                misses.append(f"Location '{user.get('location') or 'unknown'}' not in {self.criteria.locations}")
        else:
            fit += 10  # No location requirement = partial credit

        # Language match (from evaluation signals)
        user_bio = (user.get("bio") or "").lower()
        sector_match = any(s.lower() in user_bio for s in self.criteria.sectors)
        if sector_match:
            fit += 25
            matches.append(f"Bio mentions target sector")
        else:
            # Check if their repos align with sector
            for signal in evaluation.signals:
                if any(s.lower() in signal.lower() for s in self.criteria.sectors):
                    fit += 15
                    matches.append(f"Repo activity aligns with target sector")
                    break

        # Builder quality — use the evaluator's overall score directly
        if evaluation.score >= 55:
            fit += 30
            matches.append(f"Strong builder profile ({evaluation.score}/100)")
        elif evaluation.score >= 35:
            fit += 15
            matches.append(f"Moderate builder profile ({evaluation.score}/100)")
        else:
            misses.append(f"Weak builder profile ({evaluation.score}/100)")

        # Red flags count against fit
        if len(evaluation.red_flags) >= 3:
            fit -= 15
            misses.append(f"{len(evaluation.red_flags)} red flags")
        elif len(evaluation.red_flags) == 0:
            fit += 10
            matches.append("No red flags")

        # Stars threshold
        if evaluation.reputation >= 50:
            fit += 10
            matches.append("Externally validated by community")

        fit = round(max(0, min(100, fit)), 1)
        return fit, matches, misses

    # ── Verdict ───────────────────────────────────────────────────────

    def _decide_verdict(self, evaluation: BuilderEvaluation, thesis_fit: float) -> str:
        """Final call: is this person worth reaching out to?"""
        combined = (evaluation.score * 0.6) + (thesis_fit * 0.4)

        if combined >= 65 and evaluation.is_builder and thesis_fit >= 50:
            return "strong_match"
        elif combined >= 45 and evaluation.is_builder:
            return "potential"
        elif combined >= 30:
            return "weak"
        else:
            return "pass"
