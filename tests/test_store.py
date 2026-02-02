"""Tests for the Neo4j triple store wrapper.

Requires a running Neo4j instance (docker compose up).
"""
# pylint: disable=missing-function-docstring  # test names are self-documenting
# pylint: disable=redefined-outer-name  # pytest fixture injection pattern

import pytest

from src.store import StoreConfig, TripleStore


@pytest.fixture
async def store():
    s = await TripleStore.connect(StoreConfig())
    await s.clear_all()
    yield s
    await s.clear_all()
    await s.close()


async def test_create_and_get_concept(store: TripleStore):
    await store.create_concept("c1", "user", kind="entity")
    node = await store.get_node("c1")
    assert node is not None
    assert node["id"] == "c1"
    assert "Concept" in node["_labels"]
    assert node["name"] == "user"


async def test_get_nonexistent_node(store: TripleStore):
    result = await store.get_node("does-not-exist")
    assert result is None


async def test_create_relationship(store: TripleStore):
    await store.create_statement("s1", "prefers", 0.8)
    await store.create_concept("c1", "user", kind="entity")
    await store.create_relationship("s1", "ABOUT_SUBJECT", "c1")

    related = await store.raw_query(
        "MATCH (s {id: 's1'})-[:ABOUT_SUBJECT]->(c) RETURN c"
    )
    assert len(related) == 1
    assert dict(related[0]["c"])["id"] == "c1"


async def test_find_statements_about(store: TripleStore):
    await store.create_concept("c1", "user", kind="entity")
    await store.create_statement("s1", "prefers", 0.8)
    await store.create_statement("s2", "dislikes", 0.6)
    await store.create_relationship("s1", "ABOUT_SUBJECT", "c1")
    await store.create_relationship("s2", "ABOUT_SUBJECT", "c1")

    stmts = await store.find_statements_about("c1")
    assert len(stmts) == 2
    # Should be ordered by confidence desc
    assert stmts[0]["confidence"] == 0.8


async def test_find_statements_excludes_superseded(store: TripleStore):
    await store.create_concept("c1", "user", kind="entity")
    await store.create_statement("s1", "prefers", 0.6)
    await store.create_statement("s2", "prefers", 0.85)
    await store.create_relationship("s1", "ABOUT_SUBJECT", "c1")
    await store.create_relationship("s2", "ABOUT_SUBJECT", "c1")
    await store.create_relationship("s2", "SUPERSEDES", "s1")

    stmts = await store.find_statements_about("c1")
    # s1 should be excluded because s2 supersedes it
    assert len(stmts) == 1
    assert stmts[0]["id"] == "s2"


async def test_find_unresolved_contradictions(store: TripleStore):
    await store.create_statement("s1", "prefers", 0.7)
    await store.create_statement("s2", "prefers", 0.7)
    await store.create_relationship("s1", "CONTRADICTS", "s2")

    contradictions = await store.find_unresolved_contradictions()
    assert len(contradictions) == 1
    pair = contradictions[0]
    ids = {pair[0]["id"], pair[1]["id"]}
    assert ids == {"s1", "s2"}


async def test_get_or_create_concept(store: TripleStore):
    # First call creates
    id1 = await store.get_or_create_concept("user", "new-id-1", kind="entity")
    assert id1 == "new-id-1"

    # Second call returns existing
    id2 = await store.get_or_create_concept("user", "new-id-2", kind="entity")
    assert id2 == "new-id-1"  # Should return the first one


async def test_find_recent_observations(store: TripleStore):
    await store.create_observation("o1", raw_content="first")
    await store.create_observation("o2", raw_content="second")

    obs = await store.find_recent_observations(limit=1)
    assert len(obs) == 1
    assert obs[0]["raw_content"] == "second"  # newest first


async def test_find_recent_statements(store: TripleStore):
    await store.create_concept("c1", "user", kind="entity")
    await store.create_concept("c2", "morning", kind="value")
    await store.create_statement("s1", "prefers", 0.9)
    await store.create_relationship("s1", "ABOUT_SUBJECT", "c1")
    await store.create_relationship("s1", "ABOUT_OBJECT", "c2")

    stmts = await store.find_recent_statements(limit=5)
    assert len(stmts) == 1
    assert stmts[0]["predicate"] == "prefers"
    assert stmts[0]["subject_name"] == "user"
    assert stmts[0]["object_name"] == "morning"


async def test_get_all_concepts(store: TripleStore):
    await store.create_concept("c1", "user", kind="entity")
    await store.create_concept("c2", "morning", kind="value")

    concepts = await store.get_all_concepts()
    assert len(concepts) == 2
    names = {c["name"] for c in concepts}
    assert names == {"morning", "user"}


async def test_get_or_create_source(store: TripleStore):
    id1 = await store.get_or_create_source("test_user", kind="user")
    assert id1 is not None

    # Second call returns same id
    id2 = await store.get_or_create_source("test_user", kind="user")
    assert id2 == id1


async def test_create_statement_with_negated(store: TripleStore):
    await store.create_statement("s1", "likes", 0.9, negated=True)
    node = await store.get_node("s1")
    assert node is not None
    assert node["negated"] is True
    assert node["predicate"] == "likes"


async def test_clear_all(store: TripleStore):
    await store.create_concept("c1", "test", kind="entity")
    await store.clear_all()
    result = await store.get_node("c1")
    assert result is None
