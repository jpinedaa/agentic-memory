# Agentic Memory Management System

## Design Document v0.1

---

## 1. Overview

A shared memory substrate that multiple agents interact with as a service. The system provides a natural language interface for storing and retrieving knowledge, backed by a graph database that enables CRDT-style eventual consistency.

### Core Principles

- **Append-only**: No overwrites, no conflicts at write time
- **Contradiction as data**: Conflicting claims coexist; tension is signal, not error
- **Dumb storage, smart conventions**: The database stores triples with no enforced schema; meaning lives in conventions that agents agree on
- **Natural language interface**: Agents interact via unstructured text; an LLM layer translates to/from structured triples

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       External World                            │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   │
│   │   Chat   │   │  Robot   │   │ Document │   │   API    │   │
│   │Interface │   │ Sensors  │   │  Loader  │   │  Feed    │   │
│   └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘   │
└────────┼──────────────┼──────────────┼──────────────┼──────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Observation Adapters                           │
│              (modular, source-specific)                         │
│                                                                 │
│    observe("user said they hate morning meetings")              │
│                                                                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                   Natural Language Interface                    │
│                                                                 │
│    observe(text)  →  LLM  →  triples                           │
│    claim(text)    →  LLM  →  triples                           │
│    remember(text) →  LLM  →  query → LLM → resolved response   │
│                                                                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                    Triple Store (Neo4j)                         │
│                                                                 │
│                  (subject, predicate, object)                   │
│                                                                 │
│    No enforced schema. No special node types.                   │
│    Just triples.                                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                             ▲
                             │
┌────────────────────────────┴────────────────────────────────────┐
│                                                                 │
│                      Agent Population                           │
│                                                                 │
│    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐   │
│    │  Main   │    │ Insight │    │  Dedup  │    │Validator│   │
│    │  Agent  │    │  Miner  │    │ Worker  │    │  Agent  │   │
│    └─────────┘    └─────────┘    └─────────┘    └─────────┘   │
│                                                                 │
│    claim("user prefers afternoon meetings")                     │
│    remember("what contradictions exist about user preferences") │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Model

For the full knowledge representation model, see [Knowledge Representation](knowledge_representation.md).

### 3.1 The Triple

The fundamental unit of storage:

```
(subject, predicate, object)
```

Triples are **reified** as Statement nodes with edges to Concept nodes, enabling metadata (confidence, provenance, negation) on every assertion.

### 3.2 Neo4j Labels

The graph uses four distinct Neo4j labels (proper labels, not `:Node` with a type property):

| Label | Purpose | Key Properties |
|-------|---------|----------------|
| `:Concept` | Any thing, idea, category, or value | `id`, `name`, `kind`, `aliases[]`, `created_at` |
| `:Statement` | A reified triple with metadata | `id`, `predicate`, `confidence`, `negated`, `created_at` |
| `:Observation` | Raw input from external world | `id`, `raw_content`, `topics[]`, `created_at` |
| `:Source` | Agent, user, or system that produced knowledge | `id`, `name`, `kind`, `created_at` |

### 3.3 Relationships

| Relationship | From → To | Purpose |
|---|---|---|
| `ABOUT_SUBJECT` | Statement → Concept | Subject of the statement |
| `ABOUT_OBJECT` | Statement → Concept | Object/value of the statement |
| `DERIVED_FROM` | Statement → Observation or Statement | Provenance chain |
| `ASSERTED_BY` | Statement → Source | Who made this assertion |
| `SUPERSEDES` | Statement → Statement | Resolution (newer replaces older) |
| `CONTRADICTS` | Statement → Statement | Conflicting statements |
| `MENTIONS` | Observation → Concept | Concepts in the observation |
| `RECORDED_BY` | Observation → Source | Who recorded this |
| `RELATED_TO` | Concept → Concept | Decomposition/hierarchy (property: `relation`) |

### 3.4 Example

```
Input: "bitcoin is a peer-to-peer network"

(:Observation {raw_content: "bitcoin is a peer-to-peer network"})
  ├──MENTIONS──▶ (:Concept {name: "bitcoin", kind: "entity"})
  ├──MENTIONS──▶ (:Concept {name: "peer-to-peer network", kind: "category"})
  └──RECORDED_BY──▶ (:Source {name: "cli_user", kind: "user"})

(:Statement {predicate: "is", confidence: 1.0})
  ├──ABOUT_SUBJECT──▶ (:Concept {name: "bitcoin"})
  ├──ABOUT_OBJECT──▶ (:Concept {name: "peer-to-peer network"})
  ├──DERIVED_FROM──▶ (the Observation)
  └──ASSERTED_BY──▶ (:Source {name: "cli_user"})

(:Concept {name: "peer-to-peer network"})
  ├──RELATED_TO {relation: "is_a"}──▶ (:Concept {name: "network"})
  └──RELATED_TO {relation: "has_property"}──▶ (:Concept {name: "peer-to-peer"})
```

See [Knowledge Representation](knowledge_representation.md) for the full model.

---

## 4. Interface

### 4.1 Design Principles

- **Natural language in, natural language out**: Callers pass strings, receive strings
- **LLM translation layer**: Converts between natural language and triples
- **Implicit metadata**: Source and timestamp bound at interface creation, never passed explicitly
- **Resolved reads**: `remember()` returns the current resolved state, handling contradictions

### 4.2 Interface Binding

Interfaces are created with a bound source identity:

```python
# Adapters create observation interfaces
chat_observer = ObservationInterface(source="chat_interface")

# Agents create claim interfaces
inference_agent = AgentInterface(source="inference_agent")
validator_agent = AgentInterface(source="validator_agent")
```

### 4.3 Methods

#### observe(text: str) → None

**Caller**: Observation adapters only

**Purpose**: Record a perception from the external world

**Behavior**:
1. LLM extracts concepts (with kind, aliases, decomposition) and statements (with confidence, negation)
2. Creates Source node (get_or_create), Observation node, links via RECORDED_BY
3. Creates Concept nodes for each mentioned concept; links via MENTIONS
4. For compound concepts, decomposes via RELATED_TO edges to sub-concepts
5. Creates Statement nodes (reified triples) with ABOUT_SUBJECT, ABOUT_OBJECT, DERIVED_FROM, ASSERTED_BY

**Example**:
```python
chat_observer.observe("user said they hate waking up early for meetings")
```

#### claim(text: str) → None

**Caller**: Agents only

**Purpose**: Assert an inference, fact, contradiction, or resolution

**Behavior**:
1. LLM parses the claim, identifies:
   - What is being asserted
   - What it's based on (searches for relevant nodes to link as basis)
   - Confidence level (inferred from language or explicit)
   - Whether it contradicts/supersedes existing claims
