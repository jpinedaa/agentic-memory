"""Persistent schema manager for the store node.

Loads schema from a YAML file, supports atomic updates with versioning,
and provides the current PredicateSchema for consumer lookups.
Schema lives outside Neo4j — it's meta-knowledge about how to interpret
domain knowledge, not domain knowledge itself.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.schema.loader import PredicateSchema

logger = logging.getLogger(__name__)


class SchemaStore:
    """Persistent schema manager for the store node.

    Loads schema from a YAML file on startup (seeding from bootstrap
    on first run), supports incremental updates with versioning,
    and rebuilds the PredicateSchema on every change.
    """

    def __init__(
        self,
        path: Path,
        bootstrap_path: Path | None = None,
    ) -> None:
        self._path = path
        self._bootstrap_path = bootstrap_path or (
            Path(__file__).parent / "bootstrap.yaml"
        )
        self._data: dict[str, Any] = {}
        self._schema: PredicateSchema | None = None

    async def load(self) -> None:
        """Load schema from file. If file doesn't exist, seed from bootstrap."""
        if self._path.exists():
            try:
                self._data = self._read_yaml(self._path)
                self._schema = PredicateSchema.from_dict(self._data)
                logger.info(
                    "Loaded schema v%s from %s (%d predicates)",
                    self._data.get("schema_version", 0),
                    self._path,
                    len(self._schema.known_predicates()),
                )
                return
            except Exception:
                logger.exception(
                    "Failed to load schema from %s, falling back to bootstrap",
                    self._path,
                )

        # Seed from bootstrap
        self._seed_from_bootstrap()

    @property
    def schema(self) -> PredicateSchema:
        """Current PredicateSchema instance for runtime lookups."""
        if self._schema is None:
            raise RuntimeError("SchemaStore not loaded — call load() first")
        return self._schema

    @property
    def version(self) -> int:
        """Current schema version number."""
        return self._data.get("schema_version", 0)

    def to_dict(self) -> dict[str, Any]:
        """Serialize full schema state to a dict."""
        return dict(self._data)

    def update(self, changes: dict[str, Any], source: str) -> dict[str, Any]:
        """Apply incremental changes, increment version, persist to file.

        Args:
            changes: Partial schema dict. Can contain:
                - "predicates": {name: {cardinality, temporality, aliases, ...}}
                - "exclusivity_groups": {name: {predicates, description, ...}}
                - "defaults": {cardinality, temporality}
            source: Who made the change (e.g. "schema_agent", "admin").

        Returns:
            Full schema dict after update (same format as to_dict).
        """
        # Merge predicates
        if "predicates" in changes:
            existing = self._data.setdefault("predicates", {})
            for name, props in changes["predicates"].items():
                canonical = name.strip().lower()
                if canonical in existing:
                    # Merge field-by-field, preserving unset fields
                    existing[canonical].update(props)
                else:
                    existing[canonical] = dict(props)

        # Merge exclusivity groups (replace entire group)
        if "exclusivity_groups" in changes:
            existing = self._data.setdefault("exclusivity_groups", {})
            for group_name, group_data in changes["exclusivity_groups"].items():
                existing[group_name] = dict(group_data)

        # Merge defaults
        if "defaults" in changes:
            self._data["defaults"] = dict(changes["defaults"])

        # Update metadata
        self._data["schema_version"] = self.version + 1
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._data["updated_by"] = source

        # Rebuild PredicateSchema and persist
        self._schema = PredicateSchema.from_dict(self._data)
        self._persist()

        logger.info(
            "Schema updated to v%s by %s (%d predicates)",
            self.version, source, len(self._schema.known_predicates()),
        )

        return self.to_dict()

    def _seed_from_bootstrap(self) -> None:
        """Seed schema from bootstrap YAML, adding provenance fields."""
        bootstrap_data = self._read_yaml(self._bootstrap_path)

        # Add provenance to all predicates
        for props in bootstrap_data.get("predicates", {}).values():
            props.setdefault("origin", "bootstrap")
            props.setdefault("reasoning", None)
            props.setdefault("last_reviewed", None)

        # Add provenance to all exclusivity groups
        for group_data in bootstrap_data.get("exclusivity_groups", {}).values():
            group_data.setdefault("origin", "bootstrap")
            group_data.setdefault("reasoning", None)

        # Add top-level metadata
        bootstrap_data["schema_version"] = 0
        bootstrap_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        bootstrap_data["updated_by"] = "bootstrap"

        self._data = bootstrap_data
        self._schema = PredicateSchema.from_dict(self._data)
        self._persist()

        logger.info(
            "Seeded schema from bootstrap (%d predicates)",
            len(self._schema.known_predicates()),
        )

    def _persist(self) -> None:
        """Write current schema state to YAML file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            yaml.dump(self._data, f, default_flow_style=False, sort_keys=False)

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        """Read and parse a YAML file."""
        with open(path) as f:
            return yaml.safe_load(f) or {}
