"""Standalone entry point for the inference agent.

Connects to the API server via HTTP and Redis for events/state.
Can be scaled: docker compose up --scale inference-agent=3
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket

from dotenv import load_dotenv

load_dotenv()

from src.agent_state import AgentState
from src.agents.inference import InferenceAgent
from src.api_client import MemoryClient
from src.events import EventBus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main() -> None:
    api_url = os.environ.get("API_BASE_URL", "http://localhost:8000")
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    instance_id = os.environ.get("AGENT_INSTANCE_ID", socket.gethostname())
    poll_interval = float(os.environ.get("POLL_INTERVAL", "30"))

    logger.info(f"Inference agent starting (instance: {instance_id})")
    logger.info(f"API: {api_url}, Redis: {redis_url}")

    memory = MemoryClient(base_url=api_url)
    event_bus = EventBus(redis_url=redis_url)
    state = AgentState(redis_url=redis_url)

    agent = InferenceAgent(
        memory=memory,
        poll_interval=poll_interval,
        event_bus=event_bus,
        state=state,
    )

    try:
        await agent.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        agent.stop()
        await memory.close()
        await event_bus.close()
        await state.close()


if __name__ == "__main__":
    asyncio.run(main())
