# Test Tracking

This document tracks tests for the Agentic Memory System — what's tested, what's missing, organization, and conventions.

---

## Running Tests

```bash
# All tests (requires Neo4j + API key)
pytest

# Store tests only (requires Neo4j, no API key)
pytest tests/test_store.py

# Skip LLM tests (no API key needed)
pytest -m "not llm"

# Verbose with output
pytest -v -s

# Single test
pytest tests/test_store.py::test_create_and_get_node
```

---

## Test Inventory

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

**Status:** ✅ Passing (10 tests)

---

### `tests/test_llm.py` — Claude API Translation Layer

**Requires:** Neo4j + `ANTHROPIC_API_KEY`
**Markers:** `@pytest.mark.llm`

| Test | What It Verifies |
|------|------------------|
| `test_extract_observation` | Observation text → ObservationData (entities, extractions, topics) |
| `test_parse_claim` | Claim text → ClaimData (subject, predicate, object, confidence) |
| `test_parse_claim_with_contradiction` | Detects contradiction language in claim |
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

**Status:** ✅ Passing (1 test) — tests in-process mode; distributed mode not yet tested

---

## Coverage Gaps

### Not Yet Tested

| Component | File | Priority | Notes |
|-----------|------|----------|-------|
| **API Endpoints** | `src/api.py` | HIGH | No `test_api.py` yet |
| **HTTP Client** | `src/api_client.py` | MEDIUM | Should test against mock/real API |
| **EventBus** | `src/events.py` | MEDIUM | Redis pub/sub |
| **AgentState** | `src/agent_state.py` | MEDIUM | Redis sets + distributed locks |
| **InferenceAgent** | `src/agents/inference.py` | MEDIUM | Agent logic |
| **ValidatorAgent** | `src/agents/validator.py` | MEDIUM | Contradiction detection |
| **CLI** | `src/cli.py` | LOW | Interactive, hard to test |

### Recently Added

| Test File | Tests | Notes |
|-----------|-------|-------|
| `test_prompts.py` | 13 | Full coverage of prompt template system |
| `conftest.py` | — | Loads .env, registers custom markers |

### Future Improvements

| Test File | Improvement | Notes |
|-----------|-------------|-------|
| `test_integration.py` | Add distributed mode variant | Currently only tests in-process |
| `test_api.py` | Create | Test HTTP endpoints with TestClient |

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

## Test Plan: API Endpoints

Priority tests to add for `src/api.py`:

```python
# tests/test_api.py

async def test_health_endpoint():
    """GET /v1/health returns 200."""

async def test_observe_endpoint():
    """POST /v1/observe creates observation."""

async def test_claim_endpoint():
    """POST /v1/claim creates claim."""

async def test_remember_endpoint():
    """POST /v1/remember returns response."""

async def test_infer_endpoint():
    """POST /v1/infer returns claim or null."""

async def test_recent_observations():
    """GET /v1/observations/recent returns list."""

async def test_recent_claims():
    """GET /v1/claims/recent returns list."""

async def test_clear_endpoint():
    """POST /v1/admin/clear wipes database."""
```

---

*Document version: 0.1*
*Last updated: 2026-01-28*
