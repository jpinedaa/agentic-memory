"""Tests for the SchemaCompiler — renders PredicateSchema into prompt fragments."""

import pytest

from src.schema import SchemaCompiler, PredicateSchema, load_bootstrap_schema
from src.prompts import PromptLoader, InferenceVars, ClaimVars


@pytest.fixture
def schema():
    return load_bootstrap_schema()


@pytest.fixture
def compiler(schema):
    return SchemaCompiler(schema)


@pytest.fixture
def empty_schema():
    return PredicateSchema(
        predicates={}, alias_map={}, exclusivity_groups=[],
    )


class TestPredicateHints:
    def test_includes_known_predicates(self, compiler, schema):
        hints = compiler.predicate_hints()
        for pred in schema.known_predicates():
            assert pred in hints

    def test_shows_cardinality(self, compiler):
        hints = compiler.predicate_hints()
        assert "single-valued" in hints
        assert "multi-valued" in hints

    def test_shows_temporality(self, compiler):
        hints = compiler.predicate_hints()
        assert "permanent" in hints
        assert "temporal" in hints

    def test_empty_schema(self, empty_schema):
        compiler = SchemaCompiler(empty_schema)
        assert compiler.predicate_hints() == ""


class TestNormalizationHints:
    def test_includes_aliases(self, compiler):
        hints = compiler.normalization_hints()
        assert "has_name" in hints
        assert "is_called" in hints

    def test_skips_predicates_without_aliases(self, compiler, schema):
        hints = compiler.normalization_hints()
        # Predicates with no aliases should not appear in normalization hints
        for name, info in schema.predicates.items():
            if not info.aliases:
                # Should not have a line starting with "- {name}:"
                assert f"- {name}:" not in hints

    def test_empty_schema(self, empty_schema):
        compiler = SchemaCompiler(empty_schema)
        assert compiler.normalization_hints() == ""


class TestConfidencePriors:
    def test_groups_by_temporality(self, compiler):
        priors = compiler.confidence_priors()
        assert "Permanent predicates" in priors
        assert "Temporal predicates" in priors

    def test_permanent_predicates_listed(self, compiler):
        priors = compiler.confidence_priors()
        assert "has_name" in priors
        assert "born_in" in priors

    def test_temporal_predicates_listed(self, compiler):
        priors = compiler.confidence_priors()
        assert "lives_in" in priors

    def test_empty_schema(self, empty_schema):
        compiler = SchemaCompiler(empty_schema)
        assert compiler.confidence_priors() == ""


class TestExclusivityWarnings:
    def test_lists_groups(self, compiler):
        warnings = compiler.exclusivity_warnings()
        assert "gender" in warnings
        assert "marital_status" in warnings

    def test_lists_group_members(self, compiler):
        warnings = compiler.exclusivity_warnings()
        assert "is_male" in warnings
        assert "is_female" in warnings

    def test_empty_schema(self, empty_schema):
        compiler = SchemaCompiler(empty_schema)
        assert compiler.exclusivity_warnings() == ""


class TestBundles:
    def test_for_inference_keys(self, compiler):
        result = compiler.for_inference()
        assert set(result.keys()) == {
            "predicate_hints", "confidence_priors", "exclusivity_warnings",
        }
        assert all(isinstance(v, str) for v in result.values())

    def test_for_claim_parser_keys(self, compiler):
        result = compiler.for_claim_parser()
        assert set(result.keys()) == {
            "normalization_hints", "confidence_priors",
        }
        assert all(isinstance(v, str) for v in result.values())

    def test_for_inference_non_empty(self, compiler):
        result = compiler.for_inference()
        assert all(v for v in result.values())

    def test_for_claim_parser_non_empty(self, compiler):
        result = compiler.for_claim_parser()
        assert all(v for v in result.values())


class TestPromptIntegration:
    """Verify compiled schema context renders correctly in actual prompts."""

    @pytest.fixture
    def loader(self):
        return PromptLoader()

    def test_for_inference_renders_in_prompt(self, compiler, loader):
        ctx = compiler.for_inference()
        vars = InferenceVars(observation_text="user likes chess", **ctx)
        prompt = loader.load("inference_agent/infer")
        rendered = prompt.render(vars)
        assert "Known Predicates" in rendered["user"]
        assert "has_name" in rendered["user"]
        assert "Confidence Guidance" in rendered["user"]
        assert "Mutual Exclusivity" in rendered["user"]

    def test_for_claim_renders_in_prompt(self, compiler, loader):
        ctx = compiler.for_claim_parser()
        vars = ClaimVars(claim_text="alice has name alice", **ctx)
        prompt = loader.load("llm_translator/claim")
        rendered = prompt.render(vars)
        assert "Predicate Normalization" in rendered["system"]
        assert "has_name" in rendered["system"]

    def test_empty_context_no_schema_sections(self, empty_schema, loader):
        compiler = SchemaCompiler(empty_schema)
        ctx = compiler.for_inference()
        vars = InferenceVars(observation_text="test", **ctx)
        prompt = loader.load("inference_agent/infer")
        rendered = prompt.render(vars)
        assert "Known Predicates" not in rendered["user"]
        assert "Mutual Exclusivity" not in rendered["user"]
