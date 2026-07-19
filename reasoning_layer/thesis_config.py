from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class Range(BaseModel):
    min: float
    max: float


class ThesisConfig(BaseModel):
    sectors: list[str]
    stage: list[Literal["pre-seed", "seed", "series-a"]]
    geography: list[str]
    check_size_usd: Range
    ownership_target_pct: Range
    risk_appetite: Literal["low", "medium", "high"]


def load_thesis_config(path: str | Path) -> ThesisConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ThesisConfig(**data)
