"""Enrich one application into founder + company intelligence.

Chains the three sourcing scanners onto a deck plus the founders' own handles:

    deck    -> company name              -> reputation(company)   [article research]
    handles -> socials(x / linkedin)     [post + engagement analysis]
            -> github(username)          [builder evaluation]
            -> reputation(founder name)  [article research on the person]

Division of inputs is deliberate: the **deck** supplies the company, the
**application form** supplies the people and their handles. A deck never
contains social handles, so socials and GitHub cannot start from it -- they
start from what the founder typed on the apply form.

Every stage fails soft. One dead scanner degrades the result rather than
aborting the run, and every failure is recorded in an `errors` list so the
gaps are visible instead of silently missing.

Cost / liveness note: reputation uses Tavily (live when TAVILY_API_KEY is set),
GitHub hits the public API, and socials follows `config.socials_*_provider`
(mock by default -- see `.env`). The orchestrator does not persist anything;
it only reads.
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from vc_brain.config import config
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.store import MemoryStore
from vc_brain.sourcing.github_evaluator import evaluate as evaluate_github
from vc_brain.sourcing.reputation import EntityType, ReputationScanner
from vc_brain.sourcing.socials.scanner import SocialsScanner


@dataclass
class FounderInput:
    """One founder as captured on the application form."""

    name: str = ""
    github: str = ""
    twitter: str = ""
    linkedin: str = ""

    def handles(self) -> dict[str, str]:
        """Social handles for the socials scanner (empty ones dropped)."""
        return {k: v for k, v in {"twitter": self.twitter, "linkedin": self.linkedin}.items() if v}


class FounderEnrichment(BaseModel):
    name: str = ""
    handles: dict[str, str] = Field(default_factory=dict)
    github_username: str = ""
    github: dict[str, Any] | None = None  # BuilderEvaluation
    socials: dict[str, Any] | None = None  # SocialsResult
    reputation: dict[str, Any] | None = None  # ReputationReport (person)
    errors: list[str] = Field(default_factory=list)


class DeckEnrichment(BaseModel):
    company_name: str = ""
    industry: str = ""
    one_liner: str = ""
    deck_chars: int = 0  # extractable characters found in the deck
    company_reputation: dict[str, Any] | None = None  # ReputationReport (company)
    founders: list[FounderEnrichment] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


def _dump(obj: Any) -> dict[str, Any] | None:
    """Serialise a pydantic model or dataclass result to plain JSON-able dict."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return {"value": obj}


# ---------------------------------------------------------------- deck ------

async def _company_from_deck(deck_path: str) -> tuple[Any | None, int, list[str]]:
    """Extract the company/market summary from a deck. Returns (extraction, chars, errors)."""
    # Imported lazily: pdf_parser depends on python-pptx, which may be absent.
    try:
        from pdf_parser.deck_parser import extract_deck_text
        from pdf_parser.extractor_agent import extract_market
    except Exception as exc:  # noqa: BLE001 -- any import failure is a soft gap
        return None, 0, [f"Deck parser unavailable ({exc}). Is python-pptx installed?"]

    try:
        text = extract_deck_text(deck_path)
    except Exception as exc:  # noqa: BLE001
        return None, 0, [f"Could not read the deck: {exc}"]

    chars = len(text.strip())
    if not chars:
        return None, 0, ["The deck has no extractable text — image-only slides need OCR."]

    if not config.openai_api_key:
        return None, chars, ["OPENAI_API_KEY not set — cannot extract company details."]

    try:
        # extract_market is sync and network-bound; keep the event loop free.
        extraction = await asyncio.to_thread(extract_market, text, config.openai_api_key)
    except Exception as exc:  # noqa: BLE001
        return None, chars, [f"Company extraction failed: {exc}"]

    return extraction, chars, []


# --------------------------------------------------------------- founder ----

async def _enrich_founder(
    founder: FounderInput,
    company: str,
    pipeline: IngestionPipeline,
    person_reputation: bool,
) -> FounderEnrichment:
    out = FounderEnrichment(
        name=founder.name,
        handles=founder.handles(),
        github_username=founder.github,
    )

    async def github() -> Any | None:
        if not founder.github:
            return None
        return await evaluate_github(founder.github)

    async def socials() -> Any | None:
        if not out.handles:
            return None
        return await SocialsScanner(pipeline).analyze(out.handles, name=founder.name)

    async def reputation() -> Any | None:
        if not (person_reputation and founder.name):
            return None
        return await ReputationScanner(pipeline).analyze(
            founder.name, hint=company, entity=EntityType.PERSON
        )

    labels = ("github", "socials", "reputation")
    results = await asyncio.gather(github(), socials(), reputation(), return_exceptions=True)
    for label, result in zip(labels, results):
        if isinstance(result, BaseException):
            out.errors.append(f"{label}: {result}")
        else:
            setattr(out, label, _dump(result))

    if not founder.github:
        out.errors.append("No GitHub handle supplied — builder evaluation skipped.")
    if not out.handles:
        out.errors.append("No social handles supplied — socials skipped.")

    return out


