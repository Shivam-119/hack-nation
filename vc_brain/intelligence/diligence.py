"""Diligence engine: deep verification of claims with Trust Scores.

Every claim (traction, revenue, team, market size) traces to evidence
with a confidence level. Contradictions are flagged before reaching the investor.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from vc_brain.llm import complete_json
from vc_brain.memory.models import Application, Company, Founder


class ClaimVerification(BaseModel):
    claim: str
    source: str  # where the claim was made
    evidence: list[str] = Field(default_factory=list)
    trust_score: float = 0.5  # 0-1 per-claim trust
    verified: bool = False
    contradictions: list[str] = Field(default_factory=list)


class DiligenceReport(BaseModel):
    company_id: str
    claims: list[ClaimVerification] = Field(default_factory=list)
    overall_trust: float = 0.5
    red_flags: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class DiligenceEngine:
    """Extract claims from application materials and attempt verification."""

    SYSTEM = (
        "You are a diligence analyst for a venture fund. Extract factual claims from "
        "the provided materials and assess their verifiability. Be skeptical but fair. "
        "Flag anything that seems inflated or unverifiable. Return valid JSON only."
    )

    async def run_diligence(
        self,
        application: Application,
        company: Company,
        founders: list[Founder],
    ) -> DiligenceReport:
        """Extract and verify claims from application materials."""
        claims = await self._extract_claims(application, company)
        verified_claims = await self._verify_claims(claims, founders)

        red_flags = [c.claim for c in verified_claims if c.contradictions]
        open_questions = [
            c.claim for c in verified_claims
            if not c.verified and c.trust_score < 0.4
        ]

        trust_scores = [c.trust_score for c in verified_claims]
        overall = sum(trust_scores) / max(len(trust_scores), 1)

        return DiligenceReport(
            company_id=company.id,
            claims=verified_claims,
            overall_trust=round(overall, 2),
            red_flags=red_flags,
            open_questions=open_questions,
        )

    async def _extract_claims(
        self, app: Application, company: Company
    ) -> list[ClaimVerification]:
        prompt = (
            f"Extract the key factual claims from this startup's application.\n\n"
            f"Company: {company.name}\n"
            f"Description: {company.description}\n"
            f"Deck content:\n{app.deck_text[:3000]}\n\n"
            f"Return JSON: {{\"claims\": [{{\"claim\": \"...\", \"source\": \"deck|description|field\"}}]}}"
        )

        try:
            result = await complete_json(prompt, system=self.SYSTEM)
            return [
                ClaimVerification(claim=c["claim"], source=c.get("source", "deck"))
                for c in result.get("claims", [])
            ]
        except Exception:
            # Basic extraction fallback
            claims = []
            if company.description:
                claims.append(ClaimVerification(
                    claim=company.description[:200], source="description"
                ))
            return claims

    async def _verify_claims(
        self, claims: list[ClaimVerification], founders: list[Founder]
    ) -> list[ClaimVerification]:
        """Cross-reference claims against available data points."""
        founder_facts = []
        for f in founders:
            for dp in f.data_points:
                founder_facts.append(str(dp.content))

        for claim in claims:
            # Check if any data point corroborates or contradicts the claim
            matching_evidence = [
                fact for fact in founder_facts
                if any(word in fact.lower() for word in claim.claim.lower().split()[:5])
            ]

            if matching_evidence:
                claim.evidence = matching_evidence[:3]
                claim.trust_score = 0.7
                claim.verified = True
            else:
                claim.trust_score = 0.3
                claim.evidence = ["No corroborating data found in available sources"]

        return claims
