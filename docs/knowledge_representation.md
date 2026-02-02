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

## 2. Reified Triples — Statements as Nodes

In Neo4j, relationships cannot be the subject or object of other relationships. To attach metadata (confidence, provenance, negation) to a triple, we **reify** it: the triple becomes a `:Statement` node with edges to its subject and object `:Concept` nodes.

```
(:Statement {predicate: "prefers", confidence: 0.9})
    ├──ABOUT_SUBJECT──▶ (:Concept {name: "user"})
    ├──ABOUT_OBJECT──▶ (:Concept {name: "afternoon meetings"})
    ├──DERIVED_FROM──▶ (:Observation {raw_content: "..."})
    └──ASSERTED_BY──▶ (:Source {name: "inference_agent"})
```

This enables:
- **Confidence** on any assertion
- **Provenance** chains (which observation led to which statement)
- **Supersession** (newer statement replaces older via SUPERSEDES edge)
- **Contradiction** tracking (two statements linked by CONTRADICTS)
- **Negation** (a statement can assert "user does NOT prefer mornings")

---

## 3. Concept Decomposition

Compound concepts are decomposed into sub-concepts via `RELATED_TO` edges, making knowledge traversable:

```
(:Concept {name: "peer-to-peer network"})
    ├──RELATED_TO {relation: "is_a"}──▶ (:Concept {name: "network"})
    └──RELATED_TO {relation: "has_property"}──▶ (:Concept {name: "peer-to-peer"})
```

This means a query about "network" can discover "peer-to-peer network" through graph traversal.

`RELATED_TO.relation` values: `"is_a"`, `"part_of"`, `"has_property"`, `"modifier"`, `"head_noun"`, `"synonym"`, `"broader"`

---

## 4. Node Types (Labels)

The graph uses four Neo4j labels. Each node type has a unique `id` constraint.

### Concept

A named thing in the world — person, place, idea, category, value.

| Property | Type | Description |
|----------|------|-------------|
| `id` | UUID | Unique identifier |
| `name` | string | Canonical name (lowercase unless proper noun) |
| `kind` | string | `"entity"`, `"attribute"`, `"value"`, `"category"`, `"action"` |
| `aliases` | string[] | Alternative names |
| `created_at` | datetime | When created |

**Created by**: `observe()` or `claim()`, via `store.get_or_create_concept()`. Deduplicated by case-insensitive name match.

### Statement

A reified triple with metadata. All knowledge assertions flow through Statement nodes.

| Property | Type | Description |
|----------|------|-------------|
| `id` | UUID | Unique identifier |
| `predicate` | string | Relationship verb (e.g. "is", "prefers", "has") |
| `confidence` | float | 0.0–1.0 certainty score |
| `negated` | boolean | True for negative assertions |
| `created_at` | datetime | When created |

**Created by**: `observe()` (from LLM-extracted statements) and `claim()` (from agent assertions).

### Observation

Raw input from the external world. Never modified after creation.

| Property | Type | Description |
|----------|------|-------------|
| `id` | UUID | Unique identifier |
| `raw_content` | string | Original unprocessed text |
| `topics` | string[] | Topic keywords |
| `created_at` | datetime | When recorded |

**Created by**: `observe()` only (adapters, CLI, external input).

### Source

An agent, user, or system that produces knowledge. First-class provenance node.

| Property | Type | Description |
|----------|------|-------------|
| `id` | UUID | Unique identifier |
| `name` | string | e.g. `"cli_user"`, `"inference_agent"` |
| `kind` | string | `"user"`, `"agent"`, `"system"` |
| `created_at` | datetime | When created |

**Created by**: `observe()` or `claim()`, via `store.get_or_create_source()`. Deduplicated by name.

---

## 5. Relationship Types

| Relationship | From → To | Purpose |
|---|---|---|
| `ABOUT_SUBJECT` | Statement → Concept | The subject of the statement |
| `ABOUT_OBJECT` | Statement → Concept | The object/value of the statement |
| `DERIVED_FROM` | Statement → Observation or Statement | Provenance chain |
| `ASSERTED_BY` | Statement → Source | Who made this assertion |
| `SUPERSEDES` | Statement → Statement | Newer replaces older (resolution) |
| `CONTRADICTS` | Statement → Statement | Conflicting statements |
| `MENTIONS` | Observation → Concept | Concepts appearing in the observation |
| `RECORDED_BY` | Observation → Source | Who recorded this |
| `RELATED_TO` | Concept → Concept | Decomposition/hierarchy (property: `relation`) |

---

## 6. Data Flow

### observe() — recording raw input

```
Input: "the user said bitcoin is a peer-to-peer network"

1. LLM extracts:
   concepts: [
     {name: "user", kind: "entity"},
     {name: "bitcoin", kind: "entity"},
     {name: "peer-to-peer network", kind: "category",
      components: [{name: "network", relation: "is_a"},
                   {name: "peer-to-peer", relation: "has_property"}]}
   ]
   statements: [{subject: "bitcoin", predicate: "is", object: "peer-to-peer network",
                  confidence: 1.0}]
   topics: ["cryptocurrency", "technology"]

2. Create Source node (get_or_create)
3. Create Observation node (raw_content preserved)
4. Link: Observation ──RECORDED_BY──▶ Source
5. Create Concept nodes (get_or_create), link: Observation ──MENTIONS──▶ Concept
6. For compound concepts, decompose: Concept ──RELATED_TO──▶ sub-Concept
7. Create Statement nodes from extracted statements:
   Statement ──ABOUT_SUBJECT──▶ Concept("bitcoin")
   Statement ──ABOUT_OBJECT──▶ Concept("peer-to-peer network")
   Statement ──DERIVED_FROM──▶ Observation
   Statement ──ASSERTED_BY──▶ Source
```