2. Creates Claim node with appropriate triples
3. Writes triples to store

**Examples**:
```python
inference_agent.claim("based on their statement about early meetings, user prefers afternoon meetings")

validator_agent.claim("the claim that user prefers morning meetings contradicts the claim that user prefers afternoon meetings")

resolution_agent.claim("resolving the meeting preference conflict: user prefers afternoon meetings, superseding the morning claim due to higher confidence")
```

#### remember(query: str) → str

**Caller**: Any (adapters, agents, external)

**Purpose**: Retrieve resolved current state of knowledge

**Behavior**:
1. LLM translates query into graph query
2. Executes query against store
3. Gathers relevant nodes (observations, claims, resolutions)
4. Resolves contradictions:
   - Superseded claims are excluded
   - Unresolved contradictions are noted
   - Most confident/recent takes precedence where no explicit resolution
5. LLM synthesizes natural language response from resolved data

**Example**:
```python
response = memory.remember("what are the user's meeting preferences?")
# Returns: "User prefers afternoon meetings (confidence: 0.85). 
#          This was inferred from their statement about disliking early meetings."
```

---

## 5. Concurrency Model

### 5.1 CRDT-Style Semantics

**No conflicts at write time.** Ever.

- `observe()` appends a new Observation node
- `claim()` appends a new Claim node
- Both operations always succeed
- Multiple agents writing simultaneously create multiple nodes

**Contradictions are data, not errors.**

When Agent A claims "user prefers morning" and Agent B claims "user prefers afternoon":
- Both claims exist in the store
- Neither overwrites the other
- A downstream agent (or the resolution layer in `remember()`) reconciles

### 5.2 Convergence

Convergence happens at read time and/or via worker agents:

**Read-time resolution** (`remember()`):
- Follows `supersedes` links to exclude old claims
- Weights by confidence and recency
- Notes unresolved contradictions in response

**Worker-agent resolution**:
- Validator agent continuously monitors for contradictions
- Resolution agent evaluates and creates Resolution nodes
- These become the authoritative resolved state

### 5.3 Write Ordering

Within a single source, writes are ordered by timestamp.

Across sources, no global ordering is guaranteed or required. Causality is captured through `basis` links, not timestamps.

---

## 6. Storage Layer

### 6.1 Neo4j Implementation

Neo4j is used with proper labels (`:Concept`, `:Statement`, `:Observation`, `:Source`) and reified triples. All assertions are Statement nodes with edges to their subject/object Concepts.

```cypher
// Create a statement (reified triple)
CREATE (s:Statement {id: $id, predicate: $pred, confidence: $conf, negated: false, created_at: datetime()})

// Link to subject and object concepts
MATCH (s:Statement {id: $stmt_id}), (c:Concept {id: $concept_id})
CREATE (s)-[:ABOUT_SUBJECT]->(c)
```

Indexes and uniqueness constraints are created automatically by `store.ensure_indexes()`.

### 6.2 Core Queries

```cypher
// Get all statements about a concept (excluding superseded)
MATCH (s:Statement)-[:ABOUT_SUBJECT|ABOUT_OBJECT]->(c:Concept {id: $concept_id})
WHERE NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s) }
OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
RETURN subj.name, s.predicate, obj.name, s.confidence

// Get all statements derived from an observation
MATCH (s:Statement)-[:DERIVED_FROM]->(o:Observation {id: $obs_id})
RETURN s

// Get all unresolved contradictions
MATCH (s1:Statement)-[:CONTRADICTS]->(s2:Statement)
WHERE NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s1) }
AND NOT EXISTS { MATCH (:Statement)-[:SUPERSEDES]->(s2) }
RETURN s1, s2

// Concept decomposition
MATCH (c:Concept)-[r:RELATED_TO]->(sub:Concept)
RETURN c.name, r.relation, sub.name
```

---

## 7. LLM Translation Layer

### 7.1 Responsibilities

The LLM layer sits between the natural language interface and the triple store:

```
Natural Language  ←→  LLM Layer  ←→  Triples/Cypher
```

**For `observe()`**:
- Extract entities mentioned
- Identify relationships expressed
- Preserve raw content
- Generate appropriate triples

**For `claim()`**:
- Parse the assertion
- Identify basis (may need to query store to find relevant nodes)
- Detect supersession/contradiction language
- Infer confidence from hedging language
- Generate appropriate triples

**For `remember()`**:
- Translate query to Cypher
- Execute and gather results
- Apply resolution logic
- Synthesize coherent natural language response

### 7.2 Prompt Structure (Sketch)

```
System: You are a translation layer between natural language and a knowledge graph.

For OBSERVE operations:
- Input: raw observation text, source identifier
- Output: JSON with extracted entities, relationships, and raw content
- Preserve original wording in raw_content

For CLAIM operations:
- Input: claim text, source identifier, relevant context from store
- Output: JSON with claim structure, basis links, confidence, contradiction/supersession flags

For REMEMBER operations:
- Input: query text, retrieved graph data
- Output: natural language synthesis of resolved state
```

### 7.3 Example Translations

**Observe**:
```
Input: "user said they hate waking up early for meetings"

Output (ObservationData):
{
  "concepts": [
    {"name": "user", "kind": "entity"},
    {"name": "early meetings", "kind": "value", "components": [
      {"name": "meetings", "relation": "head_noun"},
      {"name": "early", "relation": "modifier"}
    ]}
  ],
  "statements": [
    {"subject": "user", "predicate": "hates", "object": "early meetings", "confidence": 0.9}
  ],
  "topics": ["meetings", "schedule", "morning"]
}
```

**Claim**:
```
Input: "based on their statement about early meetings, user prefers afternoon meetings"
Context: [obs_123 about hating early meetings]

Output:
{
  "subject": "user",
  "predicate": "prefers",
  "object": "afternoon meetings",
  "confidence": 0.8,
  "negated": false,
  "basis_descriptions": ["user said they hate waking up early for meetings"],
  "supersedes_description": null,
  "contradicts_description": null
}
```

---

## 8. Agent Architecture

### 8.1 Agent Types

**Observation Adapters** (not agents, but similar lifecycle):
- Bound to external source
- Can only call `observe()`
- Examples: chat interface, document loader, API poller

**Worker Agents** (run continuously):
- Monitor store for patterns
- Make claims based on analysis
- Examples: deduplication, contradiction detection, insight mining

**Task Agents** (triggered):
- Invoked for specific tasks
- May use `remember()` and `claim()`
- Examples: question answering, summarization

### 8.2 Agent Loop (Worker)

