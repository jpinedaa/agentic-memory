"""Standalone CLI entry point.

Connects to the API server via HTTP.
Registers as a 'cli' agent in the topology.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time

from dotenv import load_dotenv

load_dotenv()

from src.api_client import MemoryClient
from src.cli import run_cli

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class CLIAgentRegistration:
    """Handles agent registration and heartbeats for the CLI process."""

    def __init__(self, base_url: str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self._agent_id: str | None = None
        self._push_interval: float = 30.0
        self._started_at = time.time()
        self._items_processed = 0
        self._heartbeat_task: asyncio.Task | None = None

    async def register(self) -> None:
        """Register this CLI as an agent."""
        try:
            r = await self._client.post("/v1/agents/register", json={
                "agent_type": "cli",
                "tags": ["interactive"],
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
            })
            r.raise_for_status()
            data = r.json()
            self._agent_id = data["agent_id"]
            self._push_interval = data.get("push_interval_seconds", 30.0)
            logger.info(f"Registered as agent {self._agent_id}")
        except Exception:
            logger.warning("Failed to register CLI as agent (topology will not show CLI)")

    async def start_heartbeat(self) -> None:
        """Start background heartbeat loop."""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while True:
            await asyncio.sleep(self._push_interval)
            await self._send_heartbeat()

    async def _send_heartbeat(self) -> None:
        """Send a single heartbeat."""
        if not self._agent_id:
            return
        try:
            import resource
            mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except Exception:
            mem_mb = 0.0

        try:
            r = await self._client.post("/v1/agents/status", json={
                "agent_id": self._agent_id,
                "agent_type": "cli",
                "tags": ["interactive"],
                "status": "running",
                "uptime_seconds": time.time() - self._started_at,
                "items_processed": self._items_processed,
                "queue_depth": 0,
                "processing_time_avg_ms": 0.0,
                "error_count": 0,
                "memory_mb": mem_mb,
            })
            if r.status_code == 200:
                data = r.json()
                self._push_interval = data.get("push_interval_seconds", self._push_interval)
        except Exception:
            logger.debug("Failed to send heartbeat")

    def record_action(self) -> None:
        """Record that an action was performed."""
        self._items_processed += 1

    async def deregister(self) -> None:
        """Deregister on shutdown."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._agent_id:
            try:
                await self._client.post(f"/v1/agents/{self._agent_id}/deregister")
                logger.info(f"Deregistered agent {self._agent_id}")
            except Exception:
                pass
        await self._client.aclose()


async def main() -> None:
    api_url = os.environ.get("API_BASE_URL", "http://localhost:8000")

    logger.info(f"CLI connecting to API at {api_url}")
    memory = MemoryClient(base_url=api_url)

    # Register CLI as an agent
    registration = CLIAgentRegistration(api_url)
    await registration.register()
    await registration.start_heartbeat()

    try:
        await run_cli(memory, on_action=registration.record_action)
    finally:
        await registration.deregister()
        await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
