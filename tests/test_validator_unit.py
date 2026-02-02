"""Unit tests for ValidatorAgent with schema-aware contradiction detection."""

import pytest
from unittest.mock import AsyncMock

from src.agents.validator import ValidatorAgent
from src.schema import load_bootstrap_schema


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
