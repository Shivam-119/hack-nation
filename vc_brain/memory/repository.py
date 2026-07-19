"""DB interface for persisting the entities our tools discover.

This is the **higher-level persistence seam**. The sourcing tools
(socials / reputation / github) stay pure data-producers — they never touch the
DB. The post-tool-processing / orchestration layer maps a tool's output into
`Founder` / `Company` entities and inserts them here.

SQLite-backed (`vc_brain.memory.db`): durable + atomic per write, and deduped by
identity (a founder/company discovered twice UPDATES rather than duplicates, and
re-ingesting the same source snapshot doesn't double its data points). Reads/
writes go straight to the DB — no in-memory cache to drift.
"""

from __future__ import annotations

import json
from datetime import datetime

from vc_brain.config import config
from vc_brain.memory import db
from vc_brain.memory.models import Company, DataPoint, Founder

_FOUNDER_FIELDS = ("name", "email", "linkedin_url", "github_url", "twitter_url", "location", "bio")
_COMPANY_FIELDS = ("website", "sector", "stage", "geography", "description")


class EntityRepository:
    """Insert / retrieve Founder + Company entities in the SQLite store."""

    def __init__(self, url: str | None = None, path: str | None = None):
        if url is None:
            url = f"sqlite:///{path}" if path else config.database_url
        self._engine = db.make_engine(url)

    # -- Founders -----------------------------------------------------------
    def upsert_founder(self, founder: Founder) -> Founder:
        """Insert a founder, or merge into an existing one matched by email/github_url."""
        existing_data = db.find_row(
            self._engine, db.founders_table,
            email=founder.email, github_url=founder.github_url,
        )
        if existing_data:
            founder = _merge_founder(Founder(**existing_data), founder)
        self._write_founder(founder)
        return founder

    def get_founder(self, founder_id: str) -> Founder | None:
        data = db.get_row(self._engine, db.founders_table, founder_id)
        return Founder(**data) if data else None

    def find_founder(self, *, email: str = "", github_url: str = "",
                     twitter_url: str = "", linkedin_url: str = "") -> Founder | None:
        data = db.find_row(
            self._engine, db.founders_table,
            email=email, github_url=github_url,
            twitter_url=twitter_url, linkedin_url=linkedin_url,
        )
        return Founder(**data) if data else None

    def all_founders(self) -> list[Founder]:
        return [Founder(**d) for d in db.load_rows(self._engine, db.founders_table).values()]

    # -- Companies ----------------------------------------------------------
    def upsert_company(self, company: Company) -> Company:
        """Insert a company, or merge into an existing one matched by name."""
        existing_data = db.find_row(self._engine, db.companies_table, name=company.name)
        if existing_data:
            company = _merge_company(Company(**existing_data), company)
        self._write_company(company)
        return company

    def get_company(self, company_id: str) -> Company | None:
        data = db.get_row(self._engine, db.companies_table, company_id)
        return Company(**data) if data else None

    def find_company(self, name: str) -> Company | None:
        data = db.find_row(self._engine, db.companies_table, name=name)
        return Company(**data) if data else None

    def all_companies(self) -> list[Company]:
        return [Company(**d) for d in db.load_rows(self._engine, db.companies_table).values()]

    def link_founder_company(
        self, founder: Founder, company_name: str, source_url: str = "", **fields: str
    ) -> Company | None:
        """Persist a discovered Company and link it to a founder (both entities locked in)."""
        name = (company_name or "").strip()
        if not name:
            return None
        company = Company(name=name, founder_ids=[founder.id])
        for key, value in fields.items():
            if value and hasattr(company, key):
                setattr(company, key, value)
        return self.upsert_company(company)

    # -- write-through ------------------------------------------------------
    def _write_founder(self, f: Founder) -> None:
        db.upsert_row(self._engine, db.founders_table, f.id, {
            "email": f.email or None,
            "github_url": f.github_url or None,
            "twitter_url": f.twitter_url or None,
            "linkedin_url": f.linkedin_url or None,
            "name": f.name or None,
            "updated_at": datetime.utcnow().isoformat(),
            "data": json.dumps(f.model_dump(mode="json")),
        })

    def _write_company(self, c: Company) -> None:
        db.upsert_row(self._engine, db.companies_table, c.id, {
            "name": c.name or None,
            "updated_at": datetime.utcnow().isoformat(),
            "data": json.dumps(c.model_dump(mode="json")),
        })


# ---------------------------------------------------------------------------
# Merge helpers (identity dedup already picked the target; combine the fields)
# ---------------------------------------------------------------------------
def _merge_points(existing: list[DataPoint], incoming: list[DataPoint]) -> list[DataPoint]:
    by_key: dict[str, DataPoint] = {dp.dedup_key(): dp for dp in existing}
    for dp in incoming:
        by_key[dp.dedup_key()] = dp  # latest wins — no double-counting on re-ingest
    return list(by_key.values())


def _merge_founder(existing: Founder, incoming: Founder) -> Founder:
    existing.data_points = _merge_points(existing.data_points, incoming.data_points)
    for field in _FOUNDER_FIELDS:
        value = getattr(incoming, field)
        if value:
            setattr(existing, field, value)
    existing.skills = sorted(set(existing.skills) | set(incoming.skills))
    existing.updated_at = datetime.utcnow()
    return existing


def _merge_company(existing: Company, incoming: Company) -> Company:
    existing.data_points = _merge_points(existing.data_points, incoming.data_points)
    for field in _COMPANY_FIELDS:
        value = getattr(incoming, field)
        if value:
            setattr(existing, field, value)
    existing.founder_ids = sorted(set(existing.founder_ids) | set(incoming.founder_ids))
    existing.updated_at = datetime.utcnow()
    return existing
