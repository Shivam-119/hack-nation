"""Multi-attribute reasoning engine: supports complex natural-language queries.

Goes beyond keyword search. Resolves compound queries like:
"technical founder, Berlin, AI infra, enterprise traction, no prior VC backing, top-tier accelerator"
"""

from __future__ import annotations

from typing import Any

from vc_brain.llm import complete_json
from vc_brain.memory.models import Founder
from vc_brain.memory.store import MemoryStore


class ReasoningEngine:
    """Natural-language query engine over the founder/company knowledge base."""

    SYSTEM = (
        "You are a search engine for a venture capital database. Given a natural-language "
        "query and a list of founder/company profiles, return the IDs of matching results "
        "ranked by relevance. Consider all attributes mentioned in the query. Return valid JSON."
    )

    def __init__(self, store: MemoryStore):
        self.store = store

    async def query(self, natural_language_query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Resolve a complex NL query against the knowledge base."""
        # First, try rule-based filtering for speed
        candidates = self._rule_based_filter(natural_language_query)

        if not candidates:
            candidates = list(self.store.founders.values())

        if not candidates:
            return []

        # Use LLM to rank and filter candidates
        return await self._llm_rank(natural_language_query, candidates, limit)

    def _rule_based_filter(self, query: str) -> list[Founder]:
        """Quick pre-filter using keyword matching on structured fields."""
        q = query.lower()
        results = list(self.store.founders.values())

        # Location filter
        location_terms = []
        for city in ("berlin", "san francisco", "new york", "london", "paris", "singapore"):
            if city in q:
                location_terms.append(city)
        if location_terms:
            results = [
                f for f in results
                if any(t in f.location.lower() for t in location_terms)
            ]

        # Skill/sector filter
        tech_terms = ["ai", "ml", "infra", "devtools", "saas", "fintech", "biotech", "crypto"]
        matched_terms = [t for t in tech_terms if t in q]
        if matched_terms:
            results = [
                f for f in results
                if any(t in " ".join(f.skills).lower() or t in f.bio.lower() for t in matched_terms)
            ]

        return results

    async def _llm_rank(
        self, query: str, candidates: list[Founder], limit: int
    ) -> list[dict[str, Any]]:
        """Use LLM to rank candidates against a complex query."""
        profiles = []
        for f in candidates[:50]:  # Cap to avoid token overflow
            profiles.append({
                "id": f.id,
                "name": f.name,
                "location": f.location,
                "bio": f.bio,
                "skills": f.skills[:10],
                "score": f.score.overall,
                "education": [e.get("institution", "") for e in f.education],
            })

        prompt = (
            f"Query: {query}\n\n"
            f"Candidate profiles:\n{profiles}\n\n"
            f"Return JSON: {{\"results\": [{{\"id\": \"...\", \"relevance\": 0-100, "
            f"\"reasoning\": \"why this founder matches\"}}]}}\n"
            f"Rank by relevance, return top {limit}."
        )

        try:
            result = await complete_json(prompt, system=self.SYSTEM)
            ranked = sorted(
                result.get("results", []),
                key=lambda r: r.get("relevance", 0),
                reverse=True,
            )
            return ranked[:limit]
        except Exception:
            # Fallback: return candidates sorted by founder score
            return [
                {"id": f.id, "name": f.name, "relevance": f.score.overall, "reasoning": "Ranked by Founder Score"}
                for f in sorted(candidates, key=lambda f: f.score.overall, reverse=True)[:limit]
            ]