```python
class WorkerAgent:
    def __init__(self, source_id: str, memory: AgentInterface):
        self.source_id = source_id
        self.memory = memory
    
    async def run(self):
        while True:
            # Check for relevant new content
            context = self.memory.remember(self.watch_query())
            
            # Process and potentially make claims
            if self.should_act(context):
                claims = self.process(context)
                for claim in claims:
                    self.memory.claim(claim)
            
            await asyncio.sleep(self.poll_interval)
    
    def watch_query(self) -> str:
        """What this agent monitors for"""
        raise NotImplementedError
    
    def should_act(self, context: str) -> bool:
        """Whether to process this context"""
        raise NotImplementedError
    
    def process(self, context: str) -> list[str]:
        """Generate claims from context"""
        raise NotImplementedError
```

### 8.3 Example Agents

**Contradiction Detector**:
```python
class ContradictionDetector(WorkerAgent):
    def watch_query(self):
        return "what recent claims exist that might contradict each other?"
    
    def should_act(self, context):
        return "no contradictions" not in context.lower()
    
    def process(self, context):
        # LLM analyzes context, identifies contradictions
        # Returns claims like "claim X contradicts claim Y"
        ...
```

**Insight Miner**:
```python
class InsightMiner(WorkerAgent):
    def watch_query(self):
        return "what patterns or insights can be derived from recent observations and claims?"
    
    def process(self, context):
        # LLM identifies higher-order patterns
        # Returns claims like "user consistently prefers X over Y"
        ...
```

---

## 9. Prototype Scope

### 9.1 Components for v0.1

1. **Neo4j container** (docker)
2. **Triple store wrapper** (Python, basic CRUD)
3. **LLM translation layer** (OpenAI/Anthropic API)
4. **Natural language interface** (`observe`, `claim`, `remember`)
5. **Chat adapter** (stdin/stdout or simple web interface)
6. **Two worker agents**:
   - Inference agent (observations → claims)
   - Validator agent (detects contradictions)

### 9.2 Test Scenario

```
Human → Chat Interface → observe("I prefer morning meetings")
                                    ↓
                              [stored as observation]
                                    ↓
        Inference Agent ← [monitors new observations]
                                    ↓
                         claim("user prefers morning meetings")
                                    ↓
Human → Chat Interface → observe("actually I hate mornings, afternoon is better")
                                    ↓
        Inference Agent → claim("user prefers afternoon meetings")
                                    ↓
        Validator Agent ← [monitors for contradictions]
                                    ↓
                         claim("morning preference contradicts afternoon preference")
                                    ↓
Human → Chat Interface → remember("what are my meeting preferences?")
                                    ↓
                         Response: "Your meeting preferences show some evolution.
                                   Initially you mentioned preferring mornings, but
                                   more recently indicated you prefer afternoons.
                                   Current preference: afternoon meetings."
```

### 9.3 Not in v0.1

- Authentication/authorization
- Multi-tenancy
- Persistence beyond Neo4j (backups, replication)
- Advanced resolution strategies
- Subscription/reactive notifications
- Performance optimization
- Production error handling

---

## 10. Open Questions

### 10.1 Resolved (v0.1–v0.2)

1. ~~**LLM choice**~~: Anthropic Claude API (tool_use for structured output)
2. ~~**Agent orchestration**~~: asyncio in dev mode; separate processes + Redis pub/sub in distributed mode
3. ~~**Chat interface**~~: CLI (stdin/stdout)
4. ~~**Subscription model**~~: Redis pub/sub with polling fallback (30s)

### 10.2 Open

1. **Confidence calibration**: Should confidence be normalized across agents?
2. **Memory decay**: Do old, low-confidence claims eventually get pruned?
3. **Scoping/namespacing**: Can there be isolated memory regions?
4. **Access control**: Can certain claims be private to certain agents?
5. **Agent framework integration**: How to best wrap MemoryAPI as tools for LangGraph, CrewAI, etc.?

---

## 11. File Structure

See Section 13.5 for the current file structure (v0.2). The original v0.1 proposal below was simplified during implementation (flattened modules, no subdirectories for store/interface/llm).

<details>
<summary>Original v0.1 proposal (superseded)</summary>

```
memory-system/
├── docker-compose.yml          # Neo4j container
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── store/
│   │   ├── __init__.py
│   │   ├── triple_store.py     # Neo4j wrapper
│   │   └── queries.py          # Cypher query builders
│   ├── interface/
│   │   ├── __init__.py
│   │   ├── base.py             # Interface base classes
│   │   ├── observation.py      # ObservationInterface
│   │   ├── agent.py            # AgentInterface
│   │   └── memory.py           # remember() implementation
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── translator.py       # NL ↔ triples translation
│   │   └── prompts.py          # Prompt templates
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py             # WorkerAgent base class
│   │   ├── inference.py        # InferenceAgent
│   │   └── validator.py        # ValidatorAgent
│   └── adapters/
│       ├── __init__.py
│       └── chat.py             # ChatAdapter
├── tests/
│   └── ...
└── main.py                     # Entry point, orchestration
```
</details>

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Triple** | (subject, predicate, object) - fundamental storage unit |
| **Node** | An entity in the graph, identified by UUID |
| **Observation** | A node representing external input; created by adapters |
| **Claim** | A node representing an assertion; created by agents |
| **Resolution** | A claim that resolves contradicting claims |
| **Basis** | Link from a claim to what it's based on |
| **Supersedes** | Link indicating one node replaces another |
| **Adapter** | Component that translates external input to observations |
| **Worker Agent** | Continuously running agent that monitors and processes |
| **Convention** | Agreed-upon meaning for predicates/types; not enforced by DB |

---

## Appendix B: References

- CRDT literature for convergence semantics
- Knowledge graph patterns
- Event sourcing / append-only architectures
- LLM-based information extraction

---

*Document version: 0.7*
*Last updated: 2026-02-02*
*Status: v0.3 P2P architecture with UI bridge. Knowledge representation redesigned: proper Neo4j labels (:Concept, :Statement, :Observation, :Source), reified triples, concept decomposition. See knowledge_representation.md.*

---

## 12. Implementation Plan

### 12.1 Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM Provider | Anthropic Claude API | First-party SDK, consistent with system goals |
| Chat Interface | CLI (stdin/stdout) | Fastest to prototype; sufficient for v0.1 |
| Orchestration | asyncio I/O concurrency | Bottleneck is network I/O (API calls, Neo4j), not CPU. GIL irrelevant for awaited coroutines |
| Agent Runtime | Framework-agnostic Python API | MemoryService is a clean API; any framework (LangGraph, CrewAI, Claude Agent SDK) can wrap it as tools later |
| Service Boundary | In-process Python API | HTTP/REST can be layered on later without changing core |
| File Structure | Flattened from design doc | Single-file modules for store, llm, interfaces; subdirectory only for agents |

