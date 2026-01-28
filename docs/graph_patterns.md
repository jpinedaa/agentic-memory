# Graph Database Patterns

This document tracks the Neo4j graph patterns used in the Agentic Memory System.

---

## 1. ExtractedTriple Pattern

**Purpose**: Store structured semantic content extracted from natural language while preserving the link to the source observation.

**Structure**:

```
(Observation) ──HAS_EXTRACTION──▶ (ExtractedTriple)
     │                              subject_text: string
     │                              predicate_text: string
     │                              object_text: string
     │                              timestamp: ISO8601
     │                              type: "ExtractedTriple"
     │
     ├──SUBJECT──▶ (Entity: name=subject)
     └──SUBJECT──▶ (Entity: name=object)   [if object is an entity]
```

**Example**:

Input: `"my girlfriend name is ami"`

```
(Observation)                          (ExtractedTriple)
  id: 5e4d...                            subject_text: "my girlfriend"
  raw_content: "my girlfriend..."  ───▶  predicate_text: "is named"
  source: "cli_user"                     object_text: "ami"
  type: "Observation"                    type: "ExtractedTriple"
      │
      ├──SUBJECT──▶ (Entity: name="my girlfriend")
      └──SUBJECT──▶ (Entity: name="ami")
```

**Why this pattern**:

- **Provenance**: Every structured fact links back to its source observation
- **Query flexibility**: Can query by subject/predicate/object text
- **Entity linking**: Entities are separate nodes, allowing multiple observations to reference the same entity
- **Raw preservation**: Original text is never lost — stored in `raw_content`

**Code references**:

- **Creation**: `src/interfaces.py` → `MemoryService.observe()` (lines 51-90)
- **LLM extraction**: `src/llm.py` → `LLMTranslator.extract_observation()`
- **Storage**: `src/store.py` → `TripleStore.create_node()`, `create_relationship()`

**Cypher queries**:

```cypher
-- Find all extracted triples
MATCH (obs:Node {type: 'Observation'})-[:HAS_EXTRACTION]->(triple)
RETURN obs.raw_content, triple.subject_text, triple.predicate_text, triple.object_text

-- Find triples about a specific subject
MATCH (triple:Node {type: 'ExtractedTriple', subject_text: 'user'})
RETURN triple

-- Trace a triple back to its source
MATCH (obs)-[:HAS_EXTRACTION]->(triple:Node {id: $triple_id})
RETURN obs.raw_content, obs.source, obs.timestamp
```

---

## Suggested Future Patterns

- **Claim-Basis Pattern**: How claims link to their evidential basis (observations or other claims)
- **Contradiction Pattern**: How contradicting claims are linked and resolved
- **Entity Merge Pattern**: Handling when two entities are discovered to be the same thing
- **Temporal Supersession Pattern**: How newer claims supersede older ones

---

*Document version: 0.1*
*Last updated: 2026-01-27*