# --------------------------------------------------------------- public -----

async def enrich_from_deck(
    deck_path: str,
    founders: list[FounderInput],
    *,
    company_name: str = "",
    person_reputation: bool = True,
    store: MemoryStore | None = None,
) -> DeckEnrichment:
    """Run company + per-founder enrichment for one application.

    `deck_path` yields the company (unless `company_name` is given directly);
    `founders` carry the handles the apply form collected. Never raises.
    """
    pipeline = IngestionPipeline(store or MemoryStore())
    result = DeckEnrichment()

    extraction, chars, deck_errors = (None, 0, [])
    if company_name:
        result.company_name = company_name
    else:
        extraction, chars, deck_errors = await _company_from_deck(deck_path)
        result.deck_chars = chars
        result.errors.extend(deck_errors)
        if extraction is not None:
            result.company_name = extraction.company_name or ""
            result.industry = extraction.primary_industry or ""
            result.one_liner = extraction.one_line_description or ""

    # Company article research + per-founder enrichment, all concurrent.
    async def company_reputation() -> Any | None:
        if not result.company_name:
            return None
        return await ReputationScanner(pipeline).analyze(
            result.company_name, hint=result.industry, entity=EntityType.COMPANY
        )

    company_task = company_reputation()
    founder_tasks = [
        _enrich_founder(f, result.company_name, pipeline, person_reputation) for f in founders
    ]
    company_res, *founder_res = await asyncio.gather(
        company_task, *founder_tasks, return_exceptions=True
    )

    if isinstance(company_res, BaseException):
        result.errors.append(f"company reputation: {company_res}")
    else:
        result.company_reputation = _dump(company_res)

    for fr in founder_res:
        if isinstance(fr, BaseException):
            result.errors.append(f"founder enrichment: {fr}")
        else:
            result.founders.append(fr)

    if not result.company_name:
        result.errors.append("No company name — company article research skipped.")

    return result


# -------------------------------------------------------------- display ----

def _trim_findings(rep: dict | None, n: int) -> dict | None:
    if not rep:
        return None
    return {
        "articles_reviewed": rep.get("articles_reviewed"),
        "by_category": rep.get("by_category"),
        "findings": [
            {
                "summary": f.get("summary", ""),
                "category": f.get("category", ""),
                "polarity": f.get("polarity", ""),
                "relevance": f.get("relevance"),
                "source": (f.get("sources") or [{}])[0].get("source", ""),
                "url": (f.get("sources") or [{}])[0].get("url", ""),
            }
            for f in (rep.get("findings") or [])[:n]
        ],
    }


# Which bucket each finding category belongs to. At pre-seed the investor wants
# the person's track record up front -- who they are, what they studied, what
# they built and won -- with adverse findings called out separately rather than
# mixed into the same undifferentiated list.
_PROFILE_BUCKETS: dict[str, tuple[str, ...]] = {
    "background": ("education", "prior_company", "current_role"),
    "achievements": ("award", "recognition", "research"),
    "adverse": ("fraud", "legal", "controversy", "failure"),
}

# `rumor` is deliberately NOT an adverse category. The extraction prompt labels
# anything sourced from Reddit/LinkedIn/X as `rumor` regardless of what it says,
# so a founder announcing their own funding round came back as `rumor` and got
# red-boxed as an adverse finding. Adverse membership is decided by the
# inherently-adverse categories above plus explicit negative polarity, so an
# unflattering rumour still lands there while a benign one does not.
_NEGATIVE = "negative"


def _interleave(findings: list[dict], limit: int) -> list[dict]:
    """Take `limit` findings, round-robin across categories.

    A wide sweep returns the same fact many times over -- one founder came back
    with 23 near-identical "is co-founder and CEO" findings. Taken in order
    those would fill the whole quota and bury the single education finding,
    which is the one an investor actually wants. Round-robin guarantees every
    category present gets a slot before any category gets a second one.
    """
    by_category: dict[str, list[dict]] = {}
    for finding in findings:
        by_category.setdefault((finding.get("category") or "").strip().lower(), []).append(finding)

    out: list[dict] = []
    while len(out) < limit:
        took = False
        for bucket in list(by_category):
            if not by_category[bucket]:
                continue
            out.append(by_category[bucket].pop(0))
            took = True
            if len(out) >= limit:
                break
        if not took:  # every category exhausted
            break
    return out


