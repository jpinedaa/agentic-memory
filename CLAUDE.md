# Agentic Memory System

## Project Briefing

This is a shared memory substrate where multiple AI agents interact via natural language, with a Neo4j graph database storing knowledge as triples (observations, claims, entities). The system uses a peer-to-peer architecture (v0.3) where every node is identical in networking (HTTP server + WebSocket + HTTP client) and differs only in capabilities (store, LLM, inference, validation, CLI). Nodes discover each other via seed URLs, maintain WebSocket neighbor connections, and propagate state via gossip. No centralized API server or Redis — all coordination is peer-to-peer.

**Just completed:** Built the UI bridge layer (`src/p2p/ui_bridge.py`) that translates P2P network state into `/v1/` endpoints the React frontend expects. Fixed cross-network connectivity (bootstrap URL remapping for Docker ↔ localhost). Added auto-reconnect when all peers die. Enhanced the UI with a status sidebar in Agent Topology showing per-node-type stats, knowledge counts, and network metrics. Fixed D3 knowledge graph rendering and event stream forwarding.

**Next up:** Multi-node integration tests, NAT traversal, TLS. See `docs/visual_ui_design.md` for UI design decisions.

## Project Overview

A shared memory substrate where multiple agents interact via natural language, backed by a Neo4j graph database storing triples. See `docs/design_tracking.md` for full design and architecture.

Core API: `MemoryAPI` protocol in `src/memory_protocol.py` — implemented by `MemoryService` (in-process) and `P2PMemoryClient` (peer-to-peer routing).

## Running Modes

### Dev Mode (single process)

Spawns all P2P nodes in-process on localhost with different ports.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
docker compose up neo4j -d       # just Neo4j
cp .env.example .env             # edit with your API key
python main.py
```

### Distributed Mode (multi-node)

Each node is a separate process. No Redis required.

```bash
# Option A: Docker (full stack)
docker compose up

# Option B: Local processes
docker compose up neo4j -d

# Terminal 1: Store + LLM node
python run_node.py --capabilities store,llm --port 9000

# Terminal 2: Inference node
python run_node.py --capabilities inference --port 9001 --bootstrap http://localhost:9000

# Terminal 3: Validator node
python run_node.py --capabilities validation --port 9002 --bootstrap http://localhost:9000

# Terminal 4: CLI node
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
| `POLL_INTERVAL` | `30` | Agent poll fallback interval (seconds) |

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
src/llm.py               → Claude API translation layer (tool_use)
src/prompts.py           → Prompt template loader (YAML + Jinja2 + Pydantic)
src/store.py             → Neo4j async wrapper
prompts/                 → YAML prompt templates (organized by agent)
src/cli.py               → stdin/stdout chat adapter
src/agents/base.py       → WorkerAgent ABC (event-driven + poll fallback)
src/agents/inference.py  → observations → claims
src/agents/validator.py  → contradiction detection
main.py                  → dev mode (in-process, multiple P2P nodes)
run_node.py              → unified distributed node entry point
ui/                      → React + D3.js dashboard (separate container, port 3000)
```

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
| `event` | Observation/claim broadcast |
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