### 12.2 File Structure (Revised)

```
agentic-memory/
├── design_tracking.md
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
├── src/
│   ├── __init__.py
│   ├── store.py                    # Neo4j triple store wrapper + queries
│   ├── llm.py                      # Claude API translation layer + prompts
│   ├── interfaces.py               # MemoryService (observe, claim, remember)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py                 # WorkerAgent ABC (asyncio loop)
│   │   ├── inference.py            # InferenceAgent
│   │   └── validator.py            # ValidatorAgent
│   └── cli.py                      # CLI chat adapter
├── tests/
│   ├── __init__.py
│   ├── test_store.py
│   ├── test_llm.py
│   ├── test_interfaces.py
│   └── test_integration.py
└── main.py
```

### 12.3 Core API Design

```python
class MemoryService:
    """Framework-agnostic memory API. Agents are callers of this service."""

    async def observe(self, text: str, source: str) -> str
    async def claim(self, text: str, source: str) -> str
    async def remember(self, query: str) -> str
```

To swap agent frameworks later: wrap these methods as tools/functions for the target framework. Core API unchanged.

### 12.4 Data Flow

#### Observation Flow (user input → graph)

```
User types: "I prefer morning meetings"
    │
    ▼
CLI (src/cli.py)
    │ calls memory.observe(text, source="cli_user")
    ▼
MemoryService.observe() (src/interfaces.py)
    │ 1. Calls llm.extract_observation(text)
    ▼
LLMTranslator.extract_observation() (src/llm.py)
    │ Claude tool_use → structured ObservationData:
    │   concepts: [{name: "user", kind: "entity"},
    │              {name: "morning meetings", kind: "value"}]
    │   statements: [{subject: "user", predicate: "prefers",
    │                 object: "morning meetings", confidence: 0.9}]
    │   topics: ["meetings", "schedule"]
    │
    ▼ (back in MemoryService.observe)
    │ 2. store.get_or_create_source("cli_user", kind="user")
    │ 3. store.create_observation(obs_id, raw_content=..., topics=...)
    │ 4. store.create_relationship(obs_id, "RECORDED_BY", source_id)
    │ 5. For each concept: store.get_or_create_concept(name, id, kind)
    │    store.create_relationship(obs_id, "MENTIONS", concept_id)
    │    (decompose compound concepts via RELATED_TO)
    │ 6. For each statement: store.create_statement(stmt_id, predicate, confidence)
    │    store.create_relationship(stmt_id, "ABOUT_SUBJECT", subj_id)
    │    store.create_relationship(stmt_id, "ABOUT_OBJECT", obj_id)
    │    store.create_relationship(stmt_id, "DERIVED_FROM", obs_id)
    │    store.create_relationship(stmt_id, "ASSERTED_BY", source_id)
    ▼
Neo4j Graph:
    (:Observation) --RECORDED_BY--> (:Source {name: "cli_user"})
    (:Observation) --MENTIONS--> (:Concept {name: "user"})
    (:Observation) --MENTIONS--> (:Concept {name: "morning meetings"})
    (:Statement {predicate: "prefers"}) --ABOUT_SUBJECT--> (:Concept {name: "user"})
    (:Statement {predicate: "prefers"}) --ABOUT_OBJECT--> (:Concept {name: "morning meetings"})
    (:Statement) --DERIVED_FROM--> (:Observation)
    (:Statement) --ASSERTED_BY--> (:Source)
```

#### Inference Flow (agent poll loop)

```
InferenceAgent.run() — polls every 5 seconds
    │
    ▼
InferenceAgent.process() (src/agents/inference.py)
    │ 1. store.find_recent_observations(limit=10)
    │ 2. Filter out already-processed observation IDs
    │ 3. For each new observation:
    ▼
MemoryService.infer(raw_content) → LLMTranslator.infer() (src/llm.py)
    │ Claude API call with inference_agent/infer prompt
    │ Input:  "I prefer morning meetings"
    │ Output: "User prefers morning meetings" (or None if SKIP/empty)
    │
    ▼ (back in WorkerAgent.run)
    │ memory.claim("User prefers morning meetings", source="inference_agent")
    ▼
MemoryService.claim() (src/interfaces.py)
    │ 1. Gathers recent statements + observations as context
    │ 2. llm.parse_claim(text, context) → ClaimData:
    │      subject: "user", predicate: "prefers", object: "morning meetings"
    │      confidence: 0.9, basis_descriptions: [...]
    │ 3. store.get_or_create_source("inference_agent", kind="agent")
    │ 4. store.create_statement(stmt_id, predicate, confidence, negated)
    │ 5. store.get_or_create_concept(subject/object)
    │ 6. ABOUT_SUBJECT, ABOUT_OBJECT, ASSERTED_BY edges
    │ 7. If basis found: store.create_relationship(stmt_id, "DERIVED_FROM", basis_id)
    ▼
Neo4j Graph (new):
    (:Statement {predicate: "prefers"}) --ABOUT_SUBJECT--> (:Concept {name: "user"})
    (:Statement) --ABOUT_OBJECT--> (:Concept {name: "morning meetings"})
    (:Statement) --DERIVED_FROM--> (:Observation)
    (:Statement) --ASSERTED_BY--> (:Source {name: "inference_agent"})
```

#### Contradiction Detection Flow

```
ValidatorAgent.run() — polls every 8 seconds
    │
    ▼
ValidatorAgent.process() (src/agents/validator.py)
    │ 1. memory.get_recent_statements(limit=20)
    │ 2. Group by subject_name, then by predicate
    │ 3. Within each group, compare object_name values
    │
    │ Found: "user prefers morning meetings" vs "user prefers afternoon meetings"
    │
    ▼ (back in WorkerAgent.run)
    │ memory.claim("the claim that user prefers 'morning meetings'
    │              contradicts the claim that user prefers 'afternoon meetings'",
    │              source="validator_agent")
    ▼
MemoryService.claim()
    │ LLM parses → contradicts_description set
    │ store.create_relationship(new_claim, "CONTRADICTS", old_claim)
    ▼
Neo4j Graph (new):
    (claim_456) --CONTRADICTS--> (claim_123)
```

#### Remember Flow (query → resolved response)

