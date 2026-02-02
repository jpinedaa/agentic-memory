# Graph Database Patterns

This document tracks the Neo4j graph patterns used in the Agentic Memory System.

For the full knowledge representation model (node types, relationship types, design philosophy), see [Knowledge Representation](knowledge_representation.md).

---

## 1. Observation Pattern

**Purpose**: `observe()` records raw input, extracts concepts with decomposition, and creates reified statements. Source provenance is tracked as a first-class node.

**Structure**:

```
(:Source {name: "cli_user", kind: "user"})
      ▲
      │ RECORDED_BY
(:Observation {raw_content: "..."})
      │
      ├──MENTIONS──▶ (:Concept {name: "bitcoin", kind: "entity"})
      ├──MENTIONS──▶ (:Concept {name: "peer-to-peer network", kind: "category"})
      │                    ├──RELATED_TO {relation: "is_a"}──▶ (:Concept {name: "network"})
      │                    └──RELATED_TO {relation: "has_property"}──▶ (:Concept {name: "peer-to-peer"})
      │
      └──(linked from Statement via DERIVED_FROM)

(:Statement {predicate: "is", confidence: 1.0})
      ├──ABOUT_SUBJECT──▶ (:Concept {name: "bitcoin"})
      ├──ABOUT_OBJECT──▶ (:Concept {name: "peer-to-peer network"})
      ├──DERIVED_FROM──▶ (:Observation above)
      └──ASSERTED_BY──▶ (:Source {name: "cli_user"})
```

**What happens**:

1. Source node created/reused via `get_or_create_source()`
2. Observation node stores the raw text
3. Concept nodes are created/reused for each extracted concept
4. Observation links to concepts via MENTIONS
5. Compound concepts are decomposed via RELATED_TO edges
6. Statement nodes (reified triples) are created with ABOUT_SUBJECT/ABOUT_OBJECT/DERIVED_FROM/ASSERTED_BY

**Code references**:

- **Creation**: `src/interfaces.py` → `MemoryService.observe()`
- **LLM extraction**: `src/llm.py` → `LLMTranslator.extract_observation()`
- **Storage**: `src/store.py` → `create_observation()`, `create_concept()`, `create_statement()`, `create_relationship()`

**Cypher queries**:

```cypher
-- All statements derived from observations (the knowledge extracted by observe())
MATCH (s:Statement)-[:DERIVED_FROM]->(o:Observation)
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, s.confidence, o.raw_content

-- Concept decomposition
MATCH (c:Concept)-[r:RELATED_TO]->(sub:Concept)
RETURN c.name, r.relation, sub.name
```

---

## 2. Claim Pattern

**Purpose**: `claim()` records agent assertions as Statement nodes with confidence, provenance, and optional contradiction/supersession links.

**Structure**:

```
(:Statement {predicate: "prefers", confidence: 0.85, negated: false})
     │
     ├──ABOUT_SUBJECT──▶ (:Concept {name: "user"})
     ├──ABOUT_OBJECT──▶ (:Concept {name: "afternoon meetings"})
     ├──ASSERTED_BY──▶ (:Source {name: "inference_agent", kind: "agent"})
     ├──DERIVED_FROM──▶ (:Observation or :Statement)    [basis]
     ├──CONTRADICTS──▶ (:Statement)                     [if applicable]
     └──SUPERSEDES──▶ (:Statement)                      [if resolution]
```

**Code references**:

- **Creation**: `src/interfaces.py` → `MemoryService.claim()`
- **LLM parsing**: `src/llm.py` → `LLMTranslator.parse_claim()`
- **Basis matching**: `src/interfaces.py` → `MemoryService._find_matching_node()`

**Cypher queries**:

```cypher
-- All statements with their basis
MATCH (s:Statement)-[:DERIVED_FROM]->(basis)
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, s.confidence, labels(basis)[0] AS basis_type

-- Statements about a concept (excluding superseded)
MATCH (s:Statement)-[:ABOUT_SUBJECT|ABOUT_OBJECT]->(c:Concept)
WHERE toLower(c.name) = 'user'
AND NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s) }
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, s.confidence
ORDER BY s.confidence DESC, s.created_at DESC
```

---

## 3. Agent Status Pattern (P2P Gossip)

**Purpose**: Track node lifecycle and health across the P2P network. Stored in-memory in each node's `RoutingTable` — no external database needed.

**Data**:

```python
PeerState:
    info: PeerInfo           # node_id, capabilities, URLs, version
    status: str              # alive | suspect | dead
    last_seen: float         # timestamp of last gossip
    heartbeat_seq: int       # monotonic counter (owner increments)
    metadata: dict           # extensible
```

Each node builds its own view of the network from gossip messages. Higher `heartbeat_seq` always wins when merging.

**Code references**:
- `src/p2p/types.py` → `PeerInfo`, `PeerState`, `Capability`
- `src/p2p/gossip.py` → `GossipProtocol` (heartbeat + push-based gossip)
- `src/p2p/routing.py` → `RoutingTable` (peer tracking + capability routing)
- `src/p2p/node.py` → `PeerNode` (health check loop, neighbor management)

---

## 4. UI Visualization

The knowledge graph is rendered in the React UI's GraphView panel using D3.js. Node types are color-coded by Neo4j label:

| Node Label | Color | D3 Radius |
|-----------|-------|-----------|
| Concept | Blue (`#58a6ff`) | 12 |
| Observation | Gray (`#8b949e`) | 8 |
| Statement | Green (`#3fb950`) | 10 |
| Source | Purple (`#a371f7`) | 10 |

Relationships (`ABOUT_SUBJECT`, `ABOUT_OBJECT`, `DERIVED_FROM`, `MENTIONS`, `RELATED_TO`, etc.) are visible as graph edges.

Data is fetched via `GET /v1/graph/nodes?limit=200` which queries Neo4j through the UI bridge on the store node, using `labels(n)` to determine node type.

---

## Suggested Future Patterns

- **Concept Merge Pattern**: Handling when two concepts refer to the same thing (e.g. `RELATED_TO {relation: "synonym"}`)
- **Temporal Patterns**: Querying how knowledge evolved over time via `created_at` ordering
- **Multi-hop Inference**: Traversing RELATED_TO chains to connect distant concepts

---

*Document version: 2.0*
*Last updated: 2026-02-02*
