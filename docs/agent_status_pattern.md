# Agent Status Pattern

This document defines the pattern for agents reporting status to the memory system, with configurable push rates.

---

## Overview

Agents push status heartbeats to the API at configurable intervals. The API aggregates status in Redis and exposes it via WebSocket for real-time visualization.

```
┌─────────────┐     heartbeat      ┌─────────────┐      store       ┌─────────────┐
│    Agent    │ ─────────────────► │   FastAPI   │ ───────────────► │    Redis    │
│  (push)     │   POST /v1/status  │   (API)     │   agent:status:* │  (storage)  │
└─────────────┘                    └─────────────┘                  └─────────────┘
                                          │
                                          │ broadcast
                                          ▼
                                   ┌─────────────┐
                                   │  WebSocket  │
                                   │   clients   │
                                   └─────────────┘
```

---

## Status Heartbeat

### Data Model

```python
@dataclass
class AgentStatus:
    # Identity
    agent_id: str           # Unique agent instance ID (UUID)
    agent_type: str         # "inference", "validator", "cli"
    tags: list[str]         # Custom tags for grouping

    # Timing
    timestamp: datetime     # When this heartbeat was sent
    started_at: datetime    # When agent started
    uptime_seconds: float   # Time since start

    # Operational
    status: str             # "running", "idle", "error", "stopping"
    last_action: str        # Description of last action taken
    last_action_at: datetime | None

    # Metrics
    items_processed: int    # Total items processed since start
    queue_depth: int        # Items waiting to be processed
    processing_time_avg_ms: float  # Average processing time
    error_count: int        # Total errors since start

    # Resources
    memory_mb: float        # Current memory usage

    # Push rate (echoed back from config)
    push_interval_seconds: float
```

### API Endpoint

```
POST /v1/agents/status
Content-Type: application/json

{
    "agent_id": "abc-123",
    "agent_type": "inference",
    "tags": ["gpu", "primary"],
    "timestamp": "2026-01-28T12:00:00Z",
    "started_at": "2026-01-28T11:00:00Z",
    "uptime_seconds": 3600.0,
    "status": "running",
    "last_action": "Processed observation obs-456",
    "last_action_at": "2026-01-28T11:59:55Z",
    "items_processed": 142,
    "queue_depth": 3,
    "processing_time_avg_ms": 250.5,
    "error_count": 2,
    "memory_mb": 156.3,
    "push_interval_seconds": 5.0
}
```

**Response:**

```json
{
    "received": true,
    "push_interval_seconds": 5.0,
    "server_time": "2026-01-28T12:00:00.123Z"
}
```

The response includes the configured push interval, allowing the API to dynamically adjust agent reporting rates.

---

## Push Rate Configuration

### Storage (Redis)

```
# Per-agent config
agent:config:{agent_id}:push_interval -> "5.0"

# Per-type defaults
agent:config:type:{agent_type}:push_interval -> "10.0"

# Per-tag config (lowest interval wins if multiple tags)
agent:config:tag:{tag}:push_interval -> "2.0"

# Global default
agent:config:default:push_interval -> "30.0"
```

### Resolution Order

1. Per-agent config (most specific)
2. Per-tag config (lowest interval if multiple tags match)
3. Per-type config
4. Global default (30 seconds)

### API Endpoints for Configuration

```
# Get config for an agent
GET /v1/agents/{agent_id}/config
Response: {"push_interval_seconds": 5.0, "source": "tag:gpu"}

# Set per-agent config
PUT /v1/agents/{agent_id}/config
Body: {"push_interval_seconds": 2.0}

# Set per-type config
PUT /v1/agents/config/type/{agent_type}
Body: {"push_interval_seconds": 10.0}

# Set per-tag config
PUT /v1/agents/config/tag/{tag}
Body: {"push_interval_seconds": 5.0}

# Set global default
PUT /v1/agents/config/default
Body: {"push_interval_seconds": 30.0}

# List all agents with current status
GET /v1/agents
Response: [{"agent_id": "...", "agent_type": "...", "status": "running", ...}]
```

---

## Agent Groups

### Built-in Groups (by type)

- `inference` - Inference agents
- `validator` - Validator agents
- `cli` - CLI instances

### Custom Tags

Agents can register with arbitrary tags:

```python
# In agent startup
await api.register_agent(
    agent_type="inference",
    tags=["gpu", "primary", "region-us-east"]
)
```

### Querying by Group

```
# All inference agents
GET /v1/agents?type=inference

# All agents with tag
GET /v1/agents?tag=gpu

# Combined
GET /v1/agents?type=inference&tag=primary
```

---

## Agent Lifecycle

### Registration

On startup, agents register with the API:

```
POST /v1/agents/register
{
    "agent_type": "inference",
    "tags": ["gpu"],
    "hostname": "worker-1",
    "pid": 12345
}

Response:
{
    "agent_id": "inf-abc-123",
    "push_interval_seconds": 10.0
}
```

### Heartbeat Loop

```python
async def heartbeat_loop(self):
    while self._running:
        status = self._collect_status()
        response = await self._api.post_status(status)

        # Update interval if server changed it
        self._push_interval = response.push_interval_seconds

        await asyncio.sleep(self._push_interval)
```

### Deregistration

On graceful shutdown:

```
POST /v1/agents/{agent_id}/deregister
```

### Stale Detection

Agents not sending heartbeats within 3x their push interval are marked `stale`. After 5x interval, marked `dead`.

---

## Redis Schema

```
# Agent status (expires after 5x push interval)
agent:status:{agent_id} -> JSON(AgentStatus)
TTL: push_interval * 5

# Agent registry (persistent)
agent:registry:{agent_id} -> JSON({agent_type, tags, registered_at})

# Active agents set (for quick listing)
agent:active -> SET of agent_ids

# Status history (optional, for graphs)
agent:history:{agent_id} -> ZSET (timestamp -> JSON snapshot)
```

---

## Implementation Plan

### Phase 1: Core Status Reporting

1. Add `AgentStatus` model to `src/models.py`
2. Add status endpoints to `src/api.py`
3. Add `AgentRegistry` class to `src/agent_registry.py` (Redis-backed)
4. Update `WorkerAgent` base class with heartbeat loop
5. Update inference/validator agents to report status

### Phase 2: Push Rate Configuration

1. Add config resolution logic to `AgentRegistry`
2. Add config endpoints to API
3. Update heartbeat loop to respect dynamic intervals

### Phase 3: WebSocket Broadcasting

1. Add WebSocket endpoint `/v1/ws/status`
2. Broadcast status updates to connected clients
3. Support filtered subscriptions (by type, tag)

---

## Code References

- `src/agents/base.py` - WorkerAgent base class (add heartbeat)
- `src/api.py` - API endpoints (add status routes)
- `src/agent_state.py` - AgentState (extend or create AgentRegistry)
- `src/events.py` - EventBus (use for status broadcasts)

---

*Document version: 0.1*
*Last updated: 2026-01-28*
