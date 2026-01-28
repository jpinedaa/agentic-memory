# Agentic Memory System

## Project Briefing

This is a shared memory substrate where multiple AI agents interact via natural language, with a Neo4j graph database storing knowledge as triples (observations, claims, entities). The system evolved from a single-process prototype (v0.1) to a fully distributed architecture (v0.2) with FastAPI, Redis pub/sub, and containerized agents. Distributed mode is functional (`docker compose up`) and the core observe/claim/remember flow works.

**Just completed:** Built a prompt template system — all LLM prompts moved from hardcoded strings to YAML files in `prompts/` with Jinja2 templating, Pydantic validation, and inheritance (`extends: shared/base`). Code updated in `src/llm.py` and `src/interfaces.py` to use `src/prompts.py` loader.

**Next up:** Rebuild Docker containers and test end-to-end with the new prompt system. Then update tests for template changes. See `docs/meta_language_exploration.md` for prompt system design decisions.

## Project Overview

A shared memory substrate where multiple agents interact via natural language, backed by a Neo4j graph database storing triples. See `docs/design_tracking.md` for full design and architecture.

Core API: `MemoryAPI` protocol in `src/memory_protocol.py` — implemented by both `MemoryService` (in-process) and `MemoryClient` (HTTP).

## Running Modes

### Dev Mode (single process)

Everything runs in one process via asyncio. No Redis required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
docker compose up neo4j -d       # just Neo4j
cp .env.example .env             # edit with your API key
python main.py
```

### Distributed Mode (multi-process)

API server + agents as separate processes. Requires Redis.

```bash
# Option A: Docker (full stack)
docker compose up

# Option B: Local processes
docker compose up neo4j redis -d
uvicorn src.api:app --port 8000                    # terminal 1
python run_inference_agent.py                       # terminal 2
python run_validator_agent.py                       # terminal 3
python run_cli.py                                   # terminal 4
```

Scale agents: `docker compose up --scale inference-agent=3`

### CLI Usage

- Plain text → records an observation
- `?query` → asks a question (remember)
- `/status` → shows graph contents
- `/clear` → wipes the graph
- `/quit` → exits

## Running Tests

```bash
pytest tests/test_store.py        # store only (needs Neo4j)
pytest -m "not llm"               # skip LLM tests
pytest                            # all tests (needs Neo4j + API key)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Claude API key |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection |
| `NEO4J_USERNAME` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `memory-system` | Neo4j password |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `LLM_MODEL` | `claude-sonnet-4-20250514` | Claude model |
| `API_BASE_URL` | `http://localhost:8000` | API server URL (for agents/CLI) |
| `POLL_INTERVAL` | `30` | Agent poll fallback interval (seconds) |

## Architecture

```
src/memory_protocol.py  → MemoryAPI protocol (shared contract)
src/interfaces.py       → MemoryService (in-process implementation)
src/api.py              → FastAPI server (HTTP boundary)
src/api_client.py       → MemoryClient (HTTP implementation)
src/events.py           → EventBus (Redis pub/sub)
src/agent_state.py      → AgentState (Redis-backed sets + distributed locks)
src/llm.py              → Claude API translation layer (tool_use)
src/prompts.py          → Prompt template loader (YAML + Jinja2 + Pydantic)
src/store.py            → Neo4j async wrapper
prompts/                → YAML prompt templates (organized by agent)
src/cli.py              → stdin/stdout chat adapter
src/agents/base.py      → WorkerAgent ABC (event-driven + poll fallback)
src/agents/inference.py → observations → claims
src/agents/validator.py → contradiction detection
main.py                 → dev mode (in-process, asyncio.gather)
run_inference_agent.py  → distributed inference agent entry point
run_validator_agent.py  → distributed validator agent entry point
run_cli.py              → distributed CLI entry point
```

## Development

**IMPORTANT: Always use the virtual environment or Docker for Python commands.**

```bash
# Activate venv before running any Python commands
source .venv/bin/activate

# Or use Docker for containerized execution
docker compose exec api python ...
```

All `python`, `pytest`, `pip`, and other Python commands must be run either:
1. Inside the activated `.venv` virtual environment, OR
2. Inside a Docker container via `docker compose exec`

Never run Python commands directly without the venv activated.

---

- Do not worry about backward compatibility unless explicitly stated. When making updates, also update relevant code, design docs (`docs/design_tracking.md`), and tests.
- All external access goes through the `MemoryAPI` protocol. Never access `.store` or `.llm` directly from agents or CLI.
- Agents must work with both `MemoryService` (in-process) and `MemoryClient` (HTTP). Use the protocol, not concrete types.
- Agent state (`_processed_obs`, `_checked_pairs`) uses `AgentState` (Redis) or `InMemoryAgentState` (dev). Never use raw Python sets for tracking.
- All store and interface methods are async.
- Tests marked `@pytest.mark.llm` require a live Claude API key. Store tests only need Neo4j.

## Prompt System

Prompts are in `prompts/` directory as YAML files with Jinja2 templating and Pydantic validation.

```
prompts/
├── shared/base.yaml           # Shared constraints (inherited)
├── llm_translator/            # Prompts for src/llm.py
├── inference_agent/           # Prompts for inference agent
└── validator_agent/           # Prompts for validator agent
```

Usage:
```python
from src.prompts import PromptLoader, InferenceVars

loader = PromptLoader()
prompt = loader.load("inference_agent/infer")
rendered = prompt.render(InferenceVars(observation_text="..."))
# rendered["system"], rendered["user"]
```

Features:
- **Inheritance**: `extends: shared/base` injects shared constraints
- **Jinja2**: `{% if include_reasoning %}...{% endif %}` for conditionals
- **Pydantic**: Type-checked variables (`InferenceVars`, `ClaimVars`, etc.)
- **Versioning**: Each prompt has `version` metadata
