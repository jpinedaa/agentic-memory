# Validation & Contradiction Redesign

Tracking the rethink of how contradictions are detected, recorded, and resolved.

---

## 1. Problems (Resolved)

### 1.1 Contradiction pipeline was fragile

The validator detected contradictions correctly (same subject + same predicate + different object), but the mechanism for recording them was a lossy round-trip:

1. Validator finds two Statement nodes with matching subject/predicate but different objects
2. Validator produced a **natural language claim** like `"the statement that user has name 'jorge' contradicts the statement that user has name 'juan'"`
3. This claim text got fed through `memory.claim()` → LLM `parse_claim()` → text-based `_find_matching_node()`
4. The LLM had to correctly set `contradicts_description`, and the text overlap heuristic had to match it back to the right node

**Fix**: The validator now calls `memory.flag_contradiction(stmt_id_1, stmt_id_2, reason)` directly, creating the `CONTRADICTS` relationship by exact ID without any LLM round-trip.

### 1.2 No semantic understanding of predicates

The validator treated all same-subject-same-predicate-different-object pairs as contradictions. But:

- `user has hobby chess` and `user has hobby painting` — not a contradiction (multi-valued)
- `user has name jorge` and `user has name juan` — possibly a contradiction, possibly not (nickname vs legal name)
- `user lives in madrid` and `user lives in tokyo` — contradiction if concurrent, not if temporal

**Fix**: A bootstrap predicate schema (`src/schema/bootstrap.yaml`) defines cardinality, temporality, and exclusivity groups. The validator checks the schema before flagging — multi-valued predicates are skipped, exclusivity group violations are caught.

### 1.3 Contradictions shouldn't auto-supersede

Two conflicting statements should coexist in juxtaposition — both live, linked by `CONTRADICTS` — until there's actual evidence or explicit input that one replaces the other. The current design supports this (SUPERSEDES is separate from CONTRADICTS), but the full lifecycle from "tension detected" to "tension resolved" needs clearer definition.

---

## 2. Direct ID Linking (Implemented)

The `flag_contradiction(stmt_id_1, stmt_id_2, reason)` method was added to the full API stack:

- **`MemoryAPI` protocol** (`src/memory_protocol.py`) — new method signature
- **`MemoryService`** (`src/interfaces.py`) — creates `CONTRADICTS` relationship directly via `store.create_relationship()`
- **`P2PMemoryClient`** (`src/p2p/memory_client.py`) — routes to STORE capability
- **Routing** (`src/p2p/routing.py`) — `flag_contradiction` requires only `{Capability.STORE}`
- **Event broadcasting** — `flag_contradiction` triggers network event propagation

The validator calls this method directly with the exact statement IDs it already has, eliminating the LLM round-trip entirely.

---

## 3. Bootstrap Schema (Implemented)

A static predicate schema provides the validator with semantic knowledge about predicates:

**Location**: `src/schema/bootstrap.yaml`
**Loader**: `src/schema/loader.py` → `PredicateSchema` class

**Schema properties per predicate:**
- `cardinality`: `single` or `multi` (default: `single`)
- `temporality`: `permanent`, `temporal`, or `unknown` (default: `unknown`)
- `aliases`: list of synonym predicates that resolve to a canonical name

**Exclusivity groups**: Sets of predicates where at most one can be true per subject (e.g., gender identity, marital status).

**Validator behavior with schema:**
- Multi-valued predicates (e.g., `has_hobby`) → skip, not a contradiction
- Unknown predicates → treated as single-valued (conservative default)
- Exclusivity group violations → flagged as contradictions across different predicates
- No schema provided → all diff-object pairs flagged (backward compatible)

The bootstrap schema is a stepping stone. It will become the seed data for the future [schema agent](schema_agent_design.md), which will learn and evolve predicate properties dynamically.

---

## 4. Contradiction Lifecycle

```
Tension Detected
  │
  ├── Both statements live, CONTRADICTS link
  │
  ▼
Juxtaposition (default state)
  │
  ├── Agents and users can see both sides
  ├── May be reclassified as not actually contradictory
  │
  ▼
Resolution (requires evidence)
  │
  ├── New observation explicitly resolves: "Actually my name is Juan, not Jorge"
  ├── SUPERSEDES link created, old statement filtered from active queries
  │
  ▼
Archived
  │
  └── Superseded statement still in graph for provenance, but excluded from active knowledge
```

---

## 5. Implementation Phases

| Phase | Scope | Status |
|---|---|---|
| 1. Fix validator ID linking | Validator creates CONTRADICTS directly via `flag_contradiction()` instead of LLM round-trip | **Done** |
| 2. Bootstrap schema | Static YAML schema with predicate cardinality, temporality, exclusivity groups; validator checks schema before flagging | **Done** |
| 3. Contradiction lifecycle | Full tension → juxtaposition → resolution → archive flow | Not started |
| 4. Dynamic schema agent | Schema agent observes predicate patterns and evolves schema — depends on [schema agent design](schema_agent_design.md) | Not started |

---

## See Also

- [Knowledge Representation](knowledge_representation.md) — Current data model
- [Schema Agent Design](schema_agent_design.md) — Dynamic schema layer (separate concern)
- [Design Tracking](design_tracking.md) — System architecture

---

*Document version: 0.2*
*Last updated: 2026-02-02*
*Status: Phases 1-2 implemented. Direct ID linking and bootstrap schema active. Contradiction lifecycle design next.*
