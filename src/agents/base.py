"""Base class for worker agents.

Worker agents run as asyncio tasks. They can operate in two modes:
1. Poll mode: sleep(interval) then check for work (default)
2. Event mode: wait for Redis pub/sub events, with poll fallback
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent_state import AgentState, InMemoryAgentState
    from src.events import EventBus
    from src.memory_protocol import MemoryAPI

logger = logging.getLogger(__name__)


class WorkerAgent(ABC):
    """Abstract base for continuously-running worker agents.

    Accepts any object satisfying the MemoryAPI protocol.
    Optionally accepts an EventBus for event-driven wakeup
    and an AgentState for persistent tracking.
    """

    def __init__(
        self,
        source_id: str,
        memory: MemoryAPI,
        poll_interval: float = 30.0,
        event_bus: EventBus | None = None,
        state: AgentState | InMemoryAgentState | None = None,
    ) -> None:
        self.source_id = source_id
        self.memory = memory
        self.poll_interval = poll_interval
        self.event_bus = event_bus
        self.state = state
        self._running = False

    @abstractmethod
    async def process(self) -> list[str]:
        """Check for work and return claim texts to assert."""
        ...

    def event_channels(self) -> list[str]:
        """Channels this agent listens to. Override in subclasses."""
        return []

    async def run(self) -> None:
        """Main agent loop. Event-driven with poll fallback."""
        self._running = True
        logger.info(f"Agent {self.source_id} started")

        if self.event_bus and self.event_channels():
            await self._run_event_driven()
        else:
            await self._run_poll()

    async def _run_poll(self) -> None:
        """Pure polling mode."""
        while self._running:
            await self._tick()
            await asyncio.sleep(self.poll_interval)

    async def _run_event_driven(self) -> None:
        """Event-driven mode with poll fallback."""
        channels = self.event_channels()
        pubsub = await self.event_bus.subscribe(*channels)
        logger.info(f"Agent {self.source_id} subscribed to {channels}")

        while self._running:
            try:
                # Wait for event or poll timeout
                message = await asyncio.wait_for(
                    pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=self.poll_interval
                    ),
                    timeout=self.poll_interval + 1,
                )
                if message and message["type"] == "message":
                    logger.info(f"Agent {self.source_id} received event on {message['channel']}")
                # Process regardless (event or timeout = poll fallback)
                await self._tick()
            except asyncio.TimeoutError:
                # Poll fallback
                await self._tick()
            except Exception:
                logger.exception(f"Agent {self.source_id} error in event loop")
                await asyncio.sleep(5)

        await pubsub.unsubscribe(*channels)
        await pubsub.close()

    async def _tick(self) -> None:
        """Single processing cycle."""
        try:
            claims = await self.process()
            for claim_text in claims:
                await self.memory.claim(claim_text, source=self.source_id)
                logger.info(f"Agent {self.source_id} claimed: {claim_text[:100]}")
        except Exception:
            logger.exception(f"Agent {self.source_id} error in tick")

    def stop(self) -> None:
        """Signal the agent to stop after the current iteration."""
        self._running = False
        logger.info(f"Agent {self.source_id} stopping")
