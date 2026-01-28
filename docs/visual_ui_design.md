# Visual UI Design

This document defines the design for the real-time visual dashboard for the Agentic Memory System.

---

## Overview

A React + D3.js dashboard providing real-time visualization of:
1. **Agent Topology** - Live view of agents, connections, and activity pulses
2. **Event Stream** - Flowing observations, claims, and inferences
3. **Graph View** - Neo4j knowledge graph visualization

The UI runs as a separate container, connecting to the API via WebSocket.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Visual UI (React)                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │
│  │ Agent Topology  │  │  Event Stream   │  │   Graph View    │     │
│  │     (D3.js)     │  │    (D3.js)      │  │    (D3.js)      │     │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘     │
│           │                    │                    │               │
│           └────────────────────┼────────────────────┘               │
│                                │                                    │
│                    ┌───────────┴───────────┐                        │
│                    │   WebSocket Client    │                        │
│                    │  (real-time updates)  │                        │
│                    └───────────┬───────────┘                        │
└────────────────────────────────┼────────────────────────────────────┘
                                 │
                    WebSocket ws://api:8000/v1/ws
                                 │
┌────────────────────────────────┼────────────────────────────────────┐
│                         FastAPI (API)                               │
│                    ┌───────────┴───────────┐                        │
│                    │  WebSocket Handler    │                        │
│                    └───────────┬───────────┘                        │
│                                │                                    │
│    ┌───────────┬───────────────┼───────────────┬───────────┐        │
│    │           │               │               │           │        │
│    ▼           ▼               ▼               ▼           ▼        │
│ Agent      Status          Events          Graph       Config       │
│ Registry   Store          (Redis)         (Neo4j)      Store        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## WebSocket Protocol

### Connection

```
ws://localhost:8000/v1/ws
```

### Message Types (Server → Client)

```typescript
// Agent status update
{
    "type": "agent_status",
    "data": {
        "agent_id": "inf-123",
        "agent_type": "inference",
        "status": "running",
        "items_processed": 142,
        "queue_depth": 3,
        "memory_mb": 156.3,
        "timestamp": "2026-01-28T12:00:00Z"
    }
}

// Agent registered/deregistered
{
    "type": "agent_lifecycle",
    "event": "registered" | "deregistered" | "stale" | "dead",
    "data": {
        "agent_id": "inf-123",
        "agent_type": "inference"
    }
}

// Memory event (observation, claim, inference)
{
    "type": "memory_event",
    "event": "observation" | "claim" | "inference" | "contradiction",
    "data": {
        "id": "obs-456",
        "content": "User prefers dark mode",
        "source": "cli",
        "timestamp": "2026-01-28T12:00:00Z",
        // Additional fields vary by event type
    }
}

// Graph update (node/relationship created)
{
    "type": "graph_update",
    "operation": "create_node" | "create_relationship" | "delete_node",
    "data": {
        "node_type": "Claim",
        "id": "claim-789",
        "properties": {...}
    }
}

// System stats
{
    "type": "system_stats",
    "data": {
        "total_agents": 5,
        "active_agents": 4,
        "total_observations": 1234,
        "total_claims": 567,
        "total_entities": 89,
        "events_per_minute": 12.5
    }
}
```

### Message Types (Client → Server)

```typescript
// Subscribe to specific event types
{
    "type": "subscribe",
    "channels": ["agent_status", "memory_event", "graph_update"]
}

// Filter by agent type/tag
{
    "type": "filter",
    "agent_types": ["inference"],
    "agent_tags": ["primary"]
}

// Request current state snapshot
{
    "type": "request_snapshot"
}

// Control push rate for an agent
{
    "type": "set_push_rate",
    "agent_id": "inf-123",
    "interval_seconds": 2.0
}
```

---

## UI Components

### 1. Agent Topology Panel

A force-directed graph showing agents connected to the central API.