```
User types: "?what are my meeting preferences?"
    │
    ▼
CLI: memory.remember("what are my meeting preferences?")
    │
    ▼
MemoryService.remember() (src/interfaces.py)
    │ 1. llm.generate_query(text) → Cypher string
    │ 2. store.raw_query(cypher) → results
    │ 3. If empty: _broad_search() fallback (recent obs + claims)
    │ 4. llm.synthesize_response(query, results) → natural language
    │    - Prioritizes Resolution nodes over Claims
    │    - Excludes superseded claims
    │    - Notes unresolved contradictions
    ▼
User sees: "Your meeting preferences have evolved. Initially you
           mentioned preferring mornings, but more recently indicated
           you prefer afternoons. Current preference: afternoon meetings."
```

#### Concurrency Model

```
main.py: asyncio.gather(cli, inference_agent, validator_agent)

    ┌─────────────────────────────────────────────────┐
    │                  Event Loop                      │
    │                                                  │
    │  ┌──────────┐  ┌──────────────┐  ┌───────────┐  │
    │  │   CLI    │  │  Inference   │  │ Validator  │  │
    │  │  await   │  │   Agent     │  │   Agent    │  │
    │  │  stdin   │  │  sleep(5s)  │  │  sleep(8s) │  │
    │  └──┬───────┘  └──┬──────────┘  └──┬─────────┘  │
    │     │             │               │              │
    │     ▼             ▼               ▼              │
    │  ┌──────────────────────────────────────────┐    │
    │  │          MemoryService API               │    │
    │  │    observe()  claim()  remember()        │    │
    │  └──────────────────┬───────────────────────┘    │
    │                     │                            │
    │         ┌───────────┼───────────┐                │
    │         ▼                       ▼                │
    │  ┌────────────┐         ┌────────────┐           │
    │  │  Claude    │         │   Neo4j    │           │
    │  │  API (I/O) │         │   (I/O)   │           │
    │  └────────────┘         └────────────┘           │
    └─────────────────────────────────────────────────┘

All three coroutines share one event loop.
While one awaits I/O (Claude API, Neo4j, stdin), others run.
No GIL contention — all bottlenecks are network I/O.
```

### 12.5 Implementation Phases

1. **Infrastructure**: docker-compose (Neo4j 5.x), requirements.txt, pyproject.toml
2. **Storage Layer**: `src/store.py` — Neo4j wrapper, CRUD, query methods
3. **LLM Translation**: `src/llm.py` — Claude API, extraction/parsing/synthesis
4. **Interfaces**: `src/interfaces.py` — MemoryService composing store + LLM
5. **Agents**: `src/agents/` — WorkerAgent base, InferenceAgent, ValidatorAgent
6. **CLI + Entry Point**: `src/cli.py`, `main.py` — asyncio orchestration
7. **Tests**: Unit + integration (meeting-preferences scenario)

### 12.5 Implementation Status (v0.1)

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Infrastructure | Done | docker-compose.yml, requirements.txt, pyproject.toml |
| 2. Storage Layer | Done | `src/store.py` — async Neo4j wrapper, Option B (properties + relationships) |
| 3. LLM Translation | Done | `src/llm.py` — Claude API with structured JSON extraction |
| 4. Interfaces | Done | `src/interfaces.py` — MemoryService with observe/claim/remember |
| 5. Agents | Done | Inference (observations→claims), Validator (contradiction detection) |
| 6. CLI + Entry Point | Done | `src/cli.py` (? for queries, text for observations), `main.py` (asyncio.gather) |
| 7. Tests | Done | test_store (10 tests), test_llm, test_interfaces, test_integration |

### 12.6 Developer Environment

