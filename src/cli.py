"""CLI chat adapter.

Provides a stdin/stdout interface for interacting with the memory system.
Uses MemoryAPI protocol — works with both in-process MemoryService
and HTTP MemoryClient.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.memory_protocol import MemoryAPI

logger = logging.getLogger(__name__)

HELP_TEXT = """
Agentic Memory System CLI
=========================
Commands:
  ?<query>    Ask a question (uses remember)
              Example: ?what are my meeting preferences?

  /status     Show current graph contents (observations, claims, entities)
  /clear      Clear all data from the graph
  /quit       Exit the CLI
  /help       Show this help message

Anything else is recorded as an observation.
  Example: I prefer morning meetings
"""


async def _print_status(memory: MemoryAPI) -> None:
    """Print a summary of the current graph state."""
    observations = await memory.get_recent_observations(limit=50)
    claims = await memory.get_recent_claims(limit=50)
    contradictions = await memory.get_unresolved_contradictions()
    entities = await memory.get_entities()

    print("\n--- Graph Status ---\n")

    print(f"Entities ({len(entities)}):")
    for e in entities:
        print(f"  - {e.get('name', e['id'][:8])}")

    print(f"\nObservations ({len(observations)}):")
    for o in observations:
        raw = o.get("raw_content", "")
        ts = o.get("timestamp", "")[:19]
        src = o.get("source", "")
        print(f"  [{ts}] ({src}) {raw}")

    print(f"\nClaims ({len(claims)}):")
    for c in claims:
        subj = c.get("subject_text", "?")
        pred = c.get("predicate_text", "?")
        obj = c.get("object_text", "?")
        conf = c.get("confidence", "?")
        src = c.get("source", "")
        node_type = c.get("type", "Claim")
        label = "RESOLUTION" if node_type == "Resolution" else "claim"
        print(f"  [{label}] {subj} {pred} {obj} (confidence: {conf}, source: {src})")

    if contradictions:
        print(f"\nUnresolved Contradictions ({len(contradictions)}):")
        for c1, c2 in contradictions:
            o1 = c1.get("object_text", "?")
            o2 = c2.get("object_text", "?")
            subj = c1.get("subject_text", "?")
            pred = c1.get("predicate_text", "?")
            print(f"  {subj} {pred}: '{o1}' vs '{o2}'")
    else:
        print("\nNo unresolved contradictions.")

    print("\n--- End Status ---\n")


async def run_cli(
    memory: MemoryAPI,
    source: str = "cli_user",
    on_action: Any | None = None,
) -> None:
    """Run the interactive CLI loop.

    Args:
        memory: Memory API implementation.
        source: Source label for observations.
        on_action: Optional callback invoked after each user action.
    """
    print(HELP_TEXT)
    print("Ready. Type observations or ?queries:\n")

    loop = asyncio.get_event_loop()

    while True:
        try:
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

            if line == "/status":
                await _print_status(memory)
                if on_action:
                    on_action()
                continue

            if line == "/clear":
                await memory.clear()
                print("Graph cleared.\n")
                if on_action:
                    on_action()
                continue

            if line.startswith("?"):
                query = line[1:].strip()
                if not query:
                    print("Usage: ?<your question>")
                    continue
                print(f"Thinking...")
                response = await memory.remember(query)
                print(f"\n{response}\n")
                if on_action:
                    on_action()
            else:
                print("Recording observation...")
                obs_id = await memory.observe(line, source=source)
                print(f"Recorded. (id: {obs_id[:8]}...)\n")
                if on_action:
                    on_action()

        except KeyboardInterrupt:
            print("\nGoodbye.")
            break
        except Exception:
            logger.exception("CLI error")
            print("Error processing input. Try again.")
