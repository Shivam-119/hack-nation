"""SQLite-backed memory store.

Replaces the JSON file store. Each entity is persisted as a JSON blob in SQLite.
Same public interface as before — callers don't need to change.

Schema:
  founders(id TEXT PK, data TEXT)
  companies(id TEXT PK, name TEXT, data TEXT)
  applications(id TEXT PK, status TEXT, data TEXT)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session

from vc_brain.memory.models import Application, Company, Founder


# ── ORM models ────────────────────────────────────────────────────────────────

class _Base(DeclarativeBase):
    pass


class _FounderRow(_Base):
    __tablename__ = "founders"
    id = Column(String, primary_key=True)
    email = Column(String, index=True, default="")
    github_url = Column(String, index=True, default="")
    name_lower = Column(String, index=True, default="")
    location_lower = Column(String, index=True, default="")
    skills_text = Column(Text, default="")  # space-joined skills for FTS
    data = Column(Text, nullable=False)


class _CompanyRow(_Base):
    __tablename__ = "companies"
    id = Column(String, primary_key=True)
    name_lower = Column(String, index=True, default="")
    data = Column(Text, nullable=False)


class _ApplicationRow(_Base):
    __tablename__ = "applications"
    id = Column(String, primary_key=True)
    status = Column(String, index=True, default="received")
    data = Column(Text, nullable=False)


# ── Store ──────────────────────────────────────────────────────────────────────

class MemoryStore:
    """SQLite-backed store with an in-memory cache for fast reads."""

    def __init__(self, db_path: str = "vc_brain.db"):
        url = f"sqlite:///{db_path}"
        self._engine = create_engine(url, connect_args={"check_same_thread": False})
        _Base.metadata.create_all(self._engine)
        self._migrate()

        # Warm in-memory cache from DB on startup
        self.founders: dict[str, Founder] = {}
        self.companies: dict[str, Company] = {}
        self.applications: dict[str, Application] = {}
        self._load()

    # -- Founders -----------------------------------------------------------

    def upsert_founder(self, founder: Founder) -> Founder:
        existing = self._find_founder_by_identity(founder)
        if existing:
            existing.data_points.extend(founder.data_points)
            for field in ("name", "email", "linkedin_url", "github_url", "twitter_url",
                          "location", "bio"):
                new_val = getattr(founder, field)
                if new_val:
                    setattr(existing, field, new_val)
            existing.skills = list(set(existing.skills + founder.skills))
            existing.updated_at = datetime.utcnow()
            self.founders[existing.id] = existing
            self._save_founder(existing)
            return existing

        self.founders[founder.id] = founder
        self._save_founder(founder)
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
        for existing in self.founders.values():
            if founder.email and founder.email == existing.email:
                return existing
            if founder.github_url and founder.github_url == existing.github_url:
                return existing
        return None

    # -- Companies ----------------------------------------------------------

    def upsert_company(self, company: Company) -> Company:
        for existing in self.companies.values():
            if company.name.lower() == existing.name.lower():
                existing.data_points.extend(company.data_points)
                for field in ("website", "sector", "stage", "geography", "description"):
                    new_val = getattr(company, field)
                    if new_val:
                        setattr(existing, field, new_val)
                existing.founder_ids = list(set(existing.founder_ids + company.founder_ids))
                existing.updated_at = datetime.utcnow()
                self.companies[existing.id] = existing
                self._save_company(existing)
                return existing

        self.companies[company.id] = company
        self._save_company(company)
        return company

    def get_company(self, company_id: str) -> Company | None:
        return self.companies.get(company_id)

    # -- Applications -------------------------------------------------------

    def add_application(self, app: Application) -> Application:
        self.applications[app.id] = app
        self._save_application(app)
        return app

    def get_application(self, app_id: str) -> Application | None:
        return self.applications.get(app_id)

    def list_applications(self, status: str | None = None) -> list[Application]:
        apps = list(self.applications.values())
        if status:
            apps = [a for a in apps if a.status.value == status]
        return apps

    # -- SQLite persistence -------------------------------------------------

    def _migrate(self) -> None:
        """Add new columns to existing tables without dropping data."""
        migrations = [
            ("founders", "name_lower", "TEXT DEFAULT ''"),
            ("founders", "location_lower", "TEXT DEFAULT ''"),
            ("founders", "skills_text", "TEXT DEFAULT ''"),
        ]
        with self._engine.connect() as conn:
            for table, col, col_def in migrations:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                    conn.commit()
                except Exception:
                    pass  # Column already exists

    def search_founders_by_text(self, query: str, limit: int = 20) -> list[Founder]:
        """Fast indexed text search across name, location, and skills."""
        q = query.lower()
        with Session(self._engine) as session:
            rows = (
                session.query(_FounderRow)
                .filter(
                    _FounderRow.name_lower.contains(q)
                    | _FounderRow.location_lower.contains(q)
                    | _FounderRow.skills_text.contains(q)
                )
                .limit(limit)
                .all()
            )
        results = []
        for row in rows:
            try:
                results.append(Founder.model_validate_json(row.data))
            except Exception:
                pass
        return results

    def _save_founder(self, founder: Founder) -> None:
        blob = founder.model_dump_json()
        skills_text = " ".join(s.lower() for s in founder.skills)
        with Session(self._engine) as session:
            row = session.get(_FounderRow, founder.id)
            if row:
                row.data = blob
                row.email = founder.email or ""
                row.github_url = founder.github_url or ""
                row.name_lower = founder.name.lower()
                row.location_lower = (founder.location or "").lower()
                row.skills_text = skills_text
            else:
                session.add(_FounderRow(
                    id=founder.id,
                    email=founder.email or "",
                    github_url=founder.github_url or "",
                    name_lower=founder.name.lower(),
                    location_lower=(founder.location or "").lower(),
                    skills_text=skills_text,
                    data=blob,
                ))
            session.commit()

    def _save_company(self, company: Company) -> None:
        blob = company.model_dump_json()
        with Session(self._engine) as session:
            row = session.get(_CompanyRow, company.id)
            if row:
                row.data = blob
                row.name_lower = company.name.lower()
            else:
                session.add(_CompanyRow(
                    id=company.id,
                    name_lower=company.name.lower(),
                    data=blob,
                ))
            session.commit()

    def _save_application(self, app: Application) -> None:
        blob = app.model_dump_json()
        with Session(self._engine) as session:
            row = session.get(_ApplicationRow, app.id)
            if row:
                row.data = blob
                row.status = app.status.value
            else:
                session.add(_ApplicationRow(
                    id=app.id,
                    status=app.status.value,
                    data=blob,
                ))
            session.commit()

    def _load(self) -> None:
        """Hydrate in-memory cache from SQLite on startup."""
        with Session(self._engine) as session:
            for row in session.query(_FounderRow).all():
                try:
                    self.founders[row.id] = Founder.model_validate_json(row.data)
                except Exception:
                    pass
            for row in session.query(_CompanyRow).all():
                try:
                    self.companies[row.id] = Company.model_validate_json(row.data)
                except Exception:
                    pass
            for row in session.query(_ApplicationRow).all():
                try:
                    self.applications[row.id] = Application.model_validate_json(row.data)
                except Exception:
                    pass


def _matches(obj: Any, key: str, val: Any) -> bool:
    attr = getattr(obj, key, None)
    if attr is None:
        return False
    if isinstance(attr, str):
        return val.lower() in attr.lower()
    if isinstance(attr, list):
        return val in attr
    return attr == val
