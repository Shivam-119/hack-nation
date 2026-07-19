"""Bridges the API layer to pdf_parser (Agent 1/2), the GitHub/socials scanners, and
reasoning_layer (the 3-axis decision layer).

pdf_parser/ and reasoning_layer/ are standalone projects with their own flat,
un-namespaced imports (e.g. `from schema import ...`), by design — see their own
CLAUDE.md conventions. This module adds both directories to sys.path once, then
imports their modules directly, so they don't need to be rewritten as installable
packages just to be reused here.

`run_evaluation` is a plain synchronous function so it can be handed to FastAPI's
`BackgroundTasks` — Starlette runs sync background tasks in a thread pool, which
keeps the (slow: several LLM calls + up to 10 Tavily searches) evaluation off the
request/response path and off the main event loop.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

from vc_brain.config import config
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.models import Application, Company, Founder
from vc_brain.memory.store import MemoryStore
from vc_brain.sourcing import github_evaluator
from vc_brain.sourcing.socials.scanner import SocialsScanner

REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_PARSER_DIR = REPO_ROOT / "pdf_parser"
REASONING_LAYER_DIR = REPO_ROOT / "reasoning_layer"

for _dir in (PDF_PARSER_DIR, REASONING_LAYER_DIR):
    _dir_str = str(_dir)
    if _dir_str not in sys.path:
        sys.path.insert(0, _dir_str)

import deck_parser as pdf_deck_parser  # noqa: E402  (pdf_parser/deck_parser.py)
import extractor_agent as pdf_extractor_agent  # noqa: E402  (pdf_parser/extractor_agent.py)
import research_agent as pdf_research_agent  # noqa: E402  (pdf_parser/research_agent.py)

import adversarial_agent as rl_adversarial_agent  # noqa: E402
import decision_draft_agent as rl_decision_draft_agent  # noqa: E402
import decision_finalizer as rl_decision_finalizer  # noqa: E402
import founder_scorer as rl_founder_scorer  # noqa: E402
import idea_vs_market_scorer as rl_idea_vs_market_scorer  # noqa: E402
import market_scorer as rl_market_scorer  # noqa: E402
import thesis_fit_filter as rl_thesis_fit_filter  # noqa: E402
from thesis_config import Range as RLRange  # noqa: E402
from thesis_config import ThesisConfig as RLThesisConfig  # noqa: E402

_RISK_APPETITE_MAP = {"conservative": "low", "moderate": "medium", "aggressive": "high"}
_DEFAULT_THESIS_CONFIG = RLThesisConfig(
    sectors=["AI", "SaaS", "fintech", "health"],
    stage=["pre-seed", "seed"],
    geography=["Remote"],
    check_size_usd=RLRange(min=50_000, max=150_000),
    ownership_target_pct=RLRange(min=5, max=15),
    risk_appetite="medium",
)


def build_thesis_config(fund_thesis: Any | None) -> RLThesisConfig:
    """Translate the API's live FundThesis (set via /api/thesis) into reasoning_layer's ThesisConfig."""
    if fund_thesis is None:
        return _DEFAULT_THESIS_CONFIG
    stages = [s for s in fund_thesis.stages if s in ("pre-seed", "seed", "series-a")] or ["pre-seed", "seed"]
    ownership = fund_thesis.target_ownership_pct or 10.0
    return RLThesisConfig(
        sectors=fund_thesis.sectors or _DEFAULT_THESIS_CONFIG.sectors,
        stage=stages,
        geography=fund_thesis.geographies or _DEFAULT_THESIS_CONFIG.geography,
        check_size_usd=RLRange(min=fund_thesis.check_size_min, max=fund_thesis.check_size_max),
        ownership_target_pct=RLRange(min=max(ownership - 2, 0), max=ownership + 2),
        risk_appetite=_RISK_APPETITE_MAP.get(fund_thesis.risk_appetite, "medium"),
    )


def _extract_handle(value: str) -> str:
    """A founder field may be a bare handle or a full profile URL — normalize to the handle."""
    value = (value or "").strip()
    if not value:
        return ""
    value = re.sub(r"^(https?://)?(www\.)?(github\.com|twitter\.com|x\.com|linkedin\.com)/(in/)?", "", value, flags=re.I)
    return value.strip("/").split("/")[0].split("?")[0]


async def _gather_founder_signals(founder: Founder, store: MemoryStore) -> dict[str, list]:
    """Run the GitHub evaluator + socials scanner for one founder's submitted handles."""
    track_record: list[str] = []
    technical_signals: list[str] = []
    citations: list[dict[str, str]] = []

    gh_handle = _extract_handle(founder.github_url)
    if gh_handle:
        try:
            evaluation = await github_evaluator.evaluate(gh_handle)
            technical_signals.append(f"GitHub ({gh_handle}): grade {evaluation.grade}, score {evaluation.score:.0f}/100")
            technical_signals.extend(evaluation.signals[:5])
            technical_signals.extend(f"Red flag: {flag}" for flag in evaluation.red_flags[:3])
            citations.append({"claim": f"GitHub evaluation for {gh_handle}", "source_url": f"https://github.com/{gh_handle}"})
        except Exception as exc:
            technical_signals.append(f"GitHub evaluation for {gh_handle} could not be completed: {exc}")

    handles: dict[str, str] = {}
    tw_handle = _extract_handle(founder.twitter_url)
    li_handle = _extract_handle(founder.linkedin_url)
    if tw_handle:
        handles["twitter"] = tw_handle
    if li_handle:
        handles["linkedin"] = li_handle

    if handles:
        try:
            result = await SocialsScanner(IngestionPipeline(store)).analyze(handles, name=founder.name)
            if result.post_analysis.summary:
                track_record.append(f"Social presence ({founder.name}): {result.post_analysis.summary}")
            track_record.extend(f"Expertise signal: {area}" for area in result.post_analysis.expertise_areas[:3])
            if result.founder_identity and result.founder_identity.description:
                track_record.append(f"Identity check ({founder.name}): {result.founder_identity.description}")
            for evidence in result.post_analysis.evidence[:5]:
                citations.append({"claim": evidence.claim, "source_url": evidence.url})
        except Exception as exc:
            track_record.append(f"Socials scan for {founder.name} could not be completed: {exc}")

    return {"track_record": track_record, "technical_signals": technical_signals, "source_citations": citations}


