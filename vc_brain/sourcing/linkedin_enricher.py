"""LinkedIn profile enrichment — fetches public profile data when a URL is provided."""

from __future__ import annotations

import re

import httpx
from pydantic import BaseModel, Field

from vc_brain.llm import complete_json
from vc_brain.memory.models import DataPoint, Founder, SourceType


SYSTEM = """You are extracting structured founder profile data from raw HTML or partial text
from a LinkedIn public profile page. Extract what you can; leave fields empty when not found.
Return only valid JSON matching the requested schema."""


class LinkedInProfile(BaseModel):
    name: str = ""
    headline: str = ""
    location: str = ""
    summary: str = ""
    current_company: str = ""
    current_title: str = ""
    skills: list[str] = Field(default_factory=list)
    education: list[dict[str, str]] = Field(default_factory=list)
    work_history: list[dict[str, str]] = Field(default_factory=list)
    confidence: float = 0.3  # default low — LinkedIn data is hard to verify


class LinkedInEnricher:
    """Enrich a Founder record using a LinkedIn profile URL."""

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; VCBrain/1.0; +https://vcbrain.io/bot)"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async def enrich(self, founder: Founder, linkedin_url: str) -> Founder:
        """Attempt to enrich founder with LinkedIn data, return updated founder."""
        founder.linkedin_url = linkedin_url

        profile = await self._fetch_profile(linkedin_url)

        # Merge non-empty fields into founder record
        if profile.name and not founder.name or founder.name == "Unknown":
            founder.name = profile.name
        if profile.location and not founder.location:
            founder.location = profile.location
        if profile.summary and not founder.bio:
            founder.bio = profile.summary
        elif profile.headline and not founder.bio:
            founder.bio = profile.headline
        if profile.skills:
            existing = set(founder.skills)
            founder.skills = list(existing | set(profile.skills))
        if profile.education:
            founder.education.extend(profile.education)
        if profile.work_history:
            founder.work_history.extend(profile.work_history)

        founder.data_points.append(
            DataPoint(
                source=SourceType.LINKEDIN,
                source_url=linkedin_url,
                confidence=profile.confidence,
                content={
                    "headline": profile.headline,
                    "current_company": profile.current_company,
                    "current_title": profile.current_title,
                    "location": profile.location,
                    "skills": profile.skills,
                },
            )
        )
        return founder

    async def _fetch_profile(self, url: str) -> LinkedInProfile:
        """Fetch and parse a LinkedIn public profile page."""
        try:
            async with httpx.AsyncClient(
                headers=self._HEADERS, timeout=15, follow_redirects=True
            ) as client:
                resp = await client.get(url)

            if resp.status_code in (401, 403, 429, 999):
                # LinkedIn blocked the request — use URL-based extraction only
                return self._extract_from_url(url)

            if resp.status_code != 200:
                return LinkedInProfile()

            return await self._parse_html(resp.text, url)

        except Exception:
            return self._extract_from_url(url)

    async def _parse_html(self, html: str, url: str) -> LinkedInProfile:
        """Use LLM to parse profile fields from page HTML."""
        # Strip most tags, keep text content (~4k chars for LLM)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s{2,}", " ", text).strip()[:4000]

        if len(text) < 100:
            # Page likely blocked or redirected to login
            return self._extract_from_url(url)

        prompt = f"""Extract the LinkedIn profile fields from this page text.

Page text:
{text}

Return JSON with these fields (omit or leave empty if not found):
{{
  "name": "full name",
  "headline": "professional headline",
  "location": "city, country",
  "summary": "about section text (max 200 chars)",
  "current_company": "current employer name",
  "current_title": "current job title",
  "skills": ["skill1", "skill2"],
  "education": [{{"school": "...", "degree": "...", "field": "..."}}],
  "work_history": [{{"company": "...", "title": "...", "duration": "..."}}]
}}"""

        try:
            data = await complete_json(prompt, system=SYSTEM)
            profile = LinkedInProfile(**data)
            if profile.name or profile.headline:
                profile.confidence = 0.55
            return profile
        except Exception:
            return self._extract_from_url(url)

    def _extract_from_url(self, url: str) -> LinkedInProfile:
        """Extract what we can from the URL slug alone (zero-scrape fallback)."""
        # linkedin.com/in/firstname-lastname-abc123
        m = re.search(r"/in/([^/?#]+)", url)
        if not m:
            return LinkedInProfile()

        slug = m.group(1)
        # Remove trailing ID hashes (e.g. "john-doe-a1b2c3" → "john doe")
        clean = re.sub(r"-[a-z0-9]{6,}$", "", slug)
        name_parts = clean.replace("-", " ").title()

        return LinkedInProfile(name=name_parts, confidence=0.2)
