# Validation & Contradiction Redesign

Tracking the rethink of how contradictions are detected, recorded, and resolved.

---

## 1. Current Problems

### 1.1 Contradiction pipeline is fragile

The validator detects contradictions correctly (same subject + same predicate + different object), but the mechanism for recording them is a lossy round-trip:

1. Validator finds two Statement nodes with matching subject/predicate but different objects
2. Validator produces a **natural language claim** like `"the statement that user has name 'jorge' contradicts the statement that user has name 'juan'"`
3. This claim text gets fed through `memory.claim()` → LLM `parse_claim()` → text-based `_find_matching_node()`
4. The LLM must correctly set `contradicts_description`, and the text overlap heuristic must match it back to the right node

Steps 3-4 are unreliable. The validator already has the exact IDs of both statements — forcing a round-trip through natural language and text matching loses information for no benefit.

### 1.2 No semantic understanding of predicates

The validator treats all same-subject-same-predicate-different-object pairs as contradictions. But:

- `user has hobby chess` and `user has hobby painting` — not a contradiction (multi-valued)
- `user has name jorge` and `user has name juan` — possibly a contradiction, possibly not (nickname vs legal name)
- `user lives in madrid` and `user lives in tokyo` — contradiction if concurrent, not if temporal

Without knowledge about predicates, the validator is both too aggressive (flagging multi-valued predicates) and too naive (can't reason about temporality or context).

### 1.3 Contradictions shouldn't auto-supersede

Two conflicting statements should coexist in juxtaposition — both live, linked by `CONTRADICTS` — until there's actual evidence or explicit input that one replaces the other. The current design supports this (SUPERSEDES is separate from CONTRADICTS), but the full lifecycle from "tension detected" to "tension resolved" needs clearer definition.

---

## 2. Short-term Fix: Direct ID Linking

The validator already has `s1["id"]` and `s2["id"]`. Instead of producing a natural language claim that round-trips through the LLM, it should create the `CONTRADICTS` relationship directly via the store.

This requires either:
- Exposing a `create_relationship` method on `MemoryAPI`, or
- Adding a dedicated `flag_contradiction(stmt_id_1, stmt_id_2)` method

---

## 3. Contradiction Lifecycle

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

## 4. Implementation Phases

| Phase | Scope | Status |
|---|---|---|
| 1. Fix validator ID linking | Validator creates CONTRADICTS directly instead of LLM round-trip | Not started |
| 2. Contradiction lifecycle | Full tension → juxtaposition → resolution → archive flow | Not started |
| 3. Schema-aware validation | Once schema layer exists, validator checks predicate cardinality before flagging | Not started — depends on [schema agent](schema_agent_design.md) |

---

## See Also

- [Knowledge Representation](knowledge_representation.md) — Current data model
- [Schema Agent Design](schema_agent_design.md) — Dynamic schema layer (separate concern)
- [Design Tracking](design_tracking.md) — System architecture

---

*Document version: 0.1*
*Last updated: 2026-02-02*
*Status: Design phase. Validator contradiction linking needs immediate fix; broader lifecycle design in progress.*
