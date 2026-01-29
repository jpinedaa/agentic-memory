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
    assert len(result.entities) > 0
    assert "user" in [e.lower() for e in result.entities]
    assert len(result.extractions) > 0
    assert len(result.topics) > 0


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
            "type": "Claim",
            "subject_text": "user",
            "predicate_text": "prefers",
            "object_text": "morning meetings",
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
            "type": "Claim",
            "subject_text": "user",
            "predicate_text": "prefers",
            "object_text": "afternoon meetings",
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
