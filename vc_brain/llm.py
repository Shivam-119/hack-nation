"""Thin wrapper around LLM providers for structured completions."""

from __future__ import annotations

import json
from typing import Any

import httpx

from vc_brain.config import config


async def complete(prompt: str, system: str = "", model: str = "auto") -> str:
    """Return an LLM completion string. Uses OpenAI as primary, Anthropic as fallback."""
    if model == "auto":
        if config.openai_api_key:
            return await _openai(prompt, system)
        if config.anthropic_api_key:
            return await _anthropic(prompt, system)
        raise RuntimeError("No LLM API key configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY.")
    if model == "openai":
        return await _openai(prompt, system)
    if model == "anthropic":
        return await _anthropic(prompt, system)
    return await _openai(prompt, system)


async def complete_json(prompt: str, system: str = "", use_response_format: bool = True) -> dict[str, Any]:
    """Return a parsed JSON dict from the LLM.

    When using OpenAI, leverages response_format=json_object for reliable structured output.
    """
    if use_response_format and config.openai_api_key:
        return await _openai_json(prompt, system)

    raw = await complete(prompt, system)
    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


async def _anthropic(prompt: str, system: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
                "system": system or "You are a helpful assistant.",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


async def _openai(prompt: str, system: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.openai_model,
                "messages": [
                    {"role": "system", "content": system or "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 4096,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _openai_json(prompt: str, system: str) -> dict[str, Any]:
    """OpenAI with response_format=json_object for reliable structured output."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.openai_model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": (system or "You are a helpful assistant.") + "\nRespond in valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 4096,
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
