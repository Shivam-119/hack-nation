from __future__ import annotations

import json
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = "gpt-4.1"
MAX_TOKENS = 2048
TEMPERATURE = 0.2

T = TypeVar("T", bound=BaseModel)


class LLMCallFailedError(Exception):
    pass


def call_structured_json(
    system: str,
    user: str,
    response_model: type[T],
    api_key: str,
    model: str = DEFAULT_MODEL,
    temperature: float = TEMPERATURE,
) -> T:
    """Call OpenAI chat completions requesting a JSON object, validate against response_model.

    Retries once with the validation error appended if the first response doesn't parse/validate,
    matching the pattern already used by the sourcing agents (pdf_parser/extractor_agent.py).
    Raises LLMCallFailedError if it fails twice, rather than silently returning something invalid.
    """
    client = OpenAI(api_key=api_key)

    def _call(extra_note: str | None) -> str:
        user_content = user if extra_note is None else f"{user}\n\n{extra_note}"
        completion = client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        )
        return completion.choices[0].message.content or ""

    raw = _call(None)
    try:
        return response_model(**json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as first_error:
        retry_note = (
            "Your previous response failed schema validation with this error:\n"
            f"{first_error}\n"
            "Fix the JSON so it matches the required schema exactly and return only the corrected JSON object."
        )
        raw_retry = _call(retry_note)
        try:
            return response_model(**json.loads(raw_retry))
        except (json.JSONDecodeError, ValidationError) as second_error:
            raise LLMCallFailedError(
                f"LLM call failed twice for {response_model.__name__}. "
                f"First error: {first_error}. Second error: {second_error}. Last raw response: {raw_retry!r}"
            ) from second_error
