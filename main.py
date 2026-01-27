"""Entry point for the Agentic Memory System (dev mode).

Runs everything in-process: CLI + agents via asyncio.gather().
Uses InMemoryAgentState (no Redis required).

For distributed mode, use docker-compose instead.
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from src.agent_state import AgentState, InMemoryAgentState
from src.agents.inference import InferenceAgent
from src.agents.validator import ValidatorAgent
from src.cli import run_cli
from src.events import EventBus
from src.interfaces import MemoryService
from src.llm import LLMTranslator
from src.store import StoreConfig, TripleStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = StoreConfig(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        username=os.environ.get("NEO4J_USERNAME", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "memory-system"),
    )
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    llm_model = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")
    redis_url = os.environ.get("REDIS_URL", "")

    # Connect to Neo4j
    logger.info("Connecting to Neo4j at %s", config.uri)
    store = await TripleStore.connect(config)
    logger.info("Connected to Neo4j")

    # Create the memory service
    llm = LLMTranslator(api_key=anthropic_key, model=llm_model)
    memory = MemoryService(store=store, llm=llm)

    # Set up state backend: Redis if available, in-memory otherwise
    event_bus = None
    state: AgentState | InMemoryAgentState
    if redis_url:
        try:
            state = AgentState(redis_url=redis_url)
            event_bus = EventBus(redis_url=redis_url)
            logger.info("Using Redis for agent state and events")
        except Exception:
            logger.warning("Redis unavailable, falling back to in-memory state")
            state = InMemoryAgentState()
    else:
        state = InMemoryAgentState()
        logger.info("No REDIS_URL set, using in-memory agent state")

    # Create agents
    inference_agent = InferenceAgent(
        memory=memory, poll_interval=5.0, event_bus=event_bus, state=state,
    )
    validator_agent = ValidatorAgent(
        memory=memory, poll_interval=8.0, event_bus=event_bus, state=state,
    )

    # Run CLI + agents concurrently
    try:
        await asyncio.gather(
            run_cli(memory),
            inference_agent.run(),
            validator_agent.run(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        inference_agent.stop()
        validator_agent.stop()
        await store.close()
        if event_bus:
            await event_bus.close()
        await state.close()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
