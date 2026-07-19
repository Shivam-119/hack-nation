"""CLI to seed the demo inbox fixtures into the DB the API reads from.

The seeding logic lives in `vc_brain.memory.seed` (also run automatically on
server startup via main.py). This is the manual entry point.

    python -m scripts.seed_mock_data            # -> config.database_url (./vc_brain.db)
    python -m scripts.seed_mock_data --store x.db
"""

from __future__ import annotations

import argparse

from vc_brain.memory.seed import FIXTURE, load_fixture, seed
from vc_brain.memory.store import MemoryStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed mock inbox data into the DB")
    parser.add_argument("--store", default=None, help="SQLite file (default: config.database_url)")
    parser.add_argument("--fixture", default=str(FIXTURE), help="applications.json path")
    args = parser.parse_args()

    apps = load_fixture(args.fixture)
    store = MemoryStore(path=args.store) if args.store else MemoryStore()
    n_apps, n_founders, n_companies = seed(store, apps)
    print(f"seeded {n_apps} applications, {n_founders} founders, {n_companies} companies")


if __name__ == "__main__":
    main()
