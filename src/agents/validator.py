"""Validator agent: detects contradictions between claims.

Monitors the claim store for pairs of claims that contradict
each other and flags them. Uses AgentState for persistent tracking
and EventBus for event-driven wakeup.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.agents.base import WorkerAgent
from src.events import CHANNEL_CLAIM

if TYPE_CHECKING:
    from src.agent_state import AgentState, InMemoryAgentState
    from src.events import EventBus
    from src.memory_protocol import MemoryAPI

logger = logging.getLogger(__name__)

STATE_KEY = "agent:validator:checked_pairs"


class ValidatorAgent(WorkerAgent):
    """Watches for contradicting claims and flags them."""

    def __init__(
        self,
        memory: MemoryAPI,
        poll_interval: float = 30.0,
        event_bus: EventBus | None = None,
        state: AgentState | InMemoryAgentState | None = None,
    ) -> None:
        super().__init__(
            source_id="validator_agent",
            memory=memory,
            poll_interval=poll_interval,
            event_bus=event_bus,
            state=state,
        )

    def event_channels(self) -> list[str]:
        return [CHANNEL_CLAIM]

    async def process(self) -> list[str]:
        """Check for contradicting claims and flag them."""
        claims = await self.memory.get_recent_claims(limit=20)

        # Group claims by entity (subject_text)
        by_subject: dict[str, list[dict]] = {}
        for c in claims:
            subj = c.get("subject_text", "unknown")
            by_subject.setdefault(subj, []).append(c)

        contradiction_claims = []

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

                        # Check if already flagged (Redis or in-memory)
                        if self.state and await self.state.is_processed(STATE_KEY, pair_key):
                            continue

                        claim_text = (
                            f"the claim that {subject} {predicate} '{obj1}' "
                            f"contradicts the claim that {subject} {predicate} '{obj2}'"
                        )
                        contradiction_claims.append(claim_text)

                        if self.state:
                            await self.state.mark_processed(STATE_KEY, pair_key)

                        logger.info(
                            f"ValidatorAgent found contradiction: "
                            f"{obj1} vs {obj2} for {subject}.{predicate}"
                        )

        return contradiction_claims
