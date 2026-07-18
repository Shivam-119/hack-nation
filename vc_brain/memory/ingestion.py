"""Ingestion pipeline: takes raw data from various sources, normalizes, and stores it."""

from __future__ import annotations

from datetime import datetime

from pypdf import PdfReader

from vc_brain.memory.models import (
    Application,
    ApplicationStatus,
    Company,
    DataPoint,
    Founder,
    SourceType,
)
from vc_brain.memory.store import MemoryStore


class IngestionPipeline:
    def __init__(self, store: MemoryStore):
        self.store = store

    def ingest_application(
        self,
        company_name: str,
        deck_path: str = "",
        founder_name: str = "",
        founder_email: str = "",
        extra_fields: dict | None = None,
    ) -> Application:
        """Process an inbound application (minimum: company name + deck)."""
        deck_text = ""
        if deck_path:
            deck_text = self._extract_deck_text(deck_path)

        # Create or update founder
        founder = Founder(
            name=founder_name or "Unknown",
            email=founder_email,
            data_points=[
                DataPoint(
                    source=SourceType.APPLICATION,
                    content={"role": "applicant", **(extra_fields or {})},
                )
            ],
        )
        founder = self.store.upsert_founder(founder)

        # Create or update company
        company = Company(
            name=company_name,
            founder_ids=[founder.id],
            data_points=[
                DataPoint(
                    source=SourceType.APPLICATION,
                    content={"deck_length": len(deck_text), "has_deck": bool(deck_text)},
                )
            ],
        )
        if extra_fields:
            company.sector = extra_fields.get("sector", "")
            company.stage = extra_fields.get("stage", "")
            company.geography = extra_fields.get("geography", "")
            company.description = extra_fields.get("description", "")

        company = self.store.upsert_company(company)

        # Create application
        app = Application(
            company_id=company.id,
            founder_ids=[founder.id],
            deck_text=deck_text,
            deck_path=deck_path,
            source_channel="inbound",
        )
        app = self.store.add_application(app)

        return app

    def ingest_founder_from_source(
        self,
        source: SourceType,
        data: dict,
    ) -> Founder:
        """Ingest a founder profile discovered via outbound sourcing."""
        founder = Founder(
            name=data.get("name", "Unknown"),
            email=data.get("email", ""),
            github_url=data.get("github_url", ""),
            linkedin_url=data.get("linkedin_url", ""),
            twitter_url=data.get("twitter_url", ""),
            location=data.get("location", ""),
            bio=data.get("bio", ""),
            skills=data.get("skills", []),
            data_points=[
                DataPoint(
                    source=source,
                    source_url=data.get("profile_url", ""),
                    content=data,
                    confidence=data.get("confidence", 0.5),
                )
            ],
        )
        return self.store.upsert_founder(founder)

    def _extract_deck_text(self, path: str) -> str:
        """Extract text from a PDF pitch deck."""
        try:
            reader = PdfReader(path)
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n---\n\n".join(pages)
        except Exception:
            return ""
