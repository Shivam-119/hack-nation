from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from .research_agent import ResearchFailedError, run_research
from .schema import MarketExtraction

THIS_DIR = Path(__file__).parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research the real-world market for a deck already processed by Agent 1.")
    parser.add_argument("--input", required=True, help="Path to Agent 1's output JSON (e.g. output/example_deck.json)")
    parser.add_argument("--out", default=None, help="Path to write the research JSON (default: output/<input_filename>_research.json)")
    return parser.parse_args()


def main() -> int:
    load_dotenv(THIS_DIR / ".env")
    load_dotenv(THIS_DIR.parent / ".env")

    args = parse_args()
    input_path = Path(args.input)
    out_path = Path(args.out) if args.out else THIS_DIR / "output" / f"{input_path.stem}_research.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    tavily_api_key = os.environ.get("TAVILY_API_KEY")
    missing = [name for name, val in [("OPENAI_API_KEY", openai_api_key), ("TAVILY_API_KEY", tavily_api_key)] if not val]
    if missing:
        print(f"Error: missing required env vars: {', '.join(missing)} (checked pdf_parser/.env and repo root .env).", file=sys.stderr)
        return 1

    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        agent1_output = MarketExtraction(**json.loads(input_path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValidationError) as e:
        print(f"Error: input file is not a valid Agent 1 output: {e}", file=sys.stderr)
        return 1

    try:
        result = run_research(agent1_output, openai_api_key=openai_api_key, tavily_api_key=tavily_api_key)
    except ResearchFailedError as e:
        error_payload = {"error": str(e)}
        out_path.write_text(json.dumps(error_payload, indent=2), encoding="utf-8")
        print(json.dumps(error_payload, indent=2))
        return 1

    output_json = result.model_dump_json(indent=2)
    out_path.write_text(output_json, encoding="utf-8")
    print(output_json)
    print(f"\nSaved to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
