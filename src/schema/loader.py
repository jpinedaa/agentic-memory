"""Schema loader: reads bootstrap YAML and provides predicate lookups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PredicateInfo:
    """Properties of a known predicate."""

    name: str
    cardinality: str  # "single" or "multi"
    temporality: str  # "permanent", "temporal", or "unknown"
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExclusivityGroup:
    """A group of predicates where at most one can be true for a subject."""

    name: str
    predicates: frozenset[str]
    description: str = ""


class PredicateSchema:
    """Lookup interface for predicate metadata.

    Loaded from a YAML file. Provides methods for the validator
    to check predicate properties before flagging contradictions.
    """

    def __init__(
        self,
        predicates: dict[str, PredicateInfo],
        alias_map: dict[str, str],
        exclusivity_groups: list[ExclusivityGroup],
        default_cardinality: str = "single",
        default_temporality: str = "unknown",
    ) -> None:
        self._predicates = predicates
        self._alias_map = alias_map
        self._exclusivity_groups = exclusivity_groups
        self._default_cardinality = default_cardinality
        self._default_temporality = default_temporality

    def normalize_predicate(self, predicate: str) -> str:
        """Resolve aliases to canonical predicate name."""
        normalized = predicate.strip().lower().replace(" ", "_")
        return self._alias_map.get(normalized, normalized)

    def get_info(self, predicate: str) -> PredicateInfo | None:
        """Get predicate info, resolving aliases. Returns None if unknown."""
        canonical = self.normalize_predicate(predicate)
        return self._predicates.get(canonical)

    def is_multi_valued(self, predicate: str) -> bool:
        """Check if a predicate allows multiple values per subject."""
        info = self.get_info(predicate)
        if info is None:
            return self._default_cardinality == "multi"
        return info.cardinality == "multi"

    def is_single_valued(self, predicate: str) -> bool:
        """Check if a predicate allows only one value per subject."""
        return not self.is_multi_valued(predicate)

    def get_exclusivity_group(self, predicate: str) -> ExclusivityGroup | None:
        """Find the exclusivity group containing this predicate, if any."""
        canonical = self.normalize_predicate(predicate)
        for group in self._exclusivity_groups:
            if canonical in group.predicates:
                return group
        return None

    def known_predicates(self) -> list[str]:
        """Return all known canonical predicate names."""
        return list(self._predicates.keys())


def load_bootstrap_schema(path: Path | None = None) -> PredicateSchema:
    """Load the bootstrap schema from YAML.

    If no path is given, loads from src/schema/bootstrap.yaml.
    """
    if path is None:
        path = Path(__file__).parent / "bootstrap.yaml"

    with open(path) as f:
        data = yaml.safe_load(f)

    defaults = data.get("defaults", {})
    default_cardinality = defaults.get("cardinality", "single")
    default_temporality = defaults.get("temporality", "unknown")

    predicates: dict[str, PredicateInfo] = {}
    alias_map: dict[str, str] = {}

    for name, props in data.get("predicates", {}).items():
        canonical = name.strip().lower()
        aliases = tuple(a.strip().lower() for a in props.get("aliases", []))
        info = PredicateInfo(
            name=canonical,
            cardinality=props.get("cardinality", default_cardinality),
            temporality=props.get("temporality", default_temporality),
            aliases=aliases,
        )
        predicates[canonical] = info
        for alias in aliases:
            alias_map[alias] = canonical

    exclusivity_groups: list[ExclusivityGroup] = []
    for group_name, group_data in data.get("exclusivity_groups", {}).items():
        group = ExclusivityGroup(
            name=group_name,
            predicates=frozenset(
                p.strip().lower() for p in group_data.get("predicates", [])
            ),
            description=group_data.get("description", ""),
        )
        exclusivity_groups.append(group)

    return PredicateSchema(
        predicates=predicates,
        alias_map=alias_map,
        exclusivity_groups=exclusivity_groups,
        default_cardinality=default_cardinality,
        default_temporality=default_temporality,
    )
