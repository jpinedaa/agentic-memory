"""Validator agent: detects contradictions between statements.

Monitors the statement store for pairs of statements that contradict
each other and flags them directly via memory.flag_contradiction().
Uses LocalAgentState for idempotency tracking. Schema-aware: skips
multi-valued predicates and checks exclusivity groups.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.agents.base import WorkerAgent

if TYPE_CHECKING:
    from src.p2p.local_state import LocalAgentState
    from src.memory_protocol import MemoryAPI
    from src.schema.loader import PredicateSchema

logger = logging.getLogger(__name__)

STATE_KEY = "agent:validator:checked_pairs"


class ValidatorAgent(WorkerAgent):
    """Watches for contradicting statements and flags them."""

    def __init__(
        self,
        memory: MemoryAPI,
        poll_interval: float = 30.0,
        state: LocalAgentState | None = None,
        schema: PredicateSchema | None = None,
    ) -> None:
        super().__init__(
            source_id="validator_agent",
            memory=memory,
            poll_interval=poll_interval,
            state=state,
            agent_type="validator",
        )
        self._schema = schema

    def event_types(self) -> list[str]:
        return ["claim"]

    async def process(self) -> list[str]:  # pylint: disable=too-many-locals
        """Check for contradicting statements and flag them.

        Returns an empty list — contradictions are flagged directly
        via memory.flag_contradiction() instead of producing NL claims.
        """
        statements = await self.memory.get_recent_statements(limit=20)
        logger.debug("Fetched %d statements to validate", len(statements))

        # Group statements by subject concept
        by_subject: dict[str, list[dict]] = {}
        for s in statements:
            subj = s.get("subject_name", "unknown")
            by_subject.setdefault(subj, []).append(s)

        logger.debug(
            "Grouped into %d subjects: %s",
            len(by_subject), list(by_subject.keys()),
        )

        flagged = 0

        for subject, subject_statements in by_subject.items():
            # Same-predicate contradictions
            flagged += await self._check_same_predicate(
                subject, subject_statements,
            )

            # Cross-predicate exclusivity group contradictions
            if self._schema:
                flagged += await self._check_exclusivity_groups(
                    subject, subject_statements,
                )

        if flagged:
            self._last_action = f"Flagged {flagged} contradiction(s)"

        # Return empty — contradictions flagged directly, not via claim()
        return []

    async def _check_same_predicate(
        self,
        subject: str,
        statements: list[dict],
    ) -> int:
        """Flag contradictions within same-subject same-predicate groups."""
        by_predicate: dict[str, list[dict]] = {}
        for s in statements:
            pred = s.get("predicate", "")
            by_predicate.setdefault(pred, []).append(s)

        flagged = 0

        for predicate, pred_statements in by_predicate.items():
            if len(pred_statements) < 2:
                continue

            # Schema check: skip multi-valued predicates
            if self._schema and self._schema.is_multi_valued(predicate):
                logger.debug(
                    "Skipping multi-valued predicate '%s' for %s",
                    predicate, subject,
                )
                continue

            for i, s1 in enumerate(pred_statements):
                for s2 in pred_statements[i + 1:]:
                    obj1 = s1.get("object_name", "")
                    obj2 = s2.get("object_name", "")
                    if obj1 == obj2:
                        continue

                    pair_key = ":".join(sorted([s1["id"], s2["id"]]))

                    if self.state and await self.state.is_processed(
                        STATE_KEY, pair_key
                    ):
                        logger.debug("Skipping already-checked pair %s", pair_key)
                        continue

                    reason = (
                        f"{subject} {predicate}: "
                        f"'{obj1}' vs '{obj2}'"
                    )
                    await self.memory.flag_contradiction(
                        s1["id"], s2["id"], reason=reason,
                    )
                    flagged += 1

                    if self.state:
                        await self.state.mark_processed(STATE_KEY, pair_key)

                    logger.info(
                        "Flagged contradiction: %s vs %s for %s.%s",
                        obj1, obj2, subject, predicate,
                    )

        return flagged

    async def _check_exclusivity_groups(
        self,
        subject: str,
        statements: list[dict],
    ) -> int:
        """Check for violations of mutual exclusivity groups."""
        # Group statements by exclusivity group
        group_stmts: dict[str, list[dict]] = {}
        for s in statements:
            pred = s.get("predicate", "")
            group = self._schema.get_exclusivity_group(pred)
            if group:
                group_stmts.setdefault(group.name, []).append(s)

        flagged = 0

        for group_name, stmts in group_stmts.items():
            if len(stmts) < 2:
                continue
            for i, s1 in enumerate(stmts):
                for s2 in stmts[i + 1:]:
                    pair_key = ":".join(sorted([s1["id"], s2["id"]]))
                    if self.state and await self.state.is_processed(
                        STATE_KEY, pair_key
                    ):
                        continue

                    reason = (
                        f"Exclusivity group '{group_name}': "
                        f"{s1.get('predicate', '')} vs "
                        f"{s2.get('predicate', '')}"
                    )
                    await self.memory.flag_contradiction(
                        s1["id"], s2["id"], reason=reason,
                    )
                    flagged += 1

                    if self.state:
                        await self.state.mark_processed(STATE_KEY, pair_key)

                    logger.info(
                        "Flagged exclusivity violation for %s: %s",
                        subject, reason,
                    )

        return flagged
