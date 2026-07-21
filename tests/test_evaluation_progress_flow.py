"""The stage instrumentation inside a real `run_evaluation` call.

Everything expensive (deck parsing, the LLM extractors, the scanners, the
reasoning pipeline) is stubbed -- what is under test is that the progress
checklist tracks the real control flow, including the failure path.
"""

import pytest

from vc_brain.config import config
from vc_brain.evaluation import service, stages
from vc_brain.intelligence.thesis_engine import FundThesis
from vc_brain.memory.models import Application
from vc_brain.memory.store import MemoryStore

THESIS = FundThesis(
    name="Test Fund", sectors=["AI"], stages=["seed"], geographies=["EU"],
    check_size_min=50_000, check_size_max=250_000, target_ownership_pct=5.0,
    risk_appetite="moderate",
)


@pytest.fixture
def store_and_app(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "openai_api_key", "test-key")
    store = MemoryStore(path=str(tmp_path / "flow.db"))
    application = Application(company_id="c1", deck_path=str(tmp_path / "deck.pdf"))
    store.add_application(application)
    return store, application.id


def _stub_pipeline_inputs(monkeypatch, seen=None):
    """Replace every expensive step, optionally recording the live stage."""
    import pdf_parser.deck_parser as deck_parser
    import pdf_parser.extractor_agent as extractor_agent
    import pdf_parser.research_agent as research_agent

    def record(store, app_id):
        if seen is not None:
            payload = stages.progress_payload(store.get_application(app_id))
            seen.append(payload["current"])

    # Must satisfy MarketExtraction -- run_evaluation revalidates the deck dict
    # through it before handing off to research.
    deck_fields = {
        "company_name": "Vektor", "one_line_description": "Vector DB in your VPC",
        "primary_industry": "AI Infrastructure", "target_market_segment": "Enterprise",
        "business_model": "SaaS", "extraction_confidence": "high",
    }

    class _Dump:
        def model_dump(self, mode="json"):
            return dict(deck_fields)

    monkeypatch.setattr(deck_parser, "extract_deck_text", lambda path: "deck text")
    monkeypatch.setattr(extractor_agent, "extract_market", lambda text, key: _Dump())
    monkeypatch.setattr(research_agent, "run_research", lambda deck, key, tavily: _Dump())
    monkeypatch.setattr(service, "_run_enrichment", lambda store, app_id, app, company: record(store, app_id))
    return record


def test_progress_walks_every_stage_and_completes(store_and_app, monkeypatch):
    store, app_id = store_and_app
    seen: list[str] = []
    _stub_pipeline_inputs(monkeypatch, seen)

    def fake_pipeline(application_id, thesis, api_key, memory):
        seen.append(stages.progress_payload(store.get_application(app_id))["current"])
        # Mirror what the real pipeline does through the memory client.
        memory.write_axis_score(application_id, "founder", {"score": 50})
        memory.write_axis_score(application_id, "idea_vs_market", {"score": 60})
        seen.append(stages.progress_payload(store.get_application(app_id))["current"])
        memory.write_decision(application_id, {"recommendation": "meet"})

    monkeypatch.setattr(service, "run_pipeline", fake_pipeline)
    service.run_evaluation(store, app_id, THESIS)

    # enrichment and axes observed live; then the last axis hands off to decision
    assert seen == ["enrichment", "axes", "decision"]

    application = store.get_application(app_id)
    assert application.evaluation_state == "evaluated"
    payload = stages.progress_payload(application)
    assert payload["complete"] is True
    assert {step["state"] for step in payload["steps"]} == {"done"}
    # every stage recorded a duration, so the UI can show per-stage timing
    assert all(step["seconds"] is not None for step in payload["steps"])


def test_earlier_stages_are_marked_done_as_the_run_proceeds(store_and_app, monkeypatch):
    store, app_id = store_and_app
    _stub_pipeline_inputs(monkeypatch)
    observed = {}

    def fake_pipeline(application_id, thesis, api_key, memory):
        payload = stages.progress_payload(store.get_application(app_id))
        observed["states"] = {step["key"]: step["state"] for step in payload["steps"]}
        observed["payload"] = payload

    monkeypatch.setattr(service, "run_pipeline", fake_pipeline)
    service.run_evaluation(store, app_id, THESIS)

    # Guard against a vacuous pass: if the run died earlier, the pipeline stub
    # never fires and every assertion below would be silently skipped.
    assert observed, store.get_application(app_id).evaluation_failure_reason
    states, payload = observed["states"], observed["payload"]
    assert states["deck"] == "done"
    assert states["extract"] == "done"
    assert states["market"] == "done"
    assert states["enrichment"] == "done"
    assert states["axes"] == "active"
    assert states["decision"] == "pending"
    assert payload["current_step"] == 5
    assert payload["elapsed_seconds"] >= 0


def test_failure_midway_marks_the_stage_that_broke(store_and_app, monkeypatch):
    store, app_id = store_and_app
    _stub_pipeline_inputs(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("market research exploded")

    import pdf_parser.research_agent as research_agent

    monkeypatch.setattr(research_agent, "run_research", boom)
    service.run_evaluation(store, app_id, THESIS)

    application = store.get_application(app_id)
    assert application.evaluation_state == "failed"
    payload = stages.progress_payload(application)
    assert payload["failed"] == "market"          # the investor sees *where*
    states = {step["key"]: step["state"] for step in payload["steps"]}
    assert states["extract"] == "done"            # completed work still shown
    assert states["market"] == "failed"
    assert states["axes"] == "pending"
    assert "exploded" in application.evaluation_failure_reason


def test_thesis_rejection_completes_without_scoring_axes(store_and_app, monkeypatch):
    """A thesis-fit rejection writes a decision straight from stage 1."""
    store, app_id = store_and_app
    _stub_pipeline_inputs(monkeypatch)

    def rejecting_pipeline(application_id, thesis, api_key, memory):
        memory.write_decision(application_id, {"recommendation": "pass"})

    monkeypatch.setattr(service, "run_pipeline", rejecting_pipeline)
    service.run_evaluation(store, app_id, THESIS)

    payload = stages.progress_payload(store.get_application(app_id))
    assert payload["complete"] is True
    assert {step["state"] for step in payload["steps"]} == {"done"}


def test_missing_prerequisites_fail_before_any_stage_starts(tmp_path, monkeypatch):
    """No deck means nothing ran, so no stage should be blamed for it."""
    monkeypatch.setattr(config, "openai_api_key", "test-key")
    store = MemoryStore(path=str(tmp_path / "flow.db"))
    application = Application(company_id="c1", deck_path="")
    store.add_application(application)

    service.run_evaluation(store, application.id, THESIS)

    reloaded = store.get_application(application.id)
    assert reloaded.evaluation_state == "failed"
    payload = stages.progress_payload(reloaded)
    assert payload["failed"] == ""
    assert {step["state"] for step in payload["steps"]} == {"pending"}
