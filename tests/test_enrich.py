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
