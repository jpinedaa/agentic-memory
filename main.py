"""Entry point for the Agentic Memory System (dev mode).

Runs everything in-process: spawns P2P nodes for store+llm, inference,
validation, and CLI on localhost with different ports.

No external dependencies beyond Neo4j and a Claude API key.
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main() -> None:
    from src.p2p.types import Capability
    from src.p2p.node import PeerNode
    from src.p2p.memory_client import P2PMemoryClient
    from src.p2p.local_state import LocalAgentState
    from src.agents.inference import InferenceAgent
    from src.agents.validator import ValidatorAgent
    from src.cli import run_cli
    from src.interfaces import MemoryService
    from src.llm import LLMTranslator
    from src.store import StoreConfig, TripleStore

    # ── Store + LLM node ────────────────────────────────────────────
    config = StoreConfig(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        username=os.environ.get("NEO4J_USERNAME", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "memory-system"),
    )
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    llm_model = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")

    logger.info("Connecting to Neo4j at %s", config.uri)
    store = await TripleStore.connect(config)
    logger.info("Connected to Neo4j")

    llm = LLMTranslator(api_key=anthropic_key, model=llm_model)
    memory_service = MemoryService(store=store, llm=llm)

    store_node = PeerNode(
        capabilities={Capability.STORE, Capability.LLM},
        listen_host="127.0.0.1",
        listen_port=9000,
        node_id="store-node",
    )
    store_node.register_service("memory", memory_service)
    store_node.register_service("store", store)
    store_node.register_service("llm", llm)
    store_node.transport_server.mount_ui_bridge(store)
    await store_node.start()

    bootstrap = ["http://127.0.0.1:9000"]

    # ── Inference node ──────────────────────────────────────────────
    inference_node = PeerNode(
        capabilities={Capability.INFERENCE},
        listen_host="127.0.0.1",
        listen_port=9001,
        bootstrap_peers=bootstrap,
        node_id="inference-node",
    )
    await inference_node.start()

    inference_memory = P2PMemoryClient(inference_node)
    state = LocalAgentState()
    inference_agent = InferenceAgent(
        memory=inference_memory, poll_interval=5.0, state=state
    )
    inference_node.add_event_listener(inference_agent.on_network_event)

    # ── Validator node ──────────────────────────────────────────────
    validator_node = PeerNode(
        capabilities={Capability.VALIDATION},
        listen_host="127.0.0.1",
        listen_port=9002,
        bootstrap_peers=bootstrap,
        node_id="validator-node",
    )
    await validator_node.start()

    validator_memory = P2PMemoryClient(validator_node)
    validator_state = LocalAgentState()
    validator_agent = ValidatorAgent(
        memory=validator_memory, poll_interval=8.0, state=validator_state
    )
    validator_node.add_event_listener(validator_agent.on_network_event)

    # ── CLI node ────────────────────────────────────────────────────
    cli_node = PeerNode(
        capabilities={Capability.CLI},
        listen_host="127.0.0.1",
        listen_port=9003,
        bootstrap_peers=bootstrap,
        node_id="cli-node",
    )
    await cli_node.start()

    cli_memory = P2PMemoryClient(cli_node)

    # ── Run everything ──────────────────────────────────────────────
    try:
        await asyncio.gather(
            run_cli(cli_memory),
            inference_agent.run(),
            validator_agent.run(),
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        inference_agent.stop()
        validator_agent.stop()
        await cli_node.stop()
        await validator_node.stop()
        await inference_node.stop()
        await store_node.stop()
        await store.close()
        await state.close()
        await validator_state.close()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
