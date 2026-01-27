"""Entry point for the Agentic Memory System.

Starts Neo4j connection, creates MemoryService, spawns agent tasks
and the CLI interface concurrently via asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from src.agents.inference import InferenceAgent
from src.agents.validator import ValidatorAgent
from src.cli import run_cli
from src.interfaces import MemoryService
from src.llm import LLMTranslator
from src.store import StoreConfig, TripleStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
# Suppress noisy Neo4j warnings about unknown labels/properties on empty DB
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
# Suppress httpx request logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main() -> None:
    # Configuration from environment
    config = StoreConfig(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        username=os.environ.get("NEO4J_USERNAME", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "memory-system"),
    )
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    llm_model = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")

    # Connect to Neo4j
    logger.info("Connecting to Neo4j at %s", config.uri)
    store = await TripleStore.connect(config)
    logger.info("Connected to Neo4j")

    # Create the memory service
    llm = LLMTranslator(api_key=anthropic_key, model=llm_model)
    memory = MemoryService(store=store, llm=llm)

    # Create agents
    inference_agent = InferenceAgent(memory=memory, poll_interval=5.0)
    validator_agent = ValidatorAgent(memory=memory, poll_interval=8.0)

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
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