### claim() — agent assertions

```
Input: "user prefers afternoon meetings based on their direct statement"
Source: "inference_agent"

1. LLM parses with recent context:
   subject: "user", predicate: "prefers", object: "afternoon meetings"
   confidence: 0.85, negated: false
   basis_descriptions: ["user said they prefer afternoon meetings"]

2. Create Source node (get_or_create)
3. Create Statement node (predicate + confidence + negated)
4. Create Concept nodes for subject/object
5. Link: Statement ──ABOUT_SUBJECT──▶ Concept("user")
         Statement ──ABOUT_OBJECT──▶ Concept("afternoon meetings")
         Statement ──ASSERTED_BY──▶ Source
6. Link basis (text matching): Statement ──DERIVED_FROM──▶ Observation/Statement
7. If supersession: Statement ──SUPERSEDES──▶ old Statement
8. If contradiction: Statement ──CONTRADICTS──▶ other Statement
```

---

## 7. Design Philosophy

### All knowledge goes through Statement nodes

There are no dynamic predicate edges (like `Entity --PREFERS--> Entity`). Every assertion is a Statement node with `ABOUT_SUBJECT` and `ABOUT_OBJECT` edges. This means:

- Every piece of knowledge has confidence, provenance, and can be superseded
- You can query "all statements where X is the object" (impossible with dynamic edge types)
- Contradictions and resolutions are tracked uniformly

### Observations and claims both create Statements

`observe()` creates Statements from LLM-extracted triples. `claim()` creates Statements from agent assertions. The difference is in provenance (DERIVED_FROM an Observation vs another Statement) and source (user vs agent).

### Concepts are universal nouns

A Concept can be an entity ("bitcoin"), a value ("afternoon"), a category ("network"), an attribute ("color"), or an action ("running"). The `kind` property distinguishes them but all are first-class graph citizens.

### Contradictions are data, not errors

When two statements conflict, both persist. The validator agent creates a CONTRADICTS link. Resolution happens via a new Statement that SUPERSEDES one of the conflicting ones. Until then, the contradiction is visible signal.

### Source is a first-class node

Provenance is traversable, not a string property. You can query "what has this agent asserted?" or "what observations came from this user?" via graph traversal.

---

## 8. Reading the Graph

### Concept-centric queries

```cypher
-- All statements about a concept (excluding superseded)
MATCH (s:Statement)-[:ABOUT_SUBJECT|ABOUT_OBJECT]->(c:Concept)
WHERE toLower(c.name) = 'bitcoin'
AND NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s) }
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, s.confidence

-- Concept decomposition
MATCH (c:Concept {name: 'peer-to-peer network'})-[r:RELATED_TO]->(sub:Concept)
RETURN c.name, r.relation, sub.name
```

### Provenance queries

```cypher
-- Trace a statement back to its source observation
MATCH (s:Statement {id: $stmt_id})-[:DERIVED_FROM]->(obs:Observation)
RETURN obs.raw_content

-- What has this agent asserted?
MATCH (s:Statement)-[:ASSERTED_BY]->(src:Source {name: 'inference_agent'})
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, s.confidence
```

### Contradiction queries

```cypher
-- Unresolved contradictions
MATCH (s1:Statement)-[:CONTRADICTS]->(s2:Statement)
WHERE NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s1) }
AND NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s2) }
RETURN s1, s2
```

---

## 9. Known Limitations

### Text-based matching for DERIVED_FROM links

When `claim()` links a new statement to its basis, it uses word-overlap heuristics against recent observations and statements. This is best-effort — it may miss relevant nodes or create false matches. Semantic similarity search (embeddings, vector index) would improve this.

### No predicate schema

Predicates are strings on Statement nodes — the system has no knowledge *about* predicates (cardinality, temporality, synonymy). This means the validator treats all same-subject/same-predicate/different-object pairs as contradictions, even for multi-valued predicates like "has hobby." A dynamic schema layer is being designed to address this. See [Schema Agent Design](schema_agent_design.md).

### Contradiction linking is fragile

The validator detects contradictions by ID but records them via a natural language round-trip through `claim()` → LLM `parse_claim()` → text-based `_find_matching_node()`. This loses the known IDs and is unreliable. Tracked in [Validation Redesign](validation_redesign.md).

### No concept merging

If observations produce `Concept("my girlfriend")` and `Concept("ami")`, the system does not automatically recognize these as the same person. A concept-merging agent could create `RELATED_TO {relation: "synonym"}` links.

### LLM extraction quality

The quality of concept decomposition and statement extraction depends entirely on the LLM. The system provides the schema and instructions, but extraction accuracy varies.

---

## See Also

- [Graph Patterns](graph_patterns.md) — Neo4j graph patterns and visualization
- [Design Tracking](design_tracking.md) — Full system architecture and data flows
- [Neo4j Guide](neo4j.md) — Database setup, queries, and troubleshooting
- [Schema Agent Design](schema_agent_design.md) — Dynamic schema layer
- [Validation Redesign](validation_redesign.md) — Contradiction detection and lifecycle

---

*Document version: 2.0*
*Last updated: 2026-02-02*
