"""Hardcoded roster of notable people/orgs on socials.

Matching a founder's discovered connections against this roster is the
deterministic (non-LLM) "connected to great people" signal. Handles are stored
normalized (lowercased, no leading '@'). This is intentionally a curated
starter set — extend it freely; the graph scorer picks up new entries with no
other changes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotableEntry:
    name: str
    category: str  # notable_founder | top_vc | accelerator | frontier_lab | top_operator
    weight: float


# handle (lowercase, no @) -> entry. Handles are Twitter/X unless noted.
NOTABLE: dict[str, NotableEntry] = {
    # --- Accelerators / their partners -----------------------------------
    "paulg": NotableEntry("Paul Graham", "accelerator", 10.0),
    "ycombinator": NotableEntry("Y Combinator", "accelerator", 9.0),
    "garrytan": NotableEntry("Garry Tan", "accelerator", 9.0),
    "jaltma": NotableEntry("Jessica Livingston", "accelerator", 8.0),
    "techstars": NotableEntry("Techstars", "accelerator", 7.0),
    # --- Investors / VCs -------------------------------------------------
    "naval": NotableEntry("Naval Ravikant", "top_vc", 9.0),
    "pmarca": NotableEntry("Marc Andreessen", "top_vc", 10.0),
    "bhorowitz": NotableEntry("Ben Horowitz", "top_vc", 9.0),
    "a16z": NotableEntry("Andreessen Horowitz", "top_vc", 9.0),
    "sequoia": NotableEntry("Sequoia Capital", "top_vc", 9.0),
    "foundersfund": NotableEntry("Founders Fund", "top_vc", 9.0),
    "eladgil": NotableEntry("Elad Gil", "top_vc", 8.0),
    "balajis": NotableEntry("Balaji Srinivasan", "top_vc", 8.0),
    "jason": NotableEntry("Jason Calacanis", "top_vc", 7.0),
    "davidsacks": NotableEntry("David Sacks", "top_vc", 8.0),
    "reidhoffman": NotableEntry("Reid Hoffman", "top_vc", 9.0),
    "hnshah": NotableEntry("Hiten Shah", "top_vc", 6.0),
    "semil": NotableEntry("Semil Shah", "top_vc", 6.0),
    "vcstar": NotableEntry("Bill Gurley", "top_vc", 8.0),
    "chamath": NotableEntry("Chamath Palihapitiya", "top_vc", 7.0),
    # --- Notable founders ------------------------------------------------
    "sama": NotableEntry("Sam Altman", "notable_founder", 10.0),
    "elonmusk": NotableEntry("Elon Musk", "notable_founder", 10.0),
    "patrickc": NotableEntry("Patrick Collison", "notable_founder", 10.0),
    "collision": NotableEntry("John Collison", "notable_founder", 9.0),
    "jack": NotableEntry("Jack Dorsey", "notable_founder", 8.0),
    "brian_armstrong": NotableEntry("Brian Armstrong", "notable_founder", 8.0),
    "levelsio": NotableEntry("Pieter Levels", "notable_founder", 7.0),
    "dhh": NotableEntry("David Heinemeier Hansson", "notable_founder", 7.0),
    "gdb": NotableEntry("Greg Brockman", "notable_founder", 8.0),
    "tobi": NotableEntry("Tobi Lütke", "notable_founder", 8.0),
    "aaronlevie": NotableEntry("Aaron Levie", "notable_founder", 7.0),
    "danielgross": NotableEntry("Daniel Gross", "notable_founder", 7.0),
    # --- Frontier labs / high-signal orgs & operators --------------------
    "openai": NotableEntry("OpenAI", "frontier_lab", 8.0),
    "anthropicai": NotableEntry("Anthropic", "frontier_lab", 8.0),
    "googledeepmind": NotableEntry("Google DeepMind", "frontier_lab", 8.0),
    "stripe": NotableEntry("Stripe", "frontier_lab", 7.0),
    "karpathy": NotableEntry("Andrej Karpathy", "top_operator", 8.0),
    "ilyasut": NotableEntry("Ilya Sutskever", "top_operator", 8.0),
    "satyanadella": NotableEntry("Satya Nadella", "top_operator", 8.0),
    "sundarpichai": NotableEntry("Sundar Pichai", "top_operator", 8.0),
    "jeffdean": NotableEntry("Jeff Dean", "top_operator", 7.0),
}

# Fallback weight per category when comparing/aggregating.
CATEGORY_WEIGHTS: dict[str, float] = {
    "notable_founder": 10.0,
    "top_vc": 9.0,
    "accelerator": 9.0,
    "frontier_lab": 8.0,
    "top_operator": 6.0,
}


def normalize_handle(handle: str) -> str:
    """Lowercase, strip surrounding whitespace and a leading '@'."""
    return handle.strip().lstrip("@").lower()


def lookup_notable(handle: str) -> NotableEntry | None:
    """Return the NotableEntry for a handle, or None if not on the roster."""
    return NOTABLE.get(normalize_handle(handle))
