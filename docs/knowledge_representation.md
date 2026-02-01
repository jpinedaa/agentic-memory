# Knowledge Representation

How knowledge is stored, structured, and queried in the Agentic Memory graph.

---

## 1. The Triple as Universal Unit

All knowledge in this system reduces to triples:

```
(subject, predicate, object)
```

A triple is the smallest unit of meaning: *something* has a *relationship* to *something else*. Every fact, observation, inference, and contradiction is either a triple or a composition of triples.

| Statement | Subject | Predicate | Object |
|-----------|---------|-----------|--------|
| "Bitcoin is a peer-to-peer network" | bitcoin | is | peer-to-peer network |
| "The user prefers dark mode" | user | prefers | dark mode |
| "Ami is the user's girlfriend" | ami | girlfriend_of | user |

Some statements produce multiple triples. "My girlfriend's name is Ami" implies both `(user, has_girlfriend, ami)` and `(ami, is_named, ami)`. The LLM extraction layer decides which triples to produce.

---

## 2. Two Layers of Representation

The graph has two distinct layers that serve different purposes:

### Layer 1: Entity Graph (structure)

Entity-to-entity edges are the **knowledge graph proper** — the web of relationships between things in the world.

```
(Entity: bitcoin) ──IS──▶ (Entity: peer-to-peer network)
(Entity: user) ──PREFERS──▶ (Entity: dark mode)
(Entity: ami) ──GIRLFRIEND_OF──▶ (Entity: user)
```

These edges are created by `observe()` from LLM-extracted triples. They represent **what the system knows about the world** as graph structure.

- Predicates are normalized to Neo4j relationship types: uppercase, spaces/hyphens become underscores
- `"has girlfriend"` → `HAS_GIRLFRIEND`
- `"is"` → `IS`
- Both subject and object are Entity nodes (deduplicated by name, case-insensitive)

### Layer 2: Provenance Graph (metadata)

Observation, Claim, and Resolution nodes track **where knowledge came from and how confident we are**.

```
(Observation: "the user said bitcoin is a peer-to-peer network")
     │
     ├──SUBJECT──▶ (Entity: user)
     ├──SUBJECT──▶ (Entity: bitcoin)

(Claim: "user understands bitcoin is peer-to-peer")
     │
     ├──SUBJECT──▶ (Entity: user)
     ├──BASIS──▶ (Observation above)
     │
     confidence: 0.85
     source: "inference_agent"
```

The provenance graph answers: *why do we believe this?* The entity graph answers: *what do we believe?*

---

## 3. Node Types

All nodes share the Neo4j label `:Node` and are distinguished by a `type` property.

### Observation

Raw input from the external world. Never modified after creation.

| Property | Type | Description |
|----------|------|-------------|
| `id` | UUID | Unique identifier |
| `type` | `"Observation"` | Node type |
| `source` | string | Who provided this (e.g. `"cli_user"`) |
| `timestamp` | ISO 8601 | When recorded |
| `raw_content` | string | Original unprocessed text |
| `topics` | string | Comma-separated topic keywords |

**Created by**: `observe()` only (adapters, CLI, external input).

**Relationships created**:
- `Observation ──SUBJECT──▶ Entity` for each mentioned entity
- `Entity ──[PREDICATE]──▶ Entity` for each extracted triple (entity graph edges)

### Entity

A named thing in the world — person, place, concept, object.

| Property | Type | Description |
|----------|------|-------------|
| `id` | UUID | Unique identifier |
| `type` | `"Entity"` | Node type |
| `name` | string | Canonical name |

**Created by**: Either `observe()` or `claim()`, via `store.get_or_create_entity()`. Deduplicated by case-insensitive name match.

**Key behavior**: If an entity named "bitcoin" already exists, any later reference to "Bitcoin" or "BITCOIN" reuses the same node. This is the only deduplication the system performs.

### Claim

A structured assertion produced by an agent. The sole output of the inference pipeline.

| Property | Type | Description |
|----------|------|-------------|
| `id` | UUID | Unique identifier |
| `type` | `"Claim"` | Node type |
| `source` | string | Which agent (e.g. `"inference_agent"`) |
| `timestamp` | ISO 8601 | When asserted |
| `subject_text` | string | Subject of the assertion |
| `predicate_text` | string | Relationship or attribute |
| `object_text` | string | Value or target |
| `confidence` | float | 0.0–1.0 certainty score |

