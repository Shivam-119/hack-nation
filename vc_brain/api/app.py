"""FastAPI application: the VC Brain API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vc_brain.intelligence.diligence import DiligenceEngine
from vc_brain.intelligence.memo_generator import MemoGenerator
from vc_brain.intelligence.reasoning import ReasoningEngine
from vc_brain.intelligence.screener import Screener
from vc_brain.intelligence.thesis_engine import FundThesis, ThesisEngine
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.models import DataPoint, Founder, SourceType
from vc_brain.memory.store import MemoryStore
from vc_brain.api import keepalive
from vc_brain.evaluation import stages
from vc_brain.evaluation.service import run_evaluation

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
store = MemoryStore()
# Seed the demo inbox if the store is empty. Idempotent (keyed on fixture ids),
# so it is a no-op once the data is present.
try:
    from vc_brain.memory.seed import ensure_seeded

    ensure_seeded(store)
except Exception:  # pragma: no cover -- seeding must never block startup
    pass
pipeline = IngestionPipeline(store)
thesis: FundThesis | None = None
thesis_engine: ThesisEngine | None = None
screener = Screener()
diligence_engine = DiligenceEngine()
memo_generator = MemoGenerator()
reasoning_engine = ReasoningEngine(store)

app = FastAPI(title="VC Brain", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
DIST = FRONTEND / "dist"
UPLOADS = Path(__file__).resolve().parents[2] / "uploads"
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class ThesisUpdate(BaseModel):
    name: str = "VC Brain"
    sectors: list[str] = []
    stages: list[str] = ["pre-seed", "seed"]
    geographies: list[str] = []
    risk_appetite: str = "moderate"
    desires: list[str] = []
    check_size_min: int = 100_000
    check_size_max: int = 100_000
    target_ownership_pct: float = 0.0


class SearchQuery(BaseModel):
    query: str
    limit: int


# ---------------------------------------------------------------------------
# Routes: Thesis
# ---------------------------------------------------------------------------
DEFAULT_THESIS = {
    "name": "Maschmeyer Group — VC Brain",
    "sectors": ["AI", "fintech", "SaaS", "health"],
    "stages": ["pre-seed", "seed"],
    "geographies": ["Germany", "DACH", "Europe"],
    "risk_appetite": "moderate",
    "desires": [],
    "configured": False,
}


def _applicability(sector: str, stage: str, geography: str, desires: list[str]) -> dict[str, Any]:
    weights = {"Sector": 40, "Stage": 25, "Geography": 20, "Desires": 15}
    non_venture = ("ice cream", "food truck", "restaurant", "cafe", "salon", "barber")
    if any(term in f"{sector} {desires}".lower() for term in non_venture):
        return {"fit_score": 0, "sanity": {"passed": False, "note": "The application does not appear to be a venture-scale software business."}, "breakdown": [{"label": label, "weight": weight, "awarded": 0, "note": "Not scored after the viability check"} for label, weight in weights.items()]}
    active = thesis_engine
    sector_ok = bool(active and sector and any(active.fits_thesis(sector, "", "")[0] for _ in [0]))
    stage_ok = bool(active and stage and active.fits_thesis("", stage, "")[0])
    geo_ok = bool(active and geography and active.fits_thesis("", "", geography)[0])
    breakdown = [
        {"label": "Sector", "weight": 40, "awarded": 40 if sector_ok else 0, "note": "Matches fund sector" if sector_ok else "Outside the configured sectors"},
        {"label": "Stage", "weight": 25, "awarded": 25 if stage_ok else 0, "note": "Matches fund stage" if stage_ok else "Outside the configured stages"},
        {"label": "Geography", "weight": 20, "awarded": 20 if geo_ok else 0, "note": "Matches fund geography" if geo_ok else "Outside the configured geographies"},
        {"label": "Desires", "weight": 15, "awarded": 0, "note": "Requires screening of the deck and founder profiles"},
    ]
    return {"fit_score": sum(item["awarded"] for item in breakdown), "sanity": {"passed": True, "note": "No immediate viability contradiction found."}, "breakdown": breakdown}


def _axis_payload(axis: dict[str, Any]) -> dict[str, Any]:
    data = dict(axis)
    for key in ("strengths", "weaknesses", "opportunities", "threats"):
        data.setdefault(key, [])
    if not data["strengths"]:
        data["strengths"] = [{"text": item} for item in data.get("evidence", [])]
    return data


def _evaluation_payload(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    """Adapt the reasoning layer's FinalDecision without creating a second model."""
    if not decision or not {"founder_axis", "market_axis", "idea_vs_market_axis"} <= decision.keys():
        return None
    axes = {}
    for source, target in (("founder_axis", "founder_axis"), ("market_axis", "market_axis"), ("idea_vs_market_axis", "idea_vs_market_axis")):
        axis = dict(decision[source])
        evidence = axis.get("key_evidence", [])
        strengths = [{"text": item.get("point", ""), "src": {"label": item.get("source", ""), "url": item.get("url", "")}} for item in evidence]
        axes[target] = {
            "score": axis.get("fit_score_pct", 0), "sentiment": axis.get("rating", "neutral"),
            "trend": axis.get("trend", "stable"), "confidence": axis.get("confidence_pct", 0) / 100,
            "strengths": [{"text": item["text"], "source": item["src"]["label"], "url": item["src"]["url"]} for item in strengths],
            "weaknesses": [], "opportunities": [], "threats": [], "evidence": [item.get("point", "") for item in evidence],
            "rationale": axis.get("rationale", axis.get("verdict", "")),
            "swot": {"strengths": strengths, "weaknesses": [], "opportunities": [], "threats": []},
        }
    return {**axes, "thesis_fit": decision.get("thesis_fit", {}), "recommendation": decision.get("recommendation"), "rationale": decision.get("rationale", ""), "adversarial_view": decision.get("adversarial_view", ""), "gaps_and_caveats": decision.get("gaps_and_caveats", [])}


