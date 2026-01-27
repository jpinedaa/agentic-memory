"""Standalone CLI entry point.

Connects to the API server via HTTP.
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from src.api_client import MemoryClient
from src.cli import run_cli

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main() -> None:
    api_url = os.environ.get("API_BASE_URL", "http://localhost:8000")

    logger.info(f"CLI connecting to API at {api_url}")
    memory = MemoryClient(base_url=api_url)

    try:
        await run_cli(memory)
    finally:
        await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
