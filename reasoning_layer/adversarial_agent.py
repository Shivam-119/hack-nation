from __future__ import annotations

import json
from pathlib import Path

from .llm_client import call_structured_json
from .schemas import AdversarialOutput

THIS_DIR = Path(__file__).parent
MODEL = "gpt-4.1"
_PROMPT_PATH = THIS_DIR / "prompts" / "adversarial_system_prompt.txt"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def generate_adversarial_view(
    draft: dict, founder_axis: dict, market_axis: dict, idea_vs_market_axis: dict, api_key: str
) -> AdversarialOutput:
    schema_json = json.dumps(AdversarialOutput.model_json_schema(), indent=2)
    user_prompt = (
        "Here is the JSON schema your response must match exactly:\n"
        f"{schema_json}\n\n"
        "Here is the draft recommendation you must argue against:\n"
        f"{json.dumps(draft, indent=2)}\n\n"
        "Here are the three axis outputs it was based on — use only evidence already present here:\n\n"
        f"Founder axis:\n{json.dumps(founder_axis, indent=2)}\n\n"
        f"Market axis:\n{json.dumps(market_axis, indent=2)}\n\n"
        f"Idea-vs-Market axis:\n{json.dumps(idea_vs_market_axis, indent=2)}"
    )
    return call_structured_json(
        system=_load_system_prompt(),
        user=user_prompt,
        response_model=AdversarialOutput,
        api_key=api_key,
        model=MODEL,
    )
