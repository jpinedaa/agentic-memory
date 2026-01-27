"""Tests for the MemoryService interfaces.

Requires both Neo4j and Claude API access.
"""

import pytest

from src.interfaces import MemoryService, _text_overlap
from src.llm import LLMTranslator
from src.store import StoreConfig, TripleStore


@pytest.fixture
async def memory():
    store = await TripleStore.connect(StoreConfig())
    await store.clear_all()
    llm = LLMTranslator()
    service = MemoryService(store=store, llm=llm)
    yield service
    await store.clear_all()
    await store.close()


def test_text_overlap():
    assert _text_overlap("user prefers morning", "user prefers afternoon") is True
    assert _text_overlap("completely different", "nothing alike here") is False
    assert _text_overlap("meeting preferences", "what are meeting preferences") is True


@pytest.mark.llm
async def test_observe(memory: MemoryService):
    obs_id = await memory.observe(
        "user said they hate waking up early for meetings",
        source="test",
    )
    assert obs_id is not None

    # Check the observation was stored
    node = await memory.store.get_node(obs_id)
    assert node is not None
    assert node["type"] == "Observation"
    assert "early" in node["raw_content"] or "meetings" in node["raw_content"]


@pytest.mark.llm
async def test_claim(memory: MemoryService):
    # First add an observation for context
    await memory.observe(
        "user said they hate waking up early for meetings",
        source="test",
    )

    claim_id = await memory.claim(
        "based on their statement about early meetings, user prefers afternoon meetings",
        source="inference_agent",
    )
    assert claim_id is not None

    node = await memory.store.get_node(claim_id)
    assert node is not None
    assert node["type"] in ("Claim", "Resolution")
    assert node["source"] == "inference_agent"


@pytest.mark.llm
async def test_remember(memory: MemoryService):
    # Seed some data
    await memory.observe(
        "user said they prefer afternoon meetings",
        source="test",
    )
    await memory.claim(
        "user prefers afternoon meetings based on their direct statement",
        source="inference_agent",
    )

    response = await memory.remember("what are the user's meeting preferences?")
    assert isinstance(response, str)
    assert len(response) > 0
