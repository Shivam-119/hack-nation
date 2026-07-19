from __future__ import annotations

from .schemas import ThesisFitResult
from .thesis_config import ThesisConfig

_WILDCARD_GEOGRAPHIES = {"global", "remote", "worldwide", "any"}


def check_thesis_fit(thesis: ThesisConfig, deck_extraction: dict) -> ThesisFitResult:
    """Stage 1: deterministic hard-constraint filter. No LLM call.

    Checks whether the deck's stated sector and geography overlap the thesis's. Stage/check-size
    are not reliably derivable from a deck alone, so they are left as soft factors for the
    decision-draft stage rather than a hard filter here.
    """
    reasons: list[str] = []
    passed = True

    sector_fields = [deck_extraction.get("primary_industry") or ""]
    sector_fields += deck_extraction.get("sub_verticals") or []
    if _any_overlap(thesis.sectors, sector_fields):
        reasons.append(f"Sector match: deck fields {sector_fields} overlap thesis sectors {thesis.sectors}.")
    else:
        reasons.append(
            f"No sector overlap: deck industry/sub-verticals {sector_fields} do not match thesis sectors {thesis.sectors}."
        )
        passed = False

    geo_fields = deck_extraction.get("geography_focus") or []
    if not geo_fields:
        # Most decks have no geography slide, so extraction returns nothing.
        # Absence of a stated geography is not evidence of a mismatch — don't
        # reject on missing information.
        reasons.append("Geography not stated in the deck — not treated as disqualifying.")
    elif _any_overlap(thesis.geography, geo_fields) or _has_wildcard_geo(thesis.geography):
        reasons.append(f"Geography match: deck geography {geo_fields} overlaps thesis geography {thesis.geography}.")
    else:
        reasons.append(
            f"No geography overlap: deck geography {geo_fields} does not match thesis geography {thesis.geography}."
        )
        passed = False

    return ThesisFitResult(passed=passed, reasons=reasons)


def _any_overlap(thesis_terms: list[str], deck_terms: list[str]) -> bool:
    if not deck_terms:
        return False
    normalized_thesis = [t.lower() for t in thesis_terms]
    for deck_term in deck_terms:
        deck_lower = (deck_term or "").lower()
        if not deck_lower:
            continue
        for thesis_term in normalized_thesis:
            if thesis_term in deck_lower or deck_lower in thesis_term:
                return True
    return False


def _has_wildcard_geo(thesis_geo: list[str]) -> bool:
    return any(g.lower() in _WILDCARD_GEOGRAPHIES for g in thesis_geo)
