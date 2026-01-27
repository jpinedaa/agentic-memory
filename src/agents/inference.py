"""Inference agent: converts observations into claims.

Monitors new observations and generates inferred claims
(e.g. "user said they hate early meetings" -> "user prefers afternoon meetings").
Uses the LLM to produce meaningful inferences.
"""

from __future__ import annotations

import logging

import anthropic

from src.agents.base import WorkerAgent

logger = logging.getLogger(__name__)

INFERENCE_PROMPT = """\
You are an inference agent for a knowledge system. Given an observation (something \
a user said or did), produce a concise factual claim that can be stored in a knowledge graph.

Rules:
- State the inference as a direct factual claim (e.g. "user prefers afternoon meetings")
- Do NOT repeat the observation verbatim — infer the underlying fact or preference
- Keep it to one sentence
- If the observation is too vague or meaningless to infer anything from, respond with exactly: SKIP

Observation: {observation}"""


class InferenceAgent(WorkerAgent):
    """Watches for new observations and infers claims from them."""

    def __init__(self, memory, poll_interval: float = 5.0) -> None:
        super().__init__(
            source_id="inference_agent",
            memory=memory,
            poll_interval=poll_interval,
        )
        self._processed_obs: set[str] = set()

    async def process(self) -> list[str]:
        """Check for unprocessed observations and infer claims via LLM."""
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

            self._processed_obs.add(obs_id)
            logger.info(f"InferenceAgent processing observation: {obs_id}")

            # Use the LLM to generate a real inference
            try:
                claim_text = await self._infer(raw)
                if claim_text:
                    claims.append(claim_text)
            except Exception:
                logger.exception(f"InferenceAgent failed to infer from: {obs_id}")

        return claims

    async def _infer(self, observation: str) -> str | None:
        """Use the LLM to produce an inference claim from an observation."""
        prompt = INFERENCE_PROMPT.format(observation=observation)
        response = await self.memory.llm._client.messages.create(
            model=self.memory.llm._model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in response.content:
            if block.type == "text":
                text = block.text.strip()
                break

        if not text or text.upper() == "SKIP":
            logger.info("InferenceAgent skipped observation (no meaningful inference)")
            return None

        return text
