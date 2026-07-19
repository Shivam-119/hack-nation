"""Basic tests for the Memory layer."""

from vc_brain.memory.models import Founder, DataPoint, SourceType
from vc_brain.memory.store import MemoryStore
from vc_brain.memory.founder_score import compute_founder_score


def test_founder_upsert_deduplicates():
    store = MemoryStore(db_path=":memory:")
    f1 = Founder(name="Alice", email="alice@example.com")
    f2 = Founder(name="Alice Updated", email="alice@example.com", skills=["python"])

    stored1 = store.upsert_founder(f1)
    stored2 = store.upsert_founder(f2)

    assert stored1.id == stored2.id
    assert stored2.name == "Alice Updated"
    assert "python" in stored2.skills


def test_founder_score_computation():
    founder = Founder(
        name="Bob",
        skills=["python", "ml", "tensorflow"],
        education=[{"institution": "MIT", "degree": "CS"}],
        data_points=[
            DataPoint(
                source=SourceType.GITHUB,
                content={"public_repos": 15, "total_stars": 200, "contributions": 500},
            ),
            DataPoint(
                source=SourceType.PRODUCT_HUNT,
                content={"launches": 2},
            ),
        ],
    )
    score = compute_founder_score(founder)
    assert score.overall > 0
    assert score.technical > 0
    assert score.execution > 0
    assert score.leadership > 0


def test_company_deduplication():
    store = MemoryStore(db_path=":memory:")
    from vc_brain.memory.models import Company

    c1 = store.upsert_company(Company(name="Acme AI", sector="AI"))
    c2 = store.upsert_company(Company(name="acme ai", geography="Berlin"))

    assert c1.id == c2.id
    assert c2.geography == "Berlin"
    assert c2.sector == "AI"
