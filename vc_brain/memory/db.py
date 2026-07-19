"""SQLite persistence backend for the Memory store (SQLAlchemy 2.0, synchronous).

Each entity is one row: identity columns broken out for dedup + querying, plus
the full Pydantic `model_dump(mode="json")` in a `data` column. The engine is
SYNCHRONOUS on purpose — the whole store API (and every `scanner.ingest()`,
agent, and route that calls it) is sync; an async/aiosqlite engine would force
rewriting all of them. `aiosqlite` remains the documented async upgrade path.

Durability comes from SQLite: every write is a single-row transaction (atomic),
and loading skips an individual corrupt row rather than discarding the whole
store — the two failure modes the old JSON file had.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import (
    Column,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

founders_table = Table(
    "founders",
    metadata,
    Column("id", String, primary_key=True),
    Column("email", String, index=True),
    Column("github_url", String, index=True),
    Column("twitter_url", String, index=True),
    Column("linkedin_url", String, index=True),
    Column("name", String, index=True),
    Column("updated_at", String),
    Column("data", Text, nullable=False),
)

companies_table = Table(
    "companies",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, index=True),
    Column("updated_at", String),
    Column("data", Text, nullable=False),
)

applications_table = Table(
    "applications",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, index=True),
    Column("status", String, index=True),
    Column("updated_at", String),
    Column("data", Text, nullable=False),
)


def to_sync_url(url: str) -> str:
    """Coerce an async SQLite URL to the sync driver (the store is synchronous)."""
    return url.replace("+aiosqlite", "").replace("+pysqlite", "")


def make_engine(url: str) -> Engine:
    engine = create_engine(to_sync_url(url), future=True)
    metadata.create_all(engine)
    return engine


def load_rows(engine: Engine, table: Table) -> dict[str, dict[str, Any]]:
    """Return {id: parsed data dict}. A single unparseable row is skipped, never
    wiping the whole table (the old JSON store's silent-total-wipe bug)."""
    out: dict[str, dict[str, Any]] = {}
    with engine.connect() as conn:
        for row in conn.execute(select(table.c.id, table.c.data)):
            try:
                out[row.id] = json.loads(row.data)
            except (json.JSONDecodeError, TypeError):
                continue
    return out


def upsert_row(engine: Engine, table: Table, row_id: str, values: dict[str, Any]) -> None:
    """Insert or update one row inside a single atomic transaction."""
    with engine.begin() as conn:
        exists = conn.execute(select(table.c.id).where(table.c.id == row_id)).first()
        if exists:
            conn.execute(update(table).where(table.c.id == row_id).values(**values))
        else:
            conn.execute(insert(table).values(id=row_id, **values))


def get_row(engine: Engine, table: Table, row_id: str) -> dict[str, Any] | None:
    """Fetch one entity's data dict by primary id."""
    with engine.connect() as conn:
        row = conn.execute(select(table.c.data).where(table.c.id == row_id)).first()
    return _parse(row)


def find_row(engine: Engine, table: Table, **identity: str) -> dict[str, Any] | None:
    """First entity matching ANY of the given identity columns (case-insensitive)."""
    conds = [func.lower(table.c[col]) == str(val).strip().lower()
             for col, val in identity.items() if val]
    if not conds:
        return None
    with engine.connect() as conn:
        row = conn.execute(select(table.c.data).where(or_(*conds))).first()
    return _parse(row)


def _parse(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    try:
        return json.loads(row.data)
    except (json.JSONDecodeError, TypeError):
        return None
