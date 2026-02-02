# Schema Evolution Framework — Phase 1 Spec

Implementation specification for the schema infrastructure layer: persistent schema on the store node, protocol additions, P2P propagation, and hot-reload on consumer agents.

Phase 1 builds the **plumbing** — the schema agent that uses this infrastructure is Phase 2.

---

## 1. Scope

Phase 1 delivers:

1. A persistent schema file on the store node (outside Neo4j)
2. A `SchemaStore` class that loads, updates, persists, and versions the schema
3. Two new `MemoryAPI` methods: `get_schema()` and `update_schema()`
4. A `schema_updated` P2P event for network-wide propagation
5. Hot-reload on the validator agent (and any future schema consumers)
6. A new `Capability.SCHEMA` for the future schema agent node
7. Routing table entries for the new methods

Phase 1 does **not** deliver the schema agent itself, schema-aware inference prompts, or the schema compiler. Those are Phases 2–4.

---

## 2. Schema File Format

The persistent schema is a YAML file on the store node. It extends the bootstrap format with per-entry provenance and versioning.

**Location on store node**: `data/schema.yaml` (configurable via `SCHEMA_PATH` env var, default `data/schema.yaml`)

**On first startup**: If no `data/schema.yaml` exists, the store node copies `src/schema/bootstrap.yaml` as the seed, adding the version and provenance fields. Subsequent startups load from `data/schema.yaml`.

### 2.1 Format

```yaml
schema_version: 1                     # monotonically increasing integer
updated_at: "2026-02-02T12:00:00Z"    # ISO 8601 timestamp of last change
updated_by: "bootstrap"               # source of last change

defaults:
  cardinality: single
  temporality: unknown

predicates:
  has_name:
    cardinality: single
    temporality: permanent
    aliases: [is_called, is_named, named]
    origin: bootstrap                  # "bootstrap" or "learned"
    reasoning: null                    # LLM rationale (null for bootstrap)
    last_reviewed: null                # ISO 8601 or null

  # Example of a learned predicate (would be added by schema agent in Phase 2)
  # mentors:
  #   cardinality: multi
  #   temporality: unknown
  #   aliases: []
  #   origin: learned
  #   reasoning: >
  #     Observed 3 subjects each mentoring multiple people.
  #     Mentoring is inherently a one-to-many relationship.
  #   last_reviewed: "2026-02-02T14:30:00Z"

exclusivity_groups:
  gender:
    predicates: [is_male, is_female, is_non_binary]
    description: "At most one gender identity active"
    origin: bootstrap
    reasoning: null
```

### 2.2 Compatibility

The new fields (`origin`, `reasoning`, `last_reviewed`, `schema_version`, `updated_at`, `updated_by`) are all **additive**. The existing `PredicateSchema` loader ignores unknown fields, so the bootstrap schema continues to work unchanged. The new `SchemaStore` understands both formats — if it loads a file without provenance fields, it treats all entries as `origin: bootstrap`.

### 2.3 Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | int | Yes | Monotonically increasing. Incremented on every `update_schema()` call. |
| `updated_at` | str (ISO 8601) | Yes | Timestamp of last schema change. |
| `updated_by` | str | Yes | Source identifier: `"bootstrap"`, `"schema_agent"`, or a specific agent/admin ID. |
| `defaults` | object | Yes | Default cardinality and temporality for unknown predicates. |
| `predicates.<name>.origin` | str | No | `"bootstrap"` or `"learned"`. Defaults to `"bootstrap"` if absent. |
| `predicates.<name>.reasoning` | str \| null | No | LLM-generated rationale for current property values. |
| `predicates.<name>.last_reviewed` | str \| null | No | When the schema agent last evaluated this predicate. |
| `exclusivity_groups.<name>.origin` | str | No | Same as predicate origin. |
| `exclusivity_groups.<name>.reasoning` | str \| null | No | Same as predicate reasoning. |

---

## 3. SchemaStore

A new class responsible for loading, persisting, updating, and versioning the schema. Lives on the store node alongside `TripleStore` (but is not part of it).

### 3.1 Location

`src/schema/store.py`

### 3.2 Interface

