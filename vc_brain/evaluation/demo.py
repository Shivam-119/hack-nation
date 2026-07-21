"""A mock screening you can watch end to end in about thirty seconds.

A real evaluation costs API spend and takes minutes, which makes it useless for
showing someone how the product works. This walks the *same* six stages the real
pipeline reports, on a timer, and finishes with a canned but coherent result.

It deliberately shares no code path with `run_evaluation`: no LLM call, no
network, no key required. That keeps it free, keeps it fast, and means it still
works when a provider is down mid-demo.

One demo application is reused. Every run resets that same row rather than
adding another, so repeated demos never inflate the inbox.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from vc_brain.evaluation import stages
from vc_brain.memory.models import Application, ApplicationStatus, Company, Founder
from vc_brain.memory.seed import _enrich_screening
from vc_brain.memory.store import MemoryStore

FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "fixtures" / "demo_application.json"

# Fixed ids, deliberately unlike the 12-hex fixture ids, so the one demo row is
# always found again rather than duplicated.
DEMO_APPLICATION_ID = "demo-application"
DEMO_COMPANY_ID = "demo-company"
DEMO_FOUNDER_ID = "demo-founder"

# ~30s total, weighted like a real run: search and enrichment dominate.
STAGE_SECONDS: dict[str, float] = {
    "deck": 3.0,
    "extract": 4.0,
    "market": 8.0,
    "enrichment": 7.0,
    "axes": 5.0,
    "decision": 3.0,
}

_RUN_KEY = "demo_run"  # stored in evaluation_artifacts; identifies the live run

TYPICAL_DURATION = "about 30 seconds"


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def _founder(data: dict[str, Any]) -> Founder:
    return Founder(
        id=DEMO_FOUNDER_ID,
        name=data.get("name", "Demo Founder"),
        email=data.get("email", ""),
        github_url=data.get("github_url", ""),
        twitter_url=data.get("twitter_url", ""),
        linkedin_url=data.get("linkedin_url", ""),
    )


def start(store: MemoryStore) -> tuple[str, str]:
    """Create or reset the demo application and return (id, run_id).

    Resetting clears any previous result, so a second demo starts from an empty
    checklist instead of showing the last run's axes while the new one walks.
    """
    fixture = load_fixture()
    now = datetime.utcnow()
    run_id = uuid.uuid4().hex

    founders = fixture.get("founders") or [{}]
    store.upsert_founder(_founder(founders[0]))
    store.upsert_company(
        Company(
            id=DEMO_COMPANY_ID,
            name=fixture["company_name"],
            website=fixture.get("website", ""),
            sector=fixture.get("sector", ""),
            stage=fixture.get("stage", ""),
            geography=fixture.get("geography", ""),
            description=fixture.get("one_liner", ""),
            founder_ids=[DEMO_FOUNDER_ID],
        )
    )

    application = Application(
        id=DEMO_APPLICATION_ID,
        company_id=DEMO_COMPANY_ID,
        founder_ids=[DEMO_FOUNDER_ID],
        status=ApplicationStatus("received"),
        source_channel="demo",
        # Newest-first ordering puts the demo at the top of the inbox, which is
        # also what the UI auto-selects -- so the run is on screen immediately.
        submitted_at=now,
        one_liner=fixture.get("one_liner", ""),
        website=fixture.get("website", ""),
        product_url=fixture.get("product_url", ""),
        raising=fixture.get("raising", ""),
        why_now=fixture.get("why_now", ""),
        accelerator=fixture.get("accelerator", ""),
        prior_companies=fixture.get("prior_companies", ""),
        applicability=fixture.get("applicability"),
        # Everything result-shaped starts empty: this run has not produced it yet.
        screening_result=None,
        decision=None,
        evaluation_artifacts={_RUN_KEY: run_id},
        # Carry the demo's own expectation so the checklist doesn't promise the
        # real pipeline's 8-12 minutes for a run that takes half a minute.
        evaluation_progress={"typical_duration": TYPICAL_DURATION},
        evaluation_state="queued",
        evaluation_failure_reason="",
        evaluation_started_at=now,
        evaluation_completed_at=None,
    )
    store.add_application(application)
    return application.id, run_id


def _owns_run(store: MemoryStore, run_id: str) -> bool:
    """True while `run_id` is still the newest run for the demo row.

    Two quick clicks would otherwise leave two threads walking the same row, the
    older one rewinding the checklist under the newer one.
    """
    application = store.get_application(DEMO_APPLICATION_ID)
    return bool(application) and (application.evaluation_artifacts or {}).get(_RUN_KEY) == run_id


def run(store: MemoryStore, run_id: str) -> None:
    """Walk the stages on a timer, then write the canned result."""
    if not _owns_run(store, run_id):
        return

    application = store.get_application(DEMO_APPLICATION_ID)
    if not application:
        return
    application.evaluation_state = "running"
    store.add_application(application)

    for key, _label in stages.STAGES:
        if not _owns_run(store, run_id):
            return  # superseded by a newer demo run
        stages.mark_stage(store, DEMO_APPLICATION_ID, key)
        time.sleep(STAGE_SECONDS.get(key, 3.0))

    if not _owns_run(store, run_id):
        return

    fixture = load_fixture()
    application = store.get_application(DEMO_APPLICATION_ID)
    if not application:
        return
    application.screening_result = _enrich_screening(fixture.get("screening"))
    application.evaluation_artifacts = {_RUN_KEY: run_id, "enrichment": fixture.get("enrichment")}
    application.evaluation_state = "evaluated"
    application.evaluation_completed_at = datetime.utcnow()
    application.status = ApplicationStatus("decision")
    store.add_application(application)
    stages.mark_complete(store, DEMO_APPLICATION_ID)