**Created by**: `claim()` only (agents via the inference pipeline).

**Relationships created**:
- `Claim ──SUBJECT──▶ Entity` (the entity this claim is about)
- `Claim ──BASIS──▶ Observation|Claim` (evidential links, what this claim is based on)
- `Claim ──CONTRADICTS──▶ Claim` (if this contradicts another claim)

### Resolution

A special Claim that explicitly resolves a contradiction by superseding one or more earlier claims.

| Property | Type | Description |
|----------|------|-------------|
| (same as Claim) | | |
| `type` | `"Resolution"` | Distinguishes from regular Claim |

**Additional relationship**:
- `Resolution ──SUPERSEDES──▶ Claim` (marks the older claim as resolved)

---

## 4. Relationship Types

### System Relationships (structural metadata)

| Relationship | From → To | Meaning | Created By |
|--------------|-----------|---------|------------|
| `SUBJECT` | Observation/Claim → Entity | "This is about that entity" | `observe()`, `claim()` |
| `BASIS` | Claim → Observation/Claim | "This claim is based on that evidence" | `claim()` |
| `CONTRADICTS` | Claim → Claim | "These claims conflict" | `claim()` (validator agent) |
| `SUPERSEDES` | Resolution → Claim | "This resolution replaces that claim" | `claim()` (resolution) |

### Knowledge Relationships (dynamic predicates)

| Relationship | From → To | Meaning | Created By |
|--------------|-----------|---------|------------|
| `IS`, `HAS`, `PREFERS`, `WORKS_AT`, ... | Entity → Entity | A fact about the world | `observe()` |

Dynamic predicates are normalized from extracted triple predicates:
```
predicate.strip().upper().replace(" ", "_").replace("-", "_")
```

---

## 5. Data Flow

### observe() — recording raw input

```
Input: "the user said bitcoin is a peer-to-peer network"

1. LLM extracts:
   entities: ["user", "bitcoin", "peer-to-peer network"]
   extractions: [{subject: "bitcoin", predicate: "is", object: "peer-to-peer network"},
                 {subject: "user", predicate: "understands", object: "bitcoin"}]
   topics: ["cryptocurrency", "technology"]

2. Create Observation node (raw_content preserved)

3. Link observation to entities:
   Observation ──SUBJECT──▶ Entity("user")
   Observation ──SUBJECT──▶ Entity("bitcoin")
   Observation ──SUBJECT──▶ Entity("peer-to-peer network")

4. Create entity-to-entity edges from triples:
   Entity("bitcoin") ──IS──▶ Entity("peer-to-peer network")
   Entity("user") ──UNDERSTANDS──▶ Entity("bitcoin")
```

No Claim nodes are created. Observations record **what was said** and build **graph structure** from the extracted triples. Interpretation is the inference agent's job.

### claim() — agent assertions

```
Input: "user understands that bitcoin is a peer-to-peer network"
Source: "inference_agent"

1. LLM parses with recent context:
   subject: "user"
   predicate: "understands"
   object: "bitcoin is a peer-to-peer network"
   confidence: 0.85
   basis_descriptions: ["the user said bitcoin is a peer-to-peer network"]

2. Create Claim node (with confidence, subject/predicate/object as properties)

3. Link claim to entity:
   Claim ──SUBJECT──▶ Entity("user")

4. Link basis (text matching against recent observations/claims):
   Claim ──BASIS──▶ Observation (matched by text overlap)

5. If contradiction detected:
   Claim ──CONTRADICTS──▶ Claim (matched by text overlap)

6. If resolution:
   Resolution ──SUPERSEDES──▶ Claim (matched by text overlap)
```

Claims record **what an agent believes** with confidence scores and evidential links back to their source material.

---

## 6. Design Philosophy

### Why two layers?

The entity graph and provenance graph serve fundamentally different query patterns:

| Question | Layer | Query Pattern |
|----------|-------|---------------|
| "What is bitcoin?" | Entity graph | Follow edges from Entity("bitcoin") |
| "Why does the system think the user understands bitcoin?" | Provenance graph | Claim → BASIS → Observation chain |
| "What contradictions exist about the user?" | Provenance graph | Claim → CONTRADICTS → Claim |
| "What relationships does the user have?" | Entity graph | All edges from Entity("user") |

### Observations don't judge, they record

`observe()` creates graph structure (entity edges) directly from extracted triples — this is a mechanical translation of natural language into graph form. No confidence scoring, no reasoning about what the input *means*.