```
                    ┌─────┐
          ┌────────►│ INF │◄── pulse when active
          │         └─────┘
          │
     ┌────┴────┐    ┌─────┐
     │   API   │◄───│ VAL │
     └────┬────┘    └─────┘
          │
          │         ┌─────┐
          └────────►│ CLI │
                    └─────┘
```

**Visual Elements:**
- **API node**: Central, larger, fixed position
- **Agent nodes**: Orbit around API, color-coded by type
  - Inference: Blue
  - Validator: Green
  - CLI: Orange
- **Connection lines**: Thickness = push rate, opacity = last seen
- **Pulses**: Animated circles travel along connections on heartbeat
- **Status glow**: Green = running, Yellow = idle, Red = error, Gray = stale
- **Metrics tooltip**: Hover to see full metrics

**D3.js Implementation:**
- `d3-force` for layout
- `d3-transition` for pulse animations
- SVG circles for nodes, paths for connections

### 2. Event Stream Panel

A flowing river of events, newest at top.

```
┌────────────────────────────────────────────────────────┐
│ ● 12:00:05  [OBS]  User mentioned they work at Google  │ ← newest
│ ○ 12:00:04  [CLM]  user → works_at → Google            │
│ ◐ 12:00:03  [INF]  Inferred from obs-123               │
│ ● 12:00:01  [OBS]  My girlfriend is called ami         │
│ ○ 12:00:00  [CLM]  user → has_girlfriend → ami         │
│ ...                                                     │
└────────────────────────────────────────────────────────┘
```

**Visual Elements:**
- **Event cards**: Slide in from top with animation
- **Color coding**: Observation (blue), Claim (green), Inference (purple), Contradiction (red)
- **Icons**: Different shapes for event types
- **Timestamp**: Relative time (5s ago) with hover for absolute
- **Filtering**: Toggle visibility by event type
- **Click to expand**: Show full details, related items

**D3.js Implementation:**
- Enter/exit transitions for smooth flow
- `d3-scale` for time axis
- Card-based layout with CSS transitions

### 3. Graph View Panel

Interactive Neo4j knowledge graph visualization.

```
         ┌──────────┐
         │  user    │
         └────┬─────┘
              │
    ┌─────────┼─────────┐
    │         │         │
    ▼         ▼         ▼
┌──────┐  ┌──────┐  ┌────────┐
│ ami  │  │Google│  │dark    │
│      │  │      │  │mode    │
└──────┘  └──────┘  └────────┘

  girlfriend  works_at  prefers
```

**Visual Elements:**
- **Entity nodes**: Circles, size = connection count
- **Claim edges**: Labeled with predicate, color = confidence
- **Observation nodes**: Smaller, connected to entities mentioned
- **Clustering**: Related entities cluster together
- **Zoom/pan**: Navigate large graphs
- **Selection**: Click node to highlight relationships
- **Time slider**: Show graph state at different points in time

**D3.js Implementation:**
- `d3-force` for layout
- `d3-zoom` for zoom/pan
- SVG markers for edge labels
- Fetch graph data via REST API, incremental updates via WebSocket

---

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Agentic Memory System                         [⚙️ Settings] [📊]   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────┐  ┌─────────────────────────────────┐  │
│  │                         │  │                                 │  │
│  │    Agent Topology       │  │        Event Stream             │  │
│  │                         │  │                                 │  │
│  │    [Force Graph]        │  │    [Flowing Events]             │  │
│  │                         │  │                                 │  │
│  │                         │  │                                 │  │
│  └─────────────────────────┘  └─────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                                                              │  │
│  │                      Graph View                              │  │
│  │                                                              │  │
│  │              [Neo4j Knowledge Graph]                         │  │
│  │                                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Agents: 5 active │ Events: 12.5/min │ Nodes: 1,890 │ Uptime   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Color Palette