```python
class SchemaStore:
    """Persistent schema manager for the store node.

    Loads schema from a YAML file, supports atomic updates with versioning,
    and provides the current PredicateSchema for consumer lookups.
    """

    def __init__(self, path: Path, bootstrap_path: Path | None = None) -> None:
        """Initialize with schema file path and optional bootstrap seed path."""
        ...

    async def load(self) -> None:
        """Load schema from file. If file doesn't exist, seed from bootstrap."""
        ...

    @property
    def schema(self) -> PredicateSchema:
        """Current PredicateSchema instance for runtime lookups."""
        ...

    @property
    def version(self) -> int:
        """Current schema version number."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Serialize full schema state to a dict (for get_schema responses and events)."""
        ...

    def update(self, changes: dict[str, Any], source: str) -> dict[str, Any]:
        """Apply incremental changes, increment version, persist to file.

        Args:
            changes: Partial schema dict. Can contain:
                - "predicates": {name: {cardinality, temporality, aliases, reasoning}}
                - "exclusivity_groups": {name: {predicates, description, reasoning}}
                - "defaults": {cardinality, temporality}
            source: Who made the change (e.g. "schema_agent", "admin").

        Returns:
            Full schema dict after update (same format as to_dict).
        """
        ...

    def _persist(self) -> None:
        """Write current schema state to YAML file."""
        ...
```

### 3.3 Atomic Updates

