# Schema Agent Design

A dynamic schema layer that evolves alongside the knowledge graph and shapes how all agents operate.

---

## 1. Core Idea

Instead of the schema being a static configuration that developers write, it's a **living layer** that evolves alongside the knowledge graph. A schema agent observes patterns in the graph and produces schema knowledge that dynamically shapes how other agents (inference, validator, future agents) operate.

The schema is not just "facts about predicates stored in the graph." It's an **operational framework** — schema knowledge gets injected into agent behavior at runtime, changing their prompts, decision logic, and constraints.

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

## 3. How Schema Flows into Agents

The schema isn't a database that agents query on every tick. It's a **template/framework layer** that gets compiled into agent behavior:

```
Schema Knowledge (graph)
       │
       ▼
┌─────────────────────┐
│   Schema Compiler    │  Reads schema from graph,
│                      │  produces agent constraints
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Agent Constraints   │  Injected into prompts,
│  (runtime config)    │  decision logic, validation
└──────────┬──────────┘
           │
     ┌─────┼─────────┐
     ▼     ▼         ▼
 Inference Validator  Future
  Agent    Agent     Agents
```

Concretely, this could mean:

- **Prompt injection**: The schema compiler renders current schema knowledge into the system prompt for each agent. E.g., the validator's prompt includes "The following predicates are multi-valued and should NOT be flagged as contradictions: has hobby, speaks language, ..."
- **Decision guards**: Before the validator flags a contradiction, it checks a schema-derived lookup. Before the inference agent creates a statement, it normalizes the predicate against known synonyms.
- **Confidence adjustment**: The inference agent reads confidence priors from the schema to calibrate its outputs.

---

## 4. Schema Agent Behavior

The schema agent is different from other agents. It doesn't process individual observations or statements — it observes **patterns** across the graph:

**Triggers:**
- New predicate appears (never seen before) → initialize with defaults
- Same predicate accumulates multiple objects for same subject without contradictions → infer multi-valued
- Contradiction is flagged but later both values confirmed → revise cardinality assumption
- Multiple predicates appear to mean the same thing → propose synonymy

**Output:**
- Schema claims stored in the graph (using existing Statement machinery, with schema-specific concepts like `predicate:has_name` as subject)
- Or: a dedicated schema store (simpler, avoids polluting the instance graph)

---

## 5. Effect on Existing Agents

| Agent | Current behavior | With schema layer |
|---|---|---|
| **Inference** | Extracts triples from observations using LLM prompts | Schema constraints injected into prompts: predicate normalization, confidence priors, domain/range hints |
| **Validator** | Flags all same-subj/same-pred/diff-obj as contradictions | Checks schema cardinality first; only flags single-valued predicates; reports unknown predicates to schema agent |
| **Schema** | (new) | Observes predicate patterns, evolves schema, compiles constraints for other agents |
| **Future agents** | — | All receive schema-derived constraints via the same framework |

---

## 6. Open Questions

- **Where does schema live?** In the same graph (predicates as Concept nodes with `kind: "predicate"`)? Or a separate lightweight store (JSON/YAML that gets reloaded)?
- **Bootstrap**: Do we seed the schema with common-sense defaults (e.g., "has name" is single-valued), or let it learn from scratch?
- **Authority**: When the schema agent and a human disagree, who wins? Should users be able to pin schema decisions?
- **Compilation frequency**: Does the schema compile into agent constraints once at startup, or does it hot-reload as the schema evolves?
- **Schema scope**: Per-subject-type schemas? (A person's "has name" is single-valued, but an organization's might not be.) Or global per-predicate?

---

## 7. Implementation Phases

| Phase | Scope | Status |
|---|---|---|
| 1. Schema data model | Decide where schema lives, define schema node/property structure | Design phase |
| 2. Schema agent (basic) | Observe predicate patterns, infer cardinality | Not started |
| 3. Schema compiler | Render schema into agent constraints (prompt injection, decision guards) | Not started |
| 4. Schema-aware inference | Inference agent normalizes predicates, uses confidence priors | Not started |
| 5. Schema-aware validation | Validator reads schema before flagging contradictions | Not started |

---

## See Also

- [Knowledge Representation](knowledge_representation.md) — Current data model
- [Validation Redesign](validation_redesign.md) — Contradiction detection and lifecycle (separate concern)
- [Design Tracking](design_tracking.md) — System architecture

---

*Document version: 0.1*
*Last updated: 2026-02-02*
*Status: Design phase. Capturing the vision for a dynamic schema layer that shapes agent behavior.*
