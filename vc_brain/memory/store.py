"""In-memory store with JSON persistence. Swap for a real DB later."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from vc_brain.memory.models import (
    Application,
    Company,
    DataPoint,
    Founder,
)


class MemoryStore:
    """Simple in-memory store backed by a JSON file for persistence."""

    def __init__(self, path: str = "vc_brain_data.json"):
        self._path = Path(path)
        self.founders: dict[str, Founder] = {}
        self.companies: dict[str, Company] = {}
        self.applications: dict[str, Application] = {}
        self._load()

    # -- Founders -----------------------------------------------------------
    def upsert_founder(self, founder: Founder) -> Founder:
        existing = self._find_founder_by_identity(founder)
        if existing:
            # Merge data points, update fields
            existing.data_points.extend(founder.data_points)
            for field in ("name", "email", "linkedin_url", "github_url", "twitter_url",
                          "location", "bio"):
                new_val = getattr(founder, field)
                if new_val:
                    setattr(existing, field, new_val)
            existing.skills = list(set(existing.skills + founder.skills))
            existing.updated_at = datetime.utcnow()
            self.founders[existing.id] = existing
            self._save()
            return existing
        self.founders[founder.id] = founder
        self._save()
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
        """Deduplication: match on email or GitHub URL."""
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
                self._save()
                return existing
        self.companies[company.id] = company
        self._save()
        return company

    def get_company(self, company_id: str) -> Company | None:
        return self.companies.get(company_id)

    # -- Applications -------------------------------------------------------
    def add_application(self, app: Application) -> Application:
        self.applications[app.id] = app
        self._save()
        return app

    def get_application(self, app_id: str) -> Application | None:
        return self.applications.get(app_id)

    def list_applications(self, status: str | None = None) -> list[Application]:
        apps = list(self.applications.values())
        if status:
            apps = [a for a in apps if a.status.value == status]
        return apps

    # -- Persistence --------------------------------------------------------
    def _save(self):
        data = {
            "founders": {k: v.model_dump(mode="json") for k, v in self.founders.items()},
            "companies": {k: v.model_dump(mode="json") for k, v in self.companies.items()},
            "applications": {k: v.model_dump(mode="json") for k, v in self.applications.items()},
        }
        self._path.write_text(json.dumps(data, indent=2, default=str))

    def _load(self):
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self.founders = {k: Founder(**v) for k, v in data.get("founders", {}).items()}
            self.companies = {k: Company(**v) for k, v in data.get("companies", {}).items()}
            self.applications = {
                k: Application(**v) for k, v in data.get("applications", {}).items()
            }
        except (json.JSONDecodeError, Exception):
            pass  # Start fresh on corrupt data


def _matches(obj: Any, key: str, val: Any) -> bool:
    attr = getattr(obj, key, None)
    if attr is None:
        return False
    if isinstance(attr, str):
        return val.lower() in attr.lower()
    if isinstance(attr, list):
        return val in attr
    return attr == val
