"""Investor-facing progress for a running evaluation.

An evaluation takes minutes, so the one thing the UI must never do is go silent
-- a static "in progress" line reads as a hang. This module is the single source
of truth for the ordered stages, owns the small blob persisted on the
application, and renders it for the API so the frontend stays dumb.

Every writer here is fail-soft: progress is a display aid, and losing it must
never take down the evaluation it is describing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from vc_brain.memory.store import MemoryStore

# The pipeline's real steps, in order, each with the label an investor reads.
STAGES: list[tuple[str, str]] = [
    ("deck", "Reading the deck"),
    ("extract", "Extracting the pitch"),
    ("market", "Researching the market"),
    ("enrichment", "Checking founder & company footprint"),
    ("axes", "Scoring the three axes"),
    ("decision", "Drafting the decision"),
]

STAGE_KEYS: list[str] = [key for key, _ in STAGES]
LABELS: dict[str, str] = dict(STAGES)

# Shown alongside the checklist so a long wait reads as expected, not broken.
TYPICAL_DURATION = "8–12 minutes"


def _now() -> datetime:
    return datetime.utcnow()


def _blank() -> dict[str, Any]:
    return {"current": "", "done": {}, "failed": "", "complete": False, "stage_started_at": ""}


def _elapsed(iso: str) -> float:
    """Seconds since `iso`, or 0.0 if it is missing or unparseable."""
    try:
        return max(0.0, (_now() - datetime.fromisoformat(iso)).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def _update(store: MemoryStore, application_id: str, mutate) -> None:
    """Re-read, mutate and persist the progress blob.

    Re-reads because this runs on the evaluation's background thread while
    request handlers may be writing the same row.
    """
    try:
        application = store.get_application(application_id)
        if not application:
            return
        progress = dict(application.evaluation_progress or _blank())
        progress["done"] = dict(progress.get("done") or {})
        mutate(progress)
        application.evaluation_progress = progress
        store.add_application(application)
    except Exception:  # noqa: BLE001 -- progress must never break the pipeline
        return


def _close_current(progress: dict[str, Any]) -> str:
    """Record how long the running stage took and return its key."""
    current = progress.get("current") or ""
    if current:
        progress["done"][current] = _elapsed(progress.get("stage_started_at") or "")
    return current


def mark_stage(store: MemoryStore, application_id: str, key: str) -> None:
    """Advance to `key`, closing out whichever stage was running."""
    if key not in LABELS:
        return

    def mutate(progress: dict[str, Any]) -> None:
        if (progress.get("current") or "") != key:
            _close_current(progress)
        progress.update(
            {"current": key, "failed": "", "complete": False, "stage_started_at": _now().isoformat()}
        )

    _update(store, application_id, mutate)


def mark_failed(store: MemoryStore, application_id: str) -> None:
    """Flag the stage that was running, so the UI shows *where* it broke."""

    def mutate(progress: dict[str, Any]) -> None:
        progress["failed"] = _close_current(progress)

    _update(store, application_id, mutate)


def mark_complete(store: MemoryStore, application_id: str) -> None:
    """Mark every stage done.

    Also covers the thesis-fit early exit, where the decision is written without
    any axis ever being scored -- the run really is finished, so the checklist
    must not be left showing a half-finished pipeline.
    """

    def mutate(progress: dict[str, Any]) -> None:
        _close_current(progress)
        progress.update({"current": "", "failed": "", "complete": True, "stage_started_at": ""})

    _update(store, application_id, mutate)


def progress_payload(application: Any) -> dict[str, Any]:
    """Render the stored blob as an ordered checklist for the API.

    Returns {} for applications that were never evaluated, so the UI shows its
    "not evaluated" affordance rather than an empty checklist.
    """
    state = getattr(application, "evaluation_state", "") or ""
    if state in ("", "not_requested"):
        return {}

    progress = getattr(application, "evaluation_progress", None) or {}
    done = progress.get("done") or {}
    current = progress.get("current") or ""
    failed = progress.get("failed") or ""
    complete = bool(progress.get("complete")) or state == "evaluated"

    steps: list[dict[str, Any]] = []
    current_step = 0
    for index, key in enumerate(STAGE_KEYS):
        if complete:
            step_state = "done"
        elif key == failed:
            step_state = "failed"
        elif key == current:
            step_state = "active"
        elif key in done:
            step_state = "done"
        else:
            step_state = "pending"
        if step_state in ("active", "failed"):
            current_step = index + 1
        seconds = done.get(key)
        steps.append(
            {
                "key": key,
                "label": LABELS[key],
                "state": step_state,
                "seconds": round(float(seconds), 1) if isinstance(seconds, (int, float)) else None,
            }
        )

    if complete:
        current_step = len(STAGE_KEYS)

    return {
        "steps": steps,
        "current": current,
        "current_step": current_step,  # 1-based; 0 while still queued
        "total": len(STAGE_KEYS),
        "complete": complete,
        "failed": failed,
        "elapsed_seconds": _run_elapsed(application, complete),
        # A run may advertise its own expectation -- the mock demo finishes in
        # seconds, and promising minutes there would read as broken.
        "typical_duration": progress.get("typical_duration") or TYPICAL_DURATION,
    }


def _run_elapsed(application: Any, complete: bool) -> float:
    """Total run time, computed here rather than in the browser.

    The stored timestamps are naive UTC; JavaScript parses a naive ISO string as
    *local* time, which would skew the clock by the viewer's UTC offset. Sending
    a plain number sidesteps that entirely.
    """
    started = getattr(application, "evaluation_started_at", None)
    if not started:
        return 0.0
    finished = getattr(application, "evaluation_completed_at", None) if complete else None
    try:
        return max(0.0, ((finished or _now()) - started).total_seconds())
    except TypeError:
        return 0.0
