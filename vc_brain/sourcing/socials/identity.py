"""Identity check: resolve WHO a name is, then score their prominence.

Given a person's display name/handle (the founder and the real people who
comment on their posts), figure out who they are and produce a **deterministic**
prominence score (0-100). The LLM/web-search only *gather* identity signals; the
score itself is pure code, so it's explainable and reproducible.

Backends (same mock-default posture as everything else):
- MockIdentityChecker (default, $0): resolves against the hardcoded notable
  roster + fixtures.
- TavilyIdentityChecker: web-search the name -> LLM extracts identity -> the
  same deterministic scorer. Reuses `config.tavily_api_key`. Falls back to Mock.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

from vc_brain.config import config
from vc_brain.llm import complete_json
from vc_brain.sourcing.socials.models import Evidence, IdentityResult
from vc_brain.sourcing.socials.notable import NOTABLE, lookup_notable, normalize_handle

_PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts" / "system"
_FALLBACK_SYSTEM = (
    "Resolve who a person is from web snippets. Return JSON with keys resolved_name, "
    "description, roles (array), affiliations (array), is_notable (bool), confidence (0-1). "
    "Use only the snippets; never invent. Respond in valid JSON."
)

# Deterministic scoring tables.
_ROLE_PTS = {
    "founder": 12, "co-founder": 12, "cofounder": 12, "ceo": 12, "cto": 10,
    "partner": 12, "general partner": 12, "gp": 12, "investor": 12, "vc": 12,
    "managing director": 10, "board member": 10, "advisor": 8, "vp": 6,
    "director": 5, "engineer": 4,
}
_PRESTIGE = {e.name.lower() for e in NOTABLE.values()
             if e.category in ("top_vc", "frontier_lab", "accelerator")} | {
    "google", "meta", "facebook", "apple", "microsoft", "openai", "stripe",
    "amazon", "nvidia", "anthropic", "deepmind", "sequoia", "a16z",
    "andreessen horowitz", "y combinator", "combinator",
}
_NAME_INDEX = {e.name.lower(): (h, e) for h, e in NOTABLE.items()}


@runtime_checkable
class IdentityChecker(Protocol):
    name: str

    async def identify(self, name: str, handle: str = "", context: str = "") -> IdentityResult:
        """Resolve who a person is + a deterministic prominence score. Never raises."""


# ---------------------------------------------------------------------------
# Deterministic prominence score (non-LLM)
# ---------------------------------------------------------------------------
def score_prominence(
    *,
    is_notable: bool,
    roles: list[str],
    affiliations: list[str],
    source_hits: int = 0,
    roster_weight: float = 0.0,
) -> float:
    score = min(roster_weight * 5.0, 50.0)
    score += min(sum(_ROLE_PTS.get(r.strip().lower(), 4) for r in roles), 24.0)
    score += min(len(_notable_affiliations(affiliations)) * 10.0, 20.0)
    score += min(source_hits * 2.0, 10.0)
    if is_notable:
        score = max(score, 60.0)
    return round(min(score, 100.0), 1)


def _notable_affiliations(affs: list[str]) -> list[str]:
    return [a for a in affs if any(p in a.lower() for p in _PRESTIGE)]


# ---------------------------------------------------------------------------
# Mock checker (default, $0)
# ---------------------------------------------------------------------------
class MockIdentityChecker:
    name = "mock"

    async def identify(self, name: str, handle: str = "", context: str = "") -> IdentityResult:
        entry = lookup_notable(handle) if handle else None
        matched_handle = normalize_handle(handle)
        if not entry:
            found = _NAME_INDEX.get(name.strip().lower())
            if found:
                matched_handle, entry = found

        if entry:
            role = _role_for_category(entry.category)
            return IdentityResult(
                query_name=name,
                handle=matched_handle,
                resolved_name=entry.name,
                description=f"{entry.category.replace('_', ' ')} (matched notable roster)",
                roles=[role],
                is_notable=True,
                prominence_score=score_prominence(
                    is_notable=True, roles=[role], affiliations=[], roster_weight=entry.weight
                ),
                confidence=0.6,
                evidence=[Evidence(
                    claim=f"Matched notable roster as {entry.name}",
                    url=f"https://twitter.com/{matched_handle}" if matched_handle else "",
                )],
                source="mock",
            )
        return IdentityResult(
            query_name=name,
            handle=matched_handle,
            resolved_name=name,
            description="No notable public profile matched.",
            prominence_score=15.0,
            confidence=0.3,
            source="mock",
        )


# ---------------------------------------------------------------------------
# Tavily checker (web search -> LLM extract -> deterministic score)
# ---------------------------------------------------------------------------
class TavilyIdentityChecker:
    name = "tavily"
    SEARCH_URL = "https://api.tavily.com/search"

    async def identify(self, name: str, handle: str = "", context: str = "") -> IdentityResult:
        if not config.tavily_api_key:
            return await MockIdentityChecker().identify(name, handle, context)
        try:
            results = await self._search(name, context)
            raw = await complete_json(
                _build_prompt(name, handle, context, results), system=_system_prompt()
            )
            return self._to_result(name, handle, raw, results)
        except Exception:
            return await MockIdentityChecker().identify(name, handle, context)

    async def _search(self, name: str, context: str) -> list[dict[str, Any]]:
        query = f"{name} {context}".strip() + " founder OR investor OR CEO OR engineer"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.SEARCH_URL,
                json={
                    "api_key": config.tavily_api_key,
                    "query": query,
                    "max_results": 5,
                    "search_depth": "basic",
                },
                timeout=30,
            )
            if resp.status_code >= 300:
                return []
            data = resp.json()
            return data.get("results", []) if isinstance(data, dict) else []

    def _to_result(
        self, name: str, handle: str, raw: dict[str, Any], results: list[dict[str, Any]]
    ) -> IdentityResult:
        roles = _as_list(raw.get("roles"))
        affiliations = _as_list(raw.get("affiliations"))
        is_notable = bool(raw.get("is_notable"))
        return IdentityResult(
            query_name=name,
            handle=normalize_handle(handle),
            resolved_name=str(raw.get("resolved_name") or name),
            description=str(raw.get("description") or ""),
            roles=roles,
            affiliations=affiliations,
            is_notable=is_notable,
            prominence_score=score_prominence(
                is_notable=is_notable,
                roles=roles,
                affiliations=affiliations,
                source_hits=len(results),
            ),
            confidence=_as_confidence(raw.get("confidence")),
            evidence=[
                Evidence(claim=str(r.get("title", "")), url=str(r.get("url", "")))
                for r in results[:3]
            ],
            source="tavily",
        )


def get_identity_checker() -> IdentityChecker:
    choice = (config.socials_identity_provider or "mock").strip().lower()
    if choice == "tavily" and config.tavily_api_key:
        return TavilyIdentityChecker()
    return MockIdentityChecker()


def aggregate_identity_score(engagers: list[IdentityResult]) -> float:
    """0-100 signal from WHO engages: notable engagers' prominence, half-weighted."""
    notable = [e for e in engagers if e.is_notable]
    return round(min(sum(e.prominence_score for e in notable) * 0.5, 100.0), 1)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _role_for_category(category: str) -> str:
    return {
        "notable_founder": "Founder",
        "top_vc": "Investor",
        "accelerator": "Investor",
        "frontier_lab": "Organization",
        "top_operator": "Operator",
    }.get(category, "Notable")


def _system_prompt() -> str:
    try:
        return (_PROMPT_DIR / "identity_extraction.txt").read_text().strip()
    except OSError:
        return _FALLBACK_SYSTEM


def _build_prompt(name: str, handle: str, context: str, results: list[dict[str, Any]]) -> str:
    lines = [f"Name: {name}"]
    if handle:
        lines.append(f"Handle: @{handle}")
    if context:
        lines.append(f"Context: {context}")
    lines.append("\nSearch results:")
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', '')}\n   {r.get('content', '')[:300]}\n   {r.get('url', '')}")
    lines.append("\nReturn the identity JSON described in the system prompt.")
    return "\n".join(lines)


def _as_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _as_confidence(v: Any) -> float:
    try:
        return max(0.0, min(float(v), 0.99))
    except (TypeError, ValueError):
        return 0.5
