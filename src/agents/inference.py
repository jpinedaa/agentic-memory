"""Inference agent: converts observations into claims.

Monitors new observations and generates inferred claims
via the MemoryAPI.infer() method. Uses AgentState for
persistent tracking and EventBus for event-driven wakeup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.agents.base import WorkerAgent
from src.events import CHANNEL_OBSERVATION

if TYPE_CHECKING:
    from src.agent_state import AgentState, InMemoryAgentState
    from src.events import EventBus
    from src.memory_protocol import MemoryAPI

logger = logging.getLogger(__name__)

STATE_KEY = "agent:inference:processed_obs"


class InferenceAgent(WorkerAgent):
    """Watches for new observations and infers claims from them."""

    def __init__(
        self,
        memory: MemoryAPI,
        poll_interval: float = 30.0,
        event_bus: EventBus | None = None,
        state: AgentState | InMemoryAgentState | None = None,
    ) -> None:
        super().__init__(
            source_id="inference_agent",
            memory=memory,
            poll_interval=poll_interval,
            event_bus=event_bus,
            state=state,
            agent_type="inference",
        )
        self._inference_started_at = datetime.now(timezone.utc).isoformat()

    def event_channels(self) -> list[str]:
        return [CHANNEL_OBSERVATION]

    async def process(self) -> list[str]:
        """Check for unprocessed observations and infer claims."""
        observations = await self.memory.get_recent_observations(limit=10)

        claims = []
        for obs in observations:
            obs_id = obs.get("id", "")

            # Skip observations from before this agent started (stale data)
            obs_ts = obs.get("timestamp", "")
            if obs_ts and obs_ts < self._inference_started_at:
                if self.state:
                    await self.state.mark_processed(STATE_KEY, obs_id)
                continue

            # Check if already processed (Redis or in-memory)
            if self.state and await self.state.is_processed(STATE_KEY, obs_id):
                continue

            raw = obs.get("raw_content", "")
            if not raw:
                if self.state:
                    await self.state.mark_processed(STATE_KEY, obs_id)
                continue

            # Distributed lock: only one instance processes each observation
            if self.state:
                acquired = await self.state.try_acquire(
                    f"inference:{obs_id}", self.source_id, ttl=300
                )
                if not acquired:
                    continue

            logger.info(f"InferenceAgent processing observation: {obs_id}")

            try:
                claim_text = await self.memory.infer(raw)
                if claim_text:
                    claims.append(claim_text)
                else:
                    logger.info("InferenceAgent skipped observation (no meaningful inference)")
            except Exception:
                logger.exception(f"InferenceAgent failed to infer from: {obs_id}")

            if self.state:
                await self.state.mark_processed(STATE_KEY, obs_id)

        return claims
