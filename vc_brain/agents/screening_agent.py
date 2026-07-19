"""Screening Agent: runs the full 3-axis screening pipeline as an agent.

Demonstrates the Observe -> Think -> Act pattern with traceability.
"""

from __future__ import annotations

from typing import Any

from vc_brain.agents.base import BaseAgent
from vc_brain.intelligence.screener import Screener
from vc_brain.memory.founder_score import compute_founder_score
from vc_brain.memory.models import Application, Company, Founder
from vc_brain.memory.store import MemoryStore


class ScreeningAgent(BaseAgent):
    name = "screening_agent"

    def __init__(self, store: MemoryStore, thesis_context: str = ""):
        self.store = store
        self.screener = Screener()
        self.thesis_context = thesis_context

    async def observe(self, context: dict[str, Any]) -> dict[str, Any]:
        """Pull application, company, and founder data from memory."""
        app_id = context["application_id"]
        application = self.store.get_application(app_id)
        if not application:
            raise ValueError(f"Application {app_id} not found")

        company = self.store.get_company(application.company_id)
        founders = [
            self.store.get_founder(fid)
            for fid in application.founder_ids
        ]
        founders = [f for f in founders if f]

        # Recompute founder scores with latest data
        for founder in founders:
            founder.score = compute_founder_score(founder)
            self.store.upsert_founder(founder)

        return {
            "application": application.model_dump(mode="json"),
            "company": company.model_dump(mode="json") if company else {},
            "founders": [f.model_dump(mode="json") for f in founders],
            "founder_count": len(founders),
        }

    async def think(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Run the 3-axis screener."""
        app = Application(**observation["application"])
        company = Company(**observation["company"]) if observation["company"] else Company(name="Unknown")
        founders = [Founder(**f) for f in observation["founders"]]

        result = await self.screener.screen(app, company, founders, self.thesis_context)

        return {
            "screening": result.model_dump(mode="json"),
            "passes": result.passes_screen,
            "confidence": min(
                result.founder_axis.confidence,
                result.market_axis.confidence,
                result.idea_vs_market_axis.confidence,
            ),
        }

    async def act(self, reasoning: dict[str, Any]) -> dict[str, Any]:
        """Write screening result back to the application in memory."""
        screening = reasoning["screening"]

        return {
            "action": "screening_complete",
            "passes_screen": reasoning["passes"],
            "screening_result": screening,
            "next_step": "diligence" if reasoning["passes"] else "passed",
        }
