from __future__ import annotations

import json
from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError

from schema import MarketExtraction

MODEL = "gpt-4o"
MAX_TOKENS = 4096
TEMPERATURE = 0.1

_PROMPT_PATH = Path(__file__).parent / "prompts" / "extraction_system_prompt.txt"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_prompt(deck_text: str, retry_error: str | None = None) -> str:
    schema_json = json.dumps(MarketExtraction.model_json_schema(), indent=2)
    parts = [
        "Here is the JSON schema you must match exactly:",
        schema_json,
        "\nHere is the deck text, with slide boundaries marked:",
        deck_text,
    ]
    if retry_error:
        parts.append(
            "\nYour previous response failed schema validation with this error:\n"
            f"{retry_error}\n"
            "Fix the JSON so it matches the schema exactly and return only the corrected JSON object."
        )
    return "\n\n".join(parts)


def _call_openai(client: OpenAI, deck_text: str, retry_error: str | None = None) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _load_system_prompt()},
            {"role": "user", "content": _build_user_prompt(deck_text, retry_error)},
        ],
    )
    return response.choices[0].message.content.strip()


def extract_market(deck_text: str, api_key: str) -> MarketExtraction:
    client = OpenAI(api_key=api_key)

    raw = _call_openai(client, deck_text)
    try:
        return MarketExtraction(**json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as first_error:
        raw_retry = _call_openai(client, deck_text, retry_error=str(first_error))
        try:
            return MarketExtraction(**json.loads(raw_retry))
        except (json.JSONDecodeError, ValidationError) as second_error:
            raise ExtractionFailedError(
                f"Extraction failed twice. First error: {first_error}. Second error: {second_error}. "
                f"Last raw response: {raw_retry!r}"
            ) from second_error


class ExtractionFailedError(Exception):
    pass
