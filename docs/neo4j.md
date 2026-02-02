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

### Node Labels

The graph uses four distinct Neo4j labels (not a generic `:Node` with type property).

| Label | Properties | Description |
|-------|------------|-------------|
| `:Concept` | `id`, `name`, `kind`, `aliases[]`, `created_at` | Named thing (person, place, idea, value, category) |
| `:Statement` | `id`, `predicate`, `confidence`, `negated`, `created_at` | Reified triple with metadata |
| `:Observation` | `id`, `raw_content`, `topics[]`, `created_at` | Raw natural language input |
| `:Source` | `id`, `name`, `kind`, `created_at` | Who produced this knowledge (user, agent, system) |

### Relationship Types

| Relationship | From | To | Meaning |
|--------------|------|------|---------|
| `ABOUT_SUBJECT` | Statement | Concept | Subject of the statement |
| `ABOUT_OBJECT` | Statement | Concept | Object/value of the statement |
| `DERIVED_FROM` | Statement | Observation or Statement | Provenance chain |
| `ASSERTED_BY` | Statement | Source | Who asserted this |
| `SUPERSEDES` | Statement | Statement | Newer replaces older |
| `CONTRADICTS` | Statement | Statement | Conflicting statements |
| `MENTIONS` | Observation | Concept | Concepts in the observation |
| `RECORDED_BY` | Observation | Source | Who recorded this |
| `RELATED_TO` | Concept | Concept | Decomposition/hierarchy (property: `relation`) |

---

## Common Queries

### Exploration

```cypher
-- See everything (limit for safety)
MATCH (n) RETURN n LIMIT 50

-- Count nodes by label
MATCH (n) RETURN labels(n)[0] AS label, count(*) ORDER BY count(*) DESC

-- List all relationship types
CALL db.relationshipTypes()

-- Show indexes and constraints
SHOW INDEXES
SHOW CONSTRAINTS
```

### Observations

```cypher
-- All observations
MATCH (o:Observation)
RETURN o.raw_content, o.topics, o.created_at
ORDER BY o.created_at DESC

-- Recent observations (last 10)
MATCH (o:Observation)
RETURN o.raw_content, o.created_at
ORDER BY o.created_at DESC
LIMIT 10

-- Observations with their source
MATCH (o:Observation)-[:RECORDED_BY]->(src:Source)
RETURN o.raw_content, src.name, o.created_at
ORDER BY o.created_at DESC

-- What concepts does an observation mention?
MATCH (o:Observation)-[:MENTIONS]->(c:Concept)
RETURN o.raw_content, collect(c.name) AS concepts
```

### Concepts

```cypher
-- All concepts
MATCH (c:Concept)
RETURN c.name, c.kind, c.aliases
ORDER BY c.name

-- Concept decomposition
MATCH (c:Concept)-[r:RELATED_TO]->(sub:Concept)
RETURN c.name, r.relation, sub.name

-- Find a specific concept (case-insensitive)
MATCH (c:Concept)
WHERE toLower(c.name) = 'bitcoin'
RETURN c
```

### Statements

```cypher
-- All statements with subject and object names
MATCH (s:Statement)
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, s.confidence, s.negated
ORDER BY s.created_at DESC

-- Active statements only (not superseded)
MATCH (s:Statement)
WHERE NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s) }
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, s.confidence

-- Statements about a specific concept
MATCH (s:Statement)-[:ABOUT_SUBJECT|ABOUT_OBJECT]->(c:Concept)
WHERE toLower(c.name) = 'user'
AND NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s) }
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, s.confidence

-- Statements with their basis
MATCH (s:Statement)-[:DERIVED_FROM]->(basis)
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, labels(basis)[0] AS basis_type,
       CASE WHEN basis:Observation THEN basis.raw_content ELSE null END AS basis_content
```

### Sources

```cypher
-- All sources
MATCH (src:Source)
RETURN src.name, src.kind, src.created_at

-- What has a source asserted?
MATCH (s:Statement)-[:ASSERTED_BY]->(src:Source {name: 'inference_agent'})
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, s.confidence
```

### Contradictions

```cypher
-- Find contradicting statements
MATCH (s1:Statement)-[:CONTRADICTS]->(s2:Statement)
OPTIONAL MATCH (s1)-[:ABOUT_SUBJECT]->(subj1:Concept)
OPTIONAL MATCH (s1)-[:ABOUT_OBJECT]->(obj1:Concept)
OPTIONAL MATCH (s2)-[:ABOUT_SUBJECT]->(subj2:Concept)
OPTIONAL MATCH (s2)-[:ABOUT_OBJECT]->(obj2:Concept)
RETURN subj1.name, s1.predicate, obj1.name,
       subj2.name, s2.predicate, obj2.name

-- Unresolved contradictions (neither side superseded)
MATCH (s1:Statement)-[:CONTRADICTS]->(s2:Statement)
WHERE NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s1) }
AND NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s2) }
RETURN s1, s2
```

### Tracing Provenance

```cypher
-- Trace a statement back to its origins
MATCH path = (s:Statement)-[:DERIVED_FROM*]->(origin)
WHERE NOT (origin)-[:DERIVED_FROM]->()
RETURN path

-- Full lineage for a specific statement
MATCH (s:Statement {id: $stmt_id})
MATCH path = (s)-[:DERIVED_FROM*0..]->(basis)
RETURN path
```

### Cleanup / Admin

```cypher
-- Delete all nodes and relationships (DANGER!)
MATCH (n) DETACH DELETE n

-- Delete only observations
MATCH (n:Observation) DETACH DELETE n

-- Count everything
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS total
```

---

## Graph Visualization Tips

### Color by Label

In the Neo4j Browser graph view, nodes are automatically colored by label. You can customize:
1. Click on a node
2. Click the colored circle at the bottom
3. Choose a color for that label

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

## Indexes and Constraints

The system automatically creates these on startup via `store.ensure_indexes()`:

```cypher
-- Uniqueness constraints
CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE
CREATE CONSTRAINT statement_id IF NOT EXISTS FOR (s:Statement) REQUIRE s.id IS UNIQUE
CREATE CONSTRAINT observation_id IF NOT EXISTS FOR (o:Observation) REQUIRE o.id IS UNIQUE
CREATE CONSTRAINT source_id IF NOT EXISTS FOR (s:Source) REQUIRE s.id IS UNIQUE

-- Performance indexes
CREATE INDEX concept_name IF NOT EXISTS FOR (c:Concept) ON (c.name)
CREATE INDEX statement_predicate IF NOT EXISTS FOR (s:Statement) ON (s.predicate)
CREATE INDEX statement_created IF NOT EXISTS FOR (s:Statement) ON (s.created_at)
CREATE INDEX observation_created IF NOT EXISTS FOR (o:Observation) ON (o.created_at)
```

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

### Data not persisting

Check the volume is mounted:
```bash
docker volume ls | grep neo4j
docker compose down  # preserves volumes
docker compose down -v  # DELETES volumes
```

---

## See Also

- [Knowledge Representation](knowledge_representation.md) - How knowledge is stored and queried
- [Graph Patterns](graph_patterns.md) - Neo4j graph patterns and visualization
- [Design Tracking](design_tracking.md) - Full system architecture

---

*Document version: 2.0*
*Last updated: 2026-02-02*
