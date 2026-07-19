"""Tests for the EntityRepository — the DB interface the post-tool-processing
layer uses to insert Founder/Company entities. Offline, isolated SQLite per test."""

from vc_brain.memory.models import Company, DataPoint, Founder, SourceType
from vc_brain.memory.repository import EntityRepository


def _repo(tmp_path):
    return EntityRepository(path=str(tmp_path / "repo.db"))


def _github_snapshot():
    return Founder(
        name="Ada",
        github_url="https://github.com/ada",
        data_points=[DataPoint(
            source=SourceType.GITHUB, source_url="https://github.com/ada",
            content={"type": "github_candidate", "public_repos": 15},
        )],
    )


def test_upsert_and_get_founder(tmp_path):
    repo = _repo(tmp_path)
    f = repo.upsert_founder(Founder(name="Grace", email="grace@x.com"))
    assert repo.get_founder(f.id).name == "Grace"


def test_founder_dedup_case_insensitive(tmp_path):
    repo = _repo(tmp_path)
    f1 = repo.upsert_founder(Founder(name="Ada", github_url="https://github.com/ada"))
    f2 = repo.upsert_founder(Founder(name="Ada Lovelace", github_url="https://GitHub.com/ada"))
    assert f1.id == f2.id  # matched despite case
    assert f2.name == "Ada Lovelace"
    assert len(repo.all_founders()) == 1


def test_reingest_does_not_inflate_data_points(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_founder(_github_snapshot())
    f = repo.upsert_founder(_github_snapshot())  # same source snapshot again
    assert len(f.data_points) == 1  # replaced, not appended


def test_company_upsert_dedup_and_link(tmp_path):
    repo = _repo(tmp_path)
    founder = repo.upsert_founder(Founder(name="Ada", github_url="https://github.com/ada"))
    c1 = repo.link_founder_company(founder, "Acme AI", sector="AI")
    c2 = repo.upsert_company(Company(name="acme ai", geography="Berlin"))  # case-variant name
    assert c1.id == c2.id
    assert c2.sector == "AI" and c2.geography == "Berlin"
    assert founder.id in repo.find_company("Acme AI").founder_ids


def test_persistence_across_instances(tmp_path):
    path = str(tmp_path / "repo.db")
    f = EntityRepository(path=path).upsert_founder(Founder(name="Ada", email="ada@x.com"))
    # brand-new repository object, same DB file -> data survived (durable)
    reopened = EntityRepository(path=path)
    assert reopened.find_founder(email="ada@x.com") is not None
    assert reopened.get_founder(f.id).name == "Ada"
