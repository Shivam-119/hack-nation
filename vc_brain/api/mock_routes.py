"""Mock API for the frontend scaffold.

The screens under `frontend/templates/` are built against shapes the real
backend does not produce yet. Rather than hide fixtures inside page JavaScript,
they are served here at `/api/mock/*` so the frontend calls real HTTP for real
shapes -- which makes this module the executable half of the API contract
(the documented half is `frontend/static/api.js`).

Backend: implement the same shapes at the real `/api/*` paths, then remove the
route from `MOCKED` in `api.js`. Nothing in the page code changes.

Everything here is a stand-in. The scoring is a handful of weighted string
comparisons, not judgement -- it exists to give the UI realistic shapes to
render, and to make the demo move when the input moves. State is per-process
and resets on reload.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, Response, UploadFile

router = APIRouter(prefix="/api/mock", tags=["mock"])

FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "fixtures"

_applications: list[dict[str, Any]] = []
_thesis: dict[str, Any] = {}
# Uploaded decks, kept in memory so the link on the detail page returns the
# actual file the founder submitted.
_decks: dict[str, bytes] = {}


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
    """Saving criteria is what lifts the first-run gate on the inbox."""
    global _thesis
    _ensure_loaded()
    _thesis = {**_thesis, **update, "configured": True}
    return _thesis


# ---------------------------------------------------------- applications --

@router.get("/applications")
async def list_applications() -> list[dict[str, Any]]:
    _ensure_loaded()
    return sorted(_applications, key=lambda a: a.get("submitted_at", ""), reverse=True)


@router.get("/applications/{app_id}")
async def get_application(app_id: str) -> dict[str, Any]:
    _ensure_loaded()
    for app in _applications:
        if app["id"] == app_id:
            return app
    # Matches the existing API's convention: 200 with an error body, not a 404.
    return {"error": f"Application {app_id} not found"}


@router.get("/applications/{app_id}/deck")
async def get_deck(app_id: str) -> Response:
    """Return the deck for an application.

    An uploaded deck comes back verbatim. Fixture applications have no bytes
    behind them, so a placeholder naming the company is generated instead --
    the link is never dead.
    """
    _ensure_loaded()

    if app_id in _decks:
        return Response(_decks[app_id], media_type="application/pdf")

    for app in _applications:
        if app["id"] == app_id:
            name = app.get("deck", {}).get("filename", "deck.pdf")
            return Response(
                _placeholder_pdf(app["company_name"]),
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="{name}"'},
            )

    return Response(b"Not found", status_code=404, media_type="text/plain")


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
    """Accept an application as multipart/form-data and screen it immediately."""
    _ensure_loaded()

    body = await deck.read()
    try:
        team = json.loads(founders)
    except json.JSONDecodeError:
        team = []

    app_id = uuid4().hex[:12]
    _decks[app_id] = body

    app = {
        "id": app_id,
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
        "applicability": _fit(sector, stage, geography),
        "screening": None,
    }

    # Screening runs on submission, not on a button press. The fit score is the
    # cheap filter in front of it: a company that fails the viability check is
    # never screened, which is the point of having a cheap gate before an
    # expensive one.
    if app["applicability"]["sanity"]["passed"] and app["applicability"]["fit_score"] >= 40:
        app["screening"] = _screen(app)
        app["status"] = "screening"

    _applications.append(app)

    return {
        "application_id": app["id"],
        "status": app["status"],
        "applicability": app["applicability"],
        "screening": app["screening"],
    }


# ------------------------------------------------------------- fit score --

# How much each criterion is worth. Mock weights -- the real scorer would earn
# these rather than declare them.
WEIGHTS = {"Sector": 40, "Stage": 25, "Geography": 20, "Desires": 15}

# Crude stand-in for the viability check. The real one is a judgement an LLM
# makes; this only needs to be good enough to demonstrate the shape and put the
# ice-cream-truck case on the right side of the line.
_NOT_VENTURE = (
    "ice cream", "food truck", "restaurant", "cafe", "catering",
    "salon", "retail shop", "cleaning", "landscaping", "barber",
)


def _fit(sector: str, stage: str, geography: str) -> dict[str, Any]:
    """Score how well an application matches the configured criteria.

    Returns the score alongside the breakdown that produced it, so the number
    is explainable on screen rather than arriving as an oracle.
    """
    _ensure_loaded()

    viable = not any(term in sector.lower() for term in _NOT_VENTURE)
    if not viable:
        return {
            "fit_score": 0,
            "sanity": {
                "passed": False,
                "note": "Not a venture-scale business — it scales with capital, not software.",
            },
            "breakdown": [
                {"label": k, "weight": v, "awarded": 0,
                 "note": "Not scored — failed the viability check"}
                for k, v in WEIGHTS.items()
            ],
        }

    # Same matching direction as ThesisEngine.fits_thesis: the thesis tag must
    # be a substring of the candidate's value. Mirrored faithfully, false
    # positives included -- "AI" matches inside "retail". See
    # docs/frontend-api-contract.md; the real version needs word boundaries.
    sectors = _thesis.get("sectors", [])
    stages = [s.lower() for s in _thesis.get("stages", [])]
    geos = _thesis.get("geographies", [])

    sector_ok = bool(sector) and any(s.lower() in sector.lower() for s in sectors)
    stage_ok = bool(stage) and stage.lower() in stages
    geo_ok = bool(geography) and any(g.lower() in geography.lower() for g in geos)

    breakdown = [
        {
            "label": "Sector", "weight": WEIGHTS["Sector"],
            "awarded": WEIGHTS["Sector"] if sector_ok else 0,
            "note": f"'{sector}' matches thesis tag" if sector_ok
                    else f"'{sector or 'not given'}' matches no thesis tag: {', '.join(sectors)}",
        },
        {
            "label": "Stage", "weight": WEIGHTS["Stage"],
            "awarded": WEIGHTS["Stage"] if stage_ok else 0,
            "note": f"{stage} is in mandate" if stage_ok
                    else f"'{stage or 'not given'}' outside mandate: {', '.join(stages)}",
        },
        {
            "label": "Geography", "weight": WEIGHTS["Geography"],
            "awarded": WEIGHTS["Geography"] if geo_ok else 0,
            "note": f"'{geography}' matches a thesis region" if geo_ok
                    else f"'{geography or 'not given'}' matches no thesis region",
        },
        {
            # Honest about its own limits: desires are about the team and what
            # they have shipped, which a form cannot establish on its own.
            "label": "Desires", "weight": WEIGHTS["Desires"], "awarded": 0,
            "note": "Not assessed from the form — needs the deck and public profiles",
        },
    ]

    return {
        "fit_score": sum(b["awarded"] for b in breakdown),
        "sanity": {"passed": True, "note": "Nothing in the application contradicts itself."},
        "breakdown": breakdown,
    }


# -------------------------------------------------------------- screening --

def _axis(score: float, strengths: list[str], weaknesses: list[str],
          evidence: list[str], confidence: float) -> dict[str, Any]:
    score = max(0.0, min(100.0, score))
    return {
        "score": round(score, 1),
        "sentiment": "bullish" if score >= 60 else "bear" if score < 35 else "neutral",
        # A first submission has no history, so there is no trend to report.
        "trend": "stable",
        "confidence": confidence,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "evidence": evidence,
    }


def _screen(app: dict[str, Any]) -> dict[str, Any]:
    """Stand-in for the real screener.

    Derived from what the applicant supplied rather than random: a team that
    gave GitHub handles scores differently from one that gave nothing. That
    keeps the demo coherent -- the numbers move when the input moves -- and
    shows why the extra form fields are worth asking for.
    """
    founders = app.get("founders") or []
    handles = [f for f in founders if f.get("github") or f.get("twitter") or f.get("linkedin")]

    f_score, f_up, f_down, f_ev = 45.0, [], [], []
    if handles:
        f_score += 14
        f_up.append(f"{len(handles)} founder(s) supplied public profiles we can verify directly")
        f_ev += [f"{f.get('name') or 'founder'} — github/{f['github']}"
                 for f in founders if f.get("github")]
    else:
        f_down.append("No public profiles supplied — nothing to verify the team against")
    if len(founders) > 1:
        f_score += 9
        f_up.append(f"{len(founders)} co-founders, so the work is split")
    elif founders:
        f_down.append("Solo founder")
    else:
        f_down.append("No founders named on the application")
    if app.get("prior_companies"):
        f_score += 11
        f_up.append("Has built something before")
        f_ev.append(f"Application answer: {app['prior_companies'][:90]}")
    if app.get("accelerator"):
        f_score += 8
        f_up.append(f"Accelerator: {app['accelerator']}")

    # Weakest of the three from a form alone: sizing needs the deck and outside
    # research, neither of which this stand-in reads.
    m_score, m_up, m_down = 50.0, [], []
    if app.get("sector"):
        m_up.append(f"Operates in {app['sector']}, which is inside the mandate")
    m_down.append("Market size not assessed — needs the deck and external research")
    if not app.get("product_url"):
        m_down.append("No live product to gauge demand from")

    i_score, i_up, i_down, i_ev = 45.0, [], [], []
    why = (app.get("why_now") or "").strip()
    if len(why) > 80:
        i_score += 16
        i_up.append("Gives a specific reason this is buildable now rather than a general tailwind")
        i_ev.append(f"Application answer, why now: {why[:120]}")
    elif why:
        i_score += 5
        i_down.append("Why-now is stated but thin")
    else:
        i_down.append("No why-now given — the central pre-seed question is unanswered")
    if app.get("product_url"):
        i_score += 9
        i_up.append("Something is already shipped and inspectable")
        i_ev.append(f"Product: {app['product_url']}")
    else:
        i_down.append("Nothing shipped to look at yet")
    if app.get("one_liner"):
        i_score += 6
    else:
        i_down.append("No plain-language description of what it does")

    return {
        "founder_axis": _axis(f_score, f_up, f_down, f_ev, 0.55 if handles else 0.3),
        "market_axis": _axis(m_score, m_up, m_down, [], 0.25),
        "idea_vs_market_axis": _axis(i_score, i_up, i_down, i_ev, 0.45),
        "passes_screen": True,
        "rejection_reasons": [],
    }


# ------------------------------------------------------- placeholder deck --

def _placeholder_pdf(company: str) -> bytes:
    """Build a one-page PDF naming the company.

    Fixture applications have no uploaded bytes, and a dead link is worse than
    an obviously-fake document. Hand-built rather than pulled from a library:
    pypdf only reads, and this is not worth a new dependency.
    """
    safe = "".join(c for c in company if c.isprintable()).replace("(", "").replace(")", "")
    content = (
        f"BT /F1 24 Tf 60 760 Td ({safe}) Tj ET\n"
        f"BT /F1 12 Tf 60 726 Td (Placeholder deck - VC Brain scaffold) Tj ET\n"
        f"BT /F1 10 Tf 60 700 Td (No file was uploaded for this application.) Tj ET"
    ).encode("latin-1", "replace")

    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(content)).encode() + b">>stream\n" + content + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj".encode() + body + b"endobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)
