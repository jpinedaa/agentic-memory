"""Validator agent: detects contradictions between claims.

Monitors the claim store for pairs of claims that contradict
each other and flags them.
"""

from __future__ import annotations

import logging

from src.agents.base import WorkerAgent

logger = logging.getLogger(__name__)


class ValidatorAgent(WorkerAgent):
    """Watches for contradicting claims and flags them."""

    def __init__(self, memory, poll_interval: float = 8.0) -> None:
        super().__init__(
            source_id="validator_agent",
            memory=memory,
            poll_interval=poll_interval,
        )
        self._checked_pairs: set[tuple[str, str]] = set()

    async def process(self) -> list[str]:
        """Check for contradicting claims and flag them."""
        claims = await self.memory.store.find_recent_claims(limit=20)

        # Group claims by entity (subject_text)
        by_subject: dict[str, list[dict]] = {}
        for c in claims:
            subj = c.get("subject_text", "unknown")
            by_subject.setdefault(subj, []).append(c)

        contradiction_claims = []

        for subject, subject_claims in by_subject.items():
            # Look for claims about the same subject with the same predicate
            # but different objects
            by_predicate: dict[str, list[dict]] = {}
            for c in subject_claims:
                pred = c.get("predicate_text", "")
                by_predicate.setdefault(pred, []).append(c)

            for predicate, pred_claims in by_predicate.items():
                if len(pred_claims) < 2:
                    continue

                # Check each pair
                for i, c1 in enumerate(pred_claims):
                    for c2 in pred_claims[i + 1 :]:
                        obj1 = c1.get("object_text", "")
                        obj2 = c2.get("object_text", "")
                        if obj1 == obj2:
                            continue

                        pair_key = tuple(sorted([c1["id"], c2["id"]]))
                        if pair_key in self._checked_pairs:
                            continue

                        self._checked_pairs.add(pair_key)

                        claim_text = (
                            f"the claim that {subject} {predicate} '{obj1}' "
                            f"contradicts the claim that {subject} {predicate} '{obj2}'"
                        )
                        contradiction_claims.append(claim_text)
                        logger.info(
                            f"ValidatorAgent found contradiction: "
                            f"{obj1} vs {obj2} for {subject}.{predicate}"
                        )

        return contradiction_claims
