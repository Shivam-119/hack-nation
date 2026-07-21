"""Keep the instance awake while an evaluation is in flight.

Free hosts spin an instance down after ~15 minutes with no *inbound* traffic.
A background evaluation is not inbound traffic, so a multi-minute run is killed
the moment the last browser tab stops polling -- taking the in-flight job with
it. While work is queued or running we therefore ping our own public URL, which
does arrive through the load balancer and counts as traffic.

Deliberately scoped to active evaluations rather than running always: an
always-on pinger would consume essentially the whole free monthly instance-hour
allowance to solve a problem that only exists during a run.
"""

from __future__ import annotations

import logging
import threading

import httpx

from vc_brain.config import config
from vc_brain.memory.store import MemoryStore

logger = logging.getLogger(__name__)

ACTIVE_STATES = {"queued", "running"}

_thread: threading.Thread | None = None
_lock = threading.Lock()
_stop = threading.Event()


def _work_in_flight(store: MemoryStore) -> bool:
    try:
        return any(app.evaluation_state in ACTIVE_STATES for app in store.list_applications())
    except Exception:  # noqa: BLE001 -- a read failure must not strand the loop
        logger.warning("keepalive: could not read applications; stopping", exc_info=True)
        return False


def _loop(store: MemoryStore, url: str, interval: float) -> None:
    """Ping until nothing is queued or running, then exit."""
    global _thread
    try:
        while _work_in_flight(store):
            # Sleep first: the request that queued the work is itself fresh
            # traffic, so an immediate ping would be redundant.
            if _stop.wait(interval):
                return
            if not _work_in_flight(store):
                return
            try:
                httpx.get(url, timeout=30)
                logger.info("keepalive: pinged %s", url)
            except Exception:  # noqa: BLE001 -- a failed ping is not fatal
                logger.warning("keepalive: ping failed", exc_info=True)
    finally:
        with _lock:
            _thread = None


def ensure_running(store: MemoryStore) -> None:
    """Start the pinger if it is not already running. Safe to call per request.

    A no-op when no public URL is configured, which is the case locally and in
    tests -- so this never spawns a thread during development.
    """
    global _thread
    if not config.keepalive_url:
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        url = f"{config.keepalive_url}/api/health"
        _thread = threading.Thread(
            target=_loop,
            args=(store, url, max(1.0, float(config.keepalive_interval_seconds))),
            name="keepalive",
            daemon=True,
        )
        _thread.start()
        logger.info("keepalive: started, pinging %s every %ss", url, config.keepalive_interval_seconds)


def stop() -> None:
    """Stop the pinger. Used by tests; production lets it exit on its own."""
    _stop.set()
