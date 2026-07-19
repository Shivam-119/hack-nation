"""Seed the demo inbox fixtures into Memory so the app has data to show.

The React frontend was built against `frontend/fixtures/applications.json`. This
loads those 10 applications into the store (SQLite) as Founder + Company +
Application entities, so `GET /api/applications`, `/{id}` and `/api/founders`
return them. Every screening axis gets full, object-shaped SWOT (fake
opportunities/threats added) so all four quadrants render.

Idempotent — companies dedup by name, founders by email/github, applications by
id — so it is safe to run on every startup (see `ensure_seeded`).
"""

from __future__ import annotations

import json
from pathlib import Path

from vc_brain.memory.models import (
    Application,
    ApplicationStatus,
    Company,
    Founder,
)
from vc_brain.memory.store import MemoryStore

FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "fixtures" / "applications.json"

_AXES = ("founder_axis", "market_axis", "idea_vs_market_axis")

# Fake SWOT filler per axis so all four quadrants render in the 3-axis detail view.
# The frontend (AxisCard/Evidence) expects each item as {text, url?, source?}.
_FAKE_SWOT = {
    "founder_axis": {
        "opportunities": [
            "Adding a commercial hire could unlock enterprise deals the technical team can't chase alone.",
            "Strong open-source following is a ready-made top-of-funnel for design partners.",
        ],
        "threats": [
            "Two technical co-founders with no GTM owner is a common stall point at seed.",
            "Key-person risk: the product depth sits with one founder.",
        ],
    },
    "market_axis": {
        "opportunities": [
            "Regulatory tailwinds are pulling budget toward this category faster than incumbents can react.",
            "Adjacent segments open a credible expansion path once the wedge lands.",
        ],
        "threats": [
            "A well-funded incumbent could ship a 'good enough' version and compress pricing.",
            "Category timing depends on a compliance trend that could slow.",
        ],
    },
    "idea_vs_market_axis": {
        "opportunities": [
            "The narrow initial wedge is defensible and expandable if execution holds.",
            "Being self-hostable removes the top objection for the target buyer.",
        ],
        "threats": [
            "The wedge may be too narrow to reach venture scale without a second act.",
            "Buyers could treat this as a feature, not a platform.",
        ],
    },
}


def _swot_items(items: list, source: str = "") -> list[dict]:
    """Normalize a SWOT list (strings or dicts) to the FLAT {text, url, source}
    shape (used by AxisCard and the API's _axis_payload)."""
    out: list[dict] = []
    for item in items or []:
        if isinstance(item, dict):
            src = item.get("src", {}) if isinstance(item.get("src"), dict) else {}
            out.append({
                "text": item.get("text", ""),
                "url": item.get("url", src.get("url", "")),
                "source": item.get("source", src.get("label", source)),
            })
        else:
            out.append({"text": str(item), "url": "", "source": source})
    return out


def _to_src_shape(items: list[dict]) -> list[dict]:
    """Convert flat {text, url, source} items to the NESTED {text, src:{url, label}}
    shape the detail view's SourceAxis component reads (axis.swot.<quadrant>)."""
    return [{"text": i["text"], "src": {"url": i.get("url", ""), "label": i.get("source", "")}}
            for i in items]


def _enrich_screening(screening: dict | None) -> dict | None:
    """Give every axis full SWOT in BOTH shapes the frontend uses:
    flat `axis.<quadrant>` (AxisCard) and nested `axis.swot.<quadrant>` (SourceAxis,
    used by the inbox detail view). Fake opportunities/threats are added."""
    if not screening:
        return screening
    for axis_key in _AXES:
        axis = screening.get(axis_key)
        if not isinstance(axis, dict):
            continue
        fake = _FAKE_SWOT.get(axis_key, {})
        axis["strengths"] = _swot_items(axis.get("strengths"), source="Screening")
        axis["weaknesses"] = _swot_items(axis.get("weaknesses"), source="Screening")
        axis["opportunities"] = _swot_items(
            axis.get("opportunities") or fake.get("opportunities"), source="Analyst view")
        axis["threats"] = _swot_items(
            axis.get("threats") or fake.get("threats"), source="Analyst view")
        axis["swot"] = {
            quadrant: _to_src_shape(axis[quadrant])
            for quadrant in ("strengths", "weaknesses", "opportunities", "threats")
        }
    return screening


def _founder(data: dict) -> Founder:
    """Map a fixture founder (POST-input shape) to a Founder entity."""
    return Founder(
        name=data.get("name") or "Unknown",
        email=data.get("email", ""),
        github_url=data.get("github", ""),
        twitter_url=data.get("twitter", ""),
        linkedin_url=data.get("linkedin", ""),
    )


def seed(store: MemoryStore, apps: list[dict]) -> tuple[int, int, int]:
    """Upsert every fixture application (+ its company and founders) into the store."""
    founders_seen: set[str] = set()
    companies_seen: set[str] = set()

    for app in apps:
        founder_ids: list[str] = []
        for fdata in app.get("founders", []):
            founder = store.upsert_founder(_founder(fdata))
            founder_ids.append(founder.id)
            founders_seen.add(founder.id)

        company = store.upsert_company(Company(
            id=app["company_id"],
            name=app["company_name"],
            website=app.get("website", ""),
            sector=app.get("sector", ""),
            stage=app.get("stage", ""),
            geography=app.get("geography", ""),
            description=app.get("one_liner", ""),
            founder_ids=founder_ids,
        ))
        companies_seen.add(company.id)

        screening = _enrich_screening(app.get("screening"))
        # A fixture may carry a precomputed enrichment (the sourcing scanners'
        # output). Stash it where the live pipeline puts it, so seeded and
        # freshly-evaluated applications render through the same path.
        artifacts = {"enrichment": app["enrichment"]} if app.get("enrichment") else {}
        has_result = bool(screening) or bool(artifacts)
        deck = app.get("deck") or {}
        store.add_application(Application(
            id=app["id"],
            company_id=company.id,
            founder_ids=founder_ids,
            status=ApplicationStatus(app.get("status", "received")),
            source_channel=app.get("source", "inbound"),
            submitted_at=app["submitted_at"],
            one_liner=app.get("one_liner", ""),
            website=app.get("website", ""),
            product_url=app.get("product_url", ""),
            raising=app.get("raising", ""),
            why_now=app.get("why_now", ""),
            accelerator=app.get("accelerator", ""),
            prior_companies=app.get("prior_companies", ""),
            deck_filename=deck.get("filename", ""),
            applicability=app.get("applicability"),
            screening_result=screening,
            evaluation_artifacts=artifacts,
            evaluation_state="evaluated" if has_result else "queued",
            evaluation_completed_at=app["submitted_at"] if has_result else None,
        ))

    return len(apps), len(founders_seen), len(companies_seen)


def load_fixture(path: str | Path | None = None) -> list[dict]:
    return json.loads(Path(path or FIXTURE).read_text())


def ensure_seeded(store: MemoryStore | None = None, path: str | Path | None = None) -> MemoryStore:
    """Seed the demo apps if any are missing. Safe to call on every startup."""
    store = store or MemoryStore()
    apps = load_fixture(path)
    fixture_ids = {app["id"] for app in apps}
    if fixture_ids.issubset(store.applications.keys()):
        return store  # already seeded — nothing to do
    seed(store, apps)
    return store