- **Python**: 3.11+
- **Virtual environment**: `.venv/` (created via `python3 -m venv .venv`)
- **Dependencies**: installed via `pip install -e ".[dev]"`
- **Neo4j**: Docker container via `docker compose up -d` (bolt://localhost:7687, auth: neo4j/memory-system)
- **Redis**: Docker container via `docker compose up -d` (redis://localhost:6379)
- **LLM**: Requires `ANTHROPIC_API_KEY` environment variable (via `.env` file or export)

---

## 13. Distributed Architecture (v0.2)

### 13.1 Motivation

v0.1 ran everything in a single Python process via asyncio. While sufficient for prototyping, this has fundamental limitations:

- **No true parallelism**: Python's GIL means asyncio is concurrent (I/O overlap) but not parallel
- **No horizontal scaling**: Cannot run multiple inference agents across machines
- **No fault isolation**: One agent crashing kills the entire process
- **No independent deployment**: Cannot update agents without restarting the whole system

v0.2 introduces a fully distributed architecture where each component runs as a separate process/container, communicating via HTTP API and Redis pub/sub.

### 13.2 Architecture Diagram

```
                    ┌──────────────┐
                    │   CLI / Web  │
                    │   (client)   │
                    └──────┬───────┘
                           │ HTTP
                           ▼
┌──────────────────────────────────────────────┐
│              FastAPI Server (api)             │
│                                              │
│  POST /v1/observe    GET /v1/observations    │
│  POST /v1/claim      GET /v1/claims          │
│  POST /v1/remember   GET /v1/contradictions  │
│  POST /v1/infer      GET /v1/entities        │
│  POST /v1/admin/clear  GET /v1/health        │
│  GET  /v1/events/stream (SSE)                │
│                                              │
│  ┌────────────────┐  ┌───────────────────┐   │
│  │ MemoryService  │  │  EventBus         │   │
│  │ (store + llm)  │  │  (Redis publish)  │   │
│  └───────┬────────┘  └────────┬──────────┘   │
└──────────┼────────────────────┼──────────────┘
           │                    │
     ┌─────┼────────────────────┼─────┐
     │     ▼                    ▼     │
     │  ┌──────┐          ┌───────┐   │
     │  │Neo4j │          │ Redis │   │
     │  │      │          │       │   │
     │  └──────┘          └───┬───┘   │
     │                        │       │
     └────────────────────────┼───────┘
                              │ pub/sub
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌───────────┐  ┌───────────┐   ┌───────────┐
        │ Inference  │  │ Inference │   │ Validator  │
        │ Agent (1)  │  │ Agent (2) │   │ Agent (1)  │
        └───────────┘  └───────────┘   └───────────┘
        (scalable via docker compose --scale)
```

### 13.3 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Service boundary | HTTP API (FastAPI) | Language-agnostic, standard, debuggable with curl |
| Event delivery | Redis pub/sub | Low-latency agent wakeup; polling fallback for missed events |
| Agent state | Redis SETs | Operational state (processed IDs) belongs in Redis, not the knowledge graph |
| Interface contract | `typing.Protocol` | `MemoryService` and `MemoryClient` have different constructors; structural typing avoids forced inheritance |
| LLM centralization | `POST /v1/infer` on server | Agents don't need Anthropic SDK; API key stays server-side |
| Distributed locks | Redis `SET NX EX` | Ensures exactly-once processing when scaling to N agents; TTL prevents deadlocks |
| Backward compat | Dev mode preserved | `python main.py` still runs everything in-process without Redis |

### 13.4 New Components

#### MemoryAPI Protocol (`src/memory_protocol.py`)

Shared interface contract satisfied by both `MemoryService` (in-process) and `MemoryClient` (HTTP):

```python
@runtime_checkable
class MemoryAPI(Protocol):
    async def observe(self, text: str, source: str) -> str: ...
    async def claim(self, text: str, source: str) -> str: ...
    async def remember(self, query: str) -> str: ...
    async def get_recent_observations(self, limit: int = 10) -> list[dict]: ...
    async def get_recent_statements(self, limit: int = 20) -> list[dict]: ...
    async def get_unresolved_contradictions(self) -> list[tuple[dict, dict]]: ...
    async def get_concepts(self) -> list[dict]: ...
    async def infer(self, observation_text: str) -> str | None: ...
    async def clear(self) -> None: ...
```

#### EventBus (`src/events.py`)

Redis pub/sub wrapper for inter-process notifications:

- Channels: `memory:events:observation`, `memory:events:claim`
- `publish_observation(obs_id)` / `publish_claim(claim_id)` — called by API after mutations
- `listen()` — async iterator yielding events for agent consumption

#### AgentState (`src/agent_state.py`)

Redis-backed persistent state replacing in-memory Python sets:

- `is_processed(key, member)` — `SISMEMBER` check
- `mark_processed(key, member)` — `SADD` to tracking set
- `try_acquire(key, instance_id, ttl)` — distributed lock via `SET NX EX`
- `InMemoryAgentState` — fallback for dev mode without Redis

#### HTTP API (`src/api.py`)

FastAPI application wrapping MemoryService:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/observe` | POST | Record observation |
| `/v1/claim` | POST | Assert a claim |
| `/v1/remember` | POST | Query resolved knowledge |
| `/v1/infer` | POST | LLM inference (used by agents) |
| `/v1/observations/recent` | GET | Recent observations |
| `/v1/claims/recent` | GET | Recent claims |
| `/v1/contradictions/unresolved` | GET | Unresolved contradictions |
| `/v1/entities` | GET | All entities |
| `/v1/admin/clear` | POST | Clear all data |
| `/v1/health` | GET | Service health check |
| `/v1/events/stream` | GET | SSE event stream |

#### HTTP Client (`src/api_client.py`)

`MemoryClient` — drop-in replacement for `MemoryService` when running out-of-process. Satisfies `MemoryAPI` protocol via `httpx.AsyncClient`.

### 13.5 File Structure (v0.2)

```
agentic-memory/
├── docker-compose.yml              # Full stack: neo4j, redis, api, agents
├── Dockerfile                      # Python 3.12-slim, installs [distributed]
├── requirements.txt
├── pyproject.toml                  # v0.2.0 with [distributed] optional deps
├── .env.example
├── .gitignore
├── CLAUDE.md                       # Developer docs and project briefing
├── docs/
│   ├── design_tracking.md          # Full design document
│   ├── graph_patterns.md           # Neo4j graph patterns
│   ├── meta_language_exploration.md # LLM communication design
│   └── test_tracking.md            # Test inventory and plans
├── prompts/
│   ├── shared/base.yaml            # Inherited constraints
│   ├── llm_translator/             # Prompts for src/llm.py
│   ├── inference_agent/            # Prompts for inference agent
│   └── validator_agent/            # Prompts for validator agent
├── src/
│   ├── __init__.py
│   ├── store.py                    # Neo4j triple store wrapper
│   ├── llm.py                      # Claude API translation (tool_use)
│   ├── interfaces.py               # MemoryService + facade methods
│   ├── memory_protocol.py          # MemoryAPI Protocol (shared contract)
│   ├── prompts.py                  # Prompt template loader (YAML + Jinja2)
│   ├── api.py                      # FastAPI HTTP server
│   ├── api_client.py               # MemoryClient (HTTP implementation)
│   ├── events.py                   # Redis EventBus (pub/sub)
│   ├── agent_state.py              # Redis AgentState + InMemoryAgentState
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py                 # WorkerAgent ABC (event-driven + polling)
│   │   ├── inference.py            # InferenceAgent
│   │   └── validator.py            # ValidatorAgent
│   └── cli.py                      # CLI chat adapter
├── run_inference_agent.py           # Standalone agent entry point
├── run_validator_agent.py           # Standalone agent entry point
├── run_cli.py                       # Standalone CLI entry point
├── main.py                          # Dev mode (in-process, all components)
└── tests/
    ├── __init__.py
    ├── conftest.py                 # Pytest config, fixtures, .env loading
    ├── test_prompts.py             # Prompt template system tests
    ├── test_store.py
    ├── test_llm.py
    ├── test_interfaces.py
    └── test_integration.py
```

### 13.6 Running Modes

#### Dev Mode (single process, no Redis required)

```bash
docker compose up -d neo4j    # just the database
python main.py                # runs API + agents + CLI in one process
```

Uses `InMemoryAgentState` as fallback. If `REDIS_URL` is set, uses Redis for state and events.

#### Distributed Mode (multi-process)

```bash
docker compose up              # starts neo4j, redis, api, agents
python run_cli.py              # or any HTTP client
```

Or manually:

```bash
docker compose up -d neo4j redis
uvicorn src.api:app --port 8000       # terminal 1
python run_inference_agent.py          # terminal 2
python run_validator_agent.py          # terminal 3
python run_cli.py                      # terminal 4
```

#### Scaled Mode

```bash
docker compose up --scale inference-agent=3
```

Multiple inference agents coordinate via Redis distributed locks — each observation is processed exactly once.

### 13.7 Distributed Concurrency Model

```
┌──────────────────────────────────────────────────────┐
│                   Docker Network                       │
│                                                        │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
│  │  API    │  │Inference│  │Inference│  │Validator│  │
│  │ Server  │  │Agent #1 │  │Agent #2 │  │ Agent   │  │
│  │ (pid 1) │  │ (pid 2) │  │ (pid 3) │  │ (pid 4) │  │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  │
│       │            │            │            │        │
│       ▼            ▼            ▼            ▼        │
│  ┌──────────────────────────────────────────────┐     │
│  │                  Redis                        │     │
│  │  pub/sub: memory:events:{observation,claim}   │     │
│  │  sets: agent:{name}:processed                 │     │
│  │  locks: agent:{name}:lock:{item_id}           │     │
│  └──────────────────────────────────────────────┘     │
│       │                                               │
│       ▼                                               │
│  ┌──────────┐                                         │
│  │  Neo4j   │  (only accessed by API server)          │
│  └──────────┘                                         │
└──────────────────────────────────────────────────────┘

Event flow:
1. CLI → POST /v1/observe → API writes to Neo4j
2. API → Redis PUBLISH memory:events:observation
3. Inference Agent #1 receives event, acquires lock (SET NX EX)
4. Inference Agent #2 receives same event, lock fails → skips
5. Agent #1 → POST /v1/infer → API calls Claude → returns claim text
6. Agent #1 → POST /v1/claim → API writes to Neo4j
7. API → Redis PUBLISH memory:events:claim
8. Validator Agent receives claim event, checks for contradictions
```

### 13.8 Implementation Status (v0.2)

| Phase | Status | Notes |
|-------|--------|-------|
| 1. MemoryAPI Protocol + Facades | Done | `src/memory_protocol.py`, facade methods in `src/interfaces.py` |
| 2. Redis EventBus + AgentState | Done | `src/events.py`, `src/agent_state.py` |
| 3. FastAPI HTTP Layer | Done | `src/api.py`, `src/api_client.py` |
| 4. Standalone Entry Points | Done | `run_inference_agent.py`, `run_validator_agent.py`, `run_cli.py` |
| 5. Containerize + Docs | Done | `Dockerfile`, `docker-compose.yml`, updated `CLAUDE.md` |

### 13.9 Open Items

- [ ] Create `tests/test_api.py` for HTTP endpoint tests
- [ ] Update existing tests for protocol-based interfaces
- [ ] Run full distributed integration test (docker compose up)
- [ ] Scale test: verify exactly-once processing with multiple inference agents
- [ ] SSE event stream testing
- [ ] Add monitoring/observability (structured logging, health metrics)
- [x] ~~Evaluate agent framework swappability~~ (superseded by P2P architecture in v0.3)
- [ ] Consider persistence/recovery strategies (what happens when agents restart mid-processing)

---

## 14. Peer-to-Peer Architecture (v0.3)

### 14.1 Motivation

v0.2 used a hub-and-spoke topology: a centralized FastAPI server + Redis broker, with agents as thin HTTP clients. This had limitations:

- **Single point of failure**: API server down = entire system down
- **Centralized bottleneck**: All requests funneled through one server
- **Agents are second-class**: They can't talk to each other or access capabilities directly
- **Infrastructure dependency**: Redis required for coordination even though its role was simple

v0.3 replaces this with a peer-to-peer network where every node is identical in networking (HTTP server + WebSocket + HTTP client) and differs only in capabilities.

### 14.2 Architecture Diagram

```
     ┌─────────────────────────────────────┐
     │            PeerNode                 │
     │                                     │
     │  ┌───────────┐  ┌────────────────┐  │
     │  │ Transport  │  │  Application   │  │
     │  │ Server     │  │  (capabilities)│  │
     │  │ (FastAPI)  │  │  Store/LLM/    │  │
     │  │ HTTP + WS  │  │  Inference/etc │  │
     │  └───────────┘  └────────────────┘  │
     │  ┌───────────┐  ┌────────────────┐  │
     │  │ Transport  │  │  Gossip +      │  │
     │  │ Client     │  │  Routing Table │  │
     │  │ (httpx+ws) │  │                │  │
     │  └───────────┘  └────────────────┘  │
     └─────────────────────────────────────┘
```

Every node runs this same structure. Communication:

```
  Store+LLM Node ◄──WS──► Inference Node
       ▲                        ▲
       │                        │
      WS                      WS
       │                        │
       ▼                        ▼
  CLI Node ◄────WS────► Validator Node
```

Nodes discover each other via bootstrap seed URLs, maintain WebSocket neighbor connections (up to 8), and propagate state via gossip.

### 14.3 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Transport | HTTP + WebSocket | Universal, works across internet, FastAPI supports both natively |
| Discovery | Seed node URLs | Simple, works across internet, no multicast needed |
| State propagation | Push-based gossip | Decentralized, convergent, evolvable |
| Coordination | Local state per node | Append-only store makes duplicate processing harmless |
| Node identity | Capability-based | Nodes differ only in what they can do, not in how they communicate |
| Interface contract | `MemoryAPI` Protocol (unchanged) | `P2PMemoryClient` satisfies same protocol as old `MemoryClient` |
| Infrastructure | No Redis | Gossip replaces pub/sub, local state replaces Redis SETs |

### 14.4 Components

#### Node Types (by capability)

| Capability | What it provides | Dependencies |
|---|---|---|
| `store` | Neo4j access (observe, claim, query) | Neo4j |
| `llm` | Claude API (infer, parse claims) | Anthropic API key |
| `inference` | InferenceAgent logic | Needs `store`+`llm` peer |
| `validation` | ValidatorAgent logic | Needs `store` peer |
| `cli` | Interactive user I/O | Needs `store`+`llm` peer |

#### Protocol Layer (`src/p2p/`)

| File | Purpose |
|---|---|
| `types.py` | `PeerInfo` (identity), `PeerState` (mutable status), `Capability` enum |
| `messages.py` | `Envelope` — universal message wrapper for all P2P communication |
| `routing.py` | `RoutingTable` — maps MemoryAPI methods to capable peers |
| `transport.py` | `TransportServer` (FastAPI) + `TransportClient` (httpx + websockets) |
| `gossip.py` | Push-based gossip — fanout to 3 random neighbors every 5s |
| `node.py` | `PeerNode` — core runtime: lifecycle, dispatch, neighbor management |
| `memory_client.py` | `P2PMemoryClient` — implements `MemoryAPI` via capability-based routing |
| `local_state.py` | `LocalAgentState` — replaces Redis-backed `AgentState` |

#### Message Types

| Type | Direction | Purpose |
|---|---|---|
| `join` / `welcome` | new → seed | Bootstrap discovery |
| `gossip` | neighbor → neighbor | Peer state propagation |
| `request` / `response` | caller → capable peer | MemoryAPI RPC |
| `event` | originator → flood | Observation/claim broadcast (TTL-limited) |
| `ping` / `pong` | peer ↔ peer | Liveness check |
| `leave` | departing → neighbors | Graceful shutdown |

### 14.5 File Structure (v0.3)

```
agentic-memory/
├── docker-compose.yml              # Full stack: neo4j + P2P nodes + UI
├── docker-compose.test.yml         # E2E test overlay
├── Dockerfile
├── Makefile                        # Deployment targets
├── pyproject.toml                  # v0.3.0
├── src/
│   ├── p2p/                        # P2P protocol layer
│   │   ├── types.py
│   │   ├── messages.py
│   │   ├── routing.py
│   │   ├── transport.py
│   │   ├── gossip.py
│   │   ├── node.py
│   │   ├── memory_client.py
│   │   ├── local_state.py
│   │   └── ui_bridge.py            # UI bridge (/v1/ endpoints for React)
│   ├── store.py                    # Neo4j (unchanged)
│   ├── llm.py                      # Claude API (unchanged)
│   ├── interfaces.py               # MemoryService (unchanged)
│   ├── memory_protocol.py          # MemoryAPI Protocol (unchanged)
│   ├── prompts.py                  # Prompt loader (unchanged)
│   ├── agents/
│   │   ├── base.py                 # WorkerAgent (updated: P2P events)
│   │   ├── inference.py            # InferenceAgent (updated: no EventBus)
│   │   └── validator.py            # ValidatorAgent (updated: no EventBus)
│   └── cli.py                      # CLI (unchanged)
├── run_node.py                     # Unified P2P node entry point
├── main.py                         # Dev mode (in-process P2P nodes)
└── tests/
    ├── test_p2p.py                 # P2P unit tests (61 tests)
    ├── test_prompts.py             # Prompt tests (13 tests)
    ├── test_store.py               # Store tests (10 tests)
    ├── test_llm.py                 # LLM tests (5 tests)
    ├── test_interfaces.py          # Interface tests (4 tests)
    └── test_integration.py         # E2E scenario (1 test)
```

#### Removed from v0.2

- `src/api.py` → replaced by per-node `TransportServer`
- `src/api_client.py` → replaced by `P2PMemoryClient`
- `src/events.py` → replaced by P2P event broadcasting
- `src/agent_state.py` → replaced by `LocalAgentState`
- `src/agent_registry.py` → replaced by `RoutingTable` + gossip
- `src/websocket_manager.py` → replaced by per-node WS
- `run_inference_agent.py`, `run_validator_agent.py`, `run_cli.py` → unified `run_node.py`
- Redis dependency → eliminated

### 14.6 Running Modes

#### Dev Mode (single process)

```bash
make dev    # or: docker compose up neo4j -d && python main.py
```

Spawns 4 PeerNodes in-process on localhost (ports 9000-9003).

#### Distributed Mode (multi-node)

```bash
make docker-up    # or: docker compose up --build -d

# Or manually:
python run_node.py --capabilities store,llm --port 9000
python run_node.py --capabilities inference --port 9001 --bootstrap http://localhost:9000
python run_node.py --capabilities validation --port 9002 --bootstrap http://localhost:9000
python run_node.py --capabilities cli --port 9003 --bootstrap http://localhost:9000
```

#### Scaled Mode

```bash
make docker-scale-inference N=3
```

### 14.7 P2P Data Flow

```
1. CLI Node sends "request" envelope (method=observe) to a store+llm peer
2. Store+LLM Node executes MemoryService.observe(), writes to Neo4j
3. Store+LLM Node broadcasts "event" (type=observe) to all neighbors
4. Event floods through network (TTL=3, msg_id dedup)
5. Inference Node receives event, wakes up, calls process()
6. Inference Node sends "request" (method=get_recent_observations) to store peer
7. Inference Node sends "request" (method=infer) to llm peer
8. Inference Node sends "request" (method=claim) to store+llm peer
9. Store+LLM Node broadcasts "event" (type=claim)
10. Validator Node receives claim event, checks for contradictions
```

### 14.8 Implementation Status (v0.3)

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Core types + messages + routing | Done | `src/p2p/types.py`, `messages.py`, `routing.py` |
| 2. Transport layer | Done | `src/p2p/transport.py` (FastAPI + httpx + websockets) |
| 3. Gossip protocol | Done | `src/p2p/gossip.py` (push-based, fanout=3, interval=5s) |
| 4. PeerNode runtime | Done | `src/p2p/node.py` (lifecycle, dispatch, neighbors) |
| 5. P2PMemoryClient | Done | `src/p2p/memory_client.py` (satisfies MemoryAPI) |
| 6. Agent updates | Done | Removed EventBus/Redis deps, event-driven via P2P |
| 7. Entry points | Done | `run_node.py`, updated `main.py` |
| 8. Unit tests | Done | 54 tests in `tests/test_p2p.py` |
| 9. Makefile + Docker | Done | Deployment targets, test overlay |

### 14.9 Open Items

- [ ] Multi-node integration test (start real nodes, verify full flow)
- [x] ~~Reconnect UI dashboard to P2P topology~~ (done: UI bridge + nginx proxy)
- [ ] NAT traversal for cross-internet deployment
- [ ] TLS on all connections (HTTPS + WSS)
- [ ] Node authentication and capability attestation
- [ ] Persistent routing table (survive restarts)
- [ ] Bandwidth-aware routing (prefer faster peers)
- [ ] Consistent hashing for deterministic observation→agent routing

### 14.10 UI Bridge (`src/p2p/ui_bridge.py`)

The React UI expects `/v1/` REST/WebSocket endpoints. Rather than modifying the frontend, a bridge layer mounted on the store node translates P2P state into the format the UI expects.

**Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/ws` | WebSocket | Sends `snapshot` on connect, polls routing table for changes, forwards P2P memory events |
| `/v1/graph/nodes` | GET | Queries Neo4j for knowledge graph nodes and edges |
| `/v1/stats` | GET | Network stats, knowledge counts, per-node-type breakdown |

**Translation:** `PeerState` → `AgentStatus` format. Primary capability chosen via priority list (`cli > inference > validation > store > llm`). Status mapped: `alive→running`, `suspect→stale`, `dead→dead`.

**Event forwarding:** The bridge registers as an event listener on the local PeerNode. When `_broadcast_event()` fires (after observe/claim), local listeners are notified first, then the event is broadcast to network neighbors.

### 14.11 Cross-Network URL Remapping

When a CLI on the host connects to Docker containers, the container's advertised URL (e.g. `http://store-node:9000`) is unreachable from the host. The bootstrap URL remapping system handles this:

1. During `_join_peer()`, if the bootstrap peer's advertised URL differs from the actual bootstrap URL, the override is saved in `_url_overrides`
2. `apply_url_overrides()` uses `dataclasses.replace()` to create new `PeerInfo` instances (since `PeerInfo` is frozen)
3. Gossip handler re-applies overrides after merging peer state, ensuring they persist

### 14.12 Auto-Reconnect

When all peers die (e.g. Docker containers restart), the health check loop detects an empty routing table and re-bootstraps from the original seed URLs. This prevents permanent disconnection after transient failures.