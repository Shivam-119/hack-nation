"""Sourcing Agent: orchestrates outbound scanning across multiple channels.

Uses GitHubSourcingAgent for GitHub and HN scanner for Hacker News.
Scores results and flags top candidates for activation.
"""

from __future__ import annotations

from typing import Any

from vc_brain.agents.base import BaseAgent
from vc_brain.memory.founder_score import compute_founder_score
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.store import MemoryStore
from vc_brain.sourcing.github_agent import GitHubSourcingAgent, InvestorCriteria
from vc_brain.sourcing.hackernews_scanner import HackerNewsScanner


class SourcingAgent(BaseAgent):
    name = "sourcing_agent"

    def __init__(self, store: MemoryStore, min_score_for_activation: float = 30.0):
        self.store = store
        self.pipeline = IngestionPipeline(store)
        self.min_score = min_score_for_activation

    async def observe(self, context: dict[str, Any]) -> dict[str, Any]:
        """Scan configured channels for founder candidates."""
        channels = context.get("channels", ["github", "hackernews"])
        results: dict[str, Any] = {"candidates": [], "sources_scanned": []}

        if "github" in channels:
            criteria = InvestorCriteria(
                sectors=context.get("sectors", ["ai"]),
                languages=context.get("languages", ["python"]),
                locations=context.get("locations", []),
            )
            agent = GitHubSourcingAgent(criteria)
            candidates = await agent.run(max_candidates=context.get("limit", 10))
            results["candidates"].extend([
                {"username": c.username, "score": c.evaluation.score, "verdict": c.verdict}
                for c in candidates
            ])
            results["sources_scanned"].append("github")

        if "hackernews" in channels:
            scanner = HackerNewsScanner(self.pipeline)
            launches = await scanner.scan_show_hn(limit=15)
            founders = await scanner.ingest_launches(launches)
            for f in founders:
                f.score = compute_founder_score(f)
                self.store.upsert_founder(f)
            results["candidates"].extend([
                {"username": f.name, "score": f.score.overall, "verdict": "potential"}
                for f in founders
            ])
            results["sources_scanned"].append("hackernews")

        return results

    async def think(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Identify who merits activation outreach."""
        candidates = observation.get("candidates", [])
        activate = [c for c in candidates if c["score"] >= self.min_score]

        return {
            "total_scanned": len(candidates),
            "scored": sorted(candidates, key=lambda x: x["score"], reverse=True),
            "activate": activate,
            "confidence": 0.6,
        }

    async def act(self, reasoning: dict[str, Any]) -> dict[str, Any]:
        """Flag top candidates for activation outreach."""
        return {
            "action": "sourcing_complete",
            "total_scanned": reasoning["total_scanned"],
            "top_candidates": reasoning["scored"][:10],
            "ready_for_activation": reasoning["activate"],
            "next_step": "activation" if reasoning["activate"] else "continue_scanning",
        }
