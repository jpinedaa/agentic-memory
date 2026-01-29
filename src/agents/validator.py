"""Validator agent: detects contradictions between claims.

Monitors the claim store for pairs of claims that contradict
each other and flags them. Uses LocalAgentState for idempotency
tracking.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.agents.base import WorkerAgent

if TYPE_CHECKING:
    from src.p2p.local_state import LocalAgentState
    from src.memory_protocol import MemoryAPI

logger = logging.getLogger(__name__)

STATE_KEY = "agent:validator:checked_pairs"


class ValidatorAgent(WorkerAgent):
    """Watches for contradicting claims and flags them."""

    def __init__(
        self,
        memory: MemoryAPI,
        poll_interval: float = 30.0,
        state: LocalAgentState | None = None,
    ) -> None:
        super().__init__(
            source_id="validator_agent",
            memory=memory,
            poll_interval=poll_interval,
            state=state,
            agent_type="validator",
        )

    def event_types(self) -> list[str]:
        return ["claim"]

    async def process(self) -> list[str]:  # pylint: disable=too-many-locals  # contradiction detection requires tracking many pair-wise variables
        """Check for contradicting claims and flag them."""
        claims = await self.memory.get_recent_claims(limit=20)
        logger.debug("Fetched %d claims to validate", len(claims))

        # Group claims by entity (subject_text)
        by_subject: dict[str, list[dict]] = {}
        for c in claims:
            subj = c.get("subject_text", "unknown")
            by_subject.setdefault(subj, []).append(c)

        contradiction_claims = []

        logger.debug("Grouped into %d subjects: %s", len(by_subject), list(by_subject.keys()))

        for subject, subject_claims in by_subject.items():
            by_predicate: dict[str, list[dict]] = {}
            for c in subject_claims:
                pred = c.get("predicate_text", "")
                by_predicate.setdefault(pred, []).append(c)

            for predicate, pred_claims in by_predicate.items():
                if len(pred_claims) < 2:
                    continue

                for i, c1 in enumerate(pred_claims):
                    for c2 in pred_claims[i + 1 :]:
                        obj1 = c1.get("object_text", "")
                        obj2 = c2.get("object_text", "")
                        if obj1 == obj2:
                            continue

                        pair_key = ":".join(sorted([c1["id"], c2["id"]]))

                        # Check if already flagged
                        if self.state and await self.state.is_processed(STATE_KEY, pair_key):
                            logger.debug("Skipping already-checked pair %s", pair_key)
                            continue

                        claim_text = (
                            f"the claim that {subject} {predicate} '{obj1}' "
                            f"contradicts the claim that {subject} {predicate} '{obj2}'"
                        )
                        contradiction_claims.append(claim_text)

                        if self.state:
                            await self.state.mark_processed(STATE_KEY, pair_key)

                        logger.info(
                            "ValidatorAgent found contradiction: "
                            "%s vs %s for %s.%s",
                            obj1, obj2, subject, predicate,
                        )

        return contradiction_claims
