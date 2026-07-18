# VC Brain

AI-first operating system for venture capital. Discover founders, screen opportunities, and deploy $100K checks in 24 hours.

Built for the Maschmeyer Group x Hack-Nation challenge.

## Setup

```bash
# 1. Install dependencies
pip install -e .

# 2. Configure API keys
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY or OPENAI_API_KEY

# 3. Run
python main.py
```

Dashboard: [http://localhost:8000](http://localhost:8000)
API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## How It Works

**Sourcing** — Scan GitHub and Hacker News for builders. Submit inbound applications with just a company name and deck.

**Screening** — Every opportunity scored on three independent axes: Founder, Market, and Idea vs. Market. Never averaged.

**Diligence** — Extract claims from pitch materials. Each claim gets its own Trust Score with evidence links.

**Decision** — Generate investment memos with required sections, explicit data gaps, and a clear recommendation.

The Founder Score persists across applications and never resets — it follows the person, not the startup.
