# Graph Database Patterns

This document tracks the Neo4j graph patterns used in the Agentic Memory System.

---

## 1. Unified Claim Pattern

**Purpose**: All structured assertions — whether extracted from observations or inferred by agents — are stored as Claim nodes. Entity-to-entity relationships are materialized as first-class Neo4j edges.

**Structure**:

```
(Observation)
     │
     ├──SUBJECT──▶ (Entity: name=subject)
     │                    │
     │                    └──PREDICATE──▶ (Entity: name=object)
     │
     ◄──BASIS── (Claim)
                  subject_text: string
                  predicate_text: string
                  object_text: string
                  confidence: float (1.0 for extracted, 0-1 for inferred)
                  source: string
                  type: "Claim"
                    │
                    └──SUBJECT──▶ (Entity: name=subject)
```

**Example**:

Input: `"my girlfriend name is ami"`

```
(Observation)                          (Claim)
  id: 5e4d...                            subject_text: "my girlfriend"
  raw_content: "my girlfriend..."        predicate_text: "is named"
  source: "cli_user"            ◄─BASIS─ object_text: "ami"
  type: "Observation"                    confidence: 1.0
      │                                  source: "cli_user"
      │                                     │
      ├──SUBJECT──▶ (Entity: "my girlfriend") ──IS_NAMED──▶ (Entity: "ami")
      │                ◄──SUBJECT──  (Claim above)
```

**Key design decisions**:

- **No ExtractedTriple**: Observations produce Claims with `confidence: 1.0`. Agent inferences produce Claims with `confidence: 0-1`. Same node type, different provenance via `BASIS` edges.
- **Entity-to-entity edges**: The predicate is materialized as a Neo4j relationship between entity nodes (e.g. `IS_NAMED`, `PREFERS`). Predicates are normalized: uppercase, spaces → underscores.
- **Provenance**: `Claim --BASIS--> Observation` traces every fact back to its source.
- **Raw preservation**: Original text is never lost — stored in `raw_content` on the Observation node.

**Code references**:

- **Creation**: `src/interfaces.py` → `MemoryService.observe()` (creates Claims + entity edges)
- **LLM extraction**: `src/llm.py` → `LLMTranslator.extract_observation()`
- **Storage**: `src/store.py` → `TripleStore.create_node()`, `create_relationship()`

**Cypher queries**:

```cypher
-- Find all claims extracted from observations
MATCH (claim:Node {type: 'Claim'})-[:BASIS]->(obs:Node {type: 'Observation'})
RETURN obs.raw_content, claim.subject_text, claim.predicate_text, claim.object_text

-- Find entity-to-entity relationships (the actual knowledge graph)
MATCH (a:Node {type: 'Entity'})-[r]->(b:Node {type: 'Entity'})
RETURN a.name, type(r), b.name

-- Trace a claim back to its source observation
MATCH (claim:Node {id: $claim_id})-[:BASIS]->(obs:Node {type: 'Observation'})
RETURN obs.raw_content, obs.source, obs.timestamp
```

---

## 2. Agent Status Pattern (P2P Gossip)

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

See `docs/agent_status_pattern.md` for full design.

---

## 3. UI Visualization

The knowledge graph is rendered in the React UI's GraphView panel using D3.js. Node types are color-coded:

| Node Type | Color | D3 Radius |
|-----------|-------|-----------|
| Entity | Blue (`#58a6ff`) | 12 |
| Observation | Gray (`#8b949e`) | 8 |
| Claim | Green (`#3fb950`) | 10 |
| Resolution | Purple (`#a371f7`) | 10 |

Entity-to-entity edges show the predicate as labels (e.g. `IS_NAMED`, `PREFERS`). System edges (`SUBJECT`, `BASIS`, `SUPERSEDES`, `CONTRADICTS`) are also visible.

The SVG element is always mounted (not conditionally rendered) to prevent D3 initialization issues. Data is fetched via `GET /v1/graph/nodes?limit=200` which queries Neo4j through the UI bridge on the store node.

---

## Suggested Future Patterns

- **Claim-Basis Pattern**: How claims link to their evidential basis (observations or other claims)
- **Contradiction Pattern**: How contradicting claims are linked and resolved
- **Entity Merge Pattern**: Handling when two entities are discovered to be the same thing
- **Temporal Supersession Pattern**: How newer claims supersede older ones

---

*Document version: 0.3*
*Last updated: 2026-01-29*
