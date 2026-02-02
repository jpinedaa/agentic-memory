"""Tests for the prompt template system."""
# pylint: disable=missing-function-docstring  # test names are self-documenting
# pylint: disable=redefined-builtin  # test var `vars` shadows builtin; harmless in test scope
# pylint: disable=redefined-outer-name  # pytest fixture injection pattern

import pytest

from src.prompts import (
    PromptLoader,
    PromptTemplate,
    ObservationVars,
    ClaimVars,
    InferenceVars,
    SynthesisVars,
)


@pytest.fixture
def loader():
    return PromptLoader()


def test_load_prompt(loader: PromptLoader):
    """Load a prompt by path."""
    prompt = loader.load("inference_agent/infer")
    assert isinstance(prompt, PromptTemplate)
    assert prompt.name == "inference"
    assert prompt.version == "1.1"


def test_prompt_not_found(loader: PromptLoader):
    """FileNotFoundError for missing prompt."""
    with pytest.raises(FileNotFoundError):
        loader.load("nonexistent/prompt")


def test_list_prompts(loader: PromptLoader):
    """List all available prompt paths."""
    prompts = loader.list_prompts()
    assert isinstance(prompts, list)
    assert "inference_agent/infer" in prompts
    assert "llm_translator/observation" in prompts
    assert "shared/base" in prompts


def test_inheritance(loader: PromptLoader):
    """Child prompt inherits from parent."""
    prompt = loader.load("llm_translator/observation")
    rendered = prompt.render()

    # Should contain constraints from shared/base
    assert "Never invent information" in rendered["system"]
    # Should also contain observation-specific content
    assert "knowledge extraction" in rendered["system"].lower()


def test_render_with_pydantic_vars(loader: PromptLoader):
    """Render with typed Pydantic model."""
    prompt = loader.load("inference_agent/infer")
    vars = InferenceVars(observation_text="user likes pizza")
    rendered = prompt.render(vars)

    assert "user likes pizza" in rendered["user"]


def test_render_with_dict_vars(loader: PromptLoader):
    """Render with plain dict."""
    prompt = loader.load("inference_agent/infer")
    rendered = prompt.render({"observation_text": "user likes pizza"})

    assert "user likes pizza" in rendered["user"]


def test_jinja2_conditionals(loader: PromptLoader):
    """{% if %} blocks render correctly."""
    prompt = loader.load("inference_agent/infer")

    # Without reasoning
    vars_no_reasoning = InferenceVars(
        observation_text="test",
        include_reasoning=False
    )
    rendered = prompt.render(vars_no_reasoning)
    assert "Reasoning Mode" not in rendered["user"]

    # With reasoning
    vars_with_reasoning = InferenceVars(
        observation_text="test",
        include_reasoning=True
    )
    rendered = prompt.render(vars_with_reasoning)
    assert "Reasoning Mode" in rendered["user"]


def test_jinja2_loops(loader: PromptLoader):
    """{% for %} blocks render correctly."""
    prompt = loader.load("llm_translator/claim")
    vars = ClaimVars(
        claim_text="user prefers morning",
        context=[
            {"node_kind": "observation", "raw_content": "user said morning is best"},
            {"node_kind": "statement", "subject_name": "user", "predicate": "likes", "object_name": "coffee"},
        ]
    )
    rendered = prompt.render(vars)

    assert "user said morning is best" in rendered["user"]
    assert "user likes coffee" in rendered["user"]


def test_render_system_only(loader: PromptLoader):
    """render_system() returns only system prompt."""
    prompt = loader.load("llm_translator/observation")
    system = prompt.render_system()

    assert isinstance(system, str)
    assert "knowledge extraction" in system.lower()


def test_render_user_only(loader: PromptLoader):
    """render_user() returns only user prompt."""
    prompt = loader.load("inference_agent/infer")
    vars = InferenceVars(observation_text="test observation")
    user = prompt.render_user(vars)

    assert isinstance(user, str)
    assert "test observation" in user


def test_observation_vars_validation():
    """ObservationVars validates input."""
    # Valid
    vars = ObservationVars(observation_text="hello")
    assert vars.observation_text == "hello"

    # Missing required field
    with pytest.raises(ValueError):
        ObservationVars()


def test_inference_vars_defaults():
    """InferenceVars has correct defaults."""
    vars = InferenceVars(observation_text="test")
    assert vars.observation_text == "test"
    assert vars.observation_id == ""
    assert vars.include_reasoning is False
    assert vars.predicate_hints == ""
    assert vars.confidence_priors == ""
    assert vars.exclusivity_warnings == ""


def test_claim_vars_defaults():
    """ClaimVars schema fields default to empty string."""
    vars = ClaimVars(claim_text="test")
    assert vars.normalization_hints == ""
    assert vars.confidence_priors == ""


def test_synthesis_vars_with_results():
    """SynthesisVars handles result list."""
    vars = SynthesisVars(
        query="what does user like?",
        results=[{"node_kind": "statement", "predicate": "likes", "object_name": "pizza"}]
    )
    assert vars.query == "what does user like?"
    assert len(vars.results) == 1


class TestSchemaContextInPrompts:

    def test_inference_with_schema_context(self, loader: PromptLoader):
        """Schema context sections render in inference prompt."""
        vars = InferenceVars(
            observation_text="user likes chess",
            predicate_hints="- has_hobby (multi-valued, temporal)",
            confidence_priors="- Temporal predicates: moderate confidence",
            exclusivity_warnings="- gender: is_male, is_female",
        )
        prompt = loader.load("inference_agent/infer")
        rendered = prompt.render(vars)
        assert "Known Predicates" in rendered["user"]
        assert "has_hobby" in rendered["user"]
        assert "Mutual Exclusivity" in rendered["user"]
        assert "Confidence Guidance" in rendered["user"]

    def test_inference_empty_schema_no_sections(self, loader: PromptLoader):
        """Empty schema context omits all schema sections."""
        vars = InferenceVars(observation_text="test")
        prompt = loader.load("inference_agent/infer")
        rendered = prompt.render(vars)
        assert "Known Predicates" not in rendered["user"]
        assert "Mutual Exclusivity" not in rendered["user"]
        assert "Confidence Guidance" not in rendered["user"]

    def test_claim_with_schema_context(self, loader: PromptLoader):
        """Schema context sections render in claim prompt."""
        vars = ClaimVars(
            claim_text="alice has name alice",
            normalization_hints='- has_name: also known as "is_called"',
            confidence_priors="- Permanent predicates: use higher confidence",
        )
        prompt = loader.load("llm_translator/claim")
        rendered = prompt.render(vars)
        assert "Predicate Normalization" in rendered["system"]
        assert "is_called" in rendered["system"]
        assert "confidence guidance" in rendered["system"].lower()

    def test_claim_empty_schema_no_sections(self, loader: PromptLoader):
        """Empty schema context omits schema sections from claim prompt."""
        vars = ClaimVars(claim_text="test")
        prompt = loader.load("llm_translator/claim")
        rendered = prompt.render(vars)
        assert "Predicate Normalization" not in rendered["system"]
