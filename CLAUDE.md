# VC Brain — Project Standards

## Stack
- Python 3.11+, FastAPI, Pydantic v2, httpx
- LLM: OpenAI GPT-4o (primary), Anthropic Claude (fallback)
- Storage: JSON-backed in-memory store (swap to SQLite/Postgres later)
- Frontend: Vanilla HTML/JS served by FastAPI

## Agentic Coding Practices

### 1. Structured Outputs — Always Use Pydantic
Every LLM response that feeds into the system MUST be parsed through a Pydantic model.
Never trust raw strings from an LLM for downstream logic.

```python
# GOOD: Pydantic model validates and types the LLM output
result = await complete_json(prompt, system=SYSTEM)
screening = ScreeningResult(**result)

# BAD: Using raw dict from LLM without validation
result = await complete_json(prompt)
score = result["score"]  # No validation, no type safety
```

### 2. Agent Loop Pattern: Observe → Think → Act
All agents follow this loop. Each step is logged for traceability.

```python
async def agent_step(state: AgentState) -> AgentState:
    observation = await observe(state)   # Gather data
    reasoning = await think(observation) # LLM reasoning
    action = await act(reasoning)        # Execute action
    return state.update(observation, reasoning, action)
```

### 3. Prompt Files
Store prompts in `prompts/` as plain text or YAML. Never inline long prompts in Python code.
System prompts go in `prompts/system/`, user prompt templates in `prompts/templates/`.

### 4. Memory Persistence
- Founder Score is append-only history. Never overwrite — snapshot and append.
- Every data point gets a `source`, `confidence`, and `extracted_at` timestamp.
- Deduplication happens on ingest (email, GitHub URL), not on read.
- When an agent writes to memory, it logs what changed and why.

### 5. Trust and Confidence
- Trust Scores are per-claim, not per-entity.
- Confidence is 0.0–1.0. Default to 0.5 (uncertain), never 1.0 (no claim is fully verified).
- Flag contradictions explicitly — never silently resolve them.

### 6. Error Handling in Agent Flows
- LLM calls can fail. Always provide a deterministic fallback.
- Never let a single LLM failure crash the pipeline.
- Log the failure, return a degraded result, and flag confidence as low.

### 7. Tool Use
- Pydantic for all data parsing and validation
- httpx for async HTTP (not requests)
- pypdf for deck extraction
- JSON for persistence (upgrade path to SQLite via SQLAlchemy)

## Code Style
- Type hints on all function signatures
- `from __future__ import annotations` at top of every module
- No wildcard imports
- Keep modules under 300 lines — split if larger
- Tests in `tests/` mirroring the source tree

## Git
- Commit messages: imperative mood, lowercase, no period
- Branch per feature: `feat/sourcing-linkedin`, `fix/dedup-logic`
