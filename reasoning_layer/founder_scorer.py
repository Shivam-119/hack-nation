from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from llm_client import LLMCallFailedError, call_structured_json
from memory_client import MemoryReadError, MockMemoryClient
from schemas import FounderAxisScore

THIS_DIR = Path(__file__).parent
MODEL = "gpt-4.1"
_PROMPT_PATH = THIS_DIR / "prompts" / "founder_scorer_system_prompt.txt"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def score_founder(founder_research: dict, founder_score: float | None, api_key: str) -> FounderAxisScore:
    schema_json = json.dumps(FounderAxisScore.model_json_schema(), indent=2)
    user_prompt = (
        "Here is the JSON schema your response must match exactly:\n"
        f"{schema_json}\n\n"
        "Here is the founder research data for this application:\n"
        f"{json.dumps(founder_research, indent=2)}\n\n"
        "Here is this person's persistent Founder Score from Memory "
        f"(null if this is a new founder with no prior score): {json.dumps(founder_score)}"
    )
    return call_structured_json(
        system=_load_system_prompt(),
        user=user_prompt,
        response_model=FounderAxisScore,
        api_key=api_key,
        model=MODEL,
    )


def _main() -> int:
    load_dotenv(THIS_DIR / ".env")
    load_dotenv(THIS_DIR.parent / ".env")

    parser = argparse.ArgumentParser(description="Score the Founder axis for a single application.")
    parser.add_argument("--application-id", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    memory = MockMemoryClient()
    try:
        founder_research = memory.get_founder_research(args.application_id)
    except MemoryReadError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    founder_score = memory.get_founder_score(founder_research.get("founder_id", ""))

    try:
        result = score_founder(founder_research, founder_score, api_key=api_key)
    except LLMCallFailedError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    output_json = result.model_dump_json(indent=2)
    print(output_json)
    memory.write_axis_score(args.application_id, "founder", result.model_dump())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
