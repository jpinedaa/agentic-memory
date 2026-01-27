"""Base class for worker agents.

Worker agents run as asyncio tasks, polling the memory service
and making claims based on their analysis.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from src.interfaces import MemoryService

logger = logging.getLogger(__name__)


class WorkerAgent(ABC):
    """Abstract base for continuously-running worker agents.

    Subclasses define what they watch for and how they process it.
    The run loop handles polling and error recovery.
    """

    def __init__(
        self,
        source_id: str,
        memory: MemoryService,
        poll_interval: float = 5.0,
    ) -> None:
        self.source_id = source_id
        self.memory = memory
        self.poll_interval = poll_interval
        self._running = False

    @abstractmethod
    def watch_query(self) -> str:
        """Natural language query describing what this agent monitors."""
        ...

    @abstractmethod
    async def process(self, context: str) -> list[str]:
        """Analyze context and return claim texts to assert.

        Returns an empty list if no action needed.
        """
        ...

    async def run(self) -> None:
        """Main agent loop. Polls memory and makes claims."""
        self._running = True
        logger.info(f"Agent {self.source_id} started")

        while self._running:
            try:
                context = await self.memory.remember(self.watch_query())
                claims = await self.process(context)
                for claim_text in claims:
                    await self.memory.claim(claim_text, source=self.source_id)
                    logger.info(f"Agent {self.source_id} claimed: {claim_text[:80]}")
            except Exception:
                logger.exception(f"Agent {self.source_id} error in loop")

            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        """Signal the agent to stop after the current iteration."""
        self._running = False
        logger.info(f"Agent {self.source_id} stopping")
