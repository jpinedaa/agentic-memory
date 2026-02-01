# Graph Database Patterns

This document tracks the Neo4j graph patterns used in the Agentic Memory System.

For the full knowledge representation model (node types, relationship types, design philosophy), see [Knowledge Representation](knowledge_representation.md).

---

## 1. Observation Pattern

**Purpose**: `observe()` records raw input and builds entity graph structure. No Claim nodes are created — claims are exclusively the inference agent's job.

**Structure**:

```
(Observation)
     │
     ├──SUBJECT──▶ (Entity: name=subject)
     │                    │
     │                    └──PREDICATE──▶ (Entity: name=object)
```

**Example**:

Input: `"my girlfriend name is ami"`

```
(Observation)
  id: 5e4d...
  raw_content: "my girlfriend name is ami"
  source: "cli_user"
  type: "Observation"
      │
      ├──SUBJECT──▶ (Entity: "my girlfriend") ──IS_NAMED──▶ (Entity: "ami")
      ├──SUBJECT──▶ (Entity: "ami")
```

**What happens**:

1. Observation node stores the raw text
2. Entity nodes are created/reused for each mentioned entity
3. Observation links to entities via SUBJECT
4. Entity-to-entity edges are created from extracted triples (the knowledge graph)

**What does NOT happen**:

- No Claim nodes are created
- No BASIS links from this path
- No confidence scores at this stage

**Code references**:

- **Creation**: `src/interfaces.py` → `MemoryService.observe()`
- **LLM extraction**: `src/llm.py` → `LLMTranslator.extract_observation()`
- **Storage**: `src/store.py` → `TripleStore.create_node()`, `create_relationship()`

**Cypher queries**:

```cypher
-- Find entity-to-entity relationships (the knowledge graph)
MATCH (a:Node {type: 'Entity'})-[r]->(b:Node {type: 'Entity'})
RETURN a.name, type(r), b.name

-- Find which observations mention an entity
MATCH (obs:Node {type: 'Observation'})-[:SUBJECT]->(e:Node {type: 'Entity'})
RETURN obs.raw_content, e.name, obs.timestamp
ORDER BY obs.timestamp DESC
```

---

## 2. Claim Pattern

**Purpose**: `claim()` records agent assertions with confidence scores and evidential links. Only agents create claims — never `observe()`.

**Structure**:

```
(Claim)
  subject_text: string
  predicate_text: string
  object_text: string
  confidence: float (0.0-1.0)
  source: string (agent name)
     │
     ├──SUBJECT──▶ (Entity: name=subject)
     ├──BASIS──▶ (Observation or Claim)
     ├──CONTRADICTS──▶ (Claim)          [if applicable]
     └──SUPERSEDES──▶ (Claim)           [if Resolution]
```

**Example**:

After the inference agent processes the observation `"my girlfriend name is ami"`:

```
(Claim)
  subject_text: "user"
  predicate_text: "has girlfriend named"
  object_text: "ami"
  confidence: 0.9
  source: "inference_agent"
     │
     ├──SUBJECT──▶ (Entity: "user")
     └──BASIS──▶ (Observation: "my girlfriend name is ami")
```

**Code references**:

- **Creation**: `src/interfaces.py` → `MemoryService.claim()`
- **LLM parsing**: `src/llm.py` → `LLMTranslator.parse_claim()`
- **Basis matching**: `src/interfaces.py` → `MemoryService._find_matching_node()`

**Cypher queries**:

```cypher
-- All claims with their basis
MATCH (c:Node {type: 'Claim'})-[:BASIS]->(basis)
RETURN c.subject_text, c.predicate_text, c.object_text,
       c.confidence, basis.type, basis.raw_content

-- Trace a claim back to its source observation
MATCH (claim:Node {id: $claim_id})-[:BASIS]->(obs:Node {type: 'Observation'})
RETURN obs.raw_content, obs.source, obs.timestamp

-- Claims about an entity (excluding superseded)
MATCH (c:Node)-[:SUBJECT]->(e:Node {type: 'Entity'})
WHERE c.type IN ['Claim', 'Resolution']
AND NOT EXISTS { MATCH (newer:Node)-[:SUPERSEDES]->(c) }
RETURN c.subject_text, c.predicate_text, c.object_text, c.confidence
ORDER BY c.confidence DESC, c.timestamp DESC
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

- **Entity Merge Pattern**: Handling when two entities are discovered to be the same thing (e.g. `SAME_AS` links)
- **Temporal Supersession Pattern**: How newer claims supersede older ones over time
- **Claim-to-Entity Edge Materialization**: Creating entity-to-entity edges from claims (currently only observations do this)

---

*Document version: 0.4*
*Last updated: 2026-01-29*
