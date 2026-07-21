from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .llm_client import LLMCallFailedError, call_structured_json
from .memory_client import MemoryReadError, MockMemoryClient
from .schemas import MarketAxisScore

THIS_DIR = Path(__file__).parent
MODEL = "gpt-5"
_PROMPT_PATH = THIS_DIR / "prompts" / "market_scorer_system_prompt.txt"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def score_market(deck_extraction: dict, market_research: dict, api_key: str) -> MarketAxisScore:
    schema_json = json.dumps(MarketAxisScore.model_json_schema(), indent=2)
    user_prompt = (
        "Here is the JSON schema your response must match exactly:\n"
        f"{schema_json}\n\n"
        "Here is Agent 1's deck market extraction:\n"
        f"{json.dumps(deck_extraction, indent=2)}\n\n"
        "Here is Agent 2's market research (four categories, deliberately unjudged by that agent):\n"
        f"{json.dumps(market_research, indent=2)}"
    )
    return call_structured_json(
        system=_load_system_prompt(),
        user=user_prompt,
        response_model=MarketAxisScore,
        api_key=api_key,
        model=MODEL,
    )


def _main() -> int:
    load_dotenv(THIS_DIR / ".env")
    load_dotenv(THIS_DIR.parent / ".env")

    parser = argparse.ArgumentParser(description="Score the Market axis for a single application.")
    parser.add_argument("--application-id", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    memory = MockMemoryClient()
    try:
        deck_extraction = memory.get_deck_extraction(args.application_id)
        market_research = memory.get_market_research(args.application_id)
    except MemoryReadError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        result = score_market(deck_extraction, market_research, api_key=api_key)
    except LLMCallFailedError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    output_json = result.model_dump_json(indent=2)
    print(output_json)
    memory.write_axis_score(args.application_id, "market", result.model_dump())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
