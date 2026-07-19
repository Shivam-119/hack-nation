"""Thesis Engine: investor configures fund parameters; every recommendation is filtered through this lens."""

from __future__ import annotations

from pydantic import BaseModel


class FundThesis(BaseModel):
    name: str
    sectors: list[str]
    stages: list[str]
    geographies: list[str]
    check_size_min: int
    check_size_max: int
    target_ownership_pct: float
    risk_appetite: str = "moderate"  # conservative | moderate | aggressive
    min_founder_score: float = 30.0
    preferred_signals: list[str] = []
    anti_signals: list[str] = []


class ThesisEngine:
    def __init__(self, thesis: FundThesis):
        self.thesis = thesis

    def fits_thesis(self, sector: str, stage: str, geography: str) -> tuple[bool, list[str]]:
        reasons = []
        passes = True

        if sector and not any(s.lower() in sector.lower() for s in self.thesis.sectors):
            reasons.append(f"Sector '{sector}' outside thesis: {self.thesis.sectors}")
            passes = False

        if stage and stage.lower() not in [s.lower() for s in self.thesis.stages]:
            reasons.append(f"Stage '{stage}' outside thesis: {self.thesis.stages}")
            passes = False

        if geography and not any(g.lower() in geography.lower() for g in self.thesis.geographies):
            reasons.append(f"Geography '{geography}' outside thesis: {self.thesis.geographies}")
            passes = False

        if not reasons:
            reasons.append("Fits fund thesis on all configured dimensions.")

        return passes, reasons

    def score_alignment(self, sector: str, stage: str, geography: str) -> float:
        score = 0.0
        checks = 0

        if self.thesis.sectors:
            checks += 1
            if any(s.lower() in sector.lower() for s in self.thesis.sectors):
                score += 1

        if self.thesis.stages:
            checks += 1
            if stage.lower() in [s.lower() for s in self.thesis.stages]:
                score += 1

        if self.thesis.geographies:
            checks += 1
            if any(g.lower() in geography.lower() for g in self.thesis.geographies):
                score += 1

        return score / max(checks, 1)