async def build_founder_research(application: Application, company: Company | None, founders: list[Founder], store: MemoryStore) -> dict[str, Any]:
    """Aggregate GitHub/socials scanner output + submitted context into the shape
    reasoning_layer's founder_scorer expects (see reasoning_layer/mock_data/founder_research_fixture.json)."""
    all_track_record: list[str] = []
    all_technical_signals: list[str] = []
    all_citations: list[dict[str, str]] = []
    has_any_handle = False

    for founder in founders:
        if founder.github_url or founder.twitter_url or founder.linkedin_url:
            has_any_handle = True
        signals = await _gather_founder_signals(founder, store)
        all_track_record.extend(signals["track_record"])
        all_technical_signals.extend(signals["technical_signals"])
        all_citations.extend(signals["source_citations"])

    if application.prior_companies:
        all_track_record.append(f"Founder-reported prior work: {application.prior_companies}")
    if application.accelerator:
        all_track_record.append(f"Accelerator: {application.accelerator}")

    primary = founders[0] if founders else None
    cold_start = not has_any_handle and not application.prior_companies and not application.accelerator

    return {
        "founder_id": primary.id if primary else "",
        "founder_score": primary.score.overall if primary else None,
        "founder_name": ", ".join(f.name for f in founders if f.name) or "Unknown",
        "background_summary": application.one_liner or (company.description if company else ""),
        "track_record": all_track_record or ["No track record data found from the submitted handles."],
        "technical_signals": all_technical_signals or ["No technical signals found from the submitted handles."],
        "cold_start": cold_start,
        "source_citations": all_citations,
    }


