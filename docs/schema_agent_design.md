# Schema Agent Design

A dynamic schema layer that evolves alongside the knowledge graph and shapes how all agents operate.

---

## 1. Core Idea: Learn to Learn

The schema is how the system **learns to learn**. As observations flow in, the system doesn't just accumulate domain knowledge — it develops meta-knowledge about *how to process* that knowledge. The schema evolves alongside the graph, shaping how all agents operate.

Instead of a static configuration that developers write, the schema is a **living layer**. A schema agent observes patterns in the graph and produces schema knowledge that dynamically shapes how other agents (inference, validator, future agents) operate.

The schema is not just "facts about predicates stored in the graph." It's an **operational framework** — schema knowledge gets injected into agent behavior at runtime, changing their prompts, decision logic, and constraints. The system should eventually converge on a schema that makes sense given the observations it has processed so far.

---

## 2. What the Schema Layer Knows

| Schema knowledge | Example | How it affects agents |
|---|---|---|
| **Predicate cardinality** | `has name` is single-valued; `has hobby` is multi-valued | Validator only flags contradictions for single-valued predicates |
| **Predicate temporality** | `lives in` is time-dependent; `was born in` is permanent | Validator considers timestamps; inference agent adds temporal qualifiers |
| **Mutual exclusivity groups** | `{is male, is female, is non-binary}` — at most one | Validator flags any pair from the group as contradictory |
| **Domain/range constraints** | `has name` links entities to values, not categories | Inference agent avoids malformed triples |
| **Predicate synonymy** | `has name` ≈ `is called` ≈ `is named` | Agents normalize predicates before creating statements |
| **Confidence priors** | Self-reported identity claims default to 0.95 | Inference agent adjusts confidence based on claim type |

---

## 3. Phase 0: Bootstrap Schema (Implemented)

Before building the dynamic schema agent, a **static bootstrap schema** provides immediate value:

**Location**: `src/schema/bootstrap.yaml`
**Loader**: `src/schema/loader.py` → `PredicateSchema` class

The bootstrap schema defines predicate properties in a YAML file:

```yaml
predicates:
  has_name:
    cardinality: single
    temporality: permanent
    aliases: [is_called, is_named]
  has_hobby:
    cardinality: multi
    temporality: unknown
    aliases: [enjoys, likes_doing]

exclusivity_groups:
  gender:
    predicates: [is_male, is_female, is_non_binary]
```

**`PredicateSchema` provides:**
- `normalize_predicate(pred)` — resolve aliases to canonical names
- `is_multi_valued(pred)` / `is_single_valued(pred)` — cardinality checks
- `get_exclusivity_group(pred)` — mutual exclusivity lookup
- `get_info(pred)` — full predicate metadata

**Current consumers:**
- **ValidatorAgent** — receives schema via constructor injection, checks cardinality before flagging contradictions, checks exclusivity groups for cross-predicate violations

**Design intent:** The bootstrap schema becomes the seed data for the schema agent. When the schema agent is implemented, it will start from these defaults and evolve them based on observed graph patterns. The `PredicateSchema` interface remains the same — only the data source changes (from static YAML to dynamic graph queries).

---

## 4. How Schema Flows into Agents

The schema isn't a database that agents query on every tick. It's a **template/framework layer** that gets compiled into agent behavior:

```
Schema Source (bootstrap YAML → future: store-node persistent file)
       │
       ▼
┌─────────────────────┐
│   Schema Loader      │  Reads schema from YAML (Phase 0)
│   (future: Compiler) │  or from store-node file (Phase 2+)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  PredicateSchema     │  Injected into agents via
│  (runtime lookups)   │  constructor, used in decision logic
└──────────┬──────────┘
           │
     ┌─────┼─────────┐
     ▼     ▼         ▼
 Inference Validator  Future
  Agent    Agent     Agents
                       ▲
                       │
              schema_updated event
              (P2P broadcast on change)
```

Concretely, this could mean:

