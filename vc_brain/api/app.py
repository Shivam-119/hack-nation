"""FastAPI application: the VC Brain API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vc_brain.intelligence.diligence import DiligenceEngine
from vc_brain.intelligence.memo_generator import MemoGenerator
from vc_brain.intelligence.reasoning import ReasoningEngine
from vc_brain.intelligence.screener import Screener
from vc_brain.intelligence.thesis_engine import FundThesis, ThesisEngine
from vc_brain.memory.founder_score import compute_founder_score
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.store import MemoryStore

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
store = MemoryStore()
pipeline = IngestionPipeline(store)
thesis = FundThesis()
thesis_engine = ThesisEngine(thesis)
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


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class ApplicationRequest(BaseModel):
    company_name: str
    founder_name: str = ""
    founder_email: str = ""
    sector: str = ""
    stage: str = ""
    geography: str = ""
    description: str = ""


class ThesisUpdate(BaseModel):
    name: str = "Default Fund"
    sectors: list[str] = ["AI", "SaaS", "Developer Tools"]
    stages: list[str] = ["pre-seed", "seed"]
    geographies: list[str] = ["US", "Europe"]
    check_size_min: int = 50_000
    check_size_max: int = 150_000
    target_ownership_pct: float = 5.0
    risk_appetite: str = "moderate"


class SearchQuery(BaseModel):
    query: str
    limit: int = 10


# ---------------------------------------------------------------------------
# Routes: Thesis
# ---------------------------------------------------------------------------
@app.get("/api/thesis")
async def get_thesis() -> FundThesis:
    return thesis


@app.put("/api/thesis")
async def update_thesis(update: ThesisUpdate) -> FundThesis:
    global thesis, thesis_engine
    thesis = FundThesis(**update.model_dump())
    thesis_engine = ThesisEngine(thesis)
    return thesis


# ---------------------------------------------------------------------------
# Routes: Inbound Applications
# ---------------------------------------------------------------------------
@app.post("/api/applications")
async def submit_application(req: ApplicationRequest) -> dict[str, Any]:
    """Submit an inbound application (minimum: company name)."""
    application = pipeline.ingest_application(
        company_name=req.company_name,
        founder_name=req.founder_name,
        founder_email=req.founder_email,
        extra_fields={
            "sector": req.sector,
            "stage": req.stage,
            "geography": req.geography,
            "description": req.description,
        },
    )

    # Update founder scores
    for fid in application.founder_ids:
        founder = store.get_founder(fid)
        if founder:
            founder.score = compute_founder_score(founder)
            store.upsert_founder(founder)

    # Thesis fit check
    fits, reasons = thesis_engine.fits_thesis(req.sector, req.stage, req.geography)

    return {
        "application_id": application.id,
        "status": application.status.value,
        "thesis_fit": fits,
        "thesis_reasons": reasons,
    }


@app.get("/api/applications")
async def list_applications(status: str | None = None) -> list[dict[str, Any]]:
    apps = store.list_applications(status)
    return [
        {
            "id": a.id,
            "company_id": a.company_id,
            "status": a.status.value,
            "source": a.source_channel,
            "submitted_at": a.submitted_at.isoformat(),
        }
        for a in apps
    ]


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
        thesis_context=f"Sectors: {thesis.sectors}, Stages: {thesis.stages}",
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
    diligence = DiligenceReport(
        company_id=company.id, **(application.diligence_result or {})
    )

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
@app.post("/api/sourcing/github")
async def scan_github(language: str = "python", min_stars: int = 50, limit: int = 10) -> dict[str, Any]:
    """Trigger a GitHub scan for potential founders."""
    from vc_brain.sourcing.github_scanner import GitHubScanner
    scanner = GitHubScanner(pipeline)
    candidates = await scanner.scan_trending(language, min_stars, limit)
    founders = await scanner.ingest_candidates(candidates)
    return {
        "candidates_found": len(candidates),
        "founders_ingested": len(founders),
        "founders": [{"id": f.id, "name": f.name} for f in founders],
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
# Routes: Dashboard (HTML)
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the investor dashboard."""
    from pathlib import Path
    template = Path(__file__).parent.parent.parent / "frontend" / "templates" / "dashboard.html"
    if template.exists():
        return template.read_text()
    return "<h1>VC Brain</h1><p>Dashboard template not found. See /docs for API.</p>"
