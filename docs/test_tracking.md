# Test Tracking

This document tracks tests for the Agentic Memory System — what's tested, what's missing, organization, and conventions.

---

## Running Tests

```bash
# Unit tests only (no external deps)
make test-unit

# All tests that don't need Neo4j or API key
make test

# Store tests (needs Neo4j)
make test-store

# All tests (needs Neo4j + API key)
make test-all

# End-to-end in Docker (needs API key)
make test-e2e

# Verbose / single test
pytest -v -s
pytest tests/test_p2p.py::TestRoutingTable::test_route_method_observe
```

---

## Test Inventory

### `tests/test_p2p.py` — P2P Protocol Layer

**Requires:** Nothing (unit tests)
**API Key:** No

| Test Class | Tests | What It Verifies |
|------------|-------|------------------|
| `TestCapability` | 2 | Enum values and string conversion |
| `TestPeerInfo` | 3 | Frozen dataclass, serialization round-trip |
| `TestPeerState` | 2 | Serialization round-trip, mutability |
| `TestGenerateNodeId` | 2 | Format and uniqueness |
| `TestEnvelope` | 3 | Defaults, serialization, unique IDs |
| `TestRoutingTable` | 16 | Add/remove peers, capability routing, exclusions, dead filtering, last_seen refresh |
| `TestMethodCapabilities` | 4 | Correct capability mapping for all MemoryAPI methods |
| `TestLocalAgentState` | 7 | Processed sets, locks, independence |
| `TestAdvertiseHost` | 2 | Advertise host overrides listen host in PeerInfo URLs |
| `TestNodeDispatch` | 8 | Ping/pong, join/welcome, leave, gossip, dedup, request handling, events |
| `TestP2PMemoryClient` | 8 | Local execution, remote failure, all MemoryAPI methods |
| `TestWorkerAgent` | 1 | Event-driven wakeup |
| `TestUrlOverrides` | 3 | Bootstrap URL remapping, no-op when not needed, gossip preserves overrides |

**Status:** ✅ Passing (61 tests)

---

### `tests/test_prompts.py` — Prompt Template System

**Requires:** Nothing (unit tests)
**API Key:** No

| Test | What It Verifies |
|------|------------------|
| `test_load_prompt` | Load prompt by path |
| `test_prompt_not_found` | FileNotFoundError for missing |
| `test_list_prompts` | List all available prompts |
| `test_inheritance` | Child inherits from parent |
| `test_render_with_pydantic_vars` | Render with typed model |
| `test_render_with_dict_vars` | Render with plain dict |
| `test_jinja2_conditionals` | `{% if %}` blocks work |
| `test_jinja2_loops` | `{% for %}` blocks work |
| `test_render_system_only` | `render_system()` helper |
| `test_render_user_only` | `render_user()` helper |
| `test_observation_vars_validation` | Pydantic validation |
| `test_inference_vars_defaults` | Default values |
| `test_synthesis_vars_with_results` | Complex vars |

**Status:** ✅ Passing (13 tests)

---

### `tests/test_store.py` — Neo4j Storage Layer

**Requires:** Neo4j running
**API Key:** No

| Test | What It Verifies |
|------|------------------|
| `test_create_and_get_node` | Basic node CRUD |
| `test_get_nonexistent_node` | Returns None for missing nodes |
| `test_create_relationship` | Relationship creation and retrieval |
| `test_query_by_type` | Filtering nodes by type property |
| `test_find_claims_about` | Finding claims linked to an entity |
| `test_find_claims_excludes_superseded` | Superseded claims are filtered out |
| `test_find_unresolved_contradictions` | Finds claim pairs with CONTRADICTS relationship |
| `test_get_or_create_entity` | Entity upsert logic |
| `test_find_recent_observations` | Timestamp ordering, limit |
| `test_clear_all` | Database wipe |

**Status:** ✅ Passing (10 tests, needs Neo4j)

---

### `tests/test_llm.py` — Claude API Translation Layer

**Requires:** `ANTHROPIC_API_KEY`
**Markers:** `@pytest.mark.llm`

| Test | What It Verifies |
|------|------------------|
| `test_extract_observation` | Observation text → ObservationData |
| `test_parse_claim` | Claim text → ClaimData |
| `test_parse_claim_with_contradiction` | Detects contradiction language |
| `test_generate_query` | Natural language → Cypher query |
| `test_synthesize_response` | Graph results → natural language answer |

**Status:** ✅ Passing (5 tests)

---

### `tests/test_interfaces.py` — MemoryService API

**Requires:** Neo4j + `ANTHROPIC_API_KEY`
**Markers:** `@pytest.mark.llm` (most tests)

| Test | What It Verifies |
|------|------------------|
| `test_text_overlap` | Helper function for basis matching |
| `test_observe` | Full observation flow (LLM extraction → Neo4j storage) |
| `test_claim` | Full claim flow (LLM parsing → Neo4j storage + linking) |
| `test_remember` | Query → Cypher → results → synthesis |

**Status:** ✅ Passing (4 tests)

---

### `tests/test_integration.py` — End-to-End Scenarios

**Requires:** Neo4j + `ANTHROPIC_API_KEY`
**Markers:** `@pytest.mark.llm`

| Test | What It Verifies |
|------|------------------|
| `test_meeting_preferences_scenario` | Full flow: observe → infer → contradict → remember |

**Status:** ✅ Passing (1 test)

---

## Coverage Gaps

### Not Yet Tested

| Component | File | Priority | Notes |
|-----------|------|----------|-------|
| **UI Bridge** | `src/p2p/ui_bridge.py` | MEDIUM | WebSocket snapshot, stats endpoint, event forwarding |
| **Transport layer** | `src/p2p/transport.py` | MEDIUM | Server start/stop, WebSocket connections (needs real network) |
| **Gossip convergence** | `src/p2p/gossip.py` | MEDIUM | Multi-node gossip propagation (integration test) |
| **Multi-node e2e** | `run_node.py` | HIGH | Full P2P network with real nodes |
| **InferenceAgent** | `src/agents/inference.py` | MEDIUM | Agent processing logic with mock memory |
| **ValidatorAgent** | `src/agents/validator.py` | MEDIUM | Contradiction detection logic |
| **CLI** | `src/cli.py` | LOW | Interactive, hard to test |

---

## Test Conventions

### Markers

```python
@pytest.mark.llm          # Requires ANTHROPIC_API_KEY
@pytest.mark.slow         # Takes > 5 seconds
@pytest.mark.integration  # End-to-end scenarios
```

### Fixtures

| Fixture | Scope | Provides |
|---------|-------|----------|
| `store` | function | Fresh TripleStore connection, cleared after test |
| `translator` | module | LLMTranslator instance (reused) |
| `memory` | function | MemoryService with fresh store |
| `system` | function | Full system setup for integration tests |

### Naming

- Test files: `test_<module>.py`
- Test functions: `test_<what>_<scenario>` (e.g., `test_find_claims_excludes_superseded`)
- Use descriptive names — tests are documentation

### Assertions

- Prefer specific assertions over generic `assert x`
- Check types and structure, not just truthiness
- For LLM tests, allow flexibility in exact wording but verify structure

---

*Document version: 0.3*
*Last updated: 2026-01-29*
