"""Data models for the reputation scanner (web-article background check).

This tool *collects and organises evidence*; it deliberately does not judge.
There are no scores, weights, credibility tiers or risk levels anywhere in the
output -- a downstream LLM reads these findings and decides what they are
worth, including how much to trust any given publication. All we report about
a source is its name and its link.

The one number we emit is `relevance`, and it is a descriptor rather than a
judgement: how much a given article is actually *about this person*.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """What kind of thing is being researched.

    Only the query angles and the extraction prompt differ between the two --
    the search, extraction, merge and reporting machinery is shared.
    """

    PERSON = "person"
    COMPANY = "company"


class Polarity(str, Enum):
    """Whether a finding reads favourably or unfavourably. A label, not a score."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class FindingCategory(str, Enum):
    """What kind of information this is, so downstream can route it.

    The set spans both entity types; a category simply goes unused when it does
    not apply (a person has no `outage`, a company has no `education`).
    """

    # People
    AWARD = "award"  # olympiads, competitions, prizes
    EDUCATION = "education"
    PRIOR_COMPANY = "prior_company"  # founded / exited / senior role, past
    CURRENT_ROLE = "current_role"  # what they do now

    # Either
    RESEARCH = "research"  # papers, patents, citations
    FUNDING = "funding"  # rounds raised, notable backers
    PRESS = "press"  # profile or feature in a real outlet
    RECOGNITION = "recognition"  # lists, keynotes, rankings

    # Companies. Scoped to pre-seed / seed: at this stage there is no
    # workforce to lay off, no M&A, no market share -- what exists is a
    # product, the people building it, and whoever has backed them so far.
    PRODUCT = "product"  # what they are building; launches, betas, releases
    TEAM = "team"  # founders and early team behind the company
    ACCELERATOR = "accelerator"  # YC, Techstars, incubators, demo days

    # Unfavourable-leaning, either
    FRAUD = "fraud"  # fraud / scam allegations
    LEGAL = "legal"  # lawsuits, court, regulator action
    CONTROVERSY = "controversy"  # misconduct, public controversy
    FAILURE = "failure"  # shutdown, insolvency, mass layoffs
    RUMOR = "rumor"  # unverified forum / social chatter

    OTHER = "other"


# Relevance anchors -- how much an article is actually about the person.
RELEVANCE_DIRECT = 10  # the article is about them
RELEVANCE_INCIDENTAL = 1  # name appears in passing, e.g. a comment thread
RELEVANCE_DEFAULT = 5


class Article(BaseModel):
    """One web result retrieved by a search provider."""

    title: str = ""
    url: str = ""
    snippet: str = ""  # short blurb returned by search
    full_text: str = ""  # full page body, when /extract was run on it
    extracted: bool = False  # True once full_text was fetched
    source: str = ""  # publication name, e.g. "reuters.com"
    published: str = ""
    query: str = ""  # which query angle surfaced this
    intent: str = ""  # positive | negative | background
    raw: dict[str, Any] = Field(default_factory=dict)

    def best_text(self, limit: int = 0) -> str:
        """Richest text available for this article, optionally truncated."""
        text = self.full_text.strip() or self.snippet.strip()
        if limit and len(text) > limit:
            return text[:limit].rsplit(" ", 1)[0] + " ..."
        return text


class SourceRef(BaseModel):
    """A single article backing a finding -- the 'proof' link."""

    source: str = ""  # publication name, e.g. "sec.gov"
    url: str = ""
    title: str = ""
    published: str = ""
    relevance: int = RELEVANCE_DEFAULT
    """How much THIS article is about the person, 1-10.

    10 = the article is directly and substantially about them.
     1 = the name appears incidentally, e.g. in the comments of an unrelated
         article, and may not even be the same person.
    """


class ReputationFinding(BaseModel):
    """One summarised piece of information, with every source that supports it.

    Findings describing the same thing across several outlets are merged, so
    `sources` may hold many entries -- that is the corroboration signal, left
    raw for downstream to weigh.
    """

    summary: str = ""  # the summarised information, one or two sentences
    category: FindingCategory = FindingCategory.OTHER
    polarity: Polarity = Polarity.NEUTRAL
    entity: str = ""  # company / institution / publication involved
    relevance: int = RELEVANCE_DEFAULT  # best relevance among its sources
    confidence: float = 0.5  # how well the text supports it, 0-1, never 1.0
    sources: list[SourceRef] = Field(default_factory=list)

    @property
    def source_count(self) -> int:
        """Number of distinct articles supporting this finding."""
        return len(self.sources)

    @property
    def primary_source(self) -> SourceRef | None:
        return self.sources[0] if self.sources else None


class ReputationReport(BaseModel):
    """Everything the sweep found about one person, organised but unjudged."""

    name: str
    hint: str = ""
    entity: EntityType = EntityType.PERSON
    findings: list[ReputationFinding] = Field(default_factory=list)
    by_category: dict[str, int] = Field(default_factory=dict)  # category -> count
    by_polarity: dict[str, int] = Field(default_factory=dict)  # polarity -> count
    articles_reviewed: int = 0
    articles_extracted: int = 0  # how many were read in full, not just snippet
    queries_run: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)  # every URL retrieved
    gaps: list[str] = Field(default_factory=list)  # what we could NOT establish
    provider: str = "mock"
    generated_at: datetime = Field(default_factory=datetime.utcnow)
