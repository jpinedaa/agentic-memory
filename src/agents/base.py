"""Base class for worker agents.

Worker agents run as asyncio tasks. They operate in event-driven mode
(woken by P2P network events) with a poll fallback.

Agent status is propagated via the P2P gossip protocol — no central
registry or heartbeat endpoint needed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.p2p.local_state import LocalAgentState
    from src.memory_protocol import MemoryAPI

logger = logging.getLogger(__name__)


class WorkerAgent(ABC):
    """Abstract base for continuously-running worker agents.

    Accepts any object satisfying the MemoryAPI protocol and an optional
    LocalAgentState for idempotency tracking.

    Event-driven wakeup is provided by the P2P node via add_event_listener().
    """

    def __init__(
        self,
        source_id: str,
        memory: MemoryAPI,
        poll_interval: float = 30.0,
        state: LocalAgentState | None = None,
        agent_type: str = "unknown",
        tags: list[str] | None = None,
    ) -> None:
        self.source_id = source_id
        self.memory = memory
        self.poll_interval = poll_interval
        self.state = state
        self._running = False

        # Status tracking
        self.agent_type = agent_type
        self.tags = tags or []
        self._started_at = datetime.utcnow()
        self._items_processed = 0
        self._error_count = 0
        self._last_action = ""
        self._last_action_at: datetime | None = None
        self._processing_times: list[float] = []

        # Event-driven wakeup
        self._event_received = asyncio.Event()

    @abstractmethod
    async def process(self) -> list[str]:
        """Check for work and return claim texts to assert."""
        ...

    def event_types(self) -> list[str]:
        """Event types this agent is interested in. Override in subclasses."""
        return []

    async def on_network_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Called by the P2P node when a relevant network event arrives."""
        if event_type in self.event_types():
            self._event_received.set()

    async def run(self) -> None:
        """Main agent loop. Event-driven with poll fallback."""
        self._running = True
        self._started_at = datetime.utcnow()
        logger.info(f"Agent {self.source_id} started")

        # Retry loop for initial connection
        for attempt in range(1, 13):
            try:
                await self._tick()
                break
            except Exception:
                logger.warning(
                    f"Agent {self.source_id} startup attempt {attempt}/12 failed, retrying..."
                )
                await asyncio.sleep(5)
        else:
            logger.error(f"Agent {self.source_id} could not connect after 12 attempts")
            return

        try:
            await self._run_event_driven()
        except asyncio.CancelledError:
            pass
        finally:
            logger.info(f"Agent {self.source_id} stopped")

    async def _run_event_driven(self) -> None:
        """Event-driven mode with poll fallback."""
        while self._running:
            try:
                # Wait for event or poll timeout
                try:
                    await asyncio.wait_for(
                        self._event_received.wait(),
                        timeout=self.poll_interval,
                    )
                except asyncio.TimeoutError:
                    pass  # Poll fallback

                self._event_received.clear()
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(f"Agent {self.source_id} error in event loop")
                self._error_count += 1
                await asyncio.sleep(5)

    async def _tick(self) -> None:
        """Single processing cycle."""
        try:
            start = time.monotonic()
            claims = await self.process()
            elapsed_ms = (time.monotonic() - start) * 1000
            self._processing_times.append(elapsed_ms)

            for claim_text in claims:
                await self.memory.claim(claim_text, source=self.source_id)
                logger.info(f"Agent {self.source_id} claimed: {claim_text[:100]}")
                self._items_processed += 1

            if claims:
                self._last_action = f"Processed {len(claims)} claim(s)"
                self._last_action_at = datetime.utcnow()
        except Exception:
            logger.exception(f"Agent {self.source_id} error in tick")
            self._error_count += 1

    def stop(self) -> None:
        """Signal the agent to stop after the current iteration."""
        self._running = False
        self._event_received.set()  # Unblock the wait
        logger.info(f"Agent {self.source_id} stopping")
