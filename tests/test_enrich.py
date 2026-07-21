"""Tests for the deck -> founder/company enrichment orchestrator.

Fully offline: the deck parser and all three scanners are monkeypatched, so
what is tested is the orchestration itself -- that each input reaches the right
module, that results are collected, and that every failure degrades softly and
is reported rather than raising.
"""

import asyncio
import dataclasses

from vc_brain.sourcing import enrich as E
from vc_brain.sourcing.enrich import FounderInput, enrich_from_deck


class _Report:
    """Stand-in for a scanner result with a model_dump."""

    def __init__(self, **kw):
        self._kw = kw

    def model_dump(self, mode="json"):
        return self._kw


@dataclasses.dataclass
class _BuilderEval:
    username: str
    score: float


def _stub_all(monkeypatch, *, deck=True, company_rep=True, github=True,
              socials=True, person_rep=True):
    """Patch the deck step and every scanner with controllable stubs."""

    async def fake_deck(deck_path):
        if not deck:
            return None, 0, ["deck failed"]
        return (
            type("X", (), {
                "company_name": "Vektor",
                "primary_industry": "AI Infrastructure",
                "one_line_description": "Vector DB in your VPC.",
            })(),
            1200,
            [],
        )

    monkeypatch.setattr(E, "_company_from_deck", fake_deck)

    async def fake_github(username):
        if not github:
            raise RuntimeError("github down")
        return _BuilderEval(username=username, score=72.0)

    monkeypatch.setattr(E, "evaluate_github", fake_github)

    class FakeSocials:
        def __init__(self, pipeline):
            pass

        async def analyze(self, handles, name=""):
            if not socials:
                raise RuntimeError("apify down")
            return _Report(name=name, handles=handles, posts=["p1", "p2"])

    monkeypatch.setattr(E, "SocialsScanner", FakeSocials)

    class FakeReputation:
        def __init__(self, pipeline=None, provider=None):
            pass

        async def analyze(self, name, hint="", entity=None):
            entity_val = getattr(entity, "value", str(entity))
            if entity_val == "company" and not company_rep:
                raise RuntimeError("tavily down")
            if entity_val == "person" and not person_rep:
                raise RuntimeError("tavily down")
            return _Report(name=name, entity=entity_val, findings=[f"{name} finding"])

    monkeypatch.setattr(E, "ReputationScanner", FakeReputation)


# -- happy path -------------------------------------------------------------

def test_deck_and_founder_reach_the_right_modules(monkeypatch):
    _stub_all(monkeypatch)

    result = asyncio.run(enrich_from_deck(
        "deck.pdf",
        [FounderInput(name="Ada Whitfield", github="adaw", twitter="adabuilds",
                      linkedin="in/adaw")],
    ))

    # Deck produced the company, and company article research ran on it.
    assert result.company_name == "Vektor"
    assert result.industry == "AI Infrastructure"
    assert result.deck_chars == 1200
    assert result.company_reputation["entity"] == "company"

    f = result.founders[0]
    assert f.name == "Ada Whitfield"
    assert f.github["score"] == 72.0                 # github got the username
    assert f.handles == {"twitter": "adabuilds", "linkedin": "in/adaw"}
    assert f.socials["posts"] == ["p1", "p2"]        # socials got the handles
    assert f.reputation["entity"] == "person"        # reputation got the name
    assert f.errors == []


def test_company_name_override_skips_the_deck(monkeypatch):
    _stub_all(monkeypatch)

    async def boom(deck_path):
        raise AssertionError("deck must not be read when company_name is given")

    monkeypatch.setattr(E, "_company_from_deck", boom)

    result = asyncio.run(enrich_from_deck("", [], company_name="Kontoform"))
    assert result.company_name == "Kontoform"
    assert result.company_reputation["name"] == "Kontoform"


# -- fail-soft --------------------------------------------------------------

def test_a_dead_scanner_degrades_rather_than_aborts(monkeypatch):
    _stub_all(monkeypatch, github=False, socials=False)

    result = asyncio.run(enrich_from_deck(
        "deck.pdf",
        [FounderInput(name="Ada", github="adaw", twitter="adabuilds")],
    ))

    f = result.founders[0]
    # The two that failed are reported; the one that worked still landed.
    assert f.github is None and any("github" in e for e in f.errors)
    assert f.socials is None and any("socials" in e for e in f.errors)
    assert f.reputation is not None
    # The run as a whole still produced a company + a founder record.
    assert result.company_name == "Vektor"
    assert len(result.founders) == 1


def test_deck_failure_is_reported_and_company_research_skipped(monkeypatch):
    _stub_all(monkeypatch, deck=False)

    result = asyncio.run(enrich_from_deck("bad.pdf", []))
    assert result.company_name == ""
    assert any("deck failed" in e for e in result.errors)
    assert any("company article research skipped" in e for e in result.errors)
    assert result.company_reputation is None


def test_missing_handles_are_flagged_not_crashed(monkeypatch):
    _stub_all(monkeypatch)

    result = asyncio.run(enrich_from_deck(
        "deck.pdf",
        [FounderInput(name="Solo Founder")],  # name only, no handles
    ))

    f = result.founders[0]
    assert f.github is None and any("No GitHub handle" in e for e in f.errors)
    assert f.socials is None and any("No social handles" in e for e in f.errors)
    # Name-based article research still runs — that only needs the name.
    assert f.reputation is not None


