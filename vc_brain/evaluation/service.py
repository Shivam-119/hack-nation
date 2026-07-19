"""Bridge persisted applications to the decision-layer pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from reasoning_layer.memory_client import MemoryClient, MemoryReadError
from reasoning_layer.pipeline import run_pipeline
from reasoning_layer.thesis_config import Range, ThesisConfig
from vc_brain.config import config
from vc_brain.intelligence.thesis_engine import FundThesis
from vc_brain.memory.store import MemoryStore


class StoreEvaluationMemory(MemoryClient):
    """Reasoning-layer adapter backed by the existing MemoryStore entities."""

    def __init__(self, store: MemoryStore, application_id: str, deck: dict[str, Any], market: dict[str, Any]):
        self.store = store
        self.application_id = application_id
        self.deck = deck
        self.market = market

    def _application(self):
        application = self.store.get_application(self.application_id)
        if not application:
            raise MemoryReadError(f"Application not found: {self.application_id}")
        return application

    def get_deck_extraction(self, application_id: str) -> dict:
        return self.deck

    def get_market_research(self, application_id: str) -> dict:
        return self.market

    def get_founder_research(self, application_id: str) -> dict:
        application = self._application()
        founder = next((self.store.get_founder(fid) for fid in application.founder_ids if self.store.get_founder(fid)), None)
        if not founder:
            raise MemoryReadError("Application has no founder information")
        return founder.model_dump(mode="json")

    def get_founder_score(self, founder_id: str) -> float | None:
        founder = self.store.get_founder(founder_id)
        return founder.score.overall if founder else None

    def write_axis_score(self, application_id: str, axis: str, result: dict) -> None:
        application = self._application()
        application.evaluation_artifacts[axis] = result
        self.store.add_application(application)

    def write_decision(self, application_id: str, decision: dict) -> None:
        application = self._application()
        application.decision = decision
        application.evaluation_state = "evaluated"
        application.evaluation_failure_reason = ""
        application.evaluation_completed_at = datetime.utcnow()
        application.status = application.status.__class__("decision")
        self.store.add_application(application)


def reasoning_thesis(thesis: FundThesis) -> ThesisConfig:
    risk = {"conservative": "low", "moderate": "medium", "aggressive": "high"}.get(thesis.risk_appetite, "medium")
    ownership = thesis.target_ownership_pct
    return ThesisConfig(
        sectors=thesis.sectors,
        stage=[stage for stage in thesis.stages if stage in {"pre-seed", "seed", "series-a"}],
        geography=thesis.geographies,
        check_size_usd=Range(min=thesis.check_size_min, max=thesis.check_size_max),
        ownership_target_pct=Range(min=ownership, max=ownership),
        risk_appetite=risk,
    )


def _handle(value: str) -> str:
    """Reduce a stored URL/handle to a bare username for the scanners."""
    v = (value or "").strip().rstrip("/")
    for p in ("https://", "http://", "www.", "x.com/", "twitter.com/", "github.com/",
              "linkedin.com/in/", "linkedin.com/", "in/", "@"):
        if v.startswith(p):
            v = v[len(p):]
    return v


def _run_enrichment(store: MemoryStore, application_id: str, application: Any, company: str) -> None:
    """Run the sourcing scanners and stash the result in evaluation_artifacts.

    Isolated and fail-soft: any failure is recorded, never raised, so the main
    evaluation completes regardless."""
    try:
        import asyncio

        from vc_brain.sourcing import FounderInput, display_shape, enrich_from_deck

        founders = []
        for founder_id in application.founder_ids:
            fo = store.get_founder(founder_id)
            if fo:
                founders.append(FounderInput(
                    name=fo.name, github=_handle(fo.github_url),
                    twitter=_handle(fo.twitter_url), linkedin=_handle(fo.linkedin_url),
                ))

        # deck_path="" + company_name skips re-parsing the deck we just read.
        result = asyncio.run(enrich_from_deck("", founders, company_name=company))
        fresh = store.get_application(application_id)
        if fresh:
            fresh.evaluation_artifacts["enrichment"] = display_shape(result.model_dump(mode="json"))
            store.add_application(fresh)
    except Exception as exc:  # noqa: BLE001
        fresh = store.get_application(application_id)
        if fresh:
            fresh.evaluation_artifacts["enrichment_error"] = str(exc)[:500]
            store.add_application(fresh)


def run_evaluation(store: MemoryStore, application_id: str, thesis: FundThesis | None) -> None:
    """Run once in a FastAPI background task and persist either outcome."""
    application = store.get_application(application_id)
    if not application:
        return
    try:
        application.evaluation_state = "running"
        application.evaluation_started_at = datetime.utcnow()
        application.evaluation_failure_reason = ""
        store.add_application(application)
        if not thesis:
            raise RuntimeError("No fund thesis is configured. Save criteria, then retry this evaluation.")
        if not config.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured for evaluation.")
        if not application.deck_path:
            raise RuntimeError("No deck is attached to this application.")

        from pdf_parser.deck_parser import extract_deck_text
        from pdf_parser.extractor_agent import extract_market
        from pdf_parser.research_agent import run_research
        from pdf_parser.schema import MarketExtraction

        deck_text = extract_deck_text(application.deck_path)
        if not deck_text.strip():
            raise RuntimeError("The deck did not contain extractable text.")
        application.deck_text = deck_text
        store.add_application(application)
        deck = extract_market(deck_text, config.openai_api_key).model_dump(mode="json")
        market = run_research(MarketExtraction(**deck), config.openai_api_key, config.tavily_api_key).model_dump(mode="json")

        # Founder + company intelligence: the sourcing scanners (reputation on
        # the company + press, socials, GitHub). Runs on the company name we
        # already extracted and the founders' handles. Fail-soft and in its own
        # block, so a slow or dead scanner never stops the evaluation.
        _run_enrichment(store, application_id, application, deck.get("company_name") or "")

        memory = StoreEvaluationMemory(store, application_id, deck, market)
        run_pipeline(application_id, reasoning_thesis(thesis), config.openai_api_key, memory)
    except Exception as exc:
        application = store.get_application(application_id)
        if application:
            application.evaluation_state = "failed"
            application.evaluation_failure_reason = str(exc)[:1000]
            application.evaluation_completed_at = datetime.utcnow()
            store.add_application(application)
