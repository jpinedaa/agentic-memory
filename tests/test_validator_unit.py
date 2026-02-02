"""Unit tests for ValidatorAgent and InferenceAgent with schema-aware features."""

import pytest
from unittest.mock import AsyncMock

from src.agents.validator import ValidatorAgent
from src.agents.inference import InferenceAgent
from src.schema import load_bootstrap_schema, PredicateSchema


@pytest.fixture
def schema():
    return load_bootstrap_schema()


@pytest.fixture
def mock_memory():
    memory = AsyncMock()
    memory.get_recent_statements = AsyncMock(return_value=[])
    memory.flag_contradiction = AsyncMock()
    return memory


@pytest.fixture
def mock_state():
    state = AsyncMock()
    state.is_processed = AsyncMock(return_value=False)
    state.mark_processed = AsyncMock()
    return state


def _stmt(id: str, subject: str, predicate: str, obj: str) -> dict:
    return {
        "id": id,
        "subject_name": subject,
        "predicate": predicate,
        "object_name": obj,
    }


class TestSchemaAwareValidation:

    @pytest.mark.asyncio
    async def test_skips_multi_valued_predicates(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "has_hobby", "chess"),
            _stmt("s2", "alice", "has_hobby", "painting"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        result = await agent.process()
        assert result == []
        mock_memory.flag_contradiction.assert_not_called()

    @pytest.mark.asyncio
    async def test_flags_single_valued_contradiction(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "has_name", "alice"),
            _stmt("s2", "alice", "has_name", "bob"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        result = await agent.process()
        assert result == []
        mock_memory.flag_contradiction.assert_called_once_with(
            "s1", "s2",
            reason="alice has_name: 'alice' vs 'bob'",
        )

    @pytest.mark.asyncio
    async def test_unknown_predicate_treated_as_single(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "unknown_pred", "val1"),
            _stmt("s2", "alice", "unknown_pred", "val2"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        await agent.process()
        mock_memory.flag_contradiction.assert_called_once()

    @pytest.mark.asyncio
    async def test_same_objects_not_flagged(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "has_name", "alice"),
            _stmt("s2", "alice", "has_name", "alice"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        await agent.process()
        mock_memory.flag_contradiction.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_subjects_not_compared(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "has_name", "alice"),
            _stmt("s2", "bob", "has_name", "bob"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        await agent.process()
        mock_memory.flag_contradiction.assert_not_called()


class TestWithoutSchema:

    @pytest.mark.asyncio
    async def test_no_schema_flags_all_diff_objects(
        self, mock_memory, mock_state,
    ):
        """Without schema, all diff-object pairs are flagged (backward compat)."""
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "has_hobby", "chess"),
            _stmt("s2", "alice", "has_hobby", "painting"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=None, state=mock_state,
        )
        await agent.process()
        mock_memory.flag_contradiction.assert_called_once()


class TestIdempotency:

    @pytest.mark.asyncio
    async def test_already_checked_pairs_skipped(
        self, schema, mock_memory, mock_state,
    ):
        mock_state.is_processed.return_value = True
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "has_name", "alice"),
            _stmt("s2", "alice", "has_name", "bob"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        await agent.process()
        mock_memory.flag_contradiction.assert_not_called()

    @pytest.mark.asyncio
    async def test_marks_pair_as_processed(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "has_name", "alice"),
            _stmt("s2", "alice", "has_name", "bob"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        await agent.process()
        mock_state.mark_processed.assert_called_once()


class TestExclusivityGroups:

    @pytest.mark.asyncio
    async def test_flags_exclusivity_violation(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "is_male", "true"),
            _stmt("s2", "alice", "is_female", "true"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        await agent.process()
        mock_memory.flag_contradiction.assert_called_once()
        call_kwargs = mock_memory.flag_contradiction.call_args
        assert "Exclusivity group 'gender'" in call_kwargs.kwargs.get(
            "reason", call_kwargs[1].get("reason", "")
        )

    @pytest.mark.asyncio
    async def test_single_in_exclusivity_group_not_flagged(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "is_female", "true"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        await agent.process()
        mock_memory.flag_contradiction.assert_not_called()


class TestReturnValue:

    @pytest.mark.asyncio
    async def test_always_returns_empty_list(
        self, schema, mock_memory, mock_state,
    ):
        """Validator no longer returns NL claims — it flags directly."""
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "has_name", "alice"),
            _stmt("s2", "alice", "has_name", "bob"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        result = await agent.process()
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_statements_returns_empty(
        self, schema, mock_memory, mock_state,
    ):
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        result = await agent.process()
        assert result == []
        mock_memory.flag_contradiction.assert_not_called()


class TestValidatorHotReload:

    def test_event_types_includes_schema_updated(self, mock_memory):
        agent = ValidatorAgent(memory=mock_memory)
        assert "schema_updated" in agent.event_types()
        assert "claim" in agent.event_types()

    @pytest.mark.asyncio
    async def test_on_network_event_swaps_schema(self, mock_memory):
        schema = load_bootstrap_schema()
        agent = ValidatorAgent(memory=mock_memory, schema=schema)
        assert agent._schema is schema

        new_schema_dict = schema.to_dict()
        new_schema_dict["predicates"]["new_pred"] = {
            "cardinality": "single",
            "temporality": "permanent",
        }
        await agent.on_network_event("schema_updated", {
            "schema": new_schema_dict,
            "version": 1,
        })
        assert agent._schema is not schema
        assert agent._schema.get_info("new_pred") is not None

    @pytest.mark.asyncio
    async def test_on_network_event_ignores_missing_schema(self, mock_memory):
        schema = load_bootstrap_schema()
        agent = ValidatorAgent(memory=mock_memory, schema=schema)
        await agent.on_network_event("schema_updated", {})
        assert agent._schema is schema  # unchanged


class TestInferenceAgent:

    def test_accepts_schema_param(self, mock_memory):
        schema = load_bootstrap_schema()
        agent = InferenceAgent(memory=mock_memory, schema=schema)
        assert agent._schema is schema

    def test_schema_defaults_to_none(self, mock_memory):
        agent = InferenceAgent(memory=mock_memory)
        assert agent._schema is None

    def test_event_types_includes_schema_updated(self, mock_memory):
        agent = InferenceAgent(memory=mock_memory)
        assert "schema_updated" in agent.event_types()
        assert "observe" in agent.event_types()

    @pytest.mark.asyncio
    async def test_on_network_event_swaps_schema(self, mock_memory):
        schema = load_bootstrap_schema()
        agent = InferenceAgent(memory=mock_memory, schema=schema)

        new_schema_dict = schema.to_dict()
        new_schema_dict["predicates"]["inferred_pred"] = {
            "cardinality": "multi",
            "temporality": "temporal",
        }
        await agent.on_network_event("schema_updated", {
            "schema": new_schema_dict,
            "version": 2,
        })
        assert agent._schema is not schema
        assert agent._schema.get_info("inferred_pred") is not None

    @pytest.mark.asyncio
    async def test_on_network_event_ignores_missing_schema(self, mock_memory):
        schema = load_bootstrap_schema()
        agent = InferenceAgent(memory=mock_memory, schema=schema)
        await agent.on_network_event("schema_updated", {})
        assert agent._schema is schema


class TestUnknownPredicateTracking:

    @pytest.mark.asyncio
    async def test_tracks_unknown_predicate(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "invented_pred", "val1"),
            _stmt("s2", "alice", "invented_pred", "val2"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        await agent.process()
        unknowns = agent.get_unknown_predicates()
        assert "invented_pred" in unknowns
        assert unknowns["invented_pred"] == 1

    @pytest.mark.asyncio
    async def test_known_predicate_not_tracked(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "has_name", "alice"),
            _stmt("s2", "alice", "has_name", "bob"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        await agent.process()
        assert agent.get_unknown_predicates() == {}

    @pytest.mark.asyncio
    async def test_no_schema_no_tracking(self, mock_memory, mock_state):
        """Without schema, no tracking occurs."""
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "anything", "val1"),
            _stmt("s2", "alice", "anything", "val2"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=None, state=mock_state,
        )
        await agent.process()
        assert agent.get_unknown_predicates() == {}

    @pytest.mark.asyncio
    async def test_count_accumulates(
        self, schema, mock_memory, mock_state,
    ):
        mock_memory.get_recent_statements.return_value = [
            _stmt("s1", "alice", "invented_pred", "v1"),
            _stmt("s2", "alice", "invented_pred", "v2"),
        ]
        agent = ValidatorAgent(
            memory=mock_memory, schema=schema, state=mock_state,
        )
        await agent.process()
        mock_state.is_processed.return_value = False
        await agent.process()
        assert agent.get_unknown_predicates()["invented_pred"] == 2

    def test_clear_unknown_predicates(self, schema, mock_memory):
        agent = ValidatorAgent(memory=mock_memory, schema=schema)
        agent._unknown_predicates["test"] = 5
        agent.clear_unknown_predicates()
        assert agent.get_unknown_predicates() == {}
