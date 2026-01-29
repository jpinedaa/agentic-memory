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
| Entity | Blue (`#58a6ff`) | 8 |
| Observation | Gray (`#8b949e`) | 6 |
| Claim | Green (`#3fb950`) | 7 |
| ExtractedTriple | Yellow (`#d29922`) | 5 |

Edges are rendered with relationship type labels. The SVG element is always mounted (not conditionally rendered) to prevent D3 initialization issues.

Data is fetched via `GET /v1/graph/nodes?limit=200` which queries Neo4j through the UI bridge on the store node.

---

## Suggested Future Patterns

- **Claim-Basis Pattern**: How claims link to their evidential basis (observations or other claims)
- **Contradiction Pattern**: How contradicting claims are linked and resolved
- **Entity Merge Pattern**: Handling when two entities are discovered to be the same thing
- **Temporal Supersession Pattern**: How newer claims supersede older ones

---

*Document version: 0.3*
*Last updated: 2026-01-29*
