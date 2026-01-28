# Meta-Language Exploration

Brainstorming document for designing how LLMs communicate with interfaces, each other, and themselves.

**Status**: Exploration / No decisions made yet

---

## The Problem Space

We have multiple communication channels that need structure:

1. **LLM → Interface**: Structured output the system can parse reliably
2. **Interface → LLM**: Prompts that consistently produce desired behavior
3. **LLM → LLM**: Agents communicating through shared memory or direct messages
4. **LLM → Self**: Reasoning, planning, self-critique patterns

---

## Existing Approaches

### 1. Tool Use / Function Calling

**What it is**: LLM providers (Anthropic, OpenAI) support declaring "tools" with JSON schemas. The LLM returns structured JSON matching the schema.

**We already use this**: `src/llm.py` uses Anthropic's tool_use for `extract_observation()` and `parse_claim()`.

```python
tools = [{
    "name": "record_observation",
    "input_schema": {
        "type": "object",
        "properties": {
            "entities": {"type": "array", "items": {"type": "string"}},
            "extractions": {...},
        }
    }
}]
```

**Pros**: Guaranteed valid JSON, native provider support, type-safe
**Cons**: Limited to JSON structure, provider-specific implementations

---

### 2. XML-like Tags

**What it is**: Using XML tags to delimit sections of LLM output.

```
<thinking>
The user mentioned a girlfriend named ami. This implies a romantic relationship.
</thinking>

<claim>
User has a girlfriend named Ami.
</claim>

<confidence>0.95</confidence>
```

**Used by**: Anthropic's own documentation, many prompt engineering guides

**Pros**: Human-readable, flexible nesting, easy to parse with regex
**Cons**: No schema validation, LLM might not close tags properly

---

### 3. Markdown Conventions

**What it is**: Using markdown structure as a protocol.

```markdown
## Observation Analysis

**Entities**: user, ami, girlfriend
**Sentiment**: positive
**Topics**: relationships, personal

## Extracted Facts

1. User has a girlfriend
2. Girlfriend's name is Ami
```

**Pros**: Very human-readable, LLMs are good at markdown
**Cons**: Harder to parse reliably, ambiguous structure

---

### 4. YAML-based Structured Output

**What it is**: Asking the LLM to output YAML.

```yaml
observation:
  entities:
    - user
    - ami
  extractions:
    - subject: user
      predicate: has girlfriend named
      object: ami
  confidence: 0.9
```

**Pros**: More readable than JSON, supports comments, good for config-like data
**Cons**: Indentation-sensitive (LLMs sometimes mess this up), needs parsing

---

### 5. Domain-Specific Languages (DSLs)

**What it is**: Custom mini-languages for specific purposes.

```
OBSERVE "my girlfriend name is ami"
  -> ENTITY(user)
  -> ENTITY(ami, type=person)
  -> TRIPLE(user, girlfriend_name, ami)
  -> CONFIDENCE(0.9)
```

**Pros**: Highly expressive for domain, can enforce constraints
**Cons**: LLMs need examples to learn it, parsing complexity

---

### 6. ReAct Pattern (Reasoning + Acting)

**What it is**: Alternating between thought and action.

```
Thought: The user mentioned their girlfriend's name. I should extract this as a relationship fact.
Action: extract_triple(subject="user", predicate="has_girlfriend", object="ami")
Observation: Triple stored with id=abc123
Thought: I should also note that "ami" is a person entity.
Action: create_entity(name="ami", type="person")
```

**Used by**: LangChain, many agent frameworks

**Pros**: Transparent reasoning, debuggable, works well for multi-step tasks
**Cons**: Verbose, token-heavy, needs careful parsing

---

### 7. Semantic Web Standards (JSON-LD, RDF)

**What it is**: Using established semantic web formats.

```json
{
  "@context": "https://schema.org/",
  "@type": "Person",
  "name": "ami",
  "relationshipTo": {
    "@type": "Person",
    "name": "user"
  }
}
```

**Pros**: Industry standard, rich ecosystem, interoperable
**Cons**: Verbose, LLMs don't naturally produce it, overkill for our use case?

---

### 8. Constrained Generation Libraries

**What it is**: Libraries that force LLM output to match a grammar/schema.

- **Outlines**: Python library for structured generation
- **Guidance**: Microsoft's library with template syntax
- **Instructor**: Pydantic-based structured outputs
- **LMQL**: Query language for LLMs

```python
# Instructor example
class Observation(BaseModel):
    entities: list[str]
    triples: list[Triple]
    confidence: float

result = client.chat.completions.create(
    response_model=Observation,
    messages=[...]
)
```

**Pros**: Type-safe, validated output, works with any LLM
**Cons**: Additional dependency, may constrain LLM creativity

---

### 9. Multi-Agent Communication Protocols

**What it is**: Standardized message formats between agents.

**AutoGen style**:
```python
{
    "sender": "inference_agent",
    "receiver": "validator_agent",
    "content": "New claim created: user has girlfriend ami",
    "metadata": {"claim_id": "abc123"}
}
```

**CrewAI style**: Task handoffs with context
**FIPA ACL**: Formal agent communication language (academic)

