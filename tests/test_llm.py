"""Tests for the LLM translation layer.

These tests call the real Claude API. Set ANTHROPIC_API_KEY to run them.
Skip with: pytest -m "not llm"
"""
# pylint: disable=missing-function-docstring  # test names are self-documenting
# pylint: disable=redefined-outer-name  # pytest fixture injection pattern

import pytest

from src.llm import LLMTranslator

pytestmark = pytest.mark.llm


@pytest.fixture
def translator():
    return LLMTranslator()


async def test_extract_observation(translator: LLMTranslator):
    result = await translator.extract_observation(
        "user said they hate waking up early for meetings"
    )
    assert len(result.concepts) > 0
    concept_names = [c.name.lower() for c in result.concepts]
    assert any("user" in n for n in concept_names)
    assert len(result.statements) > 0
    assert len(result.topics) > 0


async def test_extract_observation_concepts_have_kind(translator: LLMTranslator):
    result = await translator.extract_observation(
        "bitcoin is a peer-to-peer network"
    )
    assert len(result.concepts) > 0
    for concept in result.concepts:
        assert concept.kind in ("entity", "attribute", "value", "category", "action")


async def test_parse_claim(translator: LLMTranslator):
    result = await translator.parse_claim(
        "based on their statement about early meetings, user prefers afternoon meetings"
    )
    assert result.subject.lower() == "user"
    assert "prefer" in result.predicate.lower() or "afternoon" in result.object.lower()
    assert 0.0 <= result.confidence <= 1.0


async def test_parse_claim_with_contradiction(translator: LLMTranslator):
    context = [
        {
            "node_kind": "statement",
            "subject_name": "user",
            "predicate": "prefers",
            "object_name": "morning meetings",
            "confidence": 0.7,
        }
    ]
    result = await translator.parse_claim(
        "the claim that user prefers morning meetings contradicts the observation that user hates early meetings",
        context=context,
    )
    assert result.contradicts_description is not None


async def test_generate_query(translator: LLMTranslator):
    cypher = await translator.generate_query("what are the user's meeting preferences?")
    assert isinstance(cypher, str)
    assert "MATCH" in cypher.upper() or "match" in cypher.lower()


async def test_synthesize_response(translator: LLMTranslator):
    results = [
        {
            "node_kind": "statement",
            "subject_name": "user",
            "predicate": "prefers",
            "object_name": "afternoon meetings",
            "confidence": 0.85,
            "source": "inference_agent",
        }
    ]
    response = await translator.synthesize_response(
        "what are the user's meeting preferences?", results
    )
    assert isinstance(response, str)
    assert len(response) > 10
    assert "afternoon" in response.lower()
