"""CLI chat adapter.

Provides a stdin/stdout interface for interacting with the memory system.
Lines starting with '?' are treated as queries (remember).
All other lines are treated as observations (observe).
"""

from __future__ import annotations

import asyncio
import logging
import sys

from src.interfaces import MemoryService

logger = logging.getLogger(__name__)

HELP_TEXT = """
Agentic Memory System CLI
=========================
Commands:
  ?<query>    Ask a question (uses remember)
              Example: ?what are my meeting preferences?

  /quit       Exit the CLI
  /help       Show this help message

Anything else is recorded as an observation.
  Example: I prefer morning meetings
"""


async def run_cli(memory: MemoryService, source: str = "cli_user") -> None:
    """Run the interactive CLI loop."""
    print(HELP_TEXT)
    print("Ready. Type observations or ?queries:\n")

    loop = asyncio.get_event_loop()

    while True:
        try:
            # Read from stdin without blocking the event loop
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break

            line = line.strip()
            if not line:
                continue

            if line == "/quit":
                print("Goodbye.")
                break

            if line == "/help":
                print(HELP_TEXT)
                continue

            if line.startswith("?"):
                # Query mode
                query = line[1:].strip()
                if not query:
                    print("Usage: ?<your question>")
                    continue
                print(f"Thinking...")
                response = await memory.remember(query)
                print(f"\n{response}\n")
            else:
                # Observation mode
                print("Recording observation...")
                obs_id = await memory.observe(line, source=source)
                print(f"Recorded. (id: {obs_id[:8]}...)\n")

        except KeyboardInterrupt:
            print("\nGoodbye.")
            break
        except Exception:
            logger.exception("CLI error")
            print("Error processing input. Try again.")
