"""Utility for loading prompt files from the prompts/ directory."""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_system(name: str) -> str:
    """Load a system prompt from prompts/system/<name>.txt.

    Raises FileNotFoundError if the file does not exist.
    """
    path = _PROMPTS_DIR / "system" / f"{name}.txt"
    return path.read_text(encoding="utf-8").strip()
