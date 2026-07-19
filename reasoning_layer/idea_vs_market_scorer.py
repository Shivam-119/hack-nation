from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .llm_client import LLMCallFailedError, call_structured_json
from .memory_client import MemoryReadError, MockMemoryClient
from .schemas import IdeaVsMarketScore

THIS_DIR = Path(__file__).parent
MODEL = "gpt-4.1"
_PROMPT_PATH = THIS_DIR / "prompts" / "idea_vs_market_system_prompt.txt"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def score_idea_vs_market(
    founder_axis: dict, market_axis: dict, deck_extraction: dict, api_key: str
) -> IdeaVsMarketScore:
    schema_json = json.dumps(IdeaVsMarketScore.model_json_schema(), indent=2)
    deck_summary = {
        "one_line_description": deck_extraction.get("one_line_description"),
        "target_market_segment": deck_extraction.get("target_market_segment"),
        "business_model": deck_extraction.get("business_model"),
    }
    user_prompt = (
        "Here is the JSON schema your response must match exactly:\n"
        f"{schema_json}\n\n"
        "Here is the Founder axis output:\n"
        f"{json.dumps(founder_axis, indent=2)}\n\n"
        "Here is the Market axis output:\n"
        f"{json.dumps(market_axis, indent=2)}\n\n"
        "Here is the deck's own description of the problem/product:\n"
        f"{json.dumps(deck_summary, indent=2)}"
    )
    return call_structured_json(
        system=_load_system_prompt(),
        user=user_prompt,
        response_model=IdeaVsMarketScore,
        api_key=api_key,
        model=MODEL,
    )


def _main() -> int:
    load_dotenv(THIS_DIR / ".env")
    load_dotenv(THIS_DIR.parent / ".env")

    parser = argparse.ArgumentParser(description="Score the Idea-vs-Market axis for a single application.")
    parser.add_argument("--application-id", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    memory = MockMemoryClient()
    try:
        deck_extraction = memory.get_deck_extraction(args.application_id)
        founder_research = memory.get_founder_research(args.application_id)
        market_research = memory.get_market_research(args.application_id)
    except MemoryReadError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    founder_score = memory.get_founder_score(founder_research.get("founder_id", ""))

    try:
        from .founder_scorer import score_founder
        from .market_scorer import score_market

        founder_axis = score_founder(founder_research, founder_score, api_key=api_key)
        market_axis = score_market(deck_extraction, market_research, api_key=api_key)
        result = score_idea_vs_market(
            founder_axis.model_dump(), market_axis.model_dump(), deck_extraction, api_key=api_key
        )
    except LLMCallFailedError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    output_json = result.model_dump_json(indent=2)
    print(output_json)
    memory.write_axis_score(args.application_id, "idea_vs_market", result.model_dump())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
