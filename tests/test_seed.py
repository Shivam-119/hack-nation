"""Test the mock-data seeder: fixtures -> DB entities the API reads."""

import json

from vc_brain.memory.seed import _enrich_screening, ensure_seeded, seed
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


AXES = ("founder_axis", "market_axis", "idea_vs_market_axis")
QUADRANTS = ("strengths", "weaknesses", "opportunities", "threats")


def test_enrich_screening_fills_the_analyst_view_quadrants():
    """The filler guarantee: opportunities and threats are always populated so
    the detail view never renders an empty card.

    Strengths and weaknesses come from the source and are NOT filled. Real
    reasoning-layer output has strengths but no weaknesses, and inventing
    weaknesses about a real company would be dishonest -- so an empty
    weaknesses list is a legitimate outcome, not a bug.
    """
    out = _enrich_screening({axis: {"strengths": [{"text": "shipped v1"}]} for axis in AXES})
    for axis_key in AXES:
        axis = out[axis_key]
        assert axis["opportunities"], f"{axis_key}.opportunities was not filled"
        assert axis["threats"], f"{axis_key}.threats was not filled"
        assert axis["strengths"]


def test_enrich_screening_normalizes_every_fixture_axis():
    """Both shapes stay consistent for everything actually in the fixture --
    including the real-evaluation entries, whose weaknesses are empty."""
    for app in json.loads(open(FIXTURE).read()):
        if not app.get("screening"):
            continue
        out = _enrich_screening(app["screening"])
        for axis_key in AXES:
            axis = out.get(axis_key)
            assert isinstance(axis, dict), f"{app['company_name']}.{axis_key} missing"
            for quadrant in QUADRANTS:
                # flat shape (AxisCard / API _axis_payload): items are {text, ...}
                assert all(isinstance(i, dict) and "text" in i for i in axis[quadrant])
                # nested shape (SourceAxis, the inbox detail view): {text, src}
                nested = axis["swot"][quadrant]
                assert len(nested) == len(axis[quadrant])
                assert all("text" in i and "src" in i for i in nested)


def test_enrich_screening_handles_none():
    assert _enrich_screening(None) is None


def test_ensure_seeded_is_a_noop_when_already_present(tmp_path):
    path = str(tmp_path / "seed.db")
    ensure_seeded(MemoryStore(path=path))          # first call seeds
    n_before = len(MemoryStore(path=path).applications)
    ensure_seeded(MemoryStore(path=path))          # second call: nothing missing
    assert len(MemoryStore(path=path).applications) == n_before
