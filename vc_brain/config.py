"""Central configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    github_token: str = ""
    crunchbase_api_key: str = ""
    producthunt_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./vc_brain.db"

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            crunchbase_api_key=os.getenv("CRUNCHBASE_API_KEY", ""),
            producthunt_token=os.getenv("PRODUCTHUNT_TOKEN", ""),
            database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./vc_brain.db"),
        )


config = Config.from_env()
