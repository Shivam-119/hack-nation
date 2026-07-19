from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from schema import MarketExtraction, MarketResearch
from tavily_client import search as tavily_search

MODEL = "gpt-4.1"
MAX_TOKENS = 4096
TEMPERATURE = 0.2
MAX_SEARCH_TURNS = 10

_PROMPT_PATH = Path(__file__).parent / "prompts" / "research_system_prompt.txt"

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the live web for real-time information relevant to market research.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to run.",
                }
            },
            "required": ["query"],
        },
    },
}


class ResearchFailedError(Exception):
    pass


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _build_initial_user_prompt(agent1_output: MarketExtraction) -> str:
    schema_json = json.dumps(MarketResearch.model_json_schema(), indent=2)
    return (
        "Here is the JSON schema your final answer must match exactly:\n"
        f"{schema_json}\n\n"
        "Here is Agent 1's extraction output for the deck you are researching:\n"
        f"{agent1_output.model_dump_json(indent=2)}"
    )


def _assistant_message_dict(message: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in message.tool_calls
        ]
    return msg


def _run_tool_calls(message: Any, tavily_api_key: str, search_log: list[str]) -> list[dict[str, Any]]:
    tool_messages: list[dict[str, Any]] = []
    for tool_call in message.tool_calls:
        try:
            args = json.loads(tool_call.function.arguments)
            query = args.get("query", "")
        except json.JSONDecodeError:
            query = ""

        if query:
            search_log.append(query)
            print(f"[search {len(search_log)}] {query}", file=sys.stderr)
            result = tavily_search(query, api_key=tavily_api_key)
        else:
            result = "Error: no query provided for this search call."

        tool_messages.append(
            {"role": "tool", "tool_call_id": tool_call.id, "content": result}
        )
    return tool_messages


def _parse_and_validate(content: str, agent1_output: MarketExtraction, search_log: list[str]) -> MarketResearch:
    result = MarketResearch(**json.loads(content))
    # Ensure the input_reference and full search_log are always accurate, regardless of what the model echoed back.
    result.input_reference = _input_reference_from(agent1_output)
    result.search_log = search_log
    return result


def _input_reference_from(agent1_output: MarketExtraction):
    from schema import InputReference

    return InputReference(
        company_name=agent1_output.company_name,
        primary_industry=agent1_output.primary_industry,
    )


def run_research(agent1_output: MarketExtraction, openai_api_key: str, tavily_api_key: str) -> MarketResearch:
    client = OpenAI(api_key=openai_api_key)
    search_log: list[str] = []

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _load_system_prompt()},
        {"role": "user", "content": _build_initial_user_prompt(agent1_output)},
    ]

    final_content: str | None = None
    turn = 0

    while turn < MAX_SEARCH_TURNS:
        turn += 1
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            messages=messages,
            tools=[WEB_SEARCH_TOOL],
            tool_choice="auto",
        )
        message = response.choices[0].message

        if not message.tool_calls:
            final_content = message.content
            break

        messages.append(_assistant_message_dict(message))
        messages.extend(_run_tool_calls(message, tavily_api_key, search_log))

    if final_content is None:
        # Hit the turn cap while the model still wanted to search — force a final answer.
        messages.append(
            {
                "role": "user",
                "content": (
                    "You have reached the maximum number of search turns. Stop searching now and "
                    "respond with only the final JSON object, synthesized from what you have found so far."
                ),
            }
        )
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            messages=messages,
            tool_choice="none",
        )
        final_content = response.choices[0].message.content

    try:
        return _parse_and_validate(final_content, agent1_output, search_log)
    except (json.JSONDecodeError, ValidationError) as first_error:
        messages.append({"role": "assistant", "content": final_content})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous response failed schema validation with this error:\n"
                    f"{first_error}\n"
                    "Fix the JSON so it matches the schema exactly and return only the corrected JSON object."
                ),
            }
        )
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            messages=messages,
            tool_choice="none",
        )
        retry_content = response.choices[0].message.content
        try:
            return _parse_and_validate(retry_content, agent1_output, search_log)
        except (json.JSONDecodeError, ValidationError) as second_error:
            raise ResearchFailedError(
                f"Research failed twice. First error: {first_error}. Second error: {second_error}. "
                f"Last raw response: {retry_content!r}"
            ) from second_error