def _application_payload(application: Any) -> dict[str, Any]:
    company = store.get_company(application.company_id)
    founders = [store.get_founder(founder_id) for founder_id in application.founder_ids]
    evaluation = _evaluation_payload(application.decision)
    screening = evaluation or application.screening_result
    if screening:
        screening = dict(screening)
        for key in ("founder_axis", "market_axis", "idea_vs_market_axis"):
            screening[key] = _axis_payload(screening.get(key, {}))
    highlights = []
    if screening:
        for axis_key in ("founder_axis", "market_axis", "idea_vs_market_axis"):
            highlights.extend(item.get("text", "") for item in screening.get(axis_key, {}).get("strengths", [])[:1])
    return {
        "id": application.id, "company_id": application.company_id,
        "company_name": company.name if company else "Unknown", "one_liner": application.one_liner or (company.description if company else ""),
        "sector": company.sector if company else "", "stage": company.stage if company else "", "geography": company.geography if company else "",
        "website": application.website or (company.website if company else ""), "product_url": application.product_url,
        "raising": application.raising, "why_now": application.why_now, "accelerator": application.accelerator, "prior_companies": application.prior_companies,
        "status": application.status.value, "source": application.source_channel, "submitted_at": application.submitted_at.isoformat(),
        "deck": {"filename": application.deck_filename, "size_bytes": application.deck_size_bytes},
        "founders": [founder.model_dump(mode="json") for founder in founders if founder],
        "applicability": application.applicability or _applicability("", "", "", []), "screening": screening,
        "evaluation": evaluation,
        "enrichment": application.evaluation_artifacts.get("enrichment"),
        "enrichment_error": application.evaluation_artifacts.get("enrichment_error"),
        "highlights": [item for item in highlights if item][:4],
        "evaluation_state": application.evaluation_state,
        "evaluation_failure_reason": application.evaluation_failure_reason,
        "evaluation_started_at": application.evaluation_started_at.isoformat() if application.evaluation_started_at else None,
        "evaluation_completed_at": application.evaluation_completed_at.isoformat() if application.evaluation_completed_at else None,
        "evaluation_progress": stages.progress_payload(application),
    }


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """Cheap liveness probe. Also the keep-alive ping target, so it must stay
    free of database work -- it can be hit every few minutes for the length of
    an evaluation."""
    return {"ok": True}


@app.get("/api/thesis")
async def get_thesis() -> dict[str, Any]:
    if not thesis:
        return DEFAULT_THESIS
    return {**thesis.model_dump(), "desires": thesis.preferred_signals + thesis.anti_signals, "configured": True}


