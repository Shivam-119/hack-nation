from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MarketSizeClaim(BaseModel):
    claim: str
    value: str | None = None
    source_cited_in_deck: str | None = None


class MarketExtraction(BaseModel):
    company_name: str | None = None
    one_line_description: str
    primary_industry: str
    sub_verticals: list[str] = Field(default_factory=list)
    target_market_segment: str
    business_model: str
    geography_focus: list[str] = Field(default_factory=list)
    stated_market_size_claims: list[MarketSizeClaim] = Field(default_factory=list)
    named_competitors_in_deck: list[str] = Field(default_factory=list)
    research_keywords: list[str] = Field(default_factory=list)
    extraction_confidence: Literal["high", "medium", "low"]
    extraction_notes: list[str] = Field(default_factory=list)
