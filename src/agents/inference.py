"""Inference agent: converts observations into claims.

Monitors new observations and generates inferred claims
via the MemoryAPI.infer() method. Uses LocalAgentState for
idempotency tracking.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.agents.base import WorkerAgent

if TYPE_CHECKING:
    from src.p2p.local_state import LocalAgentState
    from src.memory_protocol import MemoryAPI

logger = logging.getLogger(__name__)

STATE_KEY = "agent:inference:processed_obs"


class InferenceAgent(WorkerAgent):
    """Watches for new observations and infers claims from them."""

    def __init__(
        self,
        memory: MemoryAPI,
        poll_interval: float = 30.0,
        state: LocalAgentState | None = None,
    ) -> None:
        super().__init__(
            source_id="inference_agent",
            memory=memory,
            poll_interval=poll_interval,
            state=state,
            agent_type="inference",
        )
        self._inference_started_at = datetime.now(timezone.utc).isoformat()

    def event_types(self) -> list[str]:
        return ["observe"]

    async def process(self) -> list[str]:
        """Check for unprocessed observations and infer claims."""
        observations = await self.memory.get_recent_observations(limit=10)
        logger.debug("Fetched %d observations to process", len(observations))

        claims = []
        for obs in observations:
            obs_id = obs.get("id", "")

            # Skip observations from before this agent started (stale data)
            obs_ts = obs.get("timestamp", "")
            if obs_ts and obs_ts < self._inference_started_at:
                logger.debug("Skipping stale observation %s (ts=%s < started=%s)", obs_id, obs_ts, self._inference_started_at)
                if self.state:
                    await self.state.mark_processed(STATE_KEY, obs_id)
                continue

            # Check if already processed
            if self.state and await self.state.is_processed(STATE_KEY, obs_id):
                logger.debug("Skipping already-processed observation %s", obs_id)
                continue

            raw = obs.get("raw_content", "")
            if not raw:
                logger.debug("Skipping observation %s (empty raw_content)", obs_id)
                if self.state:
                    await self.state.mark_processed(STATE_KEY, obs_id)
                continue

            # Distributed lock: only one instance processes each observation
            if self.state:
                acquired = await self.state.try_acquire(
                    f"inference:{obs_id}", self.source_id, ttl=300
                )
                if not acquired:
                    logger.debug("Lock not acquired for observation %s", obs_id)
                    continue

            logger.info("InferenceAgent processing observation: %s", obs_id)
            logger.debug("Observation text: %s", raw[:200])

            try:
                claim_text = await self.memory.infer(raw)
                if claim_text:
                    claims.append(claim_text)
                else:
                    logger.info("InferenceAgent skipped observation (no meaningful inference)")
            except Exception:  # pylint: disable=broad-exception-caught  # individual observation failure must not stop the agent
                logger.exception("InferenceAgent failed to infer from: %s", obs_id)

            if self.state:
                await self.state.mark_processed(STATE_KEY, obs_id)

        return claims
