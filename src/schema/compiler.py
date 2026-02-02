"""Schema compiler: renders PredicateSchema into prompt-ready text fragments."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.schema.loader import PredicateSchema


class SchemaCompiler:
    """Compiles a PredicateSchema into formatted text fragments for LLM prompts.

    Each method returns a string suitable for injection into a Jinja2 template.
    Returns empty string when there's nothing to render.
    """

    def __init__(self, schema: PredicateSchema) -> None:
        self._schema = schema

    def predicate_hints(self) -> str:
        """Known predicates with cardinality/temporality annotations.

        For the inference prompt — tells the LLM which predicates exist
        and their constraints so it produces well-formed claims.
        """
        predicates = self._schema.predicates
        if not predicates:
            return ""

        single = []
        multi = []
        for name, info in sorted(predicates.items()):
            temporality = f", {info.temporality}" if info.temporality != "unknown" else ""
            label = f"- {name} (single-valued{temporality})"
            if info.cardinality == "multi":
                label = f"- {name} (multi-valued{temporality}) — multiple values allowed"
                multi.append(label)
            else:
                single.append(label)

        lines = []
        if single:
            lines.append("Single-valued predicates (one value per subject):")
            lines.extend(single)
        if multi:
            if lines:
                lines.append("")
            lines.append("Multi-valued predicates (multiple values per subject):")
            lines.extend(multi)

        return "\n".join(lines)

    def normalization_hints(self) -> str:
        """Alias → canonical mappings for predicates with aliases.

        For the claim parser — helps the LLM use canonical predicate forms
        instead of variants.
        """
        predicates = self._schema.predicates
        hints = []
        for name, info in sorted(predicates.items()):
            if info.aliases:
                aliases_str = ", ".join(f'"{a}"' for a in sorted(info.aliases))
                hints.append(f"- {name}: also known as {aliases_str}")

        if not hints:
            return ""
        return "\n".join(hints)

    def confidence_priors(self) -> str:
        """Confidence guidance grouped by predicate temporality.

        Permanent predicates warrant higher confidence for direct statements.
        Temporal predicates warrant moderate confidence since values change.
        """
        predicates = self._schema.predicates
        if not predicates:
            return ""

        permanent = []
        temporal = []
        for name, info in sorted(predicates.items()):
            if info.temporality == "permanent":
                permanent.append(name)
            elif info.temporality == "temporal":
                temporal.append(name)

        if not permanent and not temporal:
            return ""

        lines = []
        if permanent:
            names = ", ".join(permanent)
            lines.append(
                f"- Permanent predicates ({names}): "
                "use higher confidence (0.9+) for direct statements, "
                "these rarely change"
            )
        if temporal:
            names = ", ".join(temporal)
            lines.append(
                f"- Temporal predicates ({names}): "
                "use moderate confidence (0.7-0.9), these can change over time"
            )

        return "\n".join(lines)

    def exclusivity_warnings(self) -> str:
        """Mutually exclusive predicate groups.

        Warns the LLM that only one predicate from each group
        can be true for a given subject.
        """
        groups = self._schema.exclusivity_groups
        if not groups:
            return ""

        lines = ["Mutually exclusive predicate groups (only one can be true per subject):"]
        for group in sorted(groups, key=lambda g: g.name):
            preds = ", ".join(sorted(group.predicates))
            desc = f" — {group.description}" if group.description else ""
            lines.append(f"- {group.name}: {preds}{desc}")

        return "\n".join(lines)

    def for_inference(self) -> dict[str, str]:
        """Bundle of fragments for the inference prompt."""
        return {
            "predicate_hints": self.predicate_hints(),
            "confidence_priors": self.confidence_priors(),
            "exclusivity_warnings": self.exclusivity_warnings(),
        }

    def for_claim_parser(self) -> dict[str, str]:
        """Bundle of fragments for the claim parsing prompt."""
        return {
            "normalization_hints": self.normalization_hints(),
            "confidence_priors": self.confidence_priors(),
        }
