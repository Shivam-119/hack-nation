"""The keep-alive pinger that stops a free host sleeping mid-evaluation.

The two properties that matter: it pings while work is in flight, and it stops
as soon as the work is done (an always-on pinger would burn the whole free
monthly instance-hour allowance).
"""

from vc_brain.api import keepalive
from vc_brain.config import config
from vc_brain.memory.models import Application
from vc_brain.memory.store import MemoryStore


def _store(tmp_path, state):
    store = MemoryStore(path=str(tmp_path / "keepalive.db"))
    application = Application(company_id="c1", evaluation_state=state)
    store.add_application(application)
    return store, application.id


def test_no_thread_without_a_public_url(tmp_path, monkeypatch):
    """Local dev and tests configure no URL, so nothing should ever spawn."""
    monkeypatch.setattr(config, "keepalive_url", "")
    store, _ = _store(tmp_path, "running")
    keepalive.ensure_running(store)
    assert keepalive._thread is None


def test_pings_while_running_then_stops_when_work_finishes(tmp_path, monkeypatch):
    store, app_id = _store(tmp_path, "running")
    keepalive._stop.clear()
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        # The evaluation finishes right after this ping.
        application = store.get_application(app_id)
        application.evaluation_state = "evaluated"
        store.add_application(application)

    monkeypatch.setattr(keepalive.httpx, "get", fake_get)
    keepalive._loop(store, "http://x/api/health", 0.01)

    assert calls == ["http://x/api/health"]  # pinged once, then exited on its own


def test_does_not_ping_when_nothing_is_in_flight(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, "evaluated")
    keepalive._stop.clear()
    calls = []
    monkeypatch.setattr(keepalive.httpx, "get", lambda url, timeout=None: calls.append(url))
    keepalive._loop(store, "http://x/api/health", 0.01)
    assert calls == []


def test_a_failed_ping_does_not_kill_the_loop(tmp_path, monkeypatch):
    """A dropped ping is not worth abandoning the evaluation over."""
    store, app_id = _store(tmp_path, "running")
    keepalive._stop.clear()
    attempts = []

    def flaky_get(url, timeout=None):
        attempts.append(url)
        if len(attempts) == 1:
            raise RuntimeError("network blip")
        application = store.get_application(app_id)
        application.evaluation_state = "evaluated"
        store.add_application(application)

    monkeypatch.setattr(keepalive.httpx, "get", flaky_get)
    keepalive._loop(store, "http://x/api/health", 0.01)

    assert len(attempts) == 2  # retried after the failure, then work completed


def test_queued_work_counts_as_in_flight(tmp_path, monkeypatch):
    """A queued evaluation has not started yet -- sleeping now would lose it."""
    store, app_id = _store(tmp_path, "queued")
    keepalive._stop.clear()
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        application = store.get_application(app_id)
        application.evaluation_state = "failed"
        store.add_application(application)

    monkeypatch.setattr(keepalive.httpx, "get", fake_get)
    keepalive._loop(store, "http://x/api/health", 0.01)
    assert calls == ["http://x/api/health"]


def test_stop_event_ends_the_loop_immediately(tmp_path, monkeypatch):
    store, _ = _store(tmp_path, "running")
    keepalive._stop.set()
    calls = []
    monkeypatch.setattr(keepalive.httpx, "get", lambda url, timeout=None: calls.append(url))
    keepalive._loop(store, "http://x/api/health", 0.01)
    keepalive._stop.clear()
    assert calls == []
