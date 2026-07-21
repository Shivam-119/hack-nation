from __future__ import annotations

import json
from pathlib import Path

from .llm_client import call_structured_json
from .schemas import DecisionDraft
from .thesis_config import ThesisConfig

THIS_DIR = Path(__file__).parent
MODEL = "gpt-5"
_PROMPT_PATH = THIS_DIR / "prompts" / "decision_draft_system_prompt.txt"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def draft_decision(
    founder_axis: dict, market_axis: dict, idea_vs_market_axis: dict, thesis: ThesisConfig, api_key: str
) -> DecisionDraft:
    schema_json = json.dumps(DecisionDraft.model_json_schema(), indent=2)
    user_prompt = (
        "Here is the JSON schema your response must match exactly:\n"
        f"{schema_json}\n\n"
        "Here are the three fixed, independent axis ratings. Do not re-rate them:\n\n"
        f"Founder axis:\n{json.dumps(founder_axis, indent=2)}\n\n"
        f"Market axis:\n{json.dumps(market_axis, indent=2)}\n\n"
        f"Idea-vs-Market axis:\n{json.dumps(idea_vs_market_axis, indent=2)}\n\n"
        "Here is the investor's thesis config:\n"
        f"{thesis.model_dump_json(indent=2)}"
    )
    return call_structured_json(
        system=_load_system_prompt(),
        user=user_prompt,
        response_model=DecisionDraft,
        api_key=api_key,
        model=MODEL,
    )