def founder_profile(rep: dict | None, limit: int = 8) -> dict[str, list[dict]]:
    """Bucket a founder's findings by category so the frontend stays dumb.

    Anything not explicitly mapped (press, funding, other, or a category added
    later) falls through to `press`, so a new category can never be silently
    dropped from the UI. Each bucket is capped independently -- a flood of
    press coverage must never squeeze out the education findings.
    """
    profile: dict[str, list[dict]] = {"background": [], "achievements": [], "adverse": [], "press": []}
    for finding in (rep or {}).get("findings") or []:
        category = (finding.get("category") or "").strip().lower()
        polarity = (finding.get("polarity") or "").strip().lower()

        # Anything the model actually judged negative belongs in adverse, whatever
        # its category -- and nothing else does.
        if category in _PROFILE_BUCKETS["adverse"] or polarity == _NEGATIVE:
            profile["adverse"].append(finding)
            continue

        for bucket in ("background", "achievements"):
            if category in _PROFILE_BUCKETS[bucket]:
                profile[bucket].append(finding)
                break
        else:
            profile["press"].append(finding)
    return {bucket: _interleave(items, limit) for bucket, items in profile.items()}


def display_shape(d: dict[str, Any]) -> dict[str, Any]:
    """Compact a full DeckEnrichment dump down to what a UI renders.

    One shape for both live results and the seeded fixture, so the frontend
    has a single thing to render.
    """
    founders = []
    for f in d.get("founders", []):
        gh = f.get("github") or {}
        so = f.get("socials") or {}
        pa = (so.get("post_analysis") or {}) if so else {}
        founders.append({
            "name": f.get("name", ""),
            "handles": f.get("handles", {}),
            "github": {
                "username": gh.get("username"), "score": gh.get("score"),
                "grade": gh.get("grade"), "is_builder": gh.get("is_builder"),
                "dimensions": {k: gh.get(k) for k in (
                    "technical_ability", "execution_ability", "founder_product_ability",
                    "technical_background", "reputation", "growth_signals")},
                "signals": (gh.get("signals") or [])[:5],
                "red_flags": gh.get("red_flags") or [],
            } if gh else None,
            "socials": {
                "profiles": {k: {"handle": v.get("handle"), "followers": v.get("followers")}
                             for k, v in (so.get("profiles") or {}).items()},
                "post_count": len(so.get("posts") or []),
                "comment_count": len(so.get("comments") or []),
                "sample_posts": [
                    {"network": p.get("network"), "text": p.get("text"), "likes": p.get("likes", 0)}
                    for p in (so.get("posts") or [])[:5]
                ],
                "analysis": {
                    "topics": pa.get("topics", []),
                    "expertise_areas": pa.get("expertise_areas", []),
                    "sentiment": pa.get("sentiment", ""),
                    "tone": pa.get("tone", ""),
                    "credibility_signals": pa.get("credibility_signals", []),
                    "red_flags": pa.get("red_flags", []),
                },
                "sources": so.get("sources", []),
            } if so else None,
            # Bucket from the FULL sweep, not a pre-truncated slice. Findings
            # are sorted alphabetically by category, so truncating first let one
            # early category (current_role) eat the whole quota and drop
            # education/recognition entirely.
            "reputation": _trim_findings(f.get("reputation"), 20),
            "profile": founder_profile(_trim_findings(f.get("reputation"), 500), limit=8),
            "errors": f.get("errors", []),
        })
    return {
        "company_name": d.get("company_name", ""),
        "industry": d.get("industry", ""),
        "one_liner": d.get("one_liner", ""),
        "company_reputation": _trim_findings(d.get("company_reputation"), 8),
        "founders": founders,
        "errors": d.get("errors", []),
    }


# ------------------------------------------------------------------ CLI -----

def _parse_founder(spec: str) -> FounderInput:
    """`Name:github:twitter:linkedin` — trailing fields optional."""
    parts = (spec.split(":") + ["", "", "", ""])[:4]
    return FounderInput(name=parts[0], github=parts[1], twitter=parts[2], linkedin=parts[3])


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="python -m vc_brain.sourcing.enrich",
        description="Enrich a deck + founder handles into company & founder intelligence.",
    )
    parser.add_argument("--deck", default="", help="Path to the pitch deck (.pdf / .pptx)")
    parser.add_argument("--company", default="", help="Company name (skips deck extraction)")
    parser.add_argument(
        "--founder", action="append", default=[],
        help="Founder as Name:github:twitter:linkedin (repeatable)",
    )
    parser.add_argument("--no-person-reputation", action="store_true",
                        help="Skip per-founder web article research")
    args = parser.parse_args()

    if not args.deck and not args.company:
        parser.error("provide --deck or --company")

    result = asyncio.run(enrich_from_deck(
        args.deck,
        [_parse_founder(s) for s in args.founder],
        company_name=args.company,
        person_reputation=not args.no_person_reputation,
    ))
    print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
