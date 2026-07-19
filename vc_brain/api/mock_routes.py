"""Mock API for the frontend scaffold.

The screens under `frontend/templates/` are built against shapes the real
backend does not produce yet. Rather than hide fixtures inside page JavaScript,
they are served here at `/api/mock/*` so the frontend calls real HTTP for real
shapes -- which makes this module the executable half of the API contract
(the documented half is `frontend/static/api.js`).

Backend: implement the same shapes at the real `/api/*` paths, then remove the
route from `MOCKED` in `api.js`. Nothing in the page code changes.

State is per-process and resets on reload. Nothing here touches the store.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile

router = APIRouter(prefix="/api/mock", tags=["mock"])

FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "fixtures"

# Loaded once, then mutated in memory so a submitted application shows up in
# the inbox for the rest of the session.
_applications: list[dict[str, Any]] = []
_thesis: dict[str, Any] = {}


def _load(name: str) -> Any:
    try:
        return json.loads((FIXTURES / name).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _ensure_loaded() -> None:
    global _thesis
    if not _applications:
        _applications.extend(_load("applications.json") or [])
    if not _thesis:
        _thesis = _load("thesis.json") or {}


# ---------------------------------------------------------------- thesis --

@router.get("/thesis")
async def get_thesis() -> dict[str, Any]:
    _ensure_loaded()
    return _thesis


@router.put("/thesis")
async def put_thesis(update: dict[str, Any]) -> dict[str, Any]:
    global _thesis
    _ensure_loaded()
    _thesis = {**_thesis, **update}
    return _thesis


# ---------------------------------------------------------- applications --

@router.get("/applications")
async def list_applications() -> list[dict[str, Any]]:
    _ensure_loaded()
    # Newest first, which is the order an inbox is read in.
    return sorted(_applications, key=lambda a: a.get("submitted_at", ""), reverse=True)


@router.get("/applications/{app_id}")
async def get_application(app_id: str) -> dict[str, Any]:
    _ensure_loaded()
    for app in _applications:
        if app["id"] == app_id:
            return app
    # Matches the existing API's convention: 200 with an error body, not a 404.
    return {"error": f"Application {app_id} not found"}


@router.post("/applications")
async def submit_application(
    company_name: str = Form(...),
    deck: UploadFile = File(...),
    website: str = Form(""),
    one_liner: str = Form(""),
    sector: str = Form(""),
    stage: str = Form(""),
    geography: str = Form(""),
    why_now: str = Form(""),
    accelerator: str = Form(""),
    prior_companies: str = Form(""),
    product_url: str = Form(""),
    raising: str = Form(""),
    founders: str = Form("[]"),
) -> dict[str, Any]:
    """Accept an application as multipart/form-data.

    The deck is required and read only for its size -- nothing is persisted.
    This exists to prove the upload contract works end to end, since no real
    endpoint accepts a file today.
    """
    _ensure_loaded()

    body = await deck.read()
    try:
        team = json.loads(founders)
    except json.JSONDecodeError:
        team = []

    app = {
        "id": uuid4().hex[:12],
        "company_id": uuid4().hex[:12],
        "company_name": company_name,
        "one_liner": one_liner,
        "sector": sector,
        "stage": stage,
        "geography": geography,
        "website": website,
        "product_url": product_url,
        "status": "received",
        "source": "inbound",
        "submitted_at": datetime.utcnow().isoformat(),
        "raising": raising,
        "accelerator": accelerator,
        "prior_companies": prior_companies,
        "why_now": why_now,
        "deck": {
            "filename": deck.filename or "deck.pdf",
            "size_bytes": len(body),
            "uploaded_at": datetime.utcnow().isoformat(),
        },
        "founders": team,
        "applicability": _applicability(sector, stage, geography),
        # Screening has not run: the inbox renders this as "not screened yet"
        # rather than inventing zeros.
        "screening": None,
    }
    _applications.append(app)

    return {
        "application_id": app["id"],
        "status": app["status"],
        "applicability": app["applicability"],
    }


# --------------------------------------------------------- applicability --

# Crude stand-in for the sanity check. The real one is a judgement call an LLM
# makes; this only needs to be good enough to demonstrate the shape and to make
# the ice-cream-truck case fall out on the right side.
_NOT_VENTURE = (
    "ice cream", "food truck", "restaurant", "cafe", "catering",
    "salon", "retail shop", "cleaning", "landscaping",
)


def _applicability(sector: str, stage: str, geography: str) -> dict[str, Any]:
    _ensure_loaded()
    reasons: list[str] = []

    haystack = f"{sector}".lower()
    viable = not any(term in haystack for term in _NOT_VENTURE)

    # Same matching direction as ThesisEngine.fits_thesis: the thesis tag must
    # be a substring of the candidate's sector, not the other way round.
    #
    # Mirrored faithfully, false positives included -- "AI" matches inside
    # "retail", "email" and "maintain". See docs/frontend-api-contract.md; the
    # real implementation needs word-boundary matching.
    sectors = _thesis.get("sectors", [])
    sector_ok = not sector or any(s.lower() in sector.lower() for s in sectors)
    if not sector_ok:
        reasons.append(f"Sector '{sector}' matches no thesis tag: {', '.join(sectors)}")

    stages = [s.lower() for s in _thesis.get("stages", [])]
    stage_ok = not stage or stage.lower() in stages
    if not stage_ok:
        reasons.append(f"Stage '{stage}' outside mandate: {', '.join(stages)}")

    geos = _thesis.get("geographies", [])
    geo_ok = not geography or any(g.lower() in geography.lower() for g in geos)
    if not geo_ok:
        reasons.append(f"Geography '{geography}' matches no thesis region")

    thesis_fit = sector_ok and stage_ok and geo_ok
    if thesis_fit and viable:
        reasons.append("Matches sector, stage and geography")

    if not viable:
        verdict = "not_viable"
        note = "Not a venture-scale business — scales with capital, not software."
        # Stated first: a failed sanity check is the headline reason, and
        # without this the verdict could arrive with no explanation at all.
        reasons.insert(0, f"'{sector}' is an operating business, not a venture-scale company")
    elif not thesis_fit:
        verdict = "out_of_scope"
        note = "Plausible company, but outside this fund's mandate."
    else:
        verdict = "in_scope"
        note = "Nothing in the application contradicts itself."

    return {
        "applicable": verdict == "in_scope",
        "verdict": verdict,
        "reasons": reasons,
        "thesis_fit": thesis_fit,
        "sanity": {"passed": viable, "note": note},
    }
