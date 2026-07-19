"""Test the mock-data seeder: fixtures -> DB entities the API reads."""

import json

from scripts.seed_mock_data import _enrich_screening, seed
from vc_brain.memory.store import MemoryStore

FIXTURE = "frontend/fixtures/applications.json"


def test_seed_populates_entities(tmp_path):
    apps = json.loads(open(FIXTURE).read())
    store = MemoryStore(path=str(tmp_path / "seed.db"))
    n_apps, n_founders, n_companies = seed(store, apps)
    assert n_apps == len(apps)
    assert len(store.applications) == n_apps
    assert n_companies == n_apps  # one company per application
    # every application links to a real company + founders
    for app in store.applications.values():
        assert store.get_company(app.company_id) is not None
        assert all(store.get_founder(fid) for fid in app.founder_ids)


def test_seed_is_idempotent(tmp_path):
    apps = json.loads(open(FIXTURE).read())
    path = str(tmp_path / "seed.db")
    seed(MemoryStore(path=path), apps)
    seed(MemoryStore(path=path), apps)  # run again on same DB
    store = MemoryStore(path=path)
    assert len(store.applications) == len(apps)      # not duplicated
    assert len(store.companies) == len(apps)


def test_enrich_screening_fills_all_swot_quadrants():
    apps = json.loads(open(FIXTURE).read())
    screened = next(a for a in apps if a.get("screening"))
    out = _enrich_screening(screened["screening"])
    for axis_key in ("founder_axis", "market_axis", "idea_vs_market_axis"):
        axis = out[axis_key]
        for quadrant in ("strengths", "weaknesses", "opportunities", "threats"):
            assert axis[quadrant], f"{axis_key}.{quadrant} is empty"
            # frontend Evidence renders item.text -> items must be objects
            assert all(isinstance(i, dict) and "text" in i for i in axis[quadrant])


def test_enrich_screening_handles_none():
    assert _enrich_screening(None) is None
