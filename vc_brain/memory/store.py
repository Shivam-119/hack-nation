"""Entity store backed by SQLite (durable + atomic).

Keeps an in-memory cache of the Pydantic entities for reads/search, and
write-throughs every upsert to SQLite as a single-row transaction (see
`vc_brain.memory.db`). The public API is unchanged and synchronous, so every
caller (`scanner.ingest()`, agents, API routes, tests) is untouched.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from vc_brain.config import config
from vc_brain.memory import db
from vc_brain.memory.models import (
    Application,
    Company,
    DataPoint,
    Founder,
)


class MemoryStore:
    """SQLite-backed entity store with an in-memory read/search cache."""

    def __init__(self, path: str | None = None):
        # `path` (a file) stays supported for tests; else the configured DB URL.
        url = f"sqlite:///{path}" if path else config.database_url
        self._engine = db.make_engine(url)
        self.founders: dict[str, Founder] = {}
        self.companies: dict[str, Company] = {}
        self.applications: dict[str, Application] = {}
        self._load()

    # -- Founders -----------------------------------------------------------
    def upsert_founder(self, founder: Founder) -> Founder:
        existing = self._find_founder_by_identity(founder)
        if existing:
            # Merge data points by dedup key (latest wins) — re-ingesting the same
            # source replaces its snapshot instead of double-counting the score.
            existing.data_points = _merge_points(existing.data_points, founder.data_points)
            for field in ("name", "email", "linkedin_url", "github_url", "twitter_url",
                          "location", "bio"):
                new_val = getattr(founder, field)
                if new_val:
                    setattr(existing, field, new_val)
            existing.skills = list(set(existing.skills + founder.skills))
            existing.updated_at = datetime.utcnow()
            self.founders[existing.id] = existing
            self._persist_founder(existing)
            return existing
        self.founders[founder.id] = founder
        self._persist_founder(founder)
        return founder

    def get_founder(self, founder_id: str) -> Founder | None:
        return self.founders.get(founder_id)

    def search_founders(self, **filters: Any) -> list[Founder]:
        results = list(self.founders.values())
        for key, val in filters.items():
            if val is None:
                continue
            results = [f for f in results if _matches(f, key, val)]
        return results

    def _find_founder_by_identity(self, founder: Founder) -> Founder | None:
        """Deduplication: match on email or GitHub URL (case-insensitive)."""
        email = _norm(founder.email)
        gh = _norm(founder.github_url)
        for existing in self.founders.values():
            if email and email == _norm(existing.email):
                return existing
            if gh and gh == _norm(existing.github_url):
                return existing
        return None

    # -- Companies ----------------------------------------------------------
    def upsert_company(self, company: Company) -> Company:
        for existing in self.companies.values():
            if company.name.lower() == existing.name.lower():
                existing.data_points = _merge_points(existing.data_points, company.data_points)
                for field in ("website", "sector", "stage", "geography", "description"):
                    new_val = getattr(company, field)
                    if new_val:
                        setattr(existing, field, new_val)
                existing.founder_ids = list(set(existing.founder_ids + company.founder_ids))
                existing.updated_at = datetime.utcnow()
                self.companies[existing.id] = existing
                self._persist_company(existing)
                return existing
        self.companies[company.id] = company
        self._persist_company(company)
        return company

    def get_company(self, company_id: str) -> Company | None:
        return self.companies.get(company_id)

    # -- Applications -------------------------------------------------------
    def add_application(self, app: Application) -> Application:
        self.applications[app.id] = app
        self._persist_application(app)
        return app

    def get_application(self, app_id: str) -> Application | None:
        return self.applications.get(app_id)

    def list_applications(self, status: str | None = None) -> list[Application]:
        apps = list(self.applications.values())
        if status:
            apps = [a for a in apps if a.status.value == status]
        return apps

    # -- Persistence (write-through to SQLite) ------------------------------
    def _persist_founder(self, f: Founder) -> None:
        db.upsert_row(self._engine, db.founders_table, f.id, {
            "email": f.email or None,
            "github_url": f.github_url or None,
            "twitter_url": f.twitter_url or None,
            "linkedin_url": f.linkedin_url or None,
            "name": f.name or None,
            "updated_at": f.updated_at.isoformat(),
            "data": json.dumps(f.model_dump(mode="json")),
        })

    def _persist_company(self, c: Company) -> None:
        db.upsert_row(self._engine, db.companies_table, c.id, {
            "name": c.name or None,
            "updated_at": c.updated_at.isoformat(),
            "data": json.dumps(c.model_dump(mode="json")),
        })

    def _persist_application(self, a: Application) -> None:
        db.upsert_row(self._engine, db.applications_table, a.id, {
            "company_id": a.company_id or None,
            "status": a.status.value,
            "updated_at": a.submitted_at.isoformat(),
            "data": json.dumps(a.model_dump(mode="json")),
        })

    def _load(self) -> None:
        """Rehydrate the cache from SQLite. A row that fails to parse/validate is
        skipped individually — a bad record never wipes the whole store."""
        for fid, data in db.load_rows(self._engine, db.founders_table).items():
            try:
                self.founders[fid] = Founder(**data)
            except Exception:
                continue
        for cid, data in db.load_rows(self._engine, db.companies_table).items():
            try:
                self.companies[cid] = Company(**data)
            except Exception:
                continue
        for aid, data in db.load_rows(self._engine, db.applications_table).items():
            try:
                self.applications[aid] = Application(**data)
            except Exception:
                continue


def _merge_points(existing: list[DataPoint], incoming: list[DataPoint]) -> list[DataPoint]:
    """Merge data points by dedup_key, keeping the latest for each key."""
    by_key: dict[str, DataPoint] = {dp.dedup_key(): dp for dp in existing}
    for dp in incoming:
        by_key[dp.dedup_key()] = dp
    return list(by_key.values())


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def _matches(obj: Any, key: str, val: Any) -> bool:
    attr = getattr(obj, key, None)
    if attr is None:
        return False
    if isinstance(attr, str):
        return val.lower() in attr.lower()
    if isinstance(attr, list):
        return val in attr
    return attr == val
