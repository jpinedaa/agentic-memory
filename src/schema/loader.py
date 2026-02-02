"""Schema loader: reads bootstrap YAML and provides predicate lookups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PredicateInfo:
    """Properties of a known predicate."""

    name: str
    cardinality: str  # "single" or "multi"
    temporality: str  # "permanent", "temporal", or "unknown"
    aliases: tuple[str, ...] = ()
    origin: str = "bootstrap"  # "bootstrap" or "learned"
    reasoning: str | None = None  # LLM rationale for current values
    last_reviewed: str | None = None  # ISO 8601 timestamp


@dataclass(frozen=True)
class ExclusivityGroup:
    """A group of predicates where at most one can be true for a subject."""

    name: str
    predicates: frozenset[str]
    description: str = ""
    origin: str = "bootstrap"
    reasoning: str | None = None


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

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict matching the YAML schema format."""
        predicates: dict[str, dict[str, Any]] = {}
        for name, info in self._predicates.items():
            entry: dict[str, Any] = {
                "cardinality": info.cardinality,
                "temporality": info.temporality,
            }
            if info.aliases:
                entry["aliases"] = list(info.aliases)
            if info.origin != "bootstrap":
                entry["origin"] = info.origin
            if info.reasoning is not None:
                entry["reasoning"] = info.reasoning
            if info.last_reviewed is not None:
                entry["last_reviewed"] = info.last_reviewed
            predicates[name] = entry

        groups: dict[str, dict[str, Any]] = {}
        for group in self._exclusivity_groups:
            entry = {
                "predicates": sorted(group.predicates),
            }
            if group.description:
                entry["description"] = group.description
            if group.origin != "bootstrap":
                entry["origin"] = group.origin
            if group.reasoning is not None:
                entry["reasoning"] = group.reasoning
            groups[group.name] = entry

        return {
            "defaults": {
                "cardinality": self._default_cardinality,
                "temporality": self._default_temporality,
            },
            "predicates": predicates,
            "exclusivity_groups": groups,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PredicateSchema:
        """Deserialize from a dict (YAML-loaded or event payload).

        Accepts both bootstrap format (no provenance fields) and
        dynamic format (with origin, reasoning, etc.).
        """
        defaults = data.get("defaults", {})
        default_cardinality = defaults.get("cardinality", "single")
        default_temporality = defaults.get("temporality", "unknown")

        predicates: dict[str, PredicateInfo] = {}
        alias_map: dict[str, str] = {}

        for name, props in data.get("predicates", {}).items():
            canonical = name.strip().lower()
            aliases = tuple(
                a.strip().lower() for a in props.get("aliases", [])
            )
            info = PredicateInfo(
                name=canonical,
                cardinality=props.get("cardinality", default_cardinality),
                temporality=props.get("temporality", default_temporality),
                aliases=aliases,
                origin=props.get("origin", "bootstrap"),
                reasoning=props.get("reasoning"),
                last_reviewed=props.get("last_reviewed"),
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
                origin=group_data.get("origin", "bootstrap"),
                reasoning=group_data.get("reasoning"),
            )
            exclusivity_groups.append(group)

        return cls(
            predicates=predicates,
            alias_map=alias_map,
            exclusivity_groups=exclusivity_groups,
            default_cardinality=default_cardinality,
            default_temporality=default_temporality,
        )


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
