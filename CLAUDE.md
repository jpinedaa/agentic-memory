# Agentic Memory System

## Project Briefing

This is a shared memory substrate where multiple AI agents interact via natural language, with a Neo4j graph database storing knowledge as reified triples. The graph uses four proper Neo4j labels: `:Concept` (named things/ideas/values), `:Statement` (reified triples with predicate, confidence, negation), `:Observation` (raw input), and `:Source` (provenance — who produced the knowledge). All knowledge flows through Statement nodes linked to subject/object Concepts via `ABOUT_SUBJECT`/`ABOUT_OBJECT`, with provenance via `DERIVED_FROM` and `ASSERTED_BY`. Compound concepts are decomposed via `RELATED_TO` edges (e.g., "peer-to-peer network" → "network" + "peer-to-peer"). There are no dynamic predicate edges — all assertions are Statement nodes. The system uses a peer-to-peer architecture (v0.3) where every node is identical in networking (HTTP server + WebSocket + HTTP client) and differs only in capabilities (store, LLM, inference, validation, CLI), coordinating via gossip with no centralized server or Redis. The React + D3.js dashboard (port 3000) is connected to the P2P backend via a UI bridge layer (`src/p2p/ui_bridge.py`). 109 non-LLM tests passing.

**Next up:** Multi-node integration tests, NAT traversal, TLS. See `docs/knowledge_representation.md` for the full knowledge model and `docs/visual_ui_design.md` for UI design decisions.

## Project Overview

A shared memory substrate where multiple agents interact via natural language, backed by a Neo4j graph database storing triples. See `docs/design_tracking.md` for full design and architecture.

Core API: `MemoryAPI` protocol in `src/memory_protocol.py` — implemented by `MemoryService` (in-process) and `P2PMemoryClient` (peer-to-peer routing).

## Quick Start (Make Targets)

```bash
make dev              # Full stack in Docker (builds latest, includes CLI)
make install          # Create venv and install dependencies (for local tests)
make test             # Run all tests (auto-skips if deps missing)
make help             # Show all available targets
```

### Individual Node Targets (for multi-terminal distributed mode)

```bash
make dev-store        # Store + LLM node on :9000
make dev-inference    # Inference node on :9001 (needs store node)
make dev-validator    # Validator node on :9002 (needs store node)
make dev-cli          # CLI node on :9003 (needs store node)
```

## Running Modes

### Dev Mode (full stack, Docker)

Builds and runs all services in Docker (Neo4j, store+LLM, inference, validator, CLI). `--build` ensures the latest code is always used. The Neo4j graph is wiped on every run for a clean slate. Requires a `.env` file (copy `.env.example` to `.env` and fill in your keys).

```bash
cp .env.example .env   # first time only — fill in ANTHROPIC_API_KEY
make dev
# Tears down any previous run (including Neo4j data), rebuilds all images,
# starts all services in background, waits for health checks, then attaches
# to the CLI container. Ctrl+C detaches and shuts down all containers cleanly.

# Use a custom env file path:
make dev ENV_FILE=~/secrets/memory.env
```

### Distributed Mode (multi-node)

Each node is a separate process. No Redis required.

```bash
# Option A: Docker (full stack)
docker compose up

# Option B: Make targets (one terminal per node)
make dev-store         # Terminal 1
make dev-inference     # Terminal 2
make dev-validator     # Terminal 3
make dev-cli           # Terminal 4

# Option C: Manual
docker compose up neo4j -d

python run_node.py --capabilities store,llm --port 9000
python run_node.py --capabilities inference --port 9001 --bootstrap http://localhost:9000
python run_node.py --capabilities validation --port 9002 --bootstrap http://localhost:9000
python run_node.py --capabilities cli --port 9003 --bootstrap http://localhost:9000
```

Scale agents: `docker compose up --scale inference-node=3`

### CLI Usage

- Plain text → records an observation
- `?query` → asks a question (remember)
- `/status` → shows graph contents
- `/clear` → wipes the graph
- `/quit` → exits

## Running Tests

