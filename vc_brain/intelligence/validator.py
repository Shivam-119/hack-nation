"""Validator agent — cross-references startup claims against external data signals.

Observe → Think → Act pattern:
- Observe: collect claims + external signals (GitHub, founder data points, web presence)
- Think: LLM cross-references each claim against the evidence
- Act: return revised trust scores and any contradictions found
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from prompts import load_system
from vc_brain.agents.base import BaseAgent
from vc_brain.intelligence.diligence import ClaimVerification, DiligenceReport
from vc_brain.llm import complete_json
from vc_brain.memory.models import Company, Founder


class ValidationResult(BaseModel):
    claim: str
    original_trust: float
    revised_trust: float
    supporting_evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    verdict: str = "unverified"  # supported | contradicted | unverified | plausible


class ValidatorReport(BaseModel):
    company_id: str
    validations: list[ValidationResult] = Field(default_factory=list)
    overall_trust: float = 0.5
    red_flags: list[str] = Field(default_factory=list)
    unverified_claims: list[str] = Field(default_factory=list)
    contradicted_claims: list[str] = Field(default_factory=list)


class ValidatorAgent(BaseAgent):
    """Cross-references claims from a DiligenceReport against available external signals."""

    name = "validator_agent"
    SYSTEM = load_system("validator")

    def __init__(self, company: Company, founders: list[Founder]):
        self.company = company
        self.founders = founders

    async def observe(self, context: dict[str, Any]) -> dict[str, Any]:
        """Gather all available external signals to cross-reference against claims."""
        report: DiligenceReport = context["report"]

        # Collect external signals from founder data points
        github_signals: list[str] = []
        founder_signals: list[str] = []
        for founder in self.founders:
            for dp in founder.data_points:
                content = dp.content
                # GitHub signals: contributor count, repo count, stars
                if str(dp.source) in ("github", "SourceType.GITHUB"):
                    if "score" in content:
                        github_signals.append(f"GitHub builder score: {content['score']}/100")
                    if "signals" in content:
                        github_signals.extend(content["signals"][:5])
                    if "red_flags" in content:
                        github_signals.extend([f"[RED FLAG] {f}" for f in content["red_flags"]])
                else:
                    if content:
                        founder_signals.append(str(content)[:200])

        return {
            "claims": [c.model_dump() for c in report.claims],
            "company": {
                "name": self.company.name,
                "sector": self.company.sector,
                "stage": self.company.stage,
                "description": self.company.description,
            },
            "founders": [
                {"name": f.name, "bio": f.bio, "skills": f.skills[:10]}
                for f in self.founders
            ],
            "github_signals": github_signals,
            "founder_signals": founder_signals,
        }

    async def think(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Cross-reference claims against observed evidence using LLM."""
        claims = observation["claims"]
        if not claims:
            return {"validations": [], "confidence": 0.5}

        prompt = (
            f"Cross-reference these startup claims against the available evidence.\n\n"
            f"Company: {observation['company']['name']} "
            f"({observation['company']['sector']}, {observation['company']['stage']})\n"
            f"Description: {observation['company']['description']}\n\n"
            f"Founders: {observation['founders']}\n\n"
            f"GitHub signals: {observation['github_signals'] or 'None available'}\n"
            f"Other signals: {observation['founder_signals'][:5] or 'None available'}\n\n"
            f"Claims to validate:\n"
        )
        for i, c in enumerate(claims[:10], 1):
            prompt += f"{i}. \"{c['claim']}\" (source: {c.get('source', 'unknown')})\n"

        prompt += (
            "\nFor each claim return a validation entry. "
            "Return JSON:\n"
            '{"validations": [{'
            '"claim": "...", '
            '"revised_trust": 0.0-1.0, '
            '"supporting_evidence": ["..."], '
            '"contradictions": ["..."], '
            '"verdict": "supported|contradicted|unverified|plausible"'
            "}]}"
        )

        try:
            result = await complete_json(prompt, system=self.SYSTEM)
            return {"validations": result.get("validations", []), "confidence": 0.7}
        except Exception:
            # Deterministic fallback — preserve original trust scores
            return {
                "validations": [
                    {
                        "claim": c["claim"],
                        "revised_trust": c.get("trust_score", 0.3),
                        "supporting_evidence": [],
                        "contradictions": [],
                        "verdict": "unverified",
                    }
                    for c in claims
                ],
                "confidence": 0.2,
            }

    async def act(self, reasoning: dict[str, Any]) -> dict[str, Any]:
        """Build the ValidatorReport from the LLM's cross-referencing."""
        original_claims = {c.claim: c for c in self._report.claims}
        validations: list[ValidationResult] = []

        for v in reasoning.get("validations", []):
            claim_text = v.get("claim", "")
            original = original_claims.get(claim_text)
            original_trust = original.trust_score if original else 0.5

            result = ValidationResult(
                claim=claim_text,
                original_trust=original_trust,
                revised_trust=float(v.get("revised_trust", original_trust)),
                supporting_evidence=v.get("supporting_evidence", []),
                contradictions=v.get("contradictions", []),
                verdict=v.get("verdict", "unverified"),
            )
            validations.append(result)

        red_flags = [v.claim for v in validations if v.verdict == "contradicted"]
        unverified = [v.claim for v in validations if v.verdict == "unverified"]
        trust_scores = [v.revised_trust for v in validations]
        overall = sum(trust_scores) / max(len(trust_scores), 1)

        report = ValidatorReport(
            company_id=self.company.id,
            validations=validations,
            overall_trust=round(overall, 2),
            red_flags=red_flags,
            unverified_claims=unverified,
            contradicted_claims=red_flags,
        )
        return report.model_dump()

    async def validate(self, report: DiligenceReport) -> ValidatorReport:
        """Entry point: validate claims in a DiligenceReport. Returns a ValidatorReport."""
        self._report = report
        trace = await self.run({"report": report})
        if trace.success:
            return ValidatorReport(**trace.final_output)
        # Fallback: return unverified report
        return ValidatorReport(
            company_id=self.company.id,
            validations=[
                ValidationResult(
                    claim=c.claim,
                    original_trust=c.trust_score,
                    revised_trust=c.trust_score,
                    verdict="unverified",
                )
                for c in report.claims
            ],
            overall_trust=report.overall_trust,
        )