def test_person_reputation_can_be_disabled(monkeypatch):
    _stub_all(monkeypatch)

    result = asyncio.run(enrich_from_deck(
        "deck.pdf",
        [FounderInput(name="Ada", github="adaw")],
        person_reputation=False,
    ))
    assert result.founders[0].reputation is None
    # Company-level research is unaffected by the per-founder switch.
    assert result.company_reputation is not None


def test_handles_helper_drops_empty_fields():
    assert FounderInput(name="A", twitter="t").handles() == {"twitter": "t"}
    assert FounderInput(name="A").handles() == {}


# -- Founder profile bucketing ----------------------------------------------

def _finding(category: str, summary: str = "x") -> dict:
    return {"summary": summary, "category": category, "polarity": "neutral",
            "relevance": 8, "sources": [{"source": "s.com", "url": "https://s.com/a"}]}


def test_founder_profile_buckets_findings_by_category():
    """The investor wants track record up front and adverse findings called
    out, not one undifferentiated list."""
    rep = {"findings": [
        _finding("education", "PhD at Princeton"),
        _finding("prior_company", "Founded Acme"),
        _finding("current_role", "CTO at Front"),
        _finding("award", "IMO gold medal"),
        _finding("recognition", "30 under 30"),
        _finding("research", "Published a paper"),
        _finding("fraud", "Accused of fraud"),
        _finding("legal", "Sued by investors"),
        _finding("press", "Profiled by TechCrunch"),
    ]}
    profile = E.founder_profile(rep)

    assert [f["summary"] for f in profile["background"]] == [
        "PhD at Princeton", "Founded Acme", "CTO at Front"]
    assert [f["summary"] for f in profile["achievements"]] == [
        "IMO gold medal", "30 under 30", "Published a paper"]
    assert [f["summary"] for f in profile["adverse"]] == [
        "Accused of fraud", "Sued by investors"]
    assert [f["summary"] for f in profile["press"]] == ["Profiled by TechCrunch"]


def test_founder_profile_never_drops_an_unmapped_category():
    """A category added later must surface somewhere rather than vanish."""
    profile = E.founder_profile({"findings": [
        _finding("funding", "Raised $4M"),
        _finding("brand_new_category", "Something novel"),
    ]})
    assert [f["summary"] for f in profile["press"]] == ["Raised $4M", "Something novel"]
    total = sum(len(v) for v in profile.values())
    assert total == 2, "every finding must land in exactly one bucket"


def test_founder_profile_handles_missing_reputation():
    for empty in (None, {}, {"findings": []}):
        profile = E.founder_profile(empty)
        assert set(profile) == {"background", "achievements", "adverse", "press"}
        assert all(v == [] for v in profile.values())


def test_a_flooded_category_cannot_starve_education():
    """Regression: a real Front run returned 23 near-identical `current_role`
    findings and 5 `education` ones. Findings sort alphabetically by category,
    so truncating before bucketing dropped every education finding -- exactly
    the thing an investor wants most."""
    findings = [_finding("current_role", f"Is co-founder and CEO (retelling {i})") for i in range(23)]
    findings += [_finding("education", f"Studied at University {i}") for i in range(5)]
    findings += [_finding("prior_company", "Was staff engineer at Elastic")]
    findings.sort(key=lambda f: f["category"])  # how sort_findings orders them

    profile = E.founder_profile({"findings": findings}, limit=8)
    categories = {f["category"] for f in profile["background"]}

    assert "education" in categories, "education starved by current_role flood"
    assert "prior_company" in categories
    assert len(profile["background"]) == 8


def test_interleave_is_round_robin_and_respects_limit():
    findings = ([_finding("award", f"a{i}") for i in range(5)]
                + [_finding("research", f"r{i}") for i in range(2)])
    out = E._interleave(findings, 4)
    assert len(out) == 4
    # Both categories represented rather than 4x award.
    assert {f["category"] for f in out} == {"award", "research"}
    # Asking for more than exists returns everything, without looping forever.
    assert len(E._interleave(findings, 99)) == 7


def test_benign_social_chatter_is_not_flagged_as_adverse():
    """Regression: the extractor labels anything from Reddit/LinkedIn/X as
    `rumor` regardless of content, so a founder announcing her own funding
    round was red-boxed as an adverse finding. Only genuinely negative items
    belong there."""
    benign = dict(_finding("rumor", "Announced Front's Series C in a LinkedIn post"), polarity="neutral")
    damaging = dict(_finding("rumor", "Ex-employees allege a hostile culture"), polarity="negative")

    profile = E.founder_profile({"findings": [benign, damaging]})

    assert [f["summary"] for f in profile["adverse"]] == ["Ex-employees allege a hostile culture"]
    assert [f["summary"] for f in profile["press"]] == ["Announced Front's Series C in a LinkedIn post"]


def test_negative_polarity_reaches_adverse_whatever_the_category():
    odd = dict(_finding("press", "A hit piece questioning his credentials"), polarity="negative")
    profile = E.founder_profile({"findings": [odd]})
    assert profile["adverse"] and not profile["press"]
