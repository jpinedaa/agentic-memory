"""Tests for the bootstrap predicate schema."""

import pytest

from src.schema.loader import (
    PredicateSchema,
    PredicateInfo,
    ExclusivityGroup,
    load_bootstrap_schema,
)


@pytest.fixture
def schema():
    return load_bootstrap_schema()


class TestLoadBootstrapSchema:

    def test_loads_predicates(self, schema):
        assert len(schema.known_predicates()) > 0

    def test_known_predicates_include_expected(self, schema):
        names = schema.known_predicates()
        assert "has_name" in names
        assert "has_hobby" in names
        assert "lives_in" in names


class TestCardinality:

    def test_multi_valued_hobby(self, schema):
        assert schema.is_multi_valued("has_hobby") is True

    def test_multi_valued_language(self, schema):
        assert schema.is_multi_valued("speaks_language") is True

    def test_multi_valued_skill(self, schema):
        assert schema.is_multi_valued("has_skill") is True

    def test_single_valued_name(self, schema):
        assert schema.is_single_valued("has_name") is True

    def test_single_valued_born_in(self, schema):
        assert schema.is_single_valued("born_in") is True

    def test_single_valued_lives_in(self, schema):
        assert schema.is_single_valued("lives_in") is True

    def test_unknown_predicate_defaults_to_single(self, schema):
        assert schema.is_single_valued("completely_unknown_pred") is True
        assert schema.is_multi_valued("completely_unknown_pred") is False


class TestAliases:

    def test_resolve_alias(self, schema):
        assert schema.normalize_predicate("is_called") == "has_name"
        assert schema.normalize_predicate("was_born_in") == "born_in"

    def test_alias_lookup_returns_canonical_info(self, schema):
        info = schema.get_info("is_called")
        assert info is not None
        assert info.name == "has_name"
        assert info.cardinality == "single"

    def test_alias_cardinality_check(self, schema):
        assert schema.is_single_valued("is_called") is True
        assert schema.is_multi_valued("enjoys") is True

    def test_unknown_alias_returns_self(self, schema):
        assert schema.normalize_predicate("something_new") == "something_new"


class TestNormalization:

    def test_spaces_replaced_with_underscores(self, schema):
        assert schema.normalize_predicate("has name") == "has_name"

    def test_leading_trailing_whitespace(self, schema):
        assert schema.normalize_predicate(" has_name ") == "has_name"

    def test_case_insensitive(self, schema):
        assert schema.normalize_predicate("Has_Name") == "has_name"


class TestExclusivityGroups:

    def test_gender_group(self, schema):
        group = schema.get_exclusivity_group("is_male")
        assert group is not None
        assert group.name == "gender"
        assert "is_female" in group.predicates
        assert "is_non_binary" in group.predicates

    def test_no_group_for_hobby(self, schema):
        assert schema.get_exclusivity_group("has_hobby") is None

    def test_no_group_for_unknown(self, schema):
        assert schema.get_exclusivity_group("unknown_pred") is None


class TestGetInfo:

    def test_known_predicate(self, schema):
        info = schema.get_info("has_name")
        assert info is not None
        assert info.name == "has_name"
        assert info.cardinality == "single"
        assert info.temporality == "permanent"

    def test_unknown_predicate(self, schema):
        assert schema.get_info("nonexistent") is None

    def test_temporal_predicate(self, schema):
        info = schema.get_info("lives_in")
        assert info is not None
        assert info.temporality == "temporal"

    def test_provenance_defaults(self, schema):
        info = schema.get_info("has_name")
        assert info is not None
        assert info.origin == "bootstrap"
        assert info.reasoning is None
        assert info.last_reviewed is None


class TestSerialization:

    def test_round_trip(self, schema):
        data = schema.to_dict()
        restored = PredicateSchema.from_dict(data)
        assert restored.known_predicates() == schema.known_predicates()
        assert restored.is_multi_valued("has_hobby") is True
        assert restored.is_single_valued("has_name") is True
        assert restored.normalize_predicate("is_called") == "has_name"

    def test_round_trip_preserves_exclusivity_groups(self, schema):
        data = schema.to_dict()
        restored = PredicateSchema.from_dict(data)
        group = restored.get_exclusivity_group("is_male")
        assert group is not None
        assert group.name == "gender"
        assert "is_female" in group.predicates

    def test_from_dict_bootstrap_format(self):
        """from_dict accepts dicts without provenance fields."""
        data = {
            "defaults": {"cardinality": "single", "temporality": "unknown"},
            "predicates": {
                "has_name": {
                    "cardinality": "single",
                    "temporality": "permanent",
                    "aliases": ["is_called"],
                },
            },
            "exclusivity_groups": {},
        }
        schema = PredicateSchema.from_dict(data)
        info = schema.get_info("has_name")
        assert info is not None
        assert info.origin == "bootstrap"
        assert info.reasoning is None
        assert schema.normalize_predicate("is_called") == "has_name"

    def test_from_dict_dynamic_format(self):
        """from_dict preserves provenance fields."""
        data = {
            "predicates": {
                "mentors": {
                    "cardinality": "multi",
                    "temporality": "unknown",
                    "origin": "learned",
                    "reasoning": "Observed multiple mentoring relationships",
                    "last_reviewed": "2026-02-02T14:30:00Z",
                },
            },
        }
        schema = PredicateSchema.from_dict(data)
        info = schema.get_info("mentors")
        assert info is not None
        assert info.cardinality == "multi"
        assert info.origin == "learned"
        assert info.reasoning == "Observed multiple mentoring relationships"
        assert info.last_reviewed == "2026-02-02T14:30:00Z"

    def test_to_dict_omits_default_provenance(self, schema):
        """to_dict omits origin/reasoning when they are defaults."""
        data = schema.to_dict()
        # Bootstrap predicates should not have origin key (it's the default)
        assert "origin" not in data["predicates"]["has_name"]
        assert "reasoning" not in data["predicates"]["has_name"]

    def test_to_dict_includes_learned_provenance(self):
        """to_dict includes origin/reasoning for learned predicates."""
        data = {
            "predicates": {
                "mentors": {
                    "cardinality": "multi",
                    "temporality": "unknown",
                    "origin": "learned",
                    "reasoning": "Multi-valued by nature",
                },
            },
        }
        schema = PredicateSchema.from_dict(data)
        exported = schema.to_dict()
        assert exported["predicates"]["mentors"]["origin"] == "learned"
        assert exported["predicates"]["mentors"]["reasoning"] == "Multi-valued by nature"
