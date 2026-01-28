# Neo4j Guide

This document covers Neo4j setup, UI usage, and common queries for the Agentic Memory System.

---

## Quick Start

```bash
# Start Neo4j only (dev mode)
docker compose up neo4j -d

# Start full stack (distributed mode)
docker compose up -d
```

---

## Neo4j Browser (UI)

### Accessing the UI

Open in browser: **http://localhost:7474**

### Login Credentials

| Field | Value |
|-------|-------|
| Connect URL | `neo4j://localhost:7687` |
| Username | `neo4j` |
| Password | `memory-system` |

### UI Tips

- **Run queries**: Type Cypher in the top bar and press `Ctrl+Enter` (or click the play button)
- **Auto-complete**: Press `Tab` for Cypher keyword suggestions
- **Graph view**: Results with nodes/relationships display as interactive graphs
- **Table view**: Click the table icon to see results as rows
- **Export**: Click the download icon to export results as CSV or JSON
- **History**: Press up arrow to cycle through previous queries
- **Multi-statement**: Separate queries with `;` to run multiple at once
- **Favorites**: Star frequently used queries to save them

---

## Data Model

### Node Types

All nodes have label `Node` with a `type` property distinguishing them.

| Type | Properties | Description |
|------|------------|-------------|
| `Observation` | `id`, `raw_content`, `source`, `timestamp`, `type` | Raw natural language input |
| `ExtractedTriple` | `id`, `subject_text`, `predicate_text`, `object_text`, `timestamp`, `type` | Structured fact from observation |
| `Entity` | `id`, `name`, `entity_type`, `type` | Named thing (person, place, concept) |
| `Claim` | `id`, `subject_text`, `predicate_text`, `object_text`, `confidence`, `status`, `timestamp`, `type` | Inferred or stated fact |

### Relationship Types

| Relationship | From | To | Meaning |
|--------------|------|------|---------|
| `HAS_EXTRACTION` | Observation | ExtractedTriple | Observation contains this triple |
| `SUBJECT` | Observation | Entity | Observation mentions this entity |
| `BASED_ON` | Claim | Observation/Claim | Claim's evidential basis |
| `ABOUT` | Claim | Entity | Claim is about this entity |
| `CONTRADICTS` | Claim | Claim | Claims are in conflict |
| `SUPERSEDES` | Claim | Claim | Newer claim replaces older |

---

## Common Queries

### Exploration

```cypher
-- See everything (limit for safety)
MATCH (n) RETURN n LIMIT 50

-- Count nodes by type
MATCH (n:Node) RETURN n.type, count(*) ORDER BY count(*) DESC

-- List all relationship types
CALL db.relationshipTypes()
```

### Observations

```cypher
-- All observations
MATCH (obs:Node {type: 'Observation'})
RETURN obs.raw_content, obs.source, obs.timestamp
ORDER BY obs.timestamp DESC

-- Recent observations (last 10)
MATCH (obs:Node {type: 'Observation'})
RETURN obs.raw_content, obs.timestamp
ORDER BY obs.timestamp DESC
LIMIT 10

-- Observations with their extractions
MATCH (obs:Node {type: 'Observation'})-[:HAS_EXTRACTION]->(triple)
RETURN obs.raw_content,
       triple.subject_text,
       triple.predicate_text,
       triple.object_text
```

### Entities

```cypher
-- All entities
MATCH (e:Node {type: 'Entity'})
RETURN e.name, e.entity_type

-- Entities and what mentions them
MATCH (obs:Node {type: 'Observation'})-[:SUBJECT]->(e:Node {type: 'Entity'})
RETURN e.name, collect(obs.raw_content) as mentioned_in

-- Find a specific entity
MATCH (e:Node {type: 'Entity', name: 'ami'})
RETURN e
```

### Claims