@app.put("/api/thesis")
async def update_thesis(update: ThesisUpdate) -> dict[str, Any]:
    global thesis, thesis_engine
    anti_signals = [item for item in update.desires if item.lower().startswith(("no ", "not "))]
    thesis = FundThesis(**update.model_dump(exclude={"desires"}), preferred_signals=[item for item in update.desires if item not in anti_signals], anti_signals=anti_signals)
    thesis_engine = ThesisEngine(thesis)
    return {**thesis.model_dump(), "desires": update.desires, "configured": True}


# ---------------------------------------------------------------------------
# Routes: Inbound Applications
# ---------------------------------------------------------------------------
@app.post("/api/applications")
async def submit_application(
    background_tasks: BackgroundTasks,
    company_name: str = Form(...), deck: UploadFile = File(...), website: str = Form(""),
    one_liner: str = Form(""), sector: str = Form(""), stage: str = Form(""), geography: str = Form(""),
    why_now: str = Form(""), accelerator: str = Form(""), prior_companies: str = Form(""),
    product_url: str = Form(""), founders: str = Form("[]"),
) -> dict[str, Any]:
    """Ingest a real founder submission into the existing entity pipeline."""
    filename = Path(deck.filename or "deck.pdf").name
    if Path(filename).suffix.lower() not in {".pdf", ".pptx"}:
        raise HTTPException(status_code=422, detail="Deck must be a PDF or PPTX file")
    try:
        submitted_founders = json.loads(founders)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Founders must be JSON") from exc
    if not isinstance(submitted_founders, list):
        raise HTTPException(status_code=422, detail="Founders must be a list")
    primary = submitted_founders[0] if submitted_founders else {}
    application = pipeline.ingest_application(
        company_name=company_name, founder_name=primary.get("name", ""), founder_email=primary.get("email", ""),
        extra_fields={"sector": sector, "stage": stage, "geography": geography, "description": one_liner},
    )
    destination = UPLOADS / application.id / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(await deck.read())
    application.deck_path = str(destination)
    application.deck_text = pipeline._extract_deck_text(str(destination)) if destination.suffix.lower() == ".pdf" else ""
    application.deck_filename, application.deck_content_type = filename, deck.content_type or "application/octet-stream"
    application.deck_size_bytes = destination.stat().st_size
    application.website, application.product_url, application.raising = website, product_url, "$100K"
    application.one_liner, application.why_now = one_liner, why_now
    application.accelerator, application.prior_companies = accelerator, prior_companies
    company = store.get_company(application.company_id)
    # ingest_application creates the primary founder from name + email only.
    # Carry their handles over too, or socials/GitHub have nothing to run on.
    if application.founder_ids and primary:
        lead = store.get_founder(application.founder_ids[0])
        if lead:
            lead.github_url = primary.get("github", "") or lead.github_url
            lead.twitter_url = primary.get("twitter", "") or lead.twitter_url
            lead.linkedin_url = primary.get("linkedin", "") or lead.linkedin_url
            store.upsert_founder(lead)
    for founder_data in submitted_founders[1:]:
        founder = store.upsert_founder(Founder(name=founder_data.get("name") or "Unknown", email=founder_data.get("email", ""), github_url=founder_data.get("github", ""), twitter_url=founder_data.get("twitter", ""), linkedin_url=founder_data.get("linkedin", "")))
        application.founder_ids.append(founder.id)
        if company and founder.id not in company.founder_ids:
            company.founder_ids.append(founder.id)
    if company:
        company.website = website or company.website
        store.upsert_company(company)

    application.applicability = _applicability(sector, stage, geography, [str(item) for item in submitted_founders])
    application.evaluation_state = "queued"
    store.add_application(application)
    background_tasks.add_task(run_evaluation, store, application.id, thesis)
    keepalive.ensure_running(store)

    return {
        "application_id": application.id,
        "status": application.status.value, "evaluation_state": application.evaluation_state,
        "applicability": application.applicability,
        "screening": None,
    }


@app.get("/api/applications")
async def list_applications(status: str | None = None) -> list[dict[str, Any]]:
    applications = [
        _application_payload(application)
        for application in sorted(store.list_applications(status), key=lambda item: item.submitted_at, reverse=True)
    ]
    return applications


@app.get("/api/applications/{app_id}")
async def get_application(app_id: str) -> dict[str, Any]:
    application = store.get_application(app_id)
    if not application:
        return {"error": "Application not found"}
    return _application_payload(application)