`update()` is synchronous at the Python level (no concurrent coroutines can interleave within a single `update()` call in asyncio's cooperative model). The method:

1. Merges `changes` into the current schema state
2. Increments `schema_version`
3. Updates `updated_at` and `updated_by`
4. Rebuilds the internal `PredicateSchema` instance (new alias map, new predicate dict)
5. Persists to file
6. Returns the full schema dict

The returned dict is used directly as the `schema_updated` event payload — no separate serialization step.

### 3.4 Merge Semantics

- **Predicates**: Each predicate in `changes["predicates"]` is merged field-by-field into the existing entry. If the predicate doesn't exist, it's created. Fields not present in the change are preserved from the existing entry.
- **Exclusivity groups**: Each group in `changes["exclusivity_groups"]` replaces the existing group with the same name entirely (groups are small and atomic).
- **Defaults**: Replaced entirely if present in changes.
- **Deletions**: Not supported in Phase 1. Predicates and groups can be added or modified, not removed.

### 3.5 Bootstrap Seeding

On first load (schema file doesn't exist):

1. Read `src/schema/bootstrap.yaml`
2. Add `schema_version: 0`, `updated_at: <now>`, `updated_by: "bootstrap"`
3. Add `origin: "bootstrap"` and `reasoning: null` to all predicates and groups
4. Write to `data/schema.yaml`

This happens once. After seeding, the bootstrap file is never read again — the dynamic schema file is the sole source of truth.

---

## 4. Protocol Additions

### 4.1 MemoryAPI

Two new methods added to the `MemoryAPI` protocol:

```python
@runtime_checkable
class MemoryAPI(Protocol):
    # ... existing methods ...

    # Schema operations
    async def get_schema(self) -> dict[str, Any]: ...
    async def update_schema(
        self, changes: dict[str, Any], source: str
    ) -> dict[str, Any]: ...
```

**`get_schema()`** — Returns the full schema as a serializable dict (same format as `SchemaStore.to_dict()`). Routed to the store node.

**`update_schema(changes, source)`** — Applies incremental changes to the schema. Returns the full updated schema dict. Routed to the store node. After successful update, the store node broadcasts a `schema_updated` event.

### 4.2 MemoryService Implementation

```python
class MemoryService:
    def __init__(
        self, store: TripleStore, llm: LLMTranslator,
        schema_store: SchemaStore | None = None,
    ) -> None:
        self.store = store
        self.llm = llm
        self.schema_store = schema_store

    async def get_schema(self) -> dict[str, Any]:
        if self.schema_store is None:
            return {}
        return self.schema_store.to_dict()

    async def update_schema(
        self, changes: dict[str, Any], source: str
    ) -> dict[str, Any]:
        if self.schema_store is None:
            raise RuntimeError("No SchemaStore configured on this node")
        return self.schema_store.update(changes, source)
```

### 4.3 P2PMemoryClient

Two new methods matching the protocol:

```python
class P2PMemoryClient:
    async def get_schema(self) -> dict[str, Any]:
        return await self._call("get_schema", {})

    async def update_schema(
        self, changes: dict[str, Any], source: str
    ) -> dict[str, Any]:
        return await self._call(
            "update_schema", {"changes": changes, "source": source}
        )
```

### 4.4 Routing Table

```python
METHOD_CAPABILITIES: dict[str, set[Capability]] = {
    # ... existing entries ...
    "get_schema": {Capability.STORE},
    "update_schema": {Capability.STORE},
}
```

Both methods route to the store node because the schema file lives there.

---

## 5. P2P Event: `schema_updated`

### 5.1 When It Fires

After a successful `update_schema()` call on the store node. The event is broadcast from `PeerNode._handle_request()` (same pattern as `observe`/`claim`/`flag_contradiction` events).

```python
# In PeerNode._handle_request():
if method == "update_schema":
    await self._broadcast_event("schema_updated", {
        "schema": result,           # full schema dict
        "version": result["schema_version"],
    })
```

### 5.2 Event Envelope

```python
Envelope(
    msg_type="event",
    sender_id=self.node_id,
    ttl=5,  # higher TTL than domain events (default 3)
            # to ensure schema reaches all nodes in larger networks
    payload={
        "event_type": "schema_updated",
        "data": {
            "schema": { ... },      # full serialized schema
            "version": 14,          # schema_version for quick checks
        },
    },
)
```

The full schema is included in the payload because:
- Schema is small (a few KB at most, even with many predicates)
- Eliminates a fetch round-trip on every receiving node
- Nodes that miss the event can still call `get_schema()` on startup

### 5.3 TTL

Schema events use TTL 5 (vs. default 3 for domain events). Schema changes are infrequent but important — ensuring propagation to all nodes is worth the extra hops. In practice, most deployments have fewer than 5 hops, so this is a safety margin.

---

## 6. Hot-Reload on Consumer Agents

### 6.1 ValidatorAgent

The validator already holds `self._schema: PredicateSchema | None`. Hot-reload adds:

```python
class ValidatorAgent(WorkerAgent):
    def event_types(self) -> list[str]:
        return ["claim", "schema_updated"]

    async def on_network_event(
        self, event_type: str, data: dict[str, Any]
    ) -> None:
        if event_type == "schema_updated":
            schema_dict = data.get("schema")
            if schema_dict:
                self._schema = PredicateSchema.from_dict(schema_dict)
                logger.info(
                    "Schema hot-reloaded to version %s",
                    data.get("version"),
                )
        # Wake agent for any subscribed event
        if event_type in self.event_types():
            self._event_received.set()
```

**Safety**: In Python's asyncio, `self._schema = new_schema` is a single reference assignment. The validator's `process()` method reads `self._schema` at the start of each tick. If a schema update arrives mid-tick, the current tick completes with the old schema, and the next tick uses the new one. No lock needed.

### 6.2 Startup Schema Fetch

Currently, agents receive schema via constructor injection (`schema=load_bootstrap_schema()`). With Phase 1, agents should fetch the current schema from the store node on startup:

```python
# In run_node.py, after node.start() and P2PMemoryClient creation:
if Capability.VALIDATION in capabilities:
    try:
        schema_dict = await memory.get_schema()
        schema = PredicateSchema.from_dict(schema_dict)
    except Exception:
        # Store node may not be ready yet; fall back to bootstrap
        schema = load_bootstrap_schema()
    agent = ValidatorAgent(
        memory=memory, poll_interval=args.poll_interval,
        state=state, schema=schema,
    )
```

This ensures the validator starts with the latest dynamic schema, not just the static bootstrap. The bootstrap remains as a fallback if the store node is unreachable during startup.

### 6.3 Future Agents

Any agent that needs schema access follows the same pattern:
1. Fetch via `get_schema()` on startup
2. Listen for `schema_updated` events during operation
3. Swap internal `PredicateSchema` reference on update

---

## 7. PredicateSchema Additions

The existing `PredicateSchema` class needs serialization support and enriched data classes.

### 7.1 Enhanced Data Classes

```python
@dataclass(frozen=True)
class PredicateInfo:
    name: str
    cardinality: str              # "single" or "multi"
    temporality: str              # "permanent", "temporal", or "unknown"
    aliases: tuple[str, ...] = ()
    origin: str = "bootstrap"     # "bootstrap" or "learned"
    reasoning: str | None = None  # LLM rationale
    last_reviewed: str | None = None  # ISO 8601

@dataclass(frozen=True)
class ExclusivityGroup:
    name: str
    predicates: frozenset[str]
    description: str = ""
    origin: str = "bootstrap"
    reasoning: str | None = None
```

### 7.2 Serialization

```python
class PredicateSchema:
    # ... existing methods ...

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict matching the YAML schema format."""
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PredicateSchema:
        """Deserialize from a dict (YAML-loaded or event payload).

        Accepts both bootstrap format (no provenance fields) and
        dynamic format (with origin, reasoning, etc.).
        """
        ...
```

`from_dict()` is the key addition. It replaces the current `load_bootstrap_schema()` path for dynamic schemas while remaining backward-compatible with the bootstrap format (missing provenance fields get defaults).

### 7.3 Backward Compatibility

`load_bootstrap_schema()` continues to work unchanged — it calls `yaml.safe_load()` and constructs `PredicateSchema` directly. The new `from_dict()` handles the same dict structure plus the additional fields. No existing code breaks.

---

## 8. Capability Addition

### 8.1 New Enum Value

```python
class Capability(str, Enum):
    STORE = "store"
    LLM = "llm"
    INFERENCE = "inference"
    VALIDATION = "validation"
    CLI = "cli"
    SCHEMA = "schema"             # new
```

### 8.2 Usage

Phase 1 registers the capability but does not start a schema agent. The capability exists so that:
- The routing table can identify schema agent nodes
- `run_node.py` can be extended in Phase 2 to start the schema agent when `--capabilities schema` is passed
- Other nodes can discover schema agent peers via gossip

---

## 9. Store Node Wiring

### 9.1 MemoryService Construction

`_setup_memory_service()` in `run_node.py` creates and injects the `SchemaStore`:

```python
async def _setup_memory_service(node, capabilities):
    # ... existing store and llm setup ...

    schema_store = None
    if Capability.STORE in capabilities:
        schema_path = Path(
            os.environ.get("SCHEMA_PATH", "data/schema.yaml")
        )
        bootstrap_path = Path(__file__).parent / "src" / "schema" / "bootstrap.yaml"
        schema_store = SchemaStore(schema_path, bootstrap_path)
        await schema_store.load()
        node.register_service("schema_store", schema_store)

    if store and llm:
        memory_service = MemoryService(
            store=store, llm=llm, schema_store=schema_store,
        )
        node.register_service("memory", memory_service)
```

### 9.2 Event Broadcasting After Schema Update

The `PeerNode._handle_request()` method already broadcasts events after `observe`/`claim`/`flag_contradiction`. The same pattern extends to `update_schema`:

```python
# In PeerNode._handle_request():
if method in ("observe", "claim", "flag_contradiction"):
    await self._broadcast_event(method, { ... })

if method == "update_schema":
    await self._broadcast_event("schema_updated", {
        "schema": result,
        "version": result.get("schema_version"),
    })
```

### 9.3 Data Directory

The `data/` directory must exist on the store node. In Docker, this is a volume mount. In local dev, `SchemaStore.load()` creates it if missing (`path.parent.mkdir(parents=True, exist_ok=True)`).

---

## 10. Changes Summary

Every file that needs modification, and what changes:

| File | Change |
|---|---|
| `src/schema/loader.py` | Add `origin`, `reasoning`, `last_reviewed` to `PredicateInfo`. Add `origin`, `reasoning` to `ExclusivityGroup`. Add `to_dict()` and `from_dict()` to `PredicateSchema`. |
| `src/schema/store.py` | **New file.** `SchemaStore` class: load, update, persist, version. |
| `src/schema/__init__.py` | Export `SchemaStore`. |
| `src/memory_protocol.py` | Add `get_schema()` and `update_schema()` to `MemoryAPI` protocol. |
| `src/interfaces.py` | Add `schema_store` param to `MemoryService.__init__()`. Implement `get_schema()` and `update_schema()`. |
| `src/p2p/memory_client.py` | Add `get_schema()` and `update_schema()` methods. |
| `src/p2p/routing.py` | Add `get_schema` and `update_schema` to `METHOD_CAPABILITIES`. |
| `src/p2p/types.py` | Add `Capability.SCHEMA` enum value. |
| `src/p2p/node.py` | Broadcast `schema_updated` event after `update_schema` requests. Use TTL 5 for schema events. |
| `src/agents/validator.py` | Listen for `schema_updated` events. Override `on_network_event()` for hot-reload. |
| `run_node.py` | Create `SchemaStore` on store nodes. Fetch schema via `get_schema()` for validator startup. |
| `main.py` | Same `SchemaStore` wiring for dev mode. |

### New files

| File | Purpose |
|---|---|
| `src/schema/store.py` | `SchemaStore` class |
| `data/.gitkeep` | Ensure data directory exists in repo |

### Not changed

| File | Reason |
|---|---|
| `src/schema/bootstrap.yaml` | Unchanged. Serves as seed for first run only. |
| `src/agents/base.py` | No changes needed. Event-driven wakeup already supports new event types via subclass override. |
| `src/agents/inference.py` | Schema-aware inference is Phase 4. |
| `src/llm.py` | Schema-aware prompts are Phase 3–4. |
| `src/store.py` | Schema is not stored in Neo4j. |

---

## 11. Edge Cases

### 11.1 Store node restart

The store node loads `data/schema.yaml` on startup. All learned schema is preserved. Connected nodes may have stale schemas — they'll get the current version on their next `get_schema()` call or when the next `schema_updated` event is broadcast.

### 11.2 Consumer node missed a `schema_updated` event

Possible if the node was disconnected or the event's TTL expired before reaching it. Mitigated by:
- Fetching `get_schema()` on agent startup (always gets current version)
- Schema events using higher TTL (5 vs default 3)
- Future enhancement (not Phase 1): include schema version in gossip metadata, so nodes can detect staleness and fetch on mismatch

### 11.3 Schema file corruption

If `data/schema.yaml` is unreadable or malformed, `SchemaStore.load()` logs an error and falls back to seeding from bootstrap. This loses learned schema but ensures the system starts.

### 11.4 Concurrent update_schema calls

Not expected in normal operation (only one schema agent should exist). If it happens, the asyncio event loop serializes the calls — the second call sees the result of the first. No data loss, just version incremented twice.

### 11.5 Schema version overflow

`schema_version` is a Python `int` (unbounded). Not a concern.

### 11.6 No store node available

If the store node is down when an agent calls `get_schema()`, the agent falls back to the bootstrap schema (same as today). When the store node comes back and a `schema_updated` event is eventually broadcast, the agent hot-reloads.

---

## 12. Testing Strategy

### 12.1 Unit Tests (no Neo4j, no API key)

| Test | What it validates |
|---|---|
| `SchemaStore` load from bootstrap seed | First-run seeding creates `data/schema.yaml` with provenance fields |
| `SchemaStore` load from existing file | Subsequent runs preserve learned entries |
| `SchemaStore.update()` merge semantics | Incremental changes are applied correctly; version increments; timestamp updates |
| `SchemaStore.update()` new predicate | Adding an unknown predicate creates it with provided fields |
| `SchemaStore.update()` modify existing | Changing cardinality of a bootstrap predicate preserves other fields |
| `PredicateSchema.from_dict()` | Round-trip: `to_dict()` → `from_dict()` produces equivalent schema |
| `PredicateSchema.from_dict()` bootstrap format | Accepts dicts without provenance fields (backward compatibility) |
| Validator hot-reload | Simulated `schema_updated` event swaps `self._schema` |
| Validator event subscription | `event_types()` includes `"schema_updated"` |

### 12.2 Integration Tests (needs Neo4j)

| Test | What it validates |
|---|---|
| `MemoryService.get_schema()` | Returns full schema dict from `SchemaStore` |
| `MemoryService.update_schema()` | Applies changes, returns updated dict |

### 12.3 P2P Tests (needs running nodes)

| Test | What it validates |
|---|---|
| `P2PMemoryClient.get_schema()` routes to store | Schema agent node can fetch schema from store node |
| `P2PMemoryClient.update_schema()` routes and broadcasts | Update on store node triggers `schema_updated` event received by validator node |
| Validator hot-reload end-to-end | Schema change propagates to validator, next validation tick uses new schema |

---

## See Also

- [Schema Agent Design](schema_agent_design.md) — overall design and phasing
- [Validation Redesign](validation_redesign.md) — how the validator uses schema today
- [Knowledge Representation](knowledge_representation.md) — the data model schema operates on

---

*Document version: 1.0*
*Last updated: 2026-02-02*
*Status: Phase 1 spec — ready for review.*
