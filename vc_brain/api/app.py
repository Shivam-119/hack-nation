"""FastAPI application: the VC Brain API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class ApplicationRequest(BaseModel):
    company_name: str
    founder_name: str
    founder_email: str = ""
    sector: str = ""
    stage: str = ""
    geography: str = ""
    description: str = ""


class ThesisUpdate(BaseModel):
    name: str
    sectors: list[str]
    stages: list[str]
    geographies: list[str]
    check_size_min: int
    check_size_max: int
    target_ownership_pct: float
    risk_appetite: str = "moderate"
    min_founder_score: float = 30.0
    preferred_signals: list[str] = []
    anti_signals: list[str] = []


class SearchQuery(BaseModel):
    query: str
    limit: int


# ---------------------------------------------------------------------------
# Routes: Thesis
# ---------------------------------------------------------------------------
@app.get("/api/thesis")
async def get_thesis() -> dict[str, Any]:
    if not thesis:
        return {"error": "No thesis configured. PUT /api/thesis first."}
    return thesis.model_dump()


@app.put("/api/thesis")
async def update_thesis(update: ThesisUpdate) -> dict[str, Any]:
    global thesis, thesis_engine
    thesis = FundThesis(**update.model_dump())
    thesis_engine = ThesisEngine(thesis)
    return thesis.model_dump()


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
    fits, reasons = None, ["No thesis configured"]
    if thesis_engine:
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
        thesis=thesis,
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


@app.get("/api/applications/{app_id}/cold-start")
async def check_cold_start(app_id: str) -> dict[str, Any]:
    """Check if an application is a cold-start case and return what data is needed."""
    application = store.get_application(app_id)
    if not application:
        return {"error": "Application not found"}

    company = store.get_company(application.company_id)
    if not company:
        return {"error": "Company not found"}

    founders = [store.get_founder(fid) for fid in application.founder_ids]
    founders = [f for f in founders if f]

    from vc_brain.intelligence.cold_start import detect_cold_start
    report = detect_cold_start(founders, application, company)
    return report.model_dump()


@app.post("/api/applications/{app_id}/validate")
async def validate_claims(app_id: str) -> dict[str, Any]:
    """Run the validator agent to cross-reference claims against external signals."""
    application = store.get_application(app_id)
    if not application:
        return {"error": "Application not found"}
    if not application.diligence_result:
        return {"error": "Run /diligence first — validator needs claims to cross-reference"}

    company = store.get_company(application.company_id)
    if not company:
        return {"error": "Company not found"}

    founders = [store.get_founder(fid) for fid in application.founder_ids]
    founders = [f for f in founders if f]

    from vc_brain.intelligence.diligence import DiligenceReport
    from vc_brain.intelligence.validator import ValidatorAgent
    diligence = DiligenceReport(company_id=company.id, **(application.diligence_result or {}))

    agent = ValidatorAgent(company=company, founders=founders)
    report = await agent.validate(diligence)
    return report.model_dump()


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
@app.get("/api/sourcing/channel-stats")
async def get_channel_stats() -> list[dict[str, Any]]:
    """Return sourcing channel effectiveness: which sources produce the best founders."""
    from vc_brain.memory.channel_stats import compute_channel_stats, channel_stats_to_dict
    all_founders = list(store.founders.values())
    stats = compute_channel_stats(all_founders)
    return channel_stats_to_dict(stats)


@app.get("/api/founders/search")
async def search_founders(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Fast indexed text search across founder name, location, and skills."""
    results = store.search_founders_by_text(q, limit=limit)
    return [
        {
            "id": f.id,
            "name": f.name,
            "location": f.location,
            "skills": f.skills[:5],
            "score": f.score.overall,
        }
        for f in results
    ]


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


class LinkedInEnrichRequest(BaseModel):
    linkedin_url: str


@app.post("/api/founders/{founder_id}/enrich/linkedin")
async def enrich_linkedin(founder_id: str, req: LinkedInEnrichRequest) -> dict[str, Any]:
    """Enrich a founder's profile using their LinkedIn URL."""
    founder = store.get_founder(founder_id)
    if not founder:
        return {"error": "Founder not found"}

    from vc_brain.sourcing.linkedin_enricher import LinkedInEnricher
    enricher = LinkedInEnricher()
    founder = await enricher.enrich(founder, req.linkedin_url)
    store.upsert_founder(founder)

    return {
        "founder_id": founder.id,
        "name": founder.name,
        "linkedin_url": founder.linkedin_url,
        "location": founder.location,
        "bio": founder.bio,
        "skills": founder.skills,
        "data_points": len(founder.data_points),
    }


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


@app.post("/api/sourcing/arxiv")
async def scan_arxiv(limit_per_query: int = 10) -> dict[str, Any]:
    """Scan arXiv for recent AI/ML papers and ingest primary authors as candidates."""
    from vc_brain.sourcing.arxiv_scanner import ArXivScanner
    scanner = ArXivScanner(pipeline)
    papers = await scanner.scan_papers(max_per_query=limit_per_query)
    founders = await scanner.ingest_researchers(papers)
    return {
        "papers_found": len(papers),
        "researchers_ingested": len(founders),
        "founders": [
            {"id": f.id, "name": f.name, "bio": f.bio[:100]}
            for f in founders
        ],
    }


@app.post("/api/sourcing/techpress")
async def scan_techpress(limit_per_feed: int = 15) -> dict[str, Any]:
    """Scan TechCrunch and other tech RSS feeds for startup launch articles."""
    from vc_brain.sourcing.rss_scanner import TechRSSScanner
    scanner = TechRSSScanner(pipeline)
    launches = await scanner.scan_feeds(limit_per_feed)
    founders = await scanner.ingest_launches(launches)
    return {
        "articles_found": len(launches),
        "founders_ingested": len(founders),
        "by_source": {
            src: sum(1 for l in launches if l.source == src)
            for src in {l.source for l in launches}
        },
        "founders": [
            {"id": f.id, "name": f.name, "bio": f.bio[:100]}
            for f in founders
        ],
    }


@app.post("/api/sourcing/producthunt")
async def scan_producthunt(limit: int = 20) -> dict[str, Any]:
    """Trigger a Product Hunt scan for recent launches and their makers."""
    from vc_brain.sourcing.producthunt_scanner import ProductHuntScanner
    from vc_brain.config import config as cfg
    scanner = ProductHuntScanner(pipeline)
    launches = await scanner.scan_launches(limit)
    founders = await scanner.ingest_launches(launches)
    return {
        "launches_found": len(launches),
        "founders_ingested": len(founders),
        "source": "api" if cfg.producthunt_token else "rss",
        "founders": [
            {"id": f.id, "name": f.name, "bio": f.bio}
            for f in founders
        ],
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
