"""Investment memo generator with per-claim Trust Scores.

Required sections: Company snapshot, Investment hypotheses, SWOT, Problem & product, Traction & KPIs.
Missing data is flagged explicitly, never fabricated.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from prompts import load_system
from vc_brain.intelligence.diligence import DiligenceReport
from vc_brain.intelligence.screener import ScreeningResult
from vc_brain.llm import complete
from vc_brain.memory.models import Application, Company, Founder


class InvestmentMemo(BaseModel):
    company_name: str
    company_snapshot: str = ""
    investment_hypotheses: list[str] = Field(default_factory=list)
    swot: dict[str, list[str]] = Field(default_factory=lambda: {
        "strengths": [], "weaknesses": [], "opportunities": [], "threats": []
    })
    problem_and_product: str = ""
    traction_and_kpis: str = ""
    team_summary: str = ""
    market_sizing: str = ""
    recommendation: str = ""  # invest | pass | more_info_needed
    confidence: float = 0.0
    data_gaps: list[str] = Field(default_factory=list)
    trust_scores: dict[str, float] = Field(default_factory=dict)


class MemoGenerator:
    """Generate an investment memo from screening and diligence results."""

    SYSTEM = load_system("memo")

    async def generate(
        self,
        application: Application,
        company: Company,
        founders: list[Founder],
        screening: ScreeningResult,
        diligence: DiligenceReport,
    ) -> InvestmentMemo:
        """Generate a full investment memo."""

        context = self._build_context(application, company, founders, screening, diligence)

        prompt = (
            f"Write an investment memo for this opportunity.\n\n"
            f"{context}\n\n"
            f"Include these required sections:\n"
            f"1. COMPANY SNAPSHOT (one paragraph)\n"
            f"2. INVESTMENT HYPOTHESES (bullet points)\n"
            f"3. SWOT (strengths, weaknesses, opportunities, threats)\n"
            f"4. PROBLEM & PRODUCT\n"
            f"5. TRACTION & KPIs\n"
            f"6. TEAM SUMMARY\n"
            f"7. RECOMMENDATION (invest / pass / more_info_needed) with confidence 0-1\n"
            f"8. DATA GAPS (explicitly list what's missing or unverifiable)\n\n"
            f"Be concise. Flag gaps, don't fill them with guesses."
        )

        raw = await complete(prompt, system=self.SYSTEM)
        memo = self._parse_memo(raw, company, screening, diligence)
        return memo

    def _build_context(
        self,
        app: Application,
        company: Company,
        founders: list[Founder],
        screening: ScreeningResult,
        diligence: DiligenceReport,
    ) -> str:
        sections = [
            f"Company: {company.name}",
            f"Sector: {company.sector or 'Not specified'}",
            f"Stage: {company.stage or 'Not specified'}",
            f"Geography: {company.geography or 'Not specified'}",
            f"Description: {company.description or 'Not provided'}",
            "",
            "--- SCREENING RESULTS ---",
            f"Founder Axis: {screening.founder_axis.score}/100 ({screening.founder_axis.sentiment})",
            f"  Evidence: {'; '.join(screening.founder_axis.evidence)}",
            f"Market Axis: {screening.market_axis.score}/100 ({screening.market_axis.sentiment})",
            f"  Evidence: {'; '.join(screening.market_axis.evidence)}",
            f"Idea vs Market: {screening.idea_vs_market_axis.score}/100 ({screening.idea_vs_market_axis.sentiment})",
            f"  Evidence: {'; '.join(screening.idea_vs_market_axis.evidence)}",
            "",
            "--- DILIGENCE ---",
            f"Overall Trust: {diligence.overall_trust}",
            f"Red Flags: {diligence.red_flags or 'None'}",
            f"Open Questions: {diligence.open_questions or 'None'}",
            "",
            "--- FOUNDERS ---",
        ]

        for f in founders:
            sections.append(
                f"  {f.name} | Score: {f.score.overall} | "
                f"Skills: {', '.join(f.skills[:5])} | Location: {f.location}"
            )

        if app.deck_text:
            sections.append(f"\n--- DECK EXCERPT ---\n{app.deck_text[:2000]}")

        return "\n".join(sections)

    def _parse_memo(
        self,
        raw: str,
        company: Company,
        screening: ScreeningResult,
        diligence: DiligenceReport,
    ) -> InvestmentMemo:
        """Parse the LLM output into structured memo. Falls back gracefully."""
        memo = InvestmentMemo(company_name=company.name)
        memo.company_snapshot = self._extract_section(raw, "COMPANY SNAPSHOT")
        memo.problem_and_product = self._extract_section(raw, "PROBLEM & PRODUCT")
        memo.traction_and_kpis = self._extract_section(raw, "TRACTION & KPI")
        memo.team_summary = self._extract_section(raw, "TEAM SUMMARY")
        memo.market_sizing = self._extract_section(raw, "MARKET SIZ")

        # SWOT
        swot_text = self._extract_section(raw, "SWOT")
        if swot_text:
            memo.swot = self._parse_swot(swot_text)

        # Hypotheses
        hyp_text = self._extract_section(raw, "INVESTMENT HYPOTHES")
        if hyp_text:
            memo.investment_hypotheses = [
                line.strip().lstrip("-•* ") for line in hyp_text.split("\n") if line.strip()
            ]

        # Recommendation
        rec_text = self._extract_section(raw, "RECOMMENDATION")
        if "invest" in rec_text.lower() and "pass" not in rec_text.lower():
            memo.recommendation = "invest"
        elif "pass" in rec_text.lower():
            memo.recommendation = "pass"
        else:
            memo.recommendation = "more_info_needed"

        # Data gaps
        gaps_text = self._extract_section(raw, "DATA GAP")
        if gaps_text:
            memo.data_gaps = [
                line.strip().lstrip("-•* ") for line in gaps_text.split("\n") if line.strip()
            ]

        # Trust scores from diligence
        memo.trust_scores = {
            c.claim[:60]: c.trust_score for c in diligence.claims
        }
        memo.confidence = diligence.overall_trust

        return memo

    def _extract_section(self, text: str, header: str) -> str:
        lines = text.split("\n")
        capturing = False
        result = []
        for line in lines:
            if header.lower() in line.lower():
                capturing = True
                continue
            if capturing:
                # Stop at next section header (lines starting with number or all-caps)
                stripped = line.strip()
                if stripped and (
                    (stripped[0].isdigit() and "." in stripped[:4])
                    or (stripped.isupper() and len(stripped) > 3)
                    or stripped.startswith("---")
                ):
                    break
                result.append(line)
        return "\n".join(result).strip()

    def _parse_swot(self, text: str) -> dict[str, list[str]]:
        swot: dict[str, list[str]] = {
            "strengths": [], "weaknesses": [], "opportunities": [], "threats": []
        }
        current = ""
        for line in text.split("\n"):
            lower = line.lower().strip()
            if "strength" in lower:
                current = "strengths"
            elif "weakness" in lower or "weaknesse" in lower:
                current = "weaknesses"
            elif "opportunit" in lower:
                current = "opportunities"
            elif "threat" in lower or "risk" in lower:
                current = "threats"
            elif current and line.strip():
                swot[current].append(line.strip().lstrip("-•* "))
        return swot