- **Prompt injection**: The schema compiler renders current schema knowledge into the system prompt for each agent. E.g., the validator's prompt includes "The following predicates are multi-valued and should NOT be flagged as contradictions: has hobby, speaks language, ..."
- **Decision guards**: Before the validator flags a contradiction, it checks a schema-derived lookup. Before the inference agent creates a statement, it normalizes the predicate against known synonyms.
- **Confidence adjustment**: The inference agent reads confidence priors from the schema to calibrate its outputs.

---

## 5. Schema Agent Behavior

The schema agent is fundamentally different from other agents. It doesn't process individual observations or statements — it observes **patterns** across the graph and uses **LLM reasoning** to understand what those patterns mean.

### 5.1 LLM-Powered Reasoning (Not Statistical Counting)

The schema agent uses an LLM because schema decisions require understanding, not thresholds. Raw pattern counts are **input context** — the LLM makes the **decision**.

Examples of why this matters:

| Pattern observed | Statistical approach | LLM reasoning |
|---|---|---|
| `lives_in: "NYC"` and `lives_in: "USA"` for same person | "Two values → multi-valued" (wrong) | "NYC is within USA — different granularity, not a conflict. Still single-valued." |
| New predicate `mentors` appears | "Unknown → use defaults" | "Mentoring is a one-to-many relationship. Likely multi-valued." |
| `is_called` and `has_name` used for same subjects | "Co-occurrence → maybe alias" | "These mean the same thing semantically. Alias." |
| `born_in` never changes across observations | "No changes → maybe permanent" | "Birth is a one-time event. Permanent." |

The LLM brings world knowledge and semantic understanding that no counting heuristic can match. This is the core reason the schema agent exists as an LLM-powered agent rather than a rule-based system.

### 5.2 Node Architecture

The schema agent runs on its **own dedicated node** with `schema` capability, following the same pattern as inference and validator agents:

```
Schema Agent Node (capability: schema)
    │
    ├─→ Reads statement patterns via P2PMemoryClient (routes to store)
    ├─→ Reasons about patterns via LLM (routes to llm peer)
    ├─→ Sends schema updates to store node (new protocol method)
    │
    └─→ Store node persists + broadcasts schema_updated event
```

Required peer capabilities: `store` (to read patterns), `llm` (to reason about them).

### 5.3 What the Schema Agent Observes

The agent periodically gathers context from the graph and presents it to the LLM:

- **Predicate usage patterns**: For each predicate, how many subjects use it, how many have multiple objects, what the objects look like
- **Contradiction history**: Which predicates have been flagged, which were resolved via supersession vs. left standing
- **Predicate co-occurrence**: Which predicates tend to appear together, suggesting possible aliases or groupings
- **New/unknown predicates**: Predicates that appear in statements but aren't yet in the schema

### 5.4 What the Schema Agent Decides

The LLM reasons about the gathered context and can:

- **Classify a new predicate**: cardinality, temporality, and initial confidence
- **Revise an existing predicate**: change cardinality or temporality based on accumulated evidence
- **Propose aliases**: merge predicates that mean the same thing
- **Propose exclusivity groups**: identify mutually exclusive predicates
- **Explain its reasoning**: each schema update includes the LLM's rationale (stored as provenance)

### 5.5 Convergence Through Evidence

Each schema property carries an **evidence summary** — not raw counts, but LLM-generated reasoning about why the current value is correct. When the schema agent revisits a predicate, it sees:

1. The current schema entry and its reasoning
2. New evidence since the last review
3. Any contradictions or anomalies related to this predicate

The LLM then decides whether the new evidence warrants a change. Because it can read its own prior reasoning, it avoids oscillation — it won't flip a value back and forth without a compelling reason the prior reasoning missed.

Bootstrap schema entries carry `origin: bootstrap` and the LLM treats them as strong priors that require substantial evidence to override.

### 5.6 Output

- Schema updates sent to store node via new `update_schema()` protocol method
- Store node persists to file (outside Neo4j) and broadcasts `schema_updated` P2P event
- Each update includes: what changed, the LLM's reasoning, and the evidence it considered

---

## 6. Effect on Existing Agents

