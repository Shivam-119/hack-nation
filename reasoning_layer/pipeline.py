from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from adversarial_agent import generate_adversarial_view
from decision_draft_agent import draft_decision
from decision_finalizer import finalize_decision
from founder_scorer import score_founder
from idea_vs_market_scorer import score_idea_vs_market
from llm_client import LLMCallFailedError
from market_scorer import score_market
from memory_client import MemoryReadError, MockMemoryClient
from thesis_config import load_thesis_config
from thesis_fit_filter import check_thesis_fit

THIS_DIR = Path(__file__).parent
DEFAULT_THESIS_PATH = THIS_DIR / "thesis_config.json"


def run_pipeline(application_id: str, thesis_path: Path, api_key: str) -> dict:
    memory = MockMemoryClient()
    thesis = load_thesis_config(thesis_path)

    deck_extraction = memory.get_deck_extraction(application_id)

    # Stage 1: deterministic hard-constraint filter. No LLM calls happen if this fails.
    thesis_fit = check_thesis_fit(thesis, deck_extraction)
    print(f"[stage 1] thesis_fit passed={thesis_fit.passed} reasons={thesis_fit.reasons}", file=sys.stderr)
    if not thesis_fit.passed:
        rejection = {
            "application_id": application_id,
            "recommendation": "pass",
            "rationale": "Rejected at thesis fit filter (Stage 1) — no downstream scoring was run.",
            "thesis_fit": thesis_fit.model_dump(),
        }
        memory.write_decision(application_id, rejection)
        return rejection

    market_research = memory.get_market_research(application_id)
    founder_research = memory.get_founder_research(application_id)
    founder_score = memory.get_founder_score(founder_research.get("founder_id", ""))

    # Stage 2: founder and market scorers are independent single-shot calls — run concurrently.
    print("[stage 2] scoring founder + market axes concurrently", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=2) as pool:
        founder_future = pool.submit(score_founder, founder_research, founder_score, api_key)
        market_future = pool.submit(score_market, deck_extraction, market_research, api_key)
        founder_axis = founder_future.result()
        market_axis = market_future.result()
    memory.write_axis_score(application_id, "founder", founder_axis.model_dump())
    memory.write_axis_score(application_id, "market", market_axis.model_dump())

    # Stage 3: idea-vs-market, reasoning only over the two axis outputs above.
    print("[stage 3] scoring idea_vs_market axis", file=sys.stderr)
    idea_vs_market_axis = score_idea_vs_market(
        founder_axis.model_dump(), market_axis.model_dump(), deck_extraction, api_key=api_key
    )
    memory.write_axis_score(application_id, "idea_vs_market", idea_vs_market_axis.model_dump())

    # Stage 4: draft decision — the only place thesis soft factors are allowed to matter.
    print("[stage 4] drafting decision", file=sys.stderr)
    draft = draft_decision(
        founder_axis.model_dump(), market_axis.model_dump(), idea_vs_market_axis.model_dump(), thesis, api_key=api_key
    )

    # Stage 5: adversarial devil's-advocate pass.
    print("[stage 5] generating adversarial view", file=sys.stderr)
    adversarial = generate_adversarial_view(
        draft.model_dump(),
        founder_axis.model_dump(),
        market_axis.model_dump(),
        idea_vs_market_axis.model_dump(),
        api_key=api_key,
    )

    # Stage 6: deterministic merge into the final decision record.
    print("[stage 6] finalizing decision", file=sys.stderr)
    final = finalize_decision(
        application_id=application_id,
        founder_axis=founder_axis.model_dump(),
        market_axis=market_axis.model_dump(),
        idea_vs_market_axis=idea_vs_market_axis.model_dump(),
        thesis_fit=thesis_fit,
        draft=draft,
        adversarial=adversarial,
    )
    result = final.model_dump()
    memory.write_decision(application_id, result)
    return result


def _main() -> int:
    load_dotenv(THIS_DIR / ".env")
    load_dotenv(THIS_DIR.parent / ".env")

    parser = argparse.ArgumentParser(description="Run the full decision-layer pipeline for one application.")
    parser.add_argument("--application-id", required=True)
    parser.add_argument("--thesis", default=str(DEFAULT_THESIS_PATH), help="Path to thesis_config.json")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    try:
        result = run_pipeline(args.application_id, Path(args.thesis), api_key=api_key)
    except (MemoryReadError, LLMCallFailedError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
