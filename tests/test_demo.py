"""The mock screening behind the Demo Apply button.

`time.sleep` is patched out everywhere so the ~30s demo runs instantly here.
"""

import pytest

from vc_brain.evaluation import demo, stages
from vc_brain.memory.store import MemoryStore


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(demo.time, "sleep", lambda seconds: None)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(path=str(tmp_path / "demo.db"))


def test_start_creates_the_demo_application(store):
    app_id, run_id = demo.start(store)
    assert app_id == demo.DEMO_APPLICATION_ID
    application = store.get_application(app_id)
    assert application.evaluation_state == "queued"
    assert application.source_channel == "demo"      # identifiable in the inbox
    assert application.deck_path == ""               # no deck needed
    assert store.get_company(application.company_id).name == "Northwind Labs"
    assert application.founder_ids and store.get_founder(application.founder_ids[0])
    assert run_id


def test_repeated_starts_reuse_one_row(store):
    demo.start(store)
    count_after_first = len(store.applications)
    for _ in range(3):
        demo.start(store)
    assert len(store.applications) == count_after_first  # inbox never grows
    assert len(store.companies) == 1
    assert list(store.applications) == [demo.DEMO_APPLICATION_ID]


def test_run_walks_every_stage_and_produces_a_result(store):
    app_id, run_id = demo.start(store)
    demo.run(store, run_id)

    application = store.get_application(app_id)
    assert application.evaluation_state == "evaluated"
    payload = stages.progress_payload(application)
    assert payload["complete"] is True
    assert {step["state"] for step in payload["steps"]} == {"done"}

    screening = application.screening_result
    assert screening["founder_axis"]["score"] > 0
    # SWOT must be in the nested shape the inbox detail view reads.
    assert screening["founder_axis"]["swot"]["strengths"][0]["text"]
    for axis in ("founder_axis", "market_axis", "idea_vs_market_axis"):
        assert screening[axis]["swot"]["threats"]
    assert application.evaluation_artifacts["enrichment"]["company_name"] == "Northwind Labs"


def test_a_superseded_run_stops_and_does_not_clobber(store):
    """Two quick clicks must not leave the older thread rewinding the row."""
    _, first_run = demo.start(store)
    _, second_run = demo.start(store)   # the second click supersedes the first

    demo.run(store, first_run)          # the stale thread finally gets scheduled

    application = store.get_application(demo.DEMO_APPLICATION_ID)
    assert application.evaluation_state == "queued"   # untouched by the stale run
    assert application.screening_result is None
    assert not application.evaluation_progress.get("current")   # no stage was walked
    assert not application.evaluation_progress.get("done")

    demo.run(store, second_run)         # the live run still owns the row
    assert store.get_application(demo.DEMO_APPLICATION_ID).evaluation_state == "evaluated"


def test_restart_clears_the_previous_result(store):
    """A second demo must start from an empty checklist, not the last result."""
    app_id, run_id = demo.start(store)
    demo.run(store, run_id)
    assert store.get_application(app_id).screening_result is not None

    demo.start(store)
    application = store.get_application(app_id)
    assert application.screening_result is None
    assert application.decision is None
    assert not application.evaluation_progress.get("done")   # timings cleared too
    assert application.evaluation_completed_at is None
    assert "enrichment" not in application.evaluation_artifacts
    # the checklist renders as fully pending again
    assert {s["state"] for s in stages.progress_payload(application)["steps"]} == {"pending"}


def test_demo_advertises_its_own_duration_not_the_real_pipeline_s(store):
    """Promising the real run's 8-12 minutes on a 30s demo reads as broken."""
    app_id, run_id = demo.start(store)
    payload = stages.progress_payload(store.get_application(app_id))
    assert payload["typical_duration"] == demo.TYPICAL_DURATION != stages.TYPICAL_DURATION

    # and it survives the stage walk rather than being reset to the default
    demo.run(store, run_id)
    after = stages.progress_payload(store.get_application(app_id))
    assert after["typical_duration"] == demo.TYPICAL_DURATION


def test_run_is_a_noop_for_an_unknown_run_id(store):
    demo.start(store)
    demo.run(store, "not-a-real-run")
    assert store.get_application(demo.DEMO_APPLICATION_ID).evaluation_state == "queued"


def test_demo_makes_no_llm_or_network_calls(store, monkeypatch):
    """The demo must work with no keys and no connectivity."""
    import httpx

    def explode(*args, **kwargs):
        raise AssertionError("the demo must not make network calls")

    monkeypatch.setattr(httpx, "get", explode)
    monkeypatch.setattr(httpx, "post", explode)
    monkeypatch.setattr(httpx.Client, "request", explode)

    _, run_id = demo.start(store)
    demo.run(store, run_id)
    assert store.get_application(demo.DEMO_APPLICATION_ID).evaluation_state == "evaluated"


def test_fixture_stays_in_sync_with_the_rendered_shape():
    """Guard the fields the inbox reads directly off the fixture."""
    fixture = demo.load_fixture()
    assert fixture["applicability"]["sanity"]["passed"] is True
    assert set(fixture["screening"]) >= {"founder_axis", "market_axis", "idea_vs_market_axis"}
    founder = fixture["enrichment"]["founders"][0]
    assert founder["github"]["dimensions"] and founder["socials"]["sample_posts"]
    assert set(demo.STAGE_SECONDS) == {key for key, _ in stages.STAGES}
