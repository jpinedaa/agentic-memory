"""Validator agent: detects contradictions between statements.

Monitors the statement store for pairs of statements that contradict
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
    """Watches for contradicting statements and flags them."""

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
        """Check for contradicting statements and flag them."""
        statements = await self.memory.get_recent_statements(limit=20)
        logger.debug("Fetched %d statements to validate", len(statements))

        # Group statements by subject concept
        by_subject: dict[str, list[dict]] = {}
        for s in statements:
            subj = s.get("subject_name", "unknown")
            by_subject.setdefault(subj, []).append(s)

        contradiction_claims = []

        logger.debug("Grouped into %d subjects: %s", len(by_subject), list(by_subject.keys()))

        for subject, subject_statements in by_subject.items():
            by_predicate: dict[str, list[dict]] = {}
            for s in subject_statements:
                pred = s.get("predicate", "")
                by_predicate.setdefault(pred, []).append(s)

            for predicate, pred_statements in by_predicate.items():
                if len(pred_statements) < 2:
                    continue

                for i, s1 in enumerate(pred_statements):
                    for s2 in pred_statements[i + 1 :]:
                        obj1 = s1.get("object_name", "")
                        obj2 = s2.get("object_name", "")
                        if obj1 == obj2:
                            continue

                        pair_key = ":".join(sorted([s1["id"], s2["id"]]))

                        # Check if already flagged
                        if self.state and await self.state.is_processed(STATE_KEY, pair_key):
                            logger.debug("Skipping already-checked pair %s", pair_key)
                            continue

                        claim_text = (
                            f"the statement that {subject} {predicate} '{obj1}' "
                            f"contradicts the statement that {subject} {predicate} '{obj2}'"
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