**Pros**: Clear contracts, enables complex multi-agent workflows
**Cons**: Overhead for simple cases

---

### 10. Self-Communication Patterns

**What it is**: How an LLM structures its own reasoning.

**Chain-of-Thought (CoT)**:
```
Let me think step by step:
1. The observation mentions "girlfriend" - this is a relationship
2. The name "ami" is provided - this is an entity
3. Therefore: user has a girlfriend named ami
```

**Constitutional AI / Self-Critique**:
```
Draft response: User's girlfriend is ami.
Critique: Should I capitalize the name?
Revised: User's girlfriend is Ami.
```

**Inner Monologue**:
```
[INTERNAL] I'm uncertain about the confidence level here.
[INTERNAL] The statement seems direct, not hedged.
[OUTPUT] Confidence: 0.9
```

---

## Questions to Consider

1. **Consistency vs Flexibility**: Strict schemas are reliable but may limit the LLM's ability to express nuance. How much structure do we need?

2. **Token Efficiency**: Verbose formats (ReAct, XML) cost more tokens. Does it matter for our use case?

3. **Debuggability**: Can we understand why the LLM produced what it did? Should reasoning be visible?

4. **Error Handling**: What happens when the LLM produces malformed output? Retry? Fallback?

5. **Evolution**: How do we version the protocol as the system grows?

6. **Inter-agent Trust**: When one agent produces a claim, should other agents trust it or verify it?

7. **Human-in-the-loop**: Should the meta-language be human-readable/editable?

---

## Current State in Our System

| Channel | Current Approach | Notes |
|---------|------------------|-------|
| LLM → Interface (extraction) | Tool Use (JSON) | `src/llm.py` - works well |
| LLM → Interface (inference) | Free text + "SKIP" keyword | `src/interfaces.py` - functional |
| Interface → LLM | **YAML templates + Jinja2 + Pydantic** | `prompts/` directory - **IMPLEMENTED** |
| Agent → Agent | Indirect via shared Neo4j | No direct communication |
| LLM → Self | Optional reasoning traces | `include_reasoning` variable in inference prompt |

---

## Brainstorm: What Could a Unified Meta-Language Look Like?

Option A: **Stick with tool_use everywhere**
- Every LLM call uses tool_use with explicit schemas
- Consistent, reliable, already working

Option B: **XML tags with conventions**
- `<thinking>` for reasoning (optional, can be stripped)
- `<output>` for structured response
- `<confidence>` as standard field
- Human-readable, debuggable

Option C: **Hybrid approach**
- Tool use for structured extraction
- XML/markdown for reasoning traces
- Standard message envelope for agent-to-agent

Option D: **Custom DSL**
- Define our own grammar for memory operations
- `OBSERVE`, `CLAIM`, `INFER`, `CONTRADICT`, `RESOLVE`
- More semantic, but learning curve

---

## Implemented: YAML + Jinja2 + Pydantic

We implemented **Option C (Hybrid approach)** with:

### Structure

```
prompts/
├── shared/
│   └── base.yaml              # Shared constraints, inherited by others
├── llm_translator/
│   ├── observation.yaml       # Extract entities/triples from observations
│   ├── claim.yaml             # Parse claims with context
│   ├── query_generation.yaml  # Natural language → Cypher
│   └── synthesis.yaml         # Graph results → natural language
├── inference_agent/
│   └── infer.yaml             # Generate claims from observations
└── validator_agent/
    └── contradiction.yaml     # Detect contradictions (future use)
```

### Features

1. **YAML format** — human-readable, good multiline support
2. **Jinja2 rendering** — conditionals (`{% if %}`) and loops (`{% for %}`)
3. **Pydantic validation** — type-checked variables with IDE support
4. **Inheritance** — `extends: shared/base` injects shared constraints
5. **Version tracking** — each prompt has `version` metadata

### Usage

```python
from src.prompts import PromptLoader, InferenceVars

loader = PromptLoader()
prompt = loader.load("inference_agent/infer")

vars = InferenceVars(
    observation_text="my girlfriend is ami",
    include_reasoning=True  # Enables chain-of-thought
)
rendered = prompt.render(vars)

# rendered["system"] → system prompt string
# rendered["user"] → user prompt string
```

### Code References

- **Loader**: `src/prompts.py` — `PromptLoader`, `PromptTemplate`, Pydantic models
- **Usage in LLM**: `src/llm.py` — `LLMTranslator` loads prompts dynamically
- **Usage in Memory**: `src/interfaces.py` — `MemoryService.infer()` uses inference prompt

---

## Next Steps

- [x] ~~Audit all current prompts in the codebase~~
- [x] ~~Implement YAML template system~~
- [x] ~~Add Jinja2 for conditionals~~
- [x] ~~Add Pydantic for validation~~
- [ ] Add prompt versioning tests (ensure changes are intentional)
- [ ] Add prompt documentation generator (from YAML metadata)
- [ ] Consider agent-to-agent message formats (when needed)
- [ ] Explore DSL for memory operations (if free-text becomes too fragile)

---

*Document version: 0.2*
*Status: Prompt template system implemented*
*Last updated: 2026-01-27*
