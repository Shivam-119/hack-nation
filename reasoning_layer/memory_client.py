from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).parent
DEFAULT_PDF_PARSER_OUTPUT_DIR = THIS_DIR.parent / "pdf_parser" / "output"
DEFAULT_FOUNDER_FIXTURE_PATH = THIS_DIR / "mock_data" / "founder_research_fixture.json"
DEFAULT_DECISIONS_DIR = THIS_DIR / "output" / "decisions"


class MemoryReadError(Exception):
    """Raised when Memory doesn't have the data a stage needs. Never fabricate a substitute — surface this instead."""


class MemoryClient(ABC):
    """Abstract seam between the reasoning layer and the Memory layer (owned by the Memory team).

    Every read/write to founder data, market data, decks, and scores goes through this
    interface — never through direct file or database access scattered through the codebase.
    Swap `MockMemoryClient` for a real implementation later by writing one new class; nothing
    else in this package should change.
    """

    @abstractmethod
    def get_deck_extraction(self, application_id: str) -> dict:
        """Returns Agent 1's output for this application."""

    @abstractmethod
    def get_market_research(self, application_id: str) -> dict:
        """Returns Agent 2's output for this application."""

    @abstractmethod
    def get_founder_research(self, application_id: str) -> dict:
        """Returns founder research data for this application."""

    @abstractmethod
    def get_founder_score(self, founder_id: str) -> float | None:
        """Persistent score for this person, across all their applications. None if new founder."""

    @abstractmethod
    def write_axis_score(self, application_id: str, axis: str, result: dict) -> None:
        """Persists a scorer agent's output back to Memory."""

    @abstractmethod
    def write_decision(self, application_id: str, decision: dict) -> None:
        """Persists the final decision record."""


class MockMemoryClient(MemoryClient):
    """Local-file-backed implementation for development and testing.

    Reads Agent 1/2 output from pdf_parser/output/, founder data from a hand-written fixture
    in mock_data/, and appends axis scores / decisions to local JSON files under output/.
    """

    def __init__(
        self,
        pdf_parser_output_dir: Path = DEFAULT_PDF_PARSER_OUTPUT_DIR,
        founder_fixture_path: Path = DEFAULT_FOUNDER_FIXTURE_PATH,
        decisions_dir: Path = DEFAULT_DECISIONS_DIR,
    ) -> None:
        self._pdf_parser_output_dir = pdf_parser_output_dir
        self._founder_fixture_path = founder_fixture_path
        self._decisions_dir = decisions_dir
        self._founder_fixtures: dict[str, Any] | None = None

    def get_deck_extraction(self, application_id: str) -> dict:
        return self._read_json(
            self._pdf_parser_output_dir / f"{application_id}.json", "deck extraction (Agent 1 output)"
        )

    def get_market_research(self, application_id: str) -> dict:
        return self._read_json(
            self._pdf_parser_output_dir / f"{application_id}_research.json", "market research (Agent 2 output)"
        )

    def get_founder_research(self, application_id: str) -> dict:
        fixtures = self._load_founder_fixtures()
        if application_id not in fixtures:
            raise MemoryReadError(
                f"No founder research fixture for application_id={application_id!r}. "
                f"Known fixture ids: {sorted(fixtures.keys())}"
            )
        return fixtures[application_id]

    def get_founder_score(self, founder_id: str) -> float | None:
        fixtures = self._load_founder_fixtures()
        for entry in fixtures.values():
            if entry.get("founder_id") == founder_id:
                return entry.get("founder_score")
        return None

    def write_axis_score(self, application_id: str, axis: str, result: dict) -> None:
        path = self._decisions_dir / f"{application_id}_{axis}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    def write_decision(self, application_id: str, decision: dict) -> None:
        path = self._decisions_dir / f"{application_id}_decision.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(decision, indent=2), encoding="utf-8")

    def _load_founder_fixtures(self) -> dict[str, Any]:
        if self._founder_fixtures is None:
            self._founder_fixtures = self._read_json(
                self._founder_fixture_path, "founder research fixture"
            )
        return self._founder_fixtures

    @staticmethod
    def _read_json(path: Path, label: str) -> dict:
        if not path.exists():
            raise MemoryReadError(f"{label} not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
