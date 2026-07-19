"""Core domain models for the Memory layer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    PITCH_DECK = "pitch_deck"
    GITHUB = "github"
    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    PRODUCT_HUNT = "product_hunt"
    HACKER_NEWS = "hacker_news"
    ARXIV = "arxiv"
    CRUNCHBASE = "crunchbase"
    ACCELERATOR = "accelerator"
    WEB = "web"  # press, court/regulator filings, journals -- reputation scanner
    MANUAL = "manual"
    APPLICATION = "application"


class Trend(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"


# ---------------------------------------------------------------------------
# Data Point — every piece of evidence is tracked individually
# ---------------------------------------------------------------------------
class DataPoint(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    source: SourceType
    source_url: str = ""
    content: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.5  # 0-1 trust score for this data point
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    tags: list[str] = Field(default_factory=list)

    def dedup_key(self) -> str:
        """Identity of this data point for merge-on-ingest (latest wins).

        A re-scanned profile SNAPSHOT (github/socials/etc.) shares
        (source, url, type), so re-ingesting the same source replaces it instead
        of appending a duplicate — that's what prevented the Founder Score from
        doubling. Reputation FINDINGS are list items, so they also key on a
        content hash to stay distinct even under the same (source, url)."""
        kind = str(self.content.get("type") or self.content.get("kind") or "")
        base = f"{self.source.value}|{self.source_url}|{kind}"
        if kind == "reputation_finding":
            digest = hashlib.sha1(
                json.dumps(self.content, sort_keys=True, default=str).encode()
            ).hexdigest()[:12]
            return f"{base}|{digest}"
        return base


# ---------------------------------------------------------------------------
# Founder — persistent across applications, carries the Founder Score
# ---------------------------------------------------------------------------
class FounderScore(BaseModel):
    """Persists across applications, never resets."""
    overall: float = 0.0  # 0-100
    technical: float = 0.0
    execution: float = 0.0
    leadership: float = 0.0
    domain_expertise: float = 0.0
    trend: Trend = Trend.STABLE
    history: list[dict[str, Any]] = Field(default_factory=list)  # timestamped snapshots


class Founder(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    email: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    twitter_url: str = ""
    location: str = ""
    bio: str = ""
    skills: list[str] = Field(default_factory=list)
    education: list[dict[str, str]] = Field(default_factory=list)
    work_history: list[dict[str, str]] = Field(default_factory=list)
    data_points: list[DataPoint] = Field(default_factory=list)
    score: FounderScore = Field(default_factory=FounderScore)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Company / Startup
# ---------------------------------------------------------------------------
class Company(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    website: str = ""
    sector: str = ""
    stage: str = ""  # pre-seed, seed, series-a, etc.
    geography: str = ""
    description: str = ""
    founded_date: str = ""
    founder_ids: list[str] = Field(default_factory=list)
    data_points: list[DataPoint] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Application — inbound or activated-outbound
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    RECEIVED = "received"
    SCREENING = "screening"
    DILIGENCE = "diligence"
    DECISION = "decision"
    FUNDED = "funded"
    PASSED = "passed"


class Application(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    company_id: str
    founder_ids: list[str] = Field(default_factory=list)
    status: ApplicationStatus = ApplicationStatus.RECEIVED
    source_channel: str = "inbound"  # inbound | outbound-github | outbound-hn | ...
    deck_text: str = ""  # extracted pitch deck text
    deck_path: str = ""
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    screening_result: dict[str, Any] | None = None
    diligence_result: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
