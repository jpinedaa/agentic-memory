"""Inference agent: converts observations into claims.

Monitors new observations and generates inferred claims
(e.g. "user said they hate early meetings" -> "user prefers afternoon meetings").
"""

from __future__ import annotations

import logging

from src.agents.base import WorkerAgent

logger = logging.getLogger(__name__)


class InferenceAgent(WorkerAgent):
    """Watches for new observations and infers claims from them."""

    def __init__(self, memory, poll_interval: float = 5.0) -> None:
        super().__init__(
            source_id="inference_agent",
            memory=memory,
            poll_interval=poll_interval,
        )
        self._processed_obs: set[str] = set()

    def watch_query(self) -> str:
        return "what are the most recent observations that haven't been analyzed yet?"

    async def process(self, context: str) -> list[str]:
        """Check for unprocessed observations and infer claims."""
        # Get recent observations directly from the store
        observations = await self.memory.store.find_recent_observations(limit=10)

        claims = []
        for obs in observations:
            obs_id = obs.get("id", "")
            if obs_id in self._processed_obs:
                continue

            raw = obs.get("raw_content", "")
            if not raw:
                self._processed_obs.add(obs_id)
                continue

            # Generate an inference claim based on the observation
            claim_text = (
                f"based on the observation that '{raw}', "
                f"I infer the following about the subject"
            )
            claims.append(claim_text)
            self._processed_obs.add(obs_id)
            logger.info(f"InferenceAgent processing observation: {obs_id}")

        return claims
