"""Tests for SchemaStore: persistent schema management."""

from pathlib import Path

import pytest
import yaml

from src.schema.store import SchemaStore


@pytest.fixture
def bootstrap_path():
    return Path(__file__).parent.parent / "src" / "schema" / "bootstrap.yaml"


async def _make_store(tmp_path, bootstrap_path):
    schema_path = tmp_path / "schema.yaml"
    s = SchemaStore(schema_path, bootstrap_path)
    await s.load()
    return s


class TestBootstrapSeeding:

    @pytest.mark.asyncio
    async def test_seeds_from_bootstrap(self, tmp_path, bootstrap_path):
        schema_path = tmp_path / "schema.yaml"
        assert not schema_path.exists()
        s = SchemaStore(schema_path, bootstrap_path)
        await s.load()
        assert schema_path.exists()

    @pytest.mark.asyncio
    async def test_seeded_file_has_version(self, tmp_path, bootstrap_path):
        await _make_store(tmp_path, bootstrap_path)
        data = yaml.safe_load((tmp_path / "schema.yaml").read_text())
        assert data["schema_version"] == 0
        assert data["updated_by"] == "bootstrap"

    @pytest.mark.asyncio
    async def test_seeded_predicates_have_provenance(self, tmp_path, bootstrap_path):
        await _make_store(tmp_path, bootstrap_path)
        data = yaml.safe_load((tmp_path / "schema.yaml").read_text())
        has_name = data["predicates"]["has_name"]
        assert has_name["origin"] == "bootstrap"

    @pytest.mark.asyncio
    async def test_schema_property(self, tmp_path, bootstrap_path):
        store = await _make_store(tmp_path, bootstrap_path)
        assert len(store.schema.known_predicates()) > 0
        assert store.schema.is_single_valued("has_name")

    @pytest.mark.asyncio
    async def test_version_property(self, tmp_path, bootstrap_path):
        store = await _make_store(tmp_path, bootstrap_path)
        assert store.version == 0


class TestLoadExisting:

    @pytest.mark.asyncio
    async def test_loads_existing_file(self, tmp_path, bootstrap_path):
        schema_path = tmp_path / "schema.yaml"
        data = {
            "schema_version": 5,
            "updated_by": "schema_agent",
            "defaults": {"cardinality": "single", "temporality": "unknown"},
            "predicates": {
                "mentors": {
                    "cardinality": "multi",
                    "temporality": "unknown",
                    "origin": "learned",
                    "reasoning": "Multi-valued by nature",
                },
            },
            "exclusivity_groups": {},
        }
        with open(schema_path, "w") as f:
            yaml.dump(data, f)

        s = SchemaStore(schema_path, bootstrap_path)
        await s.load()
        assert s.version == 5
        assert s.schema.is_multi_valued("mentors")
        info = s.schema.get_info("mentors")
        assert info.origin == "learned"

    @pytest.mark.asyncio
    async def test_corrupt_file_falls_back_to_bootstrap(
        self, tmp_path, bootstrap_path
    ):
        schema_path = tmp_path / "schema.yaml"
        schema_path.write_text("{{{{invalid yaml")
        s = SchemaStore(schema_path, bootstrap_path)
        await s.load()
        assert s.version == 0
        assert len(s.schema.known_predicates()) > 0


class TestUpdate:

    @pytest.mark.asyncio
    async def test_add_new_predicate(self, tmp_path, bootstrap_path):
        store = await _make_store(tmp_path, bootstrap_path)
        result = store.update(
            {"predicates": {"mentors": {"cardinality": "multi", "temporality": "unknown"}}},
            source="test",
        )
        assert store.schema.is_multi_valued("mentors")
        assert result["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_modify_existing_predicate(self, tmp_path, bootstrap_path):
        store = await _make_store(tmp_path, bootstrap_path)
        store.update(
            {"predicates": {"has_name": {"cardinality": "multi"}}},
            source="test",
        )
        assert store.schema.is_multi_valued("has_name")
        info = store.schema.get_info("has_name")
        assert info.temporality == "permanent"

    @pytest.mark.asyncio
    async def test_version_increments(self, tmp_path, bootstrap_path):
        store = await _make_store(tmp_path, bootstrap_path)
        assert store.version == 0
        store.update({"predicates": {"x": {"cardinality": "single"}}}, "test")
        assert store.version == 1
        store.update({"predicates": {"y": {"cardinality": "multi"}}}, "test")
        assert store.version == 2

    @pytest.mark.asyncio
    async def test_updated_by_and_timestamp(self, tmp_path, bootstrap_path):
        store = await _make_store(tmp_path, bootstrap_path)
        result = store.update(
            {"predicates": {"z": {"cardinality": "single"}}},
            source="schema_agent",
        )
        assert result["updated_by"] == "schema_agent"
        assert "updated_at" in result

    @pytest.mark.asyncio
    async def test_add_exclusivity_group(self, tmp_path, bootstrap_path):
        store = await _make_store(tmp_path, bootstrap_path)
        store.update(
            {"exclusivity_groups": {
                "test_group": {
                    "predicates": ["pred_a", "pred_b"],
                    "description": "Test group",
                    "origin": "learned",
                },
            }},
            source="test",
        )
        group = store.schema.get_exclusivity_group("pred_a")
        assert group is not None
        assert group.name == "test_group"

    @pytest.mark.asyncio
    async def test_persists_to_file(self, tmp_path, bootstrap_path):
        store = await _make_store(tmp_path, bootstrap_path)
        store.update(
            {"predicates": {"mentors": {"cardinality": "multi"}}},
            source="test",
        )
        data = yaml.safe_load((tmp_path / "schema.yaml").read_text())
        assert "mentors" in data["predicates"]
        assert data["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_to_dict_matches_state(self, tmp_path, bootstrap_path):
        store = await _make_store(tmp_path, bootstrap_path)
        store.update(
            {"predicates": {"foo": {"cardinality": "multi"}}},
            source="test",
        )
        d = store.to_dict()
        assert d["schema_version"] == 1
        assert "foo" in d["predicates"]

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path, bootstrap_path):
        schema_path = tmp_path / "nested" / "dir" / "schema.yaml"
        s = SchemaStore(schema_path, bootstrap_path)
        await s.load()
        assert schema_path.exists()
