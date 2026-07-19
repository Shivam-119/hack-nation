from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from deck_parser import DeckParseError, extract_deck_text
from extractor_agent import ExtractionFailedError, extract_market

THIS_DIR = Path(__file__).parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract market/industry info from a pitch deck.")
    parser.add_argument("--deck", required=True, help="Path to the pitch deck (.pdf or .pptx)")
    parser.add_argument("--out", default=None, help="Path to write the output JSON (default: output/<deck_filename>.json)")
    return parser.parse_args()


def main() -> int:
    load_dotenv(THIS_DIR / ".env")
    load_dotenv(THIS_DIR.parent / ".env")

    args = parse_args()
    deck_path = Path(args.deck)
    out_path = Path(args.out) if args.out else THIS_DIR / "output" / f"{deck_path.stem}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set (checked pdf_parser/.env and repo root .env).", file=sys.stderr)
        return 1

    try:
        deck_text = extract_deck_text(deck_path)
    except DeckParseError as e:
        error_payload = {"error": str(e)}
        out_path.write_text(json.dumps(error_payload, indent=2), encoding="utf-8")
        print(json.dumps(error_payload, indent=2))
        return 1

    try:
        result = extract_market(deck_text, api_key=api_key)
    except ExtractionFailedError as e:
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
