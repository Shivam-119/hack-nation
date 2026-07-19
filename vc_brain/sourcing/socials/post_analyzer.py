"""Analyze a founder's posts for investment signal (OpenAI, Pydantic-validated).

The only LLM step in the socials tool. It reads recent posts and returns a
validated `PostAnalysis` (topics, expertise, sentiment, credibility, red flags,
per-claim evidence). On ANY failure — no key, network error, bad JSON — it
degrades to a deterministic fallback with low confidence and never raises, so
one bad LLM call can't crash the pipeline.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from vc_brain.llm import complete_json
from vc_brain.sourcing.socials.models import Evidence, PostAnalysis, SocialPost, SocialProfile

_PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts" / "system"

_FALLBACK_SYSTEM = (
    "You are a VC analyst. From a founder's social posts, extract JSON with keys: "
    "topics, expertise_areas, sentiment, tone, credibility_signals, red_flags, summary, "
    "confidence (0-1), evidence (array of {claim,url}). Base claims only on the posts; "
    "never fabricate. Respond in valid JSON."
)


def _system_prompt() -> str:
    try:
        return (_PROMPT_DIR / "post_analysis.txt").read_text().strip()
    except OSError:
        return _FALLBACK_SYSTEM


async def analyze_posts(
    posts: list[SocialPost], profile: SocialProfile | None = None
) -> PostAnalysis:
    """Return a validated PostAnalysis; never raises."""
    if not posts:
        return PostAnalysis(summary="No posts available to analyze.", confidence=0.2)

    prompt = _build_prompt(posts, profile)
    try:
        raw = await complete_json(prompt, system=_system_prompt())
        return _coerce(raw)
    except Exception:
        return _fallback(posts)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------
def _build_prompt(posts: list[SocialPost], profile: SocialProfile | None) -> str:
    lines: list[str] = []
    if profile:
        lines.append(f"Founder: {profile.name or profile.handle} (@{profile.handle})")
        if profile.bio:
            lines.append(f"Bio: {profile.bio}")
        lines.append(f"Followers: {profile.followers}")
        lines.append("")
    lines.append("Recent posts:")
    for i, p in enumerate(posts, 1):
        eng = f"[likes={p.likes} reposts={p.reposts} replies={p.replies}]"
        lines.append(f"{i}. {eng} {p.text}".strip())
        if p.url:
            lines.append(f"   url: {p.url}")
    lines.append("")
    lines.append("Analyze these posts and return the JSON object described in the system prompt.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output coercion / fallback
# ---------------------------------------------------------------------------
def _coerce(raw: dict[str, Any]) -> PostAnalysis:
    """Build a validated PostAnalysis from a loosely-shaped LLM dict."""
    return PostAnalysis(
        topics=_as_str_list(raw.get("topics")),
        expertise_areas=_as_str_list(raw.get("expertise_areas")),
        sentiment=str(raw.get("sentiment") or "neutral"),
        tone=str(raw.get("tone") or ""),
        credibility_signals=_as_str_list(raw.get("credibility_signals")),
        red_flags=_as_str_list(raw.get("red_flags")),
        summary=str(raw.get("summary") or ""),
        confidence=_as_confidence(raw.get("confidence")),
        evidence=_as_evidence(raw.get("evidence")),
    )


def _fallback(posts: list[SocialPost]) -> PostAnalysis:
    """Deterministic, no-LLM analysis so the pipeline still yields something."""
    tags = Counter(t.lower() for p in posts for t in p.hashtags)
    topics = [t for t, _ in tags.most_common(5)]
    signals: list[str] = []
    if any(p.likes + p.reposts > 200 for p in posts):
        signals.append("high engagement on some posts")
    if len(posts) >= 5:
        signals.append("active, consistent posting")
    return PostAnalysis(
        topics=topics,
        credibility_signals=signals,
        summary=f"Heuristic read of {len(posts)} posts (LLM analysis unavailable).",
        confidence=0.3,
    )


def _as_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        out: list[str] = []
        for x in v:
            if isinstance(x, dict):  # LLM sometimes returns {claim/text: "..."}
                x = x.get("claim") or x.get("text") or x.get("name") or next(iter(x.values()), "")
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _as_confidence(v: Any) -> float:
    try:
        return max(0.0, min(float(v), 0.99))
    except (TypeError, ValueError):
        return 0.5


def _as_evidence(v: Any) -> list[Evidence]:
    out: list[Evidence] = []
    if isinstance(v, list):
        for item in v:
            if isinstance(item, dict):
                out.append(Evidence(claim=str(item.get("claim", "")), url=str(item.get("url", ""))))
    return out