```cypher
-- All claims
MATCH (c:Node {type: 'Claim'})
RETURN c.subject_text, c.predicate_text, c.object_text, c.confidence, c.status

-- Active claims only (not superseded)
MATCH (c:Node {type: 'Claim'})
WHERE c.status <> 'superseded'
RETURN c.subject_text, c.predicate_text, c.object_text, c.confidence

-- Claims with their basis
MATCH (c:Node {type: 'Claim'})-[:BASED_ON]->(basis)
RETURN c.subject_text, c.predicate_text, c.object_text,
       basis.type, basis.raw_content

-- Claims about a specific entity
MATCH (c:Node {type: 'Claim'})-[:ABOUT]->(e:Node {name: 'user'})
RETURN c.subject_text, c.predicate_text, c.object_text
```

### Contradictions

```cypher
-- Find contradicting claims
MATCH (c1:Node {type: 'Claim'})-[:CONTRADICTS]->(c2:Node {type: 'Claim'})
RETURN c1.subject_text, c1.predicate_text, c1.object_text,
       c2.subject_text, c2.predicate_text, c2.object_text

-- Unresolved contradictions
MATCH (c1:Node {type: 'Claim'})-[:CONTRADICTS]->(c2:Node {type: 'Claim'})
WHERE c1.status <> 'superseded' AND c2.status <> 'superseded'
RETURN c1, c2
```

### Tracing Provenance

```cypher
-- Trace a claim back to its origins
MATCH path = (c:Node {type: 'Claim'})-[:BASED_ON*]->(origin)
WHERE NOT (origin)-[:BASED_ON]->()
RETURN path

-- Full lineage for a specific claim
MATCH (c:Node {type: 'Claim', id: $claim_id})
MATCH path = (c)-[:BASED_ON*0..]->(basis)
RETURN path
```

### Cleanup / Admin

```cypher
-- Delete all nodes and relationships (DANGER!)
MATCH (n) DETACH DELETE n

-- Delete only observations
MATCH (n:Node {type: 'Observation'}) DETACH DELETE n

-- Count everything
MATCH (n) RETURN count(n) as total_nodes
```

---

## Graph Visualization Tips

### Color by Type

In the Neo4j Browser graph view:
1. Click on a node
2. Click the colored circle at the bottom
3. Choose a color for that node type
4. Repeat for each type (Observation=blue, Claim=green, Entity=orange, etc.)

### Expand Relationships

- **Double-click** a node to expand its relationships
- **Shift+click** to select multiple nodes
- **Right-click** for context menu (expand, hide, etc.)

### Layout

- Drag nodes to reposition
- Use the layout buttons (force-directed, hierarchical) at bottom right
- Press `Ctrl+click` on empty space to pan

---

## Connection from Code

### Python (neo4j driver)

```python
from neo4j import AsyncGraphDatabase

driver = AsyncGraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", "memory-system")
)

async with driver.session() as session:
    result = await session.run("MATCH (n) RETURN n LIMIT 10")
    records = await result.data()
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Connection URI |
| `NEO4J_USERNAME` | `neo4j` | Username |
| `NEO4J_PASSWORD` | `memory-system` | Password |

In Docker Compose, services use `bolt://neo4j:7687` (internal network).

---

## Troubleshooting

### Can't connect to browser

```bash
# Check if Neo4j is running
docker compose ps neo4j

# Check logs
docker compose logs neo4j

# Restart
docker compose restart neo4j
```

### "No write operations allowed" error

Neo4j Community Edition doesn't support clusters. Ensure only one instance is writing.

### Slow queries

```cypher
-- Add index on frequently queried properties
CREATE INDEX node_type_index FOR (n:Node) ON (n.type)
CREATE INDEX node_id_index FOR (n:Node) ON (n.id)
CREATE INDEX entity_name_index FOR (n:Node) ON (n.name)
```

### Data not persisting

Check the volume is mounted:
```bash
docker volume ls | grep neo4j
docker compose down  # preserves volumes
docker compose down -v  # DELETES volumes
```

---

## See Also

- [Graph Patterns](graph_patterns.md) - Detailed documentation of graph patterns
- [Design Tracking](design_tracking.md) - Full system architecture

---

*Document version: 0.1*
*Last updated: 2026-01-28*
