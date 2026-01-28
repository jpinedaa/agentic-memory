"""Base class for worker agents.

Worker agents run as asyncio tasks. They can operate in two modes:
1. Poll mode: sleep(interval) then check for work (default)
2. Event mode: wait for Redis pub/sub events, with poll fallback

Agents register with the API on startup and send periodic status
heartbeats for real-time monitoring.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

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
        agent_type: str = "unknown",
        tags: list[str] | None = None,
    ) -> None:
        self.source_id = source_id
        self.memory = memory
        self.poll_interval = poll_interval
        self.event_bus = event_bus
        self.state = state
        self._running = False

        # Status tracking
        self.agent_type = agent_type
        self.tags = tags or []
        self.agent_id: str | None = None
        self._started_at = datetime.utcnow()
        self._items_processed = 0
        self._error_count = 0
        self._last_action = ""
        self._last_action_at: datetime | None = None
        self._processing_times: list[float] = []
        self._push_interval = poll_interval
        self._heartbeat_task: asyncio.Task | None = None

    @abstractmethod
    async def process(self) -> list[str]:
        """Check for work and return claim texts to assert."""
        ...

    def event_channels(self) -> list[str]:
        """Channels this agent listens to. Override in subclasses."""
        return []

    async def _register(self) -> None:
        """Register with the API and get agent_id + push interval."""
        if not hasattr(self.memory, '_client'):
            # In-process mode, skip registration
            self.agent_id = self.source_id
            return

        try:
            import httpx
            client = self.memory._client
            r = await client.post("/v1/agents/register", json={
                "agent_type": self.agent_type,
                "tags": self.tags,
                "hostname": platform.node(),
                "pid": os.getpid(),
            })
            r.raise_for_status()
            data = r.json()
            self.agent_id = data["agent_id"]
            self._push_interval = data["push_interval_seconds"]
            logger.info(f"Registered as {self.agent_id} (push_interval={self._push_interval}s)")
        except Exception:
            logger.warning("Failed to register with API, using source_id as agent_id")
            self.agent_id = self.source_id

    async def _deregister(self) -> None:
        """Deregister from the API on shutdown."""
        if not self.agent_id or not hasattr(self.memory, '_client'):
            return

        try:
            client = self.memory._client
            await client.post(f"/v1/agents/{self.agent_id}/deregister")
            logger.info(f"Deregistered agent {self.agent_id}")
        except Exception:
            logger.debug("Failed to deregister (API may be down)")

    async def _send_heartbeat(self) -> None:
        """Send a single status heartbeat to the API."""
        if not self.agent_id or not hasattr(self.memory, '_client'):
            return

        now = datetime.utcnow()
        uptime = (now - self._started_at).total_seconds()
        avg_time = (
            sum(self._processing_times[-100:]) / len(self._processing_times[-100:])
            if self._processing_times
            else 0.0
        )

        # Get memory usage
        memory_mb = 0.0
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            memory_mb = usage.ru_maxrss / 1024  # Linux: KB -> MB
        except Exception:
            pass

        status = {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "tags": self.tags,
            "timestamp": now.isoformat() + "Z",
            "started_at": self._started_at.isoformat() + "Z",
            "uptime_seconds": uptime,
            "status": "running" if self._running else "stopping",
            "last_action": self._last_action,
            "last_action_at": self._last_action_at.isoformat() + "Z" if self._last_action_at else None,
            "items_processed": self._items_processed,
            "queue_depth": 0,
            "processing_time_avg_ms": avg_time,
            "error_count": self._error_count,
            "memory_mb": memory_mb,
            "push_interval_seconds": self._push_interval,
        }

        try:
            client = self.memory._client
            r = await client.post("/v1/agents/status", json=status)
            r.raise_for_status()
            data = r.json()
            # Update push interval if server changed it
            self._push_interval = data.get("push_interval_seconds", self._push_interval)
        except Exception:
            logger.debug("Failed to send heartbeat")

    async def _heartbeat_loop(self) -> None:
        """Background task that sends periodic heartbeats."""
        while self._running:
            await self._send_heartbeat()
            await asyncio.sleep(self._push_interval)

    async def run(self) -> None:
        """Main agent loop. Event-driven with poll fallback.

        Retries on startup connection errors (e.g. API not ready yet).
        """
        self._running = True
        self._started_at = datetime.utcnow()
        logger.info(f"Agent {self.source_id} started")

        # Register with API
        await self._register()

        # Retry loop for initial connection
        for attempt in range(1, 13):  # up to ~60s of retries
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

        # Start heartbeat loop
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            if self.event_bus and self.event_channels():
                await self._run_event_driven()
            else:
                await self._run_poll()
        finally:
            # Cleanup
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
            await self._deregister()

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
                self._error_count += 1
                await asyncio.sleep(5)

        await pubsub.unsubscribe(*channels)
        await pubsub.close()

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
        logger.info(f"Agent {self.source_id} stopping")
