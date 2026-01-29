"""Unified entry point for P2P nodes.

Each node runs an HTTP+WebSocket server and connects to the P2P network.
Capabilities determine what the node can do:

    store      — Neo4j access (observe, claim, query, etc.)
    llm        — Claude API access (infer, parse claims, etc.)
    inference  — Runs the InferenceAgent
    validation — Runs the ValidatorAgent
    cli        — Interactive CLI for user input

Examples:

    # Store + LLM node (the "memory" node)
    python run_node.py --capabilities store,llm --port 9000

    # Inference agent node
    python run_node.py --capabilities inference --port 9001 --bootstrap http://localhost:9000

    # Validator node
    python run_node.py --capabilities validation --port 9002 --bootstrap http://localhost:9000

    # CLI node
    python run_node.py --capabilities cli --port 9003 --bootstrap http://localhost:9000
"""

from __future__ import annotations

import argparse
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a P2P agentic memory node")
    parser.add_argument(
        "--capabilities",
        type=str,
        required=True,
        help="Comma-separated capabilities: store,llm,inference,validation,cli",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("NODE_PORT", "9000")),
        help="Port to listen on (default: 9000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("NODE_HOST", "0.0.0.0"),
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--bootstrap",
        type=str,
        default=os.environ.get("BOOTSTRAP_PEERS", ""),
        help="Comma-separated bootstrap peer URLs",
    )
    parser.add_argument(
        "--node-id",
        type=str,
        default=None,
        help="Node ID (auto-generated if not provided)",
    )
    parser.add_argument(
        "--advertise-host",
        type=str,
        default=os.environ.get("ADVERTISE_HOST", ""),
        help="Hostname other nodes use to reach this node (default: same as --host)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("POLL_INTERVAL", "30")),
        help="Agent poll interval in seconds (default: 30)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    from src.p2p.types import Capability
    from src.p2p.node import PeerNode
    from src.p2p.memory_client import P2PMemoryClient
    from src.p2p.local_state import LocalAgentState

    # Parse capabilities
    cap_names = [c.strip() for c in args.capabilities.split(",") if c.strip()]
    capabilities = set()
    for name in cap_names:
        try:
            capabilities.add(Capability(name))
        except ValueError:
            logger.error(f"Unknown capability: {name}")
            return

    # Parse bootstrap peers
    bootstrap = [
        u.strip() for u in args.bootstrap.split(",") if u.strip()
    ]

    # Create the node
    node = PeerNode(
        capabilities=capabilities,
        listen_host=args.host,
        listen_port=args.port,
        bootstrap_peers=bootstrap,
        node_id=args.node_id,
        advertise_host=args.advertise_host or None,
    )

    # Register local services based on capabilities
    if Capability.STORE in capabilities or Capability.LLM in capabilities:
        await _setup_memory_service(node, capabilities)

    # Mount UI bridge on store nodes (must happen before start)
    if Capability.STORE in capabilities:
        store_service = node.get_service("store")
        if store_service:
            node.transport_server.mount_ui_bridge(store_service)

    # Start the node
    await node.start()

    # Create P2P memory client (for agents and CLI)
    memory = P2PMemoryClient(node)
    state = LocalAgentState()

    # Start agents and/or CLI based on capabilities
    tasks: list[asyncio.Task] = []

    if Capability.INFERENCE in capabilities:
        from src.agents.inference import InferenceAgent

        agent = InferenceAgent(
            memory=memory, poll_interval=args.poll_interval, state=state
        )
        node.add_event_listener(agent.on_network_event)
        tasks.append(asyncio.create_task(agent.run()))
        logger.info("Started InferenceAgent")

    if Capability.VALIDATION in capabilities:
        from src.agents.validator import ValidatorAgent

        agent = ValidatorAgent(
            memory=memory, poll_interval=args.poll_interval, state=state
        )
        node.add_event_listener(agent.on_network_event)
        tasks.append(asyncio.create_task(agent.run()))
        logger.info("Started ValidatorAgent")

    if Capability.CLI in capabilities:
        from src.cli import run_cli

        tasks.append(asyncio.create_task(run_cli(memory)))
        logger.info("Started CLI")

    if not tasks:
        # Pure service node (store/llm only) — just keep running
        logger.info("Running as service node (no agent/CLI)")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
    else:
        try:
            await asyncio.gather(*tasks)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

    # Shutdown
    await node.stop()
    await state.close()
    logger.info("Node shutdown complete")


async def _setup_memory_service(
    node: PeerNode, capabilities: set
) -> None:
    """Set up MemoryService with store and/or LLM based on capabilities."""
    from src.p2p.types import Capability

    store = None
    llm = None

    if Capability.STORE in capabilities:
        from src.store import StoreConfig, TripleStore

        config = StoreConfig(
            uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            username=os.environ.get("NEO4J_USERNAME", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "memory-system"),
        )
        logger.info("Connecting to Neo4j at %s", config.uri)
        store = await TripleStore.connect(config)
        logger.info("Connected to Neo4j")
        node.register_service("store", store)

    if Capability.LLM in capabilities:
        from src.llm import LLMTranslator

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        llm_model = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")
        llm = LLMTranslator(api_key=anthropic_key, model=llm_model)
        node.register_service("llm", llm)

    if store and llm:
        from src.interfaces import MemoryService

        memory_service = MemoryService(store=store, llm=llm)
        node.register_service("memory", memory_service)


if __name__ == "__main__":
    asyncio.run(main())
