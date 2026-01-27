# Agentic Memory System

## Project Overview

A shared memory substrate where multiple agents interact via natural language, backed by a Neo4j graph database storing triples. See `design_tracking.md` for full design and architecture.

Core API: `MemoryService` in `src/interfaces.py` exposes `observe()`, `claim()`, `remember()`.

## Developer Environment

### Prerequisites

- Python 3.11+
- Docker (for Neo4j)
- `ANTHROPIC_API_KEY` environment variable set

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d
cp .env.example .env       # then edit .env with your API key
```

### Running

```bash
source .venv/bin/activate
python main.py             # loads .env automatically
```

CLI usage: plain text records an observation, `?query` asks a question, `/quit` exits.

### Running Tests

```bash
# Store tests only (needs Neo4j running)
pytest tests/test_store.py

# All tests including LLM (needs Neo4j + ANTHROPIC_API_KEY)
pytest

# Skip LLM tests
pytest -m "not llm"
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (none, required) | Claude API key |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USERNAME` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `memory-system` | Neo4j password |
| `LLM_MODEL` | `claude-sonnet-4-20250514` | Claude model to use |

## Architecture

```
main.py                 → asyncio.gather(cli, inference_agent, validator_agent)
src/cli.py              → stdin/stdout chat adapter
src/interfaces.py       → MemoryService (observe, claim, remember)
src/llm.py              → Claude API translation layer
src/store.py            → Neo4j async wrapper
src/agents/base.py      → WorkerAgent ABC (asyncio poll loop)
src/agents/inference.py → observations → claims
src/agents/validator.py → contradiction detection
```

## Development

- Do not worry about backward compatibility unless explicitly stated. When making updates, also update relevant code, design docs (`design_tracking.md`), and tests. Keep the codebase clean rather than patching.
- The memory service is framework-agnostic. Agents are thin clients of `MemoryService`. Do not couple agent framework logic into the core API.
- All store and interface methods are async. Use `await` consistently.
- Tests marked `@pytest.mark.llm` require a live Claude API key. Store tests only need Neo4j.
