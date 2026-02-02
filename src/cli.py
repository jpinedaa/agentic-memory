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


async def _print_status(memory: MemoryAPI) -> None:  # pylint: disable=too-many-locals  # status display aggregates many store queries
    """Print a summary of the current graph state."""
    observations = await memory.get_recent_observations(limit=50)
    statements = await memory.get_recent_statements(limit=50)
    contradictions = await memory.get_unresolved_contradictions()
    concepts = await memory.get_concepts()

    print("\n--- Graph Status ---\n")

    print(f"Concepts ({len(concepts)}):")
    for c in concepts:
        kind = c.get("kind", "")
        kind_str = f" [{kind}]" if kind else ""
        print(f"  - {c.get('name', c['id'][:8])}{kind_str}")

    print(f"\nObservations ({len(observations)}):")
    for o in observations:
        raw = o.get("raw_content", "")
        ts = str(o.get("created_at", ""))[:19]
        print(f"  [{ts}] {raw}")

    print(f"\nStatements ({len(statements)}):")
    for s in statements:
        subj = s.get("subject_name", "?")
        pred = s.get("predicate", "?")
        obj = s.get("object_name", "?")
        conf = s.get("confidence", "?")
        src = s.get("source", "")
        neg = "NOT " if s.get("negated") else ""
        print(f"  {subj} {neg}{pred} {obj} (confidence: {conf}, source: {src})")

    if contradictions:
        print(f"\nUnresolved Contradictions ({len(contradictions)}):")
        for s1, s2 in contradictions:
            o1 = s1.get("object_name", "?")
            o2 = s2.get("object_name", "?")
            subj = s1.get("subject_name", "?")
            pred = s1.get("predicate", "?")
            print(f"  {subj} {pred}: '{o1}' vs '{o2}'")
    else:
        print("\nNo unresolved contradictions.")

    print("\n--- End Status ---\n")


async def run_cli(  # pylint: disable=too-many-branches,too-many-statements
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
                print("Thinking...")
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
        except Exception:  # pylint: disable=broad-exception-caught  # CLI must not crash on transient errors
            logger.exception("CLI error")
            print("Error processing input. Try again.")
