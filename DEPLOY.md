# Deploying VC Brain (free)

One FastAPI process serves both the API and the built React frontend, and the DB
auto-seeds the demo apps on startup — so a free, ephemeral host works out of the box.

## Render (recommended, free)

1. Push to GitHub (already done).
2. In the [Render dashboard](https://dashboard.render.com) → **New → Blueprint**, pick
   this repo. It reads `render.yaml` and builds the `Dockerfile`.
3. Set the three secret env vars when prompted:
   - `OPENAI_API_KEY`
   - `APIFY_TOKEN` (optional — only for live socials)
   - `TAVILY_API_KEY` (optional — only for live reputation/identity)
4. Deploy. First build takes a few minutes (installs deps + builds the frontend).

Free tier sleeps after ~15 min idle (≈30s cold start) and the disk is ephemeral — the
seeded demo data regenerates on each start, so that's fine. Real submissions are lost on
restart; see "Persistent data" below to keep them.

## Run the container locally (same image as prod)

```bash
docker build -t vc-brain .
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... vc-brain
# open http://localhost:8000
```

## Other free hosts

The `Dockerfile` is host-agnostic — it also works on **Hugging Face Spaces** (Docker
Space, no credit card), **Fly.io** (`fly launch`), or **Google Cloud Run**. All need the
same three env vars.

## Persistent data (optional)

The store is SQLite by default (`DATABASE_URL=sqlite:///./vc_brain.db`), which is ephemeral
on free hosts. To keep submitted applications across restarts, point `DATABASE_URL` at a
free Postgres (e.g. [Neon](https://neon.tech)) and add a driver (`pip install psycopg2-binary`).
The store uses generic SQLAlchemy Core, so only the connection URL changes.

## Config knobs

- `PORT` — injected by the host; the app binds it automatically.
- `VC_BRAIN_SEED=0` — skip auto-seeding the demo apps.
- `VC_BRAIN_RELOAD=1` — enable uvicorn autoreload (local dev only).