```bash
make test                         # all tests (auto-skips if deps missing)
make test-all                     # starts Neo4j first, then runs all tests
make test-unit                    # unit tests only (no Neo4j, no API key)
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
| `LLM_MODEL` | `claude-sonnet-4-20250514` | Claude model |
| `NODE_PORT` | `9000` | Node listen port |
| `NODE_HOST` | `0.0.0.0` | Node bind host |
| `BOOTSTRAP_PEERS` | (none) | Comma-separated bootstrap peer URLs |
| `ADVERTISE_HOST` | (listen host) | Hostname other nodes use to reach this node (for Docker/k8s) |
| `LOG_CONFIG` | `logging.json` | Path to JSON logging dictConfig file |
| `POLL_INTERVAL` | `30` | Agent poll fallback interval (seconds) |
| `SCHEMA_PATH` | `data/schema.yaml` | Path to persistent schema file (store node) |

## Architecture

```
src/p2p/types.py        → PeerInfo, PeerState, Capability enum
src/p2p/messages.py      → Envelope (universal message wrapper)
src/p2p/routing.py       → RoutingTable + capability-based method routing
src/p2p/transport.py     → TransportServer (FastAPI) + TransportClient (httpx/ws)
src/p2p/gossip.py        → GossipProtocol (push-based, fanout to neighbors)
src/p2p/node.py          → PeerNode (core runtime, lifecycle, dispatch)
src/p2p/memory_client.py → P2PMemoryClient (implements MemoryAPI via peer routing)
src/p2p/local_state.py   → LocalAgentState (replaces Redis AgentState)
src/p2p/ui_bridge.py     → UI bridge (translates P2P state to /v1/ endpoints for React UI)
src/memory_protocol.py   → MemoryAPI protocol (shared contract)
src/interfaces.py        → MemoryService (in-process implementation)
src/llm.py               → Claude API translation layer (extract, parse, infer, query, synthesize)
src/prompts.py           → Prompt template loader (YAML + Jinja2 + Pydantic)
src/store.py             → Neo4j async wrapper
prompts/                 → YAML prompt templates (organized by agent)
src/cli.py               → stdin/stdout chat adapter
src/agents/base.py       → WorkerAgent ABC (event-driven + poll fallback)
src/agents/inference.py  → observations → claims
src/agents/validator.py  → schema-aware contradiction detection
src/schema/              → predicate schema (YAML bootstrap + loader + persistent store)
src/schema/store.py      → SchemaStore (persistent schema manager on store node)
main.py                  → dev mode (in-process, multiple P2P nodes)
run_node.py              → unified distributed node entry point
ui/                      → React + D3.js dashboard (separate container, port 3000)
```

## Debugging Running Nodes (make dev)

When the user has `make dev` running, you can query the live system to debug issues. The store node (port 9000) exposes HTTP endpoints:

```bash
# Node health + peer count
curl -s http://localhost:9000/p2p/health

# Full graph (nodes + edges) — uses ui_bridge, handles neo4j type serialization
curl -s http://localhost:9000/v1/graph/nodes

# Network + knowledge stats (observations, statements, concepts, sources, relationships)
curl -s http://localhost:9000/v1/stats

# Docker container logs per node
docker compose logs store-node --tail 30
docker compose logs inference-node --tail 30
docker compose logs validator-node --tail 30
docker compose logs cli-node --tail 30
```

**Ports**: store=9000, inference=9001, validator=9002, CLI=9003. In Docker, all nodes listen internally on :9000 but are mapped to these host ports.

**Tip**: The `/v1/graph/nodes` endpoint returns the complete graph with all nodes and edges — pipe through `python3 -m json.tool` or jq for readable output. You can filter for specific edge types (e.g., `CONTRADICTS`, `DERIVED_FROM`) to verify relationship creation.

## Development

**IMPORTANT: Always use the virtual environment or Docker for Python commands.**

```bash
# Activate venv before running any Python commands
source .venv/bin/activate

