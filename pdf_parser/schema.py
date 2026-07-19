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


class InputReference(BaseModel):
    company_name: str | None = None
    primary_industry: str


class MarketSizeEstimate(BaseModel):
    figure: str
    source_name: str
    source_url: str
    published_date: str | None = None


class MarketSize(BaseModel):
    estimates: list[MarketSizeEstimate] = Field(default_factory=list)
    notes: str | None = None


class Competitor(BaseModel):
    name: str
    description: str
    funding_status: str | None = None
    source_url: str


class RegulatoryItem(BaseModel):
    topic: str
    description: str
    source_url: str


class IndustryTrend(BaseModel):
    trend: str
    description: str
    source_url: str


class MarketResearch(BaseModel):
    input_reference: InputReference
    market_size: MarketSize
    competitors: list[Competitor] = Field(default_factory=list)
    regulatory_landscape: list[RegulatoryItem] = Field(default_factory=list)
    industry_trends: list[IndustryTrend] = Field(default_factory=list)
    search_log: list[str] = Field(default_factory=list)
    research_confidence: Literal["high", "medium", "low"]
    research_notes: list[str] = Field(default_factory=list)
