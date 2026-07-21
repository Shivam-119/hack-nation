"""Entry point: run the VC Brain server.

Seeds the demo inbox fixtures into the DB before the app starts, so a fresh
checkout shows the 10 sample applications on first run (idempotent — existing
data is left in place). Set VC_BRAIN_SEED=0 to skip.
"""

import os

import uvicorn


def _seed() -> None:
    if os.getenv("VC_BRAIN_SEED", "1").lower() in ("0", "false", "no"):
        return
    try:
        from vc_brain.memory.seed import ensure_seeded

        ensure_seeded()
    except Exception as exc:  # never let seeding block the server
        print(f"[seed] skipped: {exc}")


if __name__ == "__main__":
    _seed()
    # Host platforms inject $PORT. reload is dev-only (VC_BRAIN_RELOAD=1 to enable).
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("VC_BRAIN_RELOAD", "0").lower() in ("1", "true", "yes")
    uvicorn.run("vc_brain.api.app:app", host="0.0.0.0", port=port, reload=reload)