```css
/* Dark theme (default) */
--bg-primary: #0d1117;
--bg-secondary: #161b22;
--bg-tertiary: #21262d;
--border: #30363d;
--text-primary: #c9d1d9;
--text-secondary: #8b949e;

/* Agent types */
--agent-inference: #58a6ff;
--agent-validator: #3fb950;
--agent-cli: #d29922;
--agent-stale: #6e7681;
--agent-dead: #f85149;

/* Event types */
--event-observation: #58a6ff;
--event-claim: #3fb950;
--event-inference: #a371f7;
--event-contradiction: #f85149;

/* Graph nodes */
--node-entity: #58a6ff;
--node-observation: #8b949e;
--node-claim: #3fb950;
--edge-default: #30363d;
--edge-highlight: #58a6ff;
```

---

## Project Structure

```
ui/
├── Dockerfile
├── package.json
├── vite.config.ts
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── components/
│   │   ├── AgentTopology/
│   │   │   ├── AgentTopology.tsx
│   │   │   ├── AgentNode.tsx
│   │   │   ├── ConnectionLine.tsx
│   │   │   └── PulseAnimation.tsx
│   │   ├── EventStream/
│   │   │   ├── EventStream.tsx
│   │   │   ├── EventCard.tsx
│   │   │   └── EventFilter.tsx
│   │   ├── GraphView/
│   │   │   ├── GraphView.tsx
│   │   │   ├── GraphNode.tsx
│   │   │   └── GraphEdge.tsx
│   │   ├── StatusBar/
│   │   │   └── StatusBar.tsx
│   │   └── common/
│   │       ├── Tooltip.tsx
│   │       └── Panel.tsx
│   ├── hooks/
│   │   ├── useWebSocket.ts
│   │   ├── useAgentStatus.ts
│   │   └── useGraphData.ts
│   ├── stores/
│   │   ├── agentStore.ts      # Zustand store for agent state
│   │   ├── eventStore.ts
│   │   └── graphStore.ts
│   ├── types/
│   │   └── index.ts           # TypeScript interfaces
│   └── styles/
│       └── globals.css
└── tsconfig.json
```

---

## Docker Configuration

```dockerfile
# ui/Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
```

```yaml
# docker-compose.yml addition
  ui:
    build: ./ui
    ports:
      - "3000:3000"
    depends_on:
      - api
    environment:
      VITE_API_URL: http://localhost:8000
      VITE_WS_URL: ws://localhost:8000
```

---

## Implementation Plan

### Phase 1: Foundation

1. Create `ui/` directory with React + Vite + TypeScript
2. Set up D3.js, Zustand, and CSS modules
3. Create WebSocket hook with reconnection logic
4. Build basic layout shell with panels

### Phase 2: Agent Topology

1. Implement force-directed graph with D3
2. Add agent nodes with status colors
3. Implement pulse animations on heartbeat
4. Add tooltips with agent metrics

### Phase 3: Event Stream

1. Build event card component
2. Implement enter/exit animations
3. Add filtering by event type
4. Add click-to-expand detail view

### Phase 4: Graph View

1. Fetch initial graph from REST API
2. Implement force-directed layout for knowledge graph
3. Add zoom/pan controls
4. Implement incremental updates via WebSocket

### Phase 5: Polish

1. Add settings panel (theme, push rates)
2. Responsive layout for different screen sizes
3. Performance optimization for large graphs
4. Add loading states and error handling

---

## API Endpoints Required

The UI needs these endpoints (in addition to existing):

```
GET  /v1/agents                    # List all agents with status
GET  /v1/agents/{id}               # Get agent details
PUT  /v1/agents/{id}/config        # Update push rate
GET  /v1/graph/nodes               # Get all nodes (paginated)
GET  /v1/graph/relationships       # Get all relationships
GET  /v1/stats                     # System statistics
WS   /v1/ws                        # WebSocket connection
```

---

## See Also

- [Agent Status Pattern](agent_status_pattern.md) - Status reporting protocol
- [Design Tracking](design_tracking.md) - Full system architecture
- [Graph Patterns](graph_patterns.md) - Neo4j data model

---

*Document version: 0.1*
*Last updated: 2026-01-28*
