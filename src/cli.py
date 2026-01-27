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

  /status     Show current graph contents (observations, claims, entities)
  /clear      Clear all data from the graph
  /quit       Exit the CLI
  /help       Show this help message

Anything else is recorded as an observation.
  Example: I prefer morning meetings
"""


async def _print_status(memory: MemoryService) -> None:
    """Print a summary of the current graph state."""
    store = memory.store

    observations = await store.find_recent_observations(limit=50)
    claims = await store.find_recent_claims(limit=50)
    contradictions = await store.find_unresolved_contradictions()

    # Entities
    entities = await store.query_by_type("Entity")

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

            if line == "/status":
                await _print_status(memory)
                continue

            if line == "/clear":
                await memory.store.clear_all()
                print("Graph cleared.\n")
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
