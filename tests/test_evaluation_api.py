from vc_brain.api.app import _evaluation_payload
from vc_brain.intelligence.thesis_engine import FundThesis, ThesisEngine


def test_reasoning_layer_evaluation_is_adapted_for_the_inbox() -> None:
    payload = _evaluation_payload(
        {
            "founder_axis": {
                "fit_score_pct": 81,
                "rating": "bullish",
                "trend": "improving",
                "confidence_pct": 88,
                "rationale": "Strong execution history",
                "key_evidence": [{"point": "Shipped a public product", "source": "GitHub"}],
            },
            "market_axis": {"fit_score_pct": 62, "rating": "neutral", "trend": "stable", "confidence_pct": 70},
            "idea_vs_market_axis": {"fit_score_pct": 69, "rating": "bullish", "trend": "stable", "confidence_pct": 65, "verdict": "idea_survives_as_is"},
            "thesis_fit": {"passed": True, "reasons": ["Sector match"]},
            "recommendation": "more_diligence_needed",
            "rationale": "Promising, with open questions.",
            "adversarial_view": "Distribution may be hard.",
            "gaps_and_caveats": ["No paid pilots yet"],
        }
    )

    assert payload is not None
    assert payload["founder_axis"]["score"] == 81
    assert payload["founder_axis"]["strengths"] == [
        {"text": "Shipped a public product", "source": "GitHub", "url": ""}
    ]
    assert payload["founder_axis"]["swot"]["strengths"][0]["src"]["label"] == "GitHub"
    assert payload["recommendation"] == "more_diligence_needed"


def test_short_thesis_tags_do_not_match_inside_words() -> None:
    engine = ThesisEngine(
        FundThesis(name="Fund", sectors=["AI"], stages=[], geographies=[], check_size_min=0, check_size_max=0, target_ownership_pct=0, risk_appetite="moderate")
    )
    assert engine.fits_thesis("AI infrastructure", "", "")[0]
    assert not engine.fits_thesis("ice cream retail", "", "")[0]
