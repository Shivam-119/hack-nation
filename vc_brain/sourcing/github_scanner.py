"""Outbound sourcing: scan GitHub for promising technical founders."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from vc_brain.config import config
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.models import Founder, SourceType


@dataclass
class GitHubCandidate:
    username: str
    name: str
    bio: str
    location: str
    public_repos: int
    followers: int
    total_stars: int
    top_languages: list[str]
    profile_url: str


class GitHubScanner:
    """Scan GitHub for founders building in target sectors."""

    BASE_URL = "https://api.github.com"

    def __init__(self, pipeline: IngestionPipeline):
        self.pipeline = pipeline
        self._headers = {}
        if config.github_token:
            self._headers["Authorization"] = f"Bearer {config.github_token}"

    async def scan_trending(
        self,
        language: str = "python",
        min_stars: int = 50,
        limit: int = 20,
    ) -> list[GitHubCandidate]:
        """Find developers with trending repos in a given language."""
        candidates = []
        async with httpx.AsyncClient(headers=self._headers) as client:
            # Search for recently created repos with stars
            resp = await client.get(
                f"{self.BASE_URL}/search/repositories",
                params={
                    "q": f"language:{language} stars:>={min_stars} created:>2024-01-01",
                    "sort": "stars",
                    "order": "desc",
                    "per_page": limit,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                return candidates

            repos = resp.json().get("items", [])
            seen_owners = set()

            for repo in repos:
                owner = repo.get("owner", {})
                username = owner.get("login", "")
                if username in seen_owners:
                    continue
                seen_owners.add(username)

                # Fetch user profile
                user_resp = await client.get(
                    f"{self.BASE_URL}/users/{username}", timeout=15
                )
                if user_resp.status_code != 200:
                    continue
                user = user_resp.json()

                candidate = GitHubCandidate(
                    username=username,
                    name=user.get("name", username),
                    bio=user.get("bio", "") or "",
                    location=user.get("location", "") or "",
                    public_repos=user.get("public_repos", 0),
                    followers=user.get("followers", 0),
                    total_stars=repo.get("stargazers_count", 0),
                    top_languages=[language],
                    profile_url=user.get("html_url", ""),
                )
                candidates.append(candidate)

        return candidates

    async def ingest_candidates(self, candidates: list[GitHubCandidate]) -> list[Founder]:
        """Store discovered candidates in Memory."""
        founders = []
        for c in candidates:
            founder = self.pipeline.ingest_founder_from_source(
                source=SourceType.GITHUB,
                data={
                    "name": c.name,
                    "github_url": c.profile_url,
                    "location": c.location,
                    "bio": c.bio,
                    "skills": c.top_languages,
                    "profile_url": c.profile_url,
                    "public_repos": c.public_repos,
                    "total_stars": c.total_stars,
                    "followers": c.followers,
                    "confidence": 0.6,
                },
            )
            founders.append(founder)
        return founders
