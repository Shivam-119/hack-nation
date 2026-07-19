"""Seed the mock inbox fixtures into the SQLite DB the API reads from.

The frontend was built against `frontend/fixtures/applications.json`. As the real
endpoints (which read from `MemoryStore` → SQLite) come online, this loads those
same 10 applications into the DB as Founder + Company + Application entities, so
`GET /api/applications`, `/api/applications/{id}`, and `/api/founders` return them.

Idempotent: companies dedup by name, founders by email/github, applications by id,
so re-running updates in place rather than duplicating.

    python -m scripts.seed_mock_data            # -> config.database_url (./vc_brain.db)
    python -m scripts.seed_mock_data --store x.db
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vc_brain.memory.models import (
    Application,
    ApplicationStatus,
    Company,
    Founder,
)
from vc_brain.memory.store import MemoryStore

FIXTURE = Path(__file__).resolve().parents[1] / "frontend" / "fixtures" / "applications.json"

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
    """Normalize a SWOT list (strings or dicts) to the {text, url, source} shape
    the frontend Evidence component renders."""
    out: list[dict] = []
    for item in items or []:
        if isinstance(item, dict):
            out.append({
                "text": item.get("text", ""),
                "url": item.get("url", item.get("src", {}).get("url", "")),
                "source": item.get("source", item.get("src", {}).get("label", source)),
            })
        else:
            out.append({"text": str(item), "url": "", "source": source})
    return out


def _enrich_screening(screening: dict | None) -> dict | None:
    """Give every axis full, object-shaped SWOT (fake opportunities/threats added)."""
    if not screening:
        return screening
    for axis_key in _AXES:
        axis = screening.get(axis_key)
        if not isinstance(axis, dict):
            continue
        axis["strengths"] = _swot_items(axis.get("strengths"), source="Screening")
        axis["weaknesses"] = _swot_items(axis.get("weaknesses"), source="Screening")
        fake = _FAKE_SWOT.get(axis_key, {})
        if not axis.get("opportunities"):
            axis["opportunities"] = _swot_items(fake.get("opportunities"), source="Analyst view")
        else:
            axis["opportunities"] = _swot_items(axis["opportunities"], source="Analyst view")
        if not axis.get("threats"):
            axis["threats"] = _swot_items(fake.get("threats"), source="Analyst view")
        else:
            axis["threats"] = _swot_items(axis["threats"], source="Analyst view")
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
    founders_seen: set[str] = set()
    companies_seen: set[str] = set()

    for app in apps:
        # Founders first — upsert dedups by email/github and returns stable ids.
        founder_ids: list[str] = []
        for fdata in app.get("founders", []):
            founder = store.upsert_founder(_founder(fdata))
            founder_ids.append(founder.id)
            founders_seen.add(founder.id)

        # Company (id preserved from the fixture so links stay stable).
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

        # Application (the read path re-derives company/founder fields from the
        # entities above and passes `screening`/`applicability` through untouched).
        screening = _enrich_screening(app.get("screening"))
        has_screen = bool(screening)
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
            evaluation_state="evaluated" if has_screen else "queued",
            evaluation_completed_at=app["submitted_at"] if has_screen else None,
        ))

    return len(apps), len(founders_seen), len(companies_seen)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed mock inbox data into the DB")
    parser.add_argument("--store", default=None, help="SQLite file (default: config.database_url)")
    parser.add_argument("--fixture", default=str(FIXTURE), help="applications.json path")
    args = parser.parse_args()

    apps = json.loads(Path(args.fixture).read_text())
    store = MemoryStore(path=args.store) if args.store else MemoryStore()
    n_apps, n_founders, n_companies = seed(store, apps)
    print(f"seeded {n_apps} applications, {n_founders} founders, {n_companies} companies")


if __name__ == "__main__":
    main()
