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
Schema Knowledge (YAML → future: graph)
       │
       ▼
┌─────────────────────┐
│   Schema Loader      │  Reads schema from YAML (Phase 0)
│   (future: Compiler) │  or from graph (Phase 2+)
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
```

Concretely, this could mean:

- **Prompt injection**: The schema compiler renders current schema knowledge into the system prompt for each agent. E.g., the validator's prompt includes "The following predicates are multi-valued and should NOT be flagged as contradictions: has hobby, speaks language, ..."
- **Decision guards**: Before the validator flags a contradiction, it checks a schema-derived lookup. Before the inference agent creates a statement, it normalizes the predicate against known synonyms.
- **Confidence adjustment**: The inference agent reads confidence priors from the schema to calibrate its outputs.

---

## 5. Schema Agent Behavior

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

## 6. Effect on Existing Agents

| Agent | Current behavior | With schema layer |
|---|---|---|
| **Inference** | Extracts triples from observations using LLM prompts | Schema constraints injected into prompts: predicate normalization, confidence priors, domain/range hints |
| **Validator** | Checks bootstrap schema cardinality + exclusivity groups | Dynamic schema replaces bootstrap; reports unknown predicates to schema agent |
| **Schema** | (new) | Observes predicate patterns, evolves schema, compiles constraints for other agents |
| **Future agents** | — | All receive schema-derived constraints via the same framework |

---

## 7. Open Questions

- **Where does dynamic schema live?** In the same graph (predicates as Concept nodes with `kind: "predicate"`)? Or a separate lightweight store (JSON/YAML that gets reloaded)?
- **Authority**: When the schema agent and a human disagree, who wins? Should users be able to pin schema decisions?
- **Compilation frequency**: Does the schema compile into agent constraints once at startup, or does it hot-reload as the schema evolves?
- **Schema scope**: Per-subject-type schemas? (A person's "has name" is single-valued, but an organization's might not be.) Or global per-predicate?

---

## 8. Implementation Phases

| Phase | Scope | Status |
|---|---|---|
| 0. Bootstrap schema | Static YAML schema with predicate cardinality, temporality, exclusivity groups. Loaded at startup, injected into validator. | **Done** |
| 1. Schema data model | Decide where dynamic schema lives, define schema node/property structure | Design phase |
| 2. Schema agent (basic) | Observe predicate patterns, infer cardinality | Not started |
| 3. Schema compiler | Render schema into agent constraints (prompt injection, decision guards) | Not started |
| 4. Schema-aware inference | Inference agent normalizes predicates, uses confidence priors | Not started |
| 5. Schema-aware validation (dynamic) | Validator reads dynamic schema instead of bootstrap; reports unknown predicates | Not started |

---

## See Also

- [Knowledge Representation](knowledge_representation.md) — Current data model
- [Validation Redesign](validation_redesign.md) — Contradiction detection and lifecycle
- [Design Tracking](design_tracking.md) — System architecture

---

*Document version: 0.2*
*Last updated: 2026-02-02*
*Status: Phase 0 (bootstrap schema) implemented. Dynamic schema agent design in progress.*
