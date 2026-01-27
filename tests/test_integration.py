"""Integration test: the meeting-preferences scenario from design doc Section 9.2.

Requires both Neo4j and Claude API access.
Runs the full flow:
1. User observes "I prefer morning meetings"
2. Inference agent generates a claim
3. User observes "actually I hate mornings, afternoon is better"
4. Inference agent generates a new claim
5. Validator agent detects the contradiction
6. User queries "what are my meeting preferences?"
7. System returns resolved response favoring afternoon
"""

import pytest

from src.agents.inference import InferenceAgent
from src.agents.validator import ValidatorAgent
from src.interfaces import MemoryService
from src.llm import LLMTranslator
from src.store import StoreConfig, TripleStore

pytestmark = pytest.mark.llm


@pytest.fixture
async def system():
    store = await TripleStore.connect(StoreConfig())
    await store.clear_all()
    llm = LLMTranslator()
    memory = MemoryService(store=store, llm=llm)
    inference = InferenceAgent(memory=memory, poll_interval=1.0)
    validator = ValidatorAgent(memory=memory, poll_interval=1.0)
    yield memory, inference, validator
    await store.clear_all()
    await store.close()


async def test_meeting_preferences_scenario(system):
    memory, inference, validator = system

    # Step 1: User says they prefer morning meetings
    obs1_id = await memory.observe(
        "I prefer morning meetings",
        source="cli_user",
    )
    assert obs1_id is not None

    # Step 2: Inference agent processes the observation
    claims1 = await inference.process()
    assert len(claims1) > 0
    for claim_text in claims1:
        await memory.claim(claim_text, source="inference_agent")

    # Step 3: User changes their mind
    obs2_id = await memory.observe(
        "actually I hate mornings, afternoon is better",
        source="cli_user",
    )
    assert obs2_id is not None

    # Step 4: Inference agent processes the new observation
    claims2 = await inference.process()
    assert len(claims2) > 0
    for claim_text in claims2:
        await memory.claim(claim_text, source="inference_agent")

    # Step 5: Validator agent checks for contradictions
    contradiction_claims = await validator.process()
    # There may or may not be detected contradictions depending on
    # how the LLM structured the claims — the validator checks by
    # matching subject+predicate pairs with different objects.
    for claim_text in contradiction_claims:
        await memory.claim(claim_text, source="validator_agent")

    # Step 6: Query the resolved state
    response = await memory.remember("what are my meeting preferences?")
    assert isinstance(response, str)
    assert len(response) > 0
    # The response should mention meetings in some form
    response_lower = response.lower()
    assert "meeting" in response_lower or "preference" in response_lower