# Or use Docker for containerized execution
docker compose exec store-node python ...
```

All `python`, `pytest`, `pip`, and other Python commands must be run either:
1. Inside the activated `.venv` virtual environment, OR
2. Inside a Docker container via `docker compose exec`

Never run Python commands directly without the venv activated.

---

### Pipeline Ownership

| Concern | Owner | Method |
|---------|-------|--------|
| Raw recording | `observe()` | Creates Observation + Concept nodes only. Does NOT create Statements. |
| Statement creation | Inference agent | Calls `claim()` to create Statements from observations. |
| Contradiction detection | Validator agent | Calls `flag_contradiction(stmt_id_1, stmt_id_2, reason)` with exact IDs. Schema-aware via bootstrap `PredicateSchema`. |
| Resolution (supersession) | `claim()` | Uses `supersedes_description` for SUPERSEDES links. |

- `claim()` does NOT create CONTRADICTS links. The `contradicts_description` field was removed from ClaimData and the LLM tool schema.
- The validator loads the bootstrap schema (`src/schema/bootstrap.yaml`) and skips multi-valued predicates. Unknown predicates default to single-valued.

### General Rules

- Do not worry about backward compatibility unless explicitly stated. When making updates, also update relevant code, design docs (`docs/design_tracking.md`), and tests.
- All external access goes through the `MemoryAPI` protocol. Never access `.store` or `.llm` directly from agents or CLI.
- Agents receive `P2PMemoryClient` as their `memory` parameter. Use the protocol, not concrete types.
- Agent state (`_processed_obs`, `_checked_pairs`) uses `LocalAgentState`. Never use raw Python sets for tracking.
- All store and interface methods are async.
- Tests marked `@pytest.mark.llm` require a live Claude API key. Store tests only need Neo4j.

## P2P Protocol

### Node Types (by capability)

| Capability | What it provides | Dependencies |
|---|---|---|
| `store` | Neo4j access (observe, claim, query) | Neo4j |
| `llm` | Claude API (infer, parse claims) | Anthropic API key |
| `inference` | InferenceAgent logic | Needs `store`+`llm` peer |
| `validation` | ValidatorAgent logic | Needs `store` peer |
| `schema` | Schema evolution agent | Needs `store`+`llm` peer |
| `cli` | Interactive user I/O | Needs `store`+`llm` peer |

### Communication

- **HTTP POST** `/p2p/message` — request/response envelope exchange
- **WebSocket** `/p2p/ws` — persistent bidirectional for gossip + events
- **GET** `/p2p/health` — liveness check
- **Gossip** — push-based, every 5s, fanout to 3 random neighbors
- **Events** — flooded to neighbors with TTL-based hop limit + msg_id dedup + local listener notification
- **UI Bridge** — `/v1/ws`, `/v1/graph/nodes`, `/v1/stats` endpoints on store node for React UI

### Message Types

| Type | Purpose |
|---|---|
| `join` / `welcome` | Bootstrap discovery |
| `gossip` | Peer state propagation |
| `request` / `response` | MemoryAPI RPC |
| `event` | Observation/claim/contradiction broadcast |
| `ping` / `pong` | Liveness |
| `leave` | Graceful shutdown |

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

## GitHub

**Repo**: `jpinedaa/agentic-memory` (remote: `origin`)

### Issue Labels

| Label | Color | Usage |
|-------|-------|-------|
| `bug` | red | Something isn't working |
| `enhancement` | teal | New feature or request |
| `documentation` | blue | Docs improvements |
| `good first issue` | purple | Good for newcomers |
| `help wanted` | green | Extra attention needed |
| `question` | violet | Needs more information |
| `duplicate` | gray | Already exists |
| `invalid` | yellow | Doesn't seem right |
| `wontfix` | white | Will not be worked on |

### Issue Conventions

- Title: short imperative description of the problem or feature
- Body: structured with `## Summary`, root cause analysis, `## Files Involved` table, `## Reproduction` steps
- Include code snippets with file paths and line numbers for AI-parseable context
- Always assign at least one label (`bug`, `enhancement`, or `documentation`)
- Use `gh issue create --label <label> --title <title> --body <body>` via CLI

### Branch & PR Conventions

- Feature branches: `feature/<short-name>`
- Bug fix branches: `fix/<short-name>`
- Design branches: `<design-topic>-design` (e.g., `schema-evolution-design`)
- PRs target the main branch unless otherwise specified