def _empty_axis_decision(application_id: str, thesis_fit: dict, recommendation: str, rationale: str, caveats: list[str]) -> dict[str, Any]:
    return {
        "application_id": application_id,
        "founder_axis": {},
        "market_axis": {},
        "idea_vs_market_axis": {},
        "thesis_fit": thesis_fit,
        "recommendation": recommendation,
        "check_size_recommended_usd": None,
        "rationale": rationale,
        "adversarial_view": "",
        "gaps_and_caveats": caveats,
    }


def run_evaluation(store: MemoryStore, application_id: str, fund_thesis: Any | None) -> None:
    """Agent 1 -> Agent 2 -> founder/socials scanners -> reasoning layer, then persists the decision.

    Synchronous by design — intended to run via FastAPI's BackgroundTasks (Starlette
    executes sync background tasks in a thread pool, off the event loop).
    """
    application = store.get_application(application_id)
    if not application:
        return
    company = store.get_company(application.company_id)
    founders = [store.get_founder(fid) for fid in application.founder_ids]
    founders = [f for f in founders if f]

    openai_api_key = config.openai_api_key
    tavily_api_key = config.tavily_api_key
    thesis_config = build_thesis_config(fund_thesis)

    try:
        deck_text = pdf_deck_parser.extract_deck_text(application.deck_path)
        agent1_output = pdf_extractor_agent.extract_market(deck_text, api_key=openai_api_key)
        deck_extraction = agent1_output.model_dump()

        thesis_fit = rl_thesis_fit_filter.check_thesis_fit(thesis_config, deck_extraction)
        if not thesis_fit.passed:
            decision = _empty_axis_decision(
                application_id,
                thesis_fit.model_dump(),
                "pass",
                "Rejected at the thesis fit filter — outside the fund's configured sectors/stage/geography.",
                [],
            )
        else:
            agent2_output = pdf_research_agent.run_research(agent1_output, openai_api_key=openai_api_key, tavily_api_key=tavily_api_key)
            market_research = agent2_output.model_dump()
            founder_research = asyncio.run(build_founder_research(application, company, founders, store))

            founder_axis = rl_founder_scorer.score_founder(founder_research, founder_research.get("founder_score"), api_key=openai_api_key)
            market_axis = rl_market_scorer.score_market(deck_extraction, market_research, api_key=openai_api_key)
            idea_vs_market_axis = rl_idea_vs_market_scorer.score_idea_vs_market(
                founder_axis.model_dump(), market_axis.model_dump(), deck_extraction, api_key=openai_api_key
            )
            draft = rl_decision_draft_agent.draft_decision(
                founder_axis.model_dump(), market_axis.model_dump(), idea_vs_market_axis.model_dump(),
                thesis_config, api_key=openai_api_key,
            )
            adversarial = rl_adversarial_agent.generate_adversarial_view(
                draft.model_dump(), founder_axis.model_dump(), market_axis.model_dump(),
                idea_vs_market_axis.model_dump(), api_key=openai_api_key,
            )
            final = rl_decision_finalizer.finalize_decision(
                application_id=application_id,
                founder_axis=founder_axis.model_dump(),
                market_axis=market_axis.model_dump(),
                idea_vs_market_axis=idea_vs_market_axis.model_dump(),
                thesis_fit=thesis_fit,
                draft=draft,
                adversarial=adversarial,
            )
            decision = final.model_dump()
    except Exception as exc:
        decision = _empty_axis_decision(
            application_id, {}, "more_diligence_needed",
            f"Automated evaluation failed and needs a manual rerun: {exc}",
            ["Evaluation pipeline error — see server logs, then retry."],
        )

    application.decision = decision
    application.status = application.status.__class__("decision")
    store.add_application(application)