@app.get("/api/applications/{app_id}/deck")
async def get_application_deck(app_id: str):
    application = store.get_application(app_id)
    if not application or not application.deck_path or not Path(application.deck_path).is_file():
        raise HTTPException(status_code=404, detail="Deck not found")
    return FileResponse(application.deck_path, media_type=application.deck_content_type or "application/pdf", filename=application.deck_filename)


@app.get("/api/applications/{app_id}/evaluation")
async def get_application_evaluation(app_id: str) -> dict[str, Any]:
    application = store.get_application(app_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    evaluation = _evaluation_payload(application.decision)
    return {
        "state": application.evaluation_state,
        "failure_reason": application.evaluation_failure_reason,
        "progress": stages.progress_payload(application),
        "result": evaluation,
    }


@app.post("/api/applications/{app_id}/evaluation")
async def queue_application_evaluation(app_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Queue a new evaluation, including retrying a previously failed one."""
    application = store.get_application(app_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.evaluation_state in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Evaluation is already in progress")
    application.evaluation_state = "queued"
    application.evaluation_failure_reason = ""
    application.evaluation_completed_at = None
    store.add_application(application)
    background_tasks.add_task(run_evaluation, store, application.id, thesis)
    keepalive.ensure_running(store)
    return {"application_id": application.id, "state": application.evaluation_state}


@app.post("/api/applications/{app_id}/screen")
async def screen_application(app_id: str) -> dict[str, Any]:
    """Run 3-axis screening on an application."""
    application = store.get_application(app_id)
    if not application:
        return {"error": "Application not found"}

    company = store.get_company(application.company_id)
    if not company:
        return {"error": "Company not found"}

    founders = [store.get_founder(fid) for fid in application.founder_ids]
    founders = [f for f in founders if f]

    result = await screener.screen(
        application, company, founders,
        thesis_context=(f"Sectors: {thesis.sectors}, Stages: {thesis.stages}" if thesis else "No thesis configured"),
    )

    application.screening_result = result.model_dump(mode="json")
    application.status = application.status.__class__("screening")
    store.add_application(application)

    return result.model_dump(mode="json")


@app.post("/api/applications/{app_id}/diligence")
async def run_diligence(app_id: str) -> dict[str, Any]:
    """Run diligence on a screened application."""
    application = store.get_application(app_id)
    if not application:
        return {"error": "Application not found"}

    company = store.get_company(application.company_id)
    if not company:
        return {"error": "Company not found"}

    founders = [store.get_founder(fid) for fid in application.founder_ids]
    founders = [f for f in founders if f]

    report = await diligence_engine.run_diligence(application, company, founders)

    application.diligence_result = report.model_dump(mode="json")
    application.status = application.status.__class__("diligence")
    store.add_application(application)

    return report.model_dump(mode="json")


@app.post("/api/applications/{app_id}/memo")
async def generate_memo(app_id: str) -> dict[str, Any]:
    """Generate an investment memo for an application that has been screened and diligenced."""
    application = store.get_application(app_id)
    if not application:
        return {"error": "Application not found"}

    company = store.get_company(application.company_id)
    if not company:
        return {"error": "Company not found"}

    founders = [store.get_founder(fid) for fid in application.founder_ids]
    founders = [f for f in founders if f]

    from vc_brain.intelligence.screener import ScreeningResult
    from vc_brain.intelligence.diligence import DiligenceReport

    screening = ScreeningResult(**(application.screening_result or {}))
    diligence = DiligenceReport(**(application.diligence_result or {"company_id": company.id}))

    memo = await memo_generator.generate(application, company, founders, screening, diligence)

    application.decision = memo.model_dump(mode="json")
    application.status = application.status.__class__("decision")
    store.add_application(application)

    return memo.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Routes: Founders
# ---------------------------------------------------------------------------
@app.get("/api/founders")
async def list_founders() -> list[dict[str, Any]]:
    return [
        {
            "id": f.id,
            "name": f.name,
            "location": f.location,
            "skills": f.skills[:5],
            "score": f.score.overall,
            "trend": f.score.trend.value,
        }
        for f in store.founders.values()
    ]


@app.get("/api/founders/{founder_id}")
async def get_founder(founder_id: str) -> dict[str, Any]:
    founder = store.get_founder(founder_id)
    if not founder:
        return {"error": "Founder not found"}
    return founder.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Routes: Search / Reasoning
# ---------------------------------------------------------------------------
@app.post("/api/search")
async def search(query: SearchQuery) -> list[dict[str, Any]]:
    """Multi-attribute natural-language search over the knowledge base."""
    return await reasoning_engine.query(query.query, query.limit)


# ---------------------------------------------------------------------------
# Routes: Outbound Sourcing
# ---------------------------------------------------------------------------
class GitHubSearchRequest(BaseModel):
    sectors: list[str]
    languages: list[str]
    locations: list[str] = []
    max_candidates: int = 15


@app.post("/api/sourcing/github")
async def scan_github(req: GitHubSearchRequest | None = None) -> dict[str, Any]:
    """Find and evaluate founders on GitHub based on investor criteria."""
    from vc_brain.sourcing.github_agent import GitHubSourcingAgent, InvestorCriteria

    if req is None:
        req = GitHubSearchRequest()

    criteria = InvestorCriteria(
        sectors=req.sectors,
        languages=req.languages,
        locations=req.locations,
    )
    agent = GitHubSourcingAgent(criteria)
    candidates = await agent.run(max_candidates=req.max_candidates)

    # Persist each evaluated candidate into memory
    for c in candidates:
        founder = Founder(
            name=c.name or c.username,
            github_url=c.profile_url,
            location=c.location or "",
            data_points=[
                DataPoint(
                    source=SourceType.GITHUB,
                    source_url=c.profile_url,
                    content={
                        "type": "github_evaluation",
                        "username": c.username,
                        "score": c.evaluation.score,
                        "grade": c.evaluation.grade,
                        "technical_ability": c.evaluation.technical_ability,
                        "execution_ability": c.evaluation.execution_ability,
                        "founder_product_ability": c.evaluation.founder_product_ability,
                        "technical_background": c.evaluation.technical_background,
                        "reputation": c.evaluation.reputation,
                        "growth_signals": c.evaluation.growth_signals,
                        "signals": c.evaluation.signals,
                        "red_flags": c.evaluation.red_flags,
                    },
                    confidence=0.7,
                )
            ],
        )
        store.upsert_founder(founder)

    return {
        "total_evaluated": len(candidates),
        "strong_matches": len([c for c in candidates if c.verdict == "strong_match"]),
        "candidates": [
            {
                "username": c.username,
                "name": c.name,
                "location": c.location,
                "profile_url": c.profile_url,
                "verdict": c.verdict,
                "builder_grade": c.evaluation.grade,
                "builder_score": c.evaluation.score,
                "thesis_fit": c.thesis_fit,
                "signals": c.evaluation.signals,
                "red_flags": c.evaluation.red_flags,
                "why_match": c.thesis_match,
                "why_not": c.thesis_miss,
                "breakdown": {
                    "technical_ability": c.evaluation.technical_ability,
                    "execution_ability": c.evaluation.execution_ability,
                    "founder_product_ability": c.evaluation.founder_product_ability,
                    "technical_background": c.evaluation.technical_background,
                    "reputation": c.evaluation.reputation,
                    "growth_signals": c.evaluation.growth_signals,
                },
                "not_measurable": c.evaluation.not_measurable,
            }
            for c in candidates
        ],
    }


@app.post("/api/sourcing/hackernews")
async def scan_hackernews(limit: int = 20) -> dict[str, Any]:
    """Trigger a Hacker News scan for Show HN posts."""
    from vc_brain.sourcing.hackernews_scanner import HackerNewsScanner
    scanner = HackerNewsScanner(pipeline)
    launches = await scanner.scan_show_hn(limit)
    founders = await scanner.ingest_launches(launches)
    return {
        "launches_found": len(launches),
        "founders_ingested": len(founders),
        "founders": [{"id": f.id, "name": f.name} for f in founders],
    }


# ---------------------------------------------------------------------------
# Routes: React single-page application
# ---------------------------------------------------------------------------
@app.get("/{path:path}", response_class=HTMLResponse)
async def spa(path: str):
    """Serve React routes after API routes have had a chance to match."""
    index = DIST / "index.html"
    if index.is_file():
        return HTMLResponse(index.read_text())
    return HTMLResponse("<h1>VC Brain frontend not built</h1><p>Run npm run build in frontend.</p>", status_code=503)
