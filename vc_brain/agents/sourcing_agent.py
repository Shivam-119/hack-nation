"""Sourcing Agent: orchestrates outbound scanning across multiple channels.

Runs GitHub and HN scanners, scores results, and flags top candidates for activation.
"""

from __future__ import annotations

from typing import Any

from vc_brain.agents.base import BaseAgent
from vc_brain.memory.founder_score import compute_founder_score
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.store import MemoryStore
from vc_brain.sourcing.github_scanner import GitHubScanner
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
            scanner = GitHubScanner(self.pipeline)
            language = context.get("language", "python")
            candidates = await scanner.scan_trending(language=language, limit=10)
            founders = await scanner.ingest_candidates(candidates)
            results["candidates"].extend([f.id for f in founders])
            results["sources_scanned"].append("github")

        if "hackernews" in channels:
            scanner = HackerNewsScanner(self.pipeline)
            launches = await scanner.scan_show_hn(limit=15)
            founders = await scanner.ingest_launches(launches)
            results["candidates"].extend([f.id for f in founders])
            results["sources_scanned"].append("hackernews")

        return results

    async def think(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Score all candidates and identify who merits activation outreach."""
        candidate_ids = observation.get("candidates", [])
        scored = []
        activate = []

        for fid in candidate_ids:
            founder = self.store.get_founder(fid)
            if not founder:
                continue
            founder.score = compute_founder_score(founder)
            self.store.upsert_founder(founder)

            scored.append({"id": fid, "name": founder.name, "score": founder.score.overall})
            if founder.score.overall >= self.min_score:
                activate.append(fid)

        return {
            "total_scanned": len(candidate_ids),
            "scored": sorted(scored, key=lambda x: x["score"], reverse=True),
            "activate_ids": activate,
            "confidence": 0.6,
        }

    async def act(self, reasoning: dict[str, Any]) -> dict[str, Any]:
        """Flag top candidates for activation outreach."""
        return {
            "action": "sourcing_complete",
            "total_scanned": reasoning["total_scanned"],
            "top_candidates": reasoning["scored"][:10],
            "ready_for_activation": reasoning["activate_ids"],
            "next_step": "activation" if reasoning["activate_ids"] else "continue_scanning",
        }
