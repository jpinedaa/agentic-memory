# Debugging Guide

How to configure logging, debug agent behavior, and create custom debug profiles.

## Quick Start

```bash
# Normal run (INFO level)
make dev

# Debug agents, LLM calls, and prompt rendering
make debug-agents
```

## Logging Architecture

All logging is configured via JSON files using Python's `logging.config.dictConfig` schema. The loader lives in `src/logging_config.py` and is called at startup by both entry points (`main.py`, `run_node.py`).

```
logging.json                  # default config (INFO level)
logging.debug-agents.json     # agent/LLM/prompt debugging
src/logging_config.py         # log_init() loader
```

### Config Resolution Order

`log_init()` picks the config file in this order:

1. **Function argument** — `log_init("/path/to/config.json")` (for tests or programmatic use)
2. **`LOG_CONFIG` env var** — `LOG_CONFIG=logging.debug-agents.json python main.py`
3. **Default** — `logging.json` in the project root

### Log Format

All configs use the same format:

```
2025-01-15 14:23:01,234 [src.agents.inference] DEBUG: Fetched 3 observations to process
│                         │                     │      └─ message
│                         │                     └─ level
│                         └─ module name (matches Python import path)
└─ timestamp
```

## Debug Profiles

### `logging.debug-agents.json` — Agent Debugging

**Makefile:** `make debug-agents`

Sets DEBUG on these modules while keeping everything else at INFO:

| Module | What you see at DEBUG |
|--------|----------------------|
| `src.agents.base` | Event vs poll wakeup, tick timing, claim counts |
| `src.agents.inference` | Skip reasons (stale, already processed, empty, lock), observation text preview |
| `src.agents.validator` | Claim count, subject grouping, pair skip reasons |
| `src.llm` | API call params (model, text length), response stats (stop_reason, token usage), tool extraction |
| `src.prompts` | Template loading (cache hit/miss, file path), inheritance chain, render output sizes |

**Example output:**

```
2025-01-15 14:23:01,200 [src.agents.base] DEBUG: Agent inference_agent woke: event received
2025-01-15 14:23:01,201 [src.agents.inference] DEBUG: Fetched 3 observations to process
2025-01-15 14:23:01,202 [src.agents.inference] DEBUG: Skipping already-processed observation obs-001
2025-01-15 14:23:01,203 [src.agents.inference] INFO: InferenceAgent processing observation: obs-002
2025-01-15 14:23:01,203 [src.agents.inference] DEBUG: Observation text: The user prefers dark mode...
2025-01-15 14:23:01,204 [src.prompts] DEBUG: _load_raw: loading /path/to/prompts/inference_agent/infer.yaml
2025-01-15 14:23:01,205 [src.prompts] DEBUG: _resolve_inheritance: infer extends shared/base
2025-01-15 14:23:01,206 [src.prompts] DEBUG: load: inference_agent/infer (version=1.0)
2025-01-15 14:23:01,207 [src.prompts] DEBUG: render: template=infer, vars=['observation_text', ...], system=342 chars, user=128 chars
2025-01-15 14:23:01,208 [src.llm] DEBUG: extract_observation: model=claude-sonnet-4-20250514, text=45 chars
2025-01-15 14:23:02,500 [src.llm] DEBUG: extract_observation: stop_reason=end_turn, usage=Usage(input_tokens=234, output_tokens=89)
2025-01-15 14:23:02,501 [src.llm] DEBUG: tool_use: name=record_observation, keys=['entities', 'extractions', 'topics']
2025-01-15 14:23:02,502 [src.agents.base] DEBUG: Agent inference_agent tick: 1 claim(s) in 1298ms
2025-01-15 14:23:02,503 [src.agents.base] INFO: Agent inference_agent claimed: The user prefers dark mode for...
```

## Creating Custom Debug Profiles

Copy an existing config and adjust the `loggers` section:

```bash
cp logging.json logging.debug-p2p.json
```

Edit the `loggers` block to add modules at DEBUG:

```json
{
  "loggers": {
    "neo4j.notifications": { "level": "ERROR" },
    "httpx": { "level": "WARNING" },
    "websockets": { "level": "WARNING" },
    "src.p2p.node": { "level": "DEBUG" },
    "src.p2p.transport": { "level": "DEBUG" },
    "src.p2p.gossip": { "level": "DEBUG" }
  }
}
```

Run it:

```bash
LOG_CONFIG=logging.debug-p2p.json .venv/bin/python main.py
```

Or add a Makefile target:

```makefile
debug-p2p: ## Run dev mode with P2P debug logging
	docker compose up neo4j -d
	LOG_CONFIG=logging.debug-p2p.json .venv/bin/python main.py
```

### Module Reference

All modules use `logging.getLogger(__name__)`, so logger names match Python import paths:

| Logger name | File | What it logs |
|-------------|------|-------------|
| `src.p2p.node` | `src/p2p/node.py` | Node lifecycle, bootstrap, peer join/leave, request dispatch, events |
| `src.p2p.transport` | `src/p2p/transport.py` | WebSocket connections, HTTP POST results, peer disconnects |
| `src.p2p.gossip` | `src/p2p/gossip.py` | Peer state updates from gossip rounds |
| `src.p2p.ui_bridge` | `src/p2p/ui_bridge.py` | UI bridge endpoint activity |
| `src.agents.base` | `src/agents/base.py` | Agent start/stop, event-driven wakeup, tick timing, errors |
| `src.agents.inference` | `src/agents/inference.py` | Observation filtering, skip reasons, inference results |
| `src.agents.validator` | `src/agents/validator.py` | Claim grouping, pair checks, contradiction detection |
| `src.llm` | `src/llm.py` | Claude API calls (params, response stats, tool extraction) |
| `src.prompts` | `src/prompts.py` | Template loading, cache, inheritance, render stats |
| `src.interfaces` | `src/interfaces.py` | MemoryService operations |
| `src.store` | `src/store.py` | Neo4j query execution |
| `src.cli` | `src/cli.py` | CLI command handling |

### Distributed Node Debugging

For distributed mode, set `LOG_CONFIG` per node:

```bash
# Terminal 1: Store node with default logging
python run_node.py --capabilities store,llm --port 9000

# Terminal 2: Inference node with debug logging
LOG_CONFIG=logging.debug-agents.json python run_node.py --capabilities inference --port 9001 --bootstrap http://localhost:9000
```

### Docker Debugging

Pass the env var through Docker Compose by adding to your service in `docker-compose.yml`:

```yaml
environment:
  - LOG_CONFIG=logging.debug-agents.json
```

Or override at runtime:

```bash
LOG_CONFIG=logging.debug-agents.json docker compose up inference-node
```

## Common Debug Scenarios

### "Why isn't the inference agent processing my observation?"

Run `make debug-agents` and look for:

- `Skipping stale observation` — observation timestamp is before agent start time
- `Skipping already-processed observation` — observation was handled in a previous tick
- `Skipping observation (empty raw_content)` — observation node has no text
- `Lock not acquired for observation` — another inference instance claimed it first

### "What prompt is being sent to Claude?"

With `debug-agents`, the `src.prompts` logger shows template loading and render sizes. The `src.llm` logger shows the API call parameters. For the full rendered prompt text, temporarily add a log line in `src/llm.py` before the API call:

```python
logger.debug("system prompt: %s", rendered["system"])
logger.debug("user prompt: %s", rendered["user"])
```

### "Why is the validator not finding contradictions?"

With `debug-agents`, look for:

- `Fetched N claims to validate` — are there enough claims?
- `Grouped into N subjects` — are claims grouped correctly by entity?
- `Skipping already-checked pair` — pair was flagged in a previous tick
- No pairs with `len(pred_claims) >= 2` means no claims share the same subject+predicate

### "Is the P2P network healthy?"

Create a `logging.debug-p2p.json` profile (see above) and watch for:

- Node bootstrap success/failure in `src.p2p.node`
- WebSocket connect/disconnect in `src.p2p.transport`
- Peer state updates in `src.p2p.gossip`
- Dead peer removal and re-bootstrap in `src.p2p.node`
