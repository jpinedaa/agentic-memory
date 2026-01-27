"""Tests for the Neo4j triple store wrapper.

Requires a running Neo4j instance (docker compose up).
"""

import pytest

from src.store import StoreConfig, TripleStore


@pytest.fixture
async def store():
    s = await TripleStore.connect(StoreConfig())
    await s.clear_all()
    yield s
    await s.clear_all()
    await s.close()


async def test_create_and_get_node(store: TripleStore):
    await store.create_node("n1", {"type": "Entity", "name": "user"})
    node = await store.get_node("n1")
    assert node is not None
    assert node["id"] == "n1"
    assert node["type"] == "Entity"
    assert node["name"] == "user"


async def test_get_nonexistent_node(store: TripleStore):
    result = await store.get_node("does-not-exist")
    assert result is None


async def test_create_relationship(store: TripleStore):
    await store.create_node("c1", {"type": "Claim", "subject_text": "user"})
    await store.create_node("e1", {"type": "Entity", "name": "user"})
    await store.create_relationship("c1", "SUBJECT", "e1")

    related = await store.get_related("c1", "SUBJECT")
    assert len(related) == 1
    assert related[0]["id"] == "e1"


async def test_query_by_type(store: TripleStore):
    await store.create_node("o1", {"type": "Observation", "raw_content": "hello", "timestamp": "2024-01-01T00:00:00Z"})
    await store.create_node("o2", {"type": "Observation", "raw_content": "world", "timestamp": "2024-01-02T00:00:00Z"})
    await store.create_node("c1", {"type": "Claim", "timestamp": "2024-01-01T00:00:00Z"})

    obs = await store.query_by_type("Observation")
    assert len(obs) == 2

    claims = await store.query_by_type("Claim")
    assert len(claims) == 1


async def test_find_claims_about(store: TripleStore):
    await store.create_node("e1", {"type": "Entity", "name": "user"})
    await store.create_node("c1", {
        "type": "Claim",
        "confidence": 0.8,
        "timestamp": "2024-01-01T00:00:00Z",
    })
    await store.create_node("c2", {
        "type": "Claim",
        "confidence": 0.6,
        "timestamp": "2024-01-02T00:00:00Z",
    })
    await store.create_relationship("c1", "SUBJECT", "e1")
    await store.create_relationship("c2", "SUBJECT", "e1")

    claims = await store.find_claims_about("e1")
    assert len(claims) == 2
    # Should be ordered by confidence desc
    assert claims[0]["confidence"] == 0.8


async def test_find_claims_excludes_superseded(store: TripleStore):
    await store.create_node("e1", {"type": "Entity", "name": "user"})
    await store.create_node("c1", {
        "type": "Claim",
        "confidence": 0.6,
        "timestamp": "2024-01-01T00:00:00Z",
    })
    await store.create_node("r1", {
        "type": "Resolution",
        "confidence": 0.85,
        "timestamp": "2024-01-03T00:00:00Z",
    })
    await store.create_relationship("c1", "SUBJECT", "e1")
    await store.create_relationship("r1", "SUBJECT", "e1")
    await store.create_relationship("r1", "SUPERSEDES", "c1")

    claims = await store.find_claims_about("e1")
    # c1 should be excluded because r1 supersedes it
    assert len(claims) == 1
    assert claims[0]["id"] == "r1"


async def test_find_unresolved_contradictions(store: TripleStore):
    await store.create_node("c1", {"type": "Claim", "object_text": "morning"})
    await store.create_node("c2", {"type": "Claim", "object_text": "afternoon"})
    await store.create_relationship("c1", "CONTRADICTS", "c2")

    contradictions = await store.find_unresolved_contradictions()
    assert len(contradictions) == 1
    pair = contradictions[0]
    ids = {pair[0]["id"], pair[1]["id"]}
    assert ids == {"c1", "c2"}


async def test_get_or_create_entity(store: TripleStore):
    # First call creates
    id1 = await store.get_or_create_entity("user", "new-id-1")
    assert id1 == "new-id-1"

    # Second call returns existing
    id2 = await store.get_or_create_entity("user", "new-id-2")
    assert id2 == "new-id-1"  # Should return the first one


async def test_find_recent_observations(store: TripleStore):
    await store.create_node("o1", {
        "type": "Observation",
        "raw_content": "first",
        "timestamp": "2024-01-01T00:00:00Z",
    })
    await store.create_node("o2", {
        "type": "Observation",
        "raw_content": "second",
        "timestamp": "2024-01-02T00:00:00Z",
    })

    obs = await store.find_recent_observations(limit=1)
    assert len(obs) == 1
    assert obs[0]["raw_content"] == "second"  # newest first


async def test_clear_all(store: TripleStore):
    await store.create_node("n1", {"type": "Entity", "name": "test"})
    await store.clear_all()
    result = await store.get_node("n1")
    assert result is None