### Claims are the inference agent's job

Only agents produce Claim nodes. A Claim is a deliberate assertion with:
- **Confidence** — how certain the agent is
- **Basis** — what evidence supports it
- **Source** — which agent made this assertion

This separation means you can always distinguish "what was directly stated" (observations + entity edges) from "what was inferred" (claims).

### Contradictions are data, not errors

When two claims conflict, both persist. The validator agent creates a CONTRADICTS link between them. Resolution happens later, via a Resolution node that SUPERSEDES one of the conflicting claims. Until then, the contradiction is visible signal — not a bug.

### Entity deduplication is name-based

The only automatic deduplication is case-insensitive entity name matching. "Bitcoin", "bitcoin", and "BITCOIN" all resolve to the same Entity node. Beyond that, the system does not attempt to merge entities that might refer to the same thing under different names. This is a deliberate simplicity choice — semantic entity resolution can be added as a future agent.

---

## 7. Reading the Graph

### Entity-centric queries (what do we know?)

```cypher
-- All relationships for an entity
MATCH (e:Node {type: 'Entity', name: 'bitcoin'})-[r]-(other:Node {type: 'Entity'})
RETURN e.name, type(r), other.name

-- What observations mention an entity?
MATCH (obs:Node {type: 'Observation'})-[:SUBJECT]->(e:Node {type: 'Entity'})
WHERE toLower(e.name) = 'bitcoin'
RETURN obs.raw_content, obs.timestamp
```

### Provenance queries (why do we believe it?)

```cypher
-- Claims about an entity (excluding superseded)
MATCH (c:Node)-[:SUBJECT]->(e:Node {type: 'Entity'})
WHERE c.type IN ['Claim', 'Resolution']
AND toLower(e.name) = 'user'
AND NOT EXISTS { MATCH (newer:Node)-[:SUPERSEDES]->(c) }
RETURN c.subject_text, c.predicate_text, c.object_text, c.confidence
ORDER BY c.confidence DESC

-- Trace a claim back to its basis
MATCH (c:Node {type: 'Claim'})-[:BASIS]->(basis)
RETURN c.subject_text, c.predicate_text, c.object_text,
       basis.type, basis.raw_content
```

### Contradiction queries

```cypher
-- Unresolved contradictions
MATCH (c1:Node)-[:CONTRADICTS]->(c2:Node)
WHERE NOT EXISTS { MATCH (:Node)-[:SUPERSEDES]->(c1) }
AND NOT EXISTS { MATCH (:Node)-[:SUPERSEDES]->(c2) }
RETURN c1, c2
```

---

## 8. Known Limitations

### Claims don't create entity-to-entity edges

When the inference agent creates a Claim like "user prefers afternoon meetings", this is stored as properties on the Claim node (`subject_text`, `predicate_text`, `object_text`). No `Entity("user") ──PREFERS──▶ Entity("afternoon meetings")` edge is created.

This means the entity graph reflects **observations only** — not inferences. Entity-centric queries will miss inferred knowledge unless they also query Claim node properties.

This is a known design trade-off. Observations are considered more structurally reliable (the user actually said something), while claims are interpretations that may be wrong or contradicted later. Materializing claim triples as entity edges would require handling edge retraction when claims are superseded — complexity the system doesn't yet need.

### Text-based matching for BASIS links

When `claim()` links a new claim to its basis, it uses word-overlap heuristics against recent observations and claims. This is best-effort — it may miss relevant basis nodes or create false matches. Semantic similarity search (embeddings, vector index) would improve this but adds infrastructure complexity.

### No entity merging

If observations produce `Entity("my girlfriend")` and `Entity("ami")`, the system does not automatically recognize these as the same person. An entity-merging agent could be added to create `SAME_AS` links or merge nodes.

### Observation entity edges are permanent

Entity-to-entity edges created by `observe()` are never retracted. If the LLM extracts an incorrect triple, that edge persists. Claims can be superseded; entity edges cannot. For now, `clear()` is the only remedy.

---

## See Also

- [Graph Patterns](graph_patterns.md) — Neo4j graph patterns and visualization
- [Design Tracking](design_tracking.md) — Full system architecture and data flows
- [Neo4j Guide](neo4j.md) — Database setup, queries, and troubleshooting

---

*Document version: 0.1*
*Last updated: 2026-01-29*
