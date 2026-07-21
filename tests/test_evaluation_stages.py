"""Stage progress for a running evaluation.

The point of these tests is that a multi-minute evaluation always renders an
honest checklist -- including the paths that skip stages (thesis-fit early exit)
and the paths that break (a stage raising).
"""

from vc_brain.evaluation import stages
from vc_brain.memory.models import Application
from vc_brain.memory.store import MemoryStore


def _store_with_app(tmp_path, state="running"):
    store = MemoryStore(path=str(tmp_path / "stages.db"))
    application = Application(company_id="c1", evaluation_state=state)
    store.add_application(application)
    return store, application.id


def _states(application):
    return {step["key"]: step["state"] for step in stages.progress_payload(application)["steps"]}


def test_not_requested_has_no_checklist(tmp_path):
    store, app_id = _store_with_app(tmp_path, state="not_requested")
    assert stages.progress_payload(store.get_application(app_id)) == {}


def test_queued_shows_every_stage_pending(tmp_path):
    store, app_id = _store_with_app(tmp_path, state="queued")
    payload = stages.progress_payload(store.get_application(app_id))
    assert payload["current_step"] == 0  # nothing started yet
    assert payload["total"] == len(stages.STAGE_KEYS)
    assert set(_states(store.get_application(app_id)).values()) == {"pending"}


def test_mark_stage_advances_and_closes_the_previous(tmp_path):
    store, app_id = _store_with_app(tmp_path)
    stages.mark_stage(store, app_id, "deck")
    stages.mark_stage(store, app_id, "extract")

    application = store.get_application(app_id)
    assert _states(application)["deck"] == "done"
    assert _states(application)["extract"] == "active"
    assert _states(application)["market"] == "pending"

    payload = stages.progress_payload(application)
    assert payload["current"] == "extract"
    assert payload["current_step"] == 2
    # the closed-out stage carries a duration, the running one does not yet
    seconds = {step["key"]: step["seconds"] for step in payload["steps"]}
    assert seconds["deck"] is not None
    assert seconds["extract"] is None


def test_labels_are_investor_facing_and_ordered(tmp_path):
    store, app_id = _store_with_app(tmp_path)
    stages.mark_stage(store, app_id, "market")
    payload = stages.progress_payload(store.get_application(app_id))
    assert [step["label"] for step in payload["steps"]] == [label for _, label in stages.STAGES]
    assert payload["typical_duration"] == stages.TYPICAL_DURATION


def test_failure_marks_the_stage_that_broke(tmp_path):
    store, app_id = _store_with_app(tmp_path)
    stages.mark_stage(store, app_id, "deck")
    stages.mark_stage(store, app_id, "market")
    stages.mark_failed(store, app_id)

    application = store.get_application(app_id)
    application.evaluation_state = "failed"
    payload = stages.progress_payload(application)
    assert payload["failed"] == "market"
    assert _states(application)["market"] == "failed"
    assert _states(application)["deck"] == "done"        # earlier work still shown
    assert _states(application)["enrichment"] == "pending"
    assert payload["current_step"] == 3                   # points at the break


def test_complete_marks_every_stage_done(tmp_path):
    store, app_id = _store_with_app(tmp_path)
    stages.mark_stage(store, app_id, "deck")
    stages.mark_complete(store, app_id)

    payload = stages.progress_payload(store.get_application(app_id))
    assert payload["complete"] is True
    assert payload["current_step"] == payload["total"]
    assert set(_states(store.get_application(app_id)).values()) == {"done"}


def test_thesis_fit_early_exit_still_reads_as_finished(tmp_path):
    """A thesis-fit rejection writes a decision without scoring any axis. The
    run is genuinely over, so the checklist must not be frozen mid-pipeline."""
    store, app_id = _store_with_app(tmp_path)
    stages.mark_stage(store, app_id, "axes")
    stages.mark_complete(store, app_id)  # what write_decision does

    application = store.get_application(app_id)
    assert set(_states(application).values()) == {"done"}
    assert stages.progress_payload(application)["complete"] is True


def test_evaluated_state_alone_reads_as_complete(tmp_path):
    """Applications evaluated before this feature existed have no progress blob;
    they must still render as finished rather than as a stalled checklist."""
    store, app_id = _store_with_app(tmp_path, state="evaluated")
    application = store.get_application(app_id)
    assert application.evaluation_progress == {}
    assert set(_states(application).values()) == {"done"}


def test_progress_survives_a_store_round_trip(tmp_path):
    """Progress is written from the evaluation's background thread and read by
    request handlers, so it has to persist, not just live in memory."""
    path = str(tmp_path / "stages.db")
    store = MemoryStore(path=path)
    application = Application(company_id="c1", evaluation_state="running")
    store.add_application(application)
    stages.mark_stage(store, application.id, "enrichment")

    reloaded = MemoryStore(path=path).get_application(application.id)
    assert stages.progress_payload(reloaded)["current"] == "enrichment"


def test_unknown_stage_key_is_ignored(tmp_path):
    store, app_id = _store_with_app(tmp_path)
    stages.mark_stage(store, app_id, "deck")
    stages.mark_stage(store, app_id, "not-a-stage")
    assert stages.progress_payload(store.get_application(app_id))["current"] == "deck"


def test_writers_never_raise_on_a_missing_application(tmp_path):
    """Progress is a display aid: it must never take down an evaluation."""
    store = MemoryStore(path=str(tmp_path / "stages.db"))
    stages.mark_stage(store, "nope", "deck")
    stages.mark_failed(store, "nope")
    stages.mark_complete(store, "nope")