| Agent | Current behavior | With schema layer |
|---|---|---|
| **Inference** | Extracts triples from observations using LLM prompts | Schema constraints injected into prompts: predicate normalization, confidence priors, domain/range hints |
| **Validator** | Checks bootstrap schema cardinality + exclusivity groups | Dynamic schema replaces bootstrap; reports unknown predicates to schema agent |
| **Schema** | (new) | Own node with `schema` capability. Uses LLM to reason about predicate patterns, evolves schema, sends updates to store node. |
| **Future agents** | — | All receive schema-derived constraints via the same framework |

---

## 7. Design Decisions

These questions from the original design have been resolved:

### 7.1 Where does dynamic schema live?

**Decision**: On the store node, but **not inside the Neo4j graph**.

The graph holds domain knowledge (what the system knows about the world). Schema is meta-knowledge — knowledge about *how to interpret and validate* domain knowledge. Mixing them in the same graph would blur that boundary and create circular dependencies (schema shapes how statements are validated, so schema can't itself be a statement subject to the same validation).

The store node owns the schema as a separate persistent artifact (file-based or embedded store). Other nodes receive compiled schema via P2P events.

### 7.2 Authority and human intervention

**Decision**: The system is designed to run **autonomously and converge** toward a schema that makes sense given the observations so far. There is no human-in-the-loop for schema decisions during normal operation.

Human intervention (inspection, override, correction) is a separate concern that can be layered on later — e.g., an admin API or dashboard for reviewing schema state. But the core design goal is a system that learns and self-corrects without human input.

### 7.3 Compilation and propagation

**Decision**: **Hot-reload via P2P event signaling**.

When the schema agent updates the schema, the store node persists the change and broadcasts a `schema_updated` event through the P2P network. All connected nodes (inference, validator, future agents) receive the event and reload their schema constraints. This uses the existing event flooding mechanism (TTL-based hop limit + msg_id dedup).

### 7.4 Schema scope

**Open**. Global per-predicate is the starting point (matching the bootstrap schema). Per-subject-type scoping (e.g., a person's "has_name" is single-valued but an organization's might not be) is a potential evolution but adds significant complexity.

## 8. Open Questions

- **Schema scope refinement**: When/if to introduce per-subject-type predicate rules
- **Convergence guarantees**: The LLM sees its own prior reasoning when revisiting predicates, which naturally resists oscillation. But pathological cases (genuinely ambiguous predicates) may still flip. Should there be a stability rule (e.g., don't re-evaluate a predicate within N claims of the last change)?
- **Schema versioning**: How to handle in-flight statements when schema changes (do existing statements get re-validated?)
- **Coreference**: Entity resolution ("my girlfriend" = "Ami") is a related but separate problem — see [Knowledge Representation](knowledge_representation.md). Should the schema agent have any role in coreference, or is that a distinct agent?

---

## 9. Implementation Phases

| Phase | Scope | Status |
|---|---|---|
| 0. Bootstrap schema | Static YAML schema with predicate cardinality, temporality, exclusivity groups. Loaded at startup, injected into validator. | **Done** |
| 1. Schema data model | Schema stored on store node (not Neo4j). Persistent file format, `schema_updated` P2P event, hot-reload on all nodes. | **Design phase** |
| 2. Schema agent (basic) | Own node with `schema` capability. LLM-powered reasoning about predicate patterns — cardinality, temporality, aliases. Needs `store` + `llm` peers. | Not started |
| 3. Schema compiler | Render schema into agent constraints (prompt injection, decision guards). Triggered by `schema_updated` events. | Not started |
| 4. Schema-aware inference | Inference agent normalizes predicates, uses confidence priors from schema. | Not started |
| 5. Schema-aware validation (dynamic) | Validator reads dynamic schema instead of bootstrap; reports unknown predicates to schema agent. | Not started |

---

## See Also

- [Schema Framework Spec](schema_framework_spec.md) — Phase 1 implementation specification (data model, protocol, propagation, hot-reload)
- [Knowledge Representation](knowledge_representation.md) — Current data model (includes coreference as a tracked concern)
- [Validation Redesign](validation_redesign.md) — Contradiction detection and lifecycle
- [Design Tracking](design_tracking.md) — System architecture

---

*Document version: 0.4*
*Last updated: 2026-02-02*
*Status: Phase 0 (bootstrap schema) implemented. Phase 1 data model and schema framework design in progress.*
