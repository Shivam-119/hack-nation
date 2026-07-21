from __future__ import annotations

from .schemas import AdversarialOutput, DecisionDraft, FinalDecision, ThesisFitResult


def finalize_decision(
    application_id: str,
    founder_axis: dict,
    market_axis: dict,
    idea_vs_market_axis: dict,
    thesis_fit: ThesisFitResult,
    draft: DecisionDraft,
    adversarial: AdversarialOutput,
) -> FinalDecision:
    """Stage 6: deterministic merge. No LLM call.

    If the adversarial agent's counter-argument is "serious", it escalates the recommendation to
    "more_diligence_needed" regardless of what the draft said. Otherwise the draft's recommendation
    stands, with the counter-argument always attached as a visible part of the final record.
    """
    recommendation = draft.recommendation
    if adversarial.counter_argument_severity == "serious":
        recommendation = "more_diligence_needed"

    return FinalDecision(
        application_id=application_id,
        founder_axis=founder_axis,
        market_axis=market_axis,
        idea_vs_market_axis=idea_vs_market_axis,
        thesis_fit=thesis_fit.model_dump(),
        recommendation=recommendation,
        check_size_recommended_usd=draft.check_size_recommended_usd,
        rationale=draft.rationale,
        adversarial_view=adversarial.counter_argument,
        gaps_and_caveats=draft.gaps_and_caveats,
    )
