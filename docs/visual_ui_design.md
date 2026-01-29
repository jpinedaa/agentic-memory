# Visual UI Design

This document defines the design for the real-time visual dashboard for the Agentic Memory System.

> **v0.3 update:** The UI is now connected to the P2P architecture via a bridge layer (`src/p2p/ui_bridge.py`) mounted on the store node. The bridge translates P2P state into `/v1/` endpoints the React frontend expects. Nginx proxies `/v1/` routes to the store node.

---

## Overview

A React + D3.js dashboard providing real-time visualization of:
1. **Agent Topology** - Live view of P2P nodes, connections, and capability distribution
2. **Event Stream** - Flowing observations, claims, and inferences
3. **Graph View** - Neo4j knowledge graph visualization

The UI runs as a separate container, connecting to any P2P node via WebSocket.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Visual UI (React)                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │
│  │ Agent Topology  │  │  Event Stream   │  │   Graph View    │     │
│  │  (D3 + Sidebar) │  │    (Live feed)  │  │    (D3.js)      │     │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘     │
│           │                    │                    │               │
│           └────────────────────┼────────────────────┘               │
│                                │                                    │
│                    ┌───────────┴───────────┐                        │
│                    │   WebSocket + REST    │                        │
│                    │  WS /v1/ws            │                        │
│                    │  GET /v1/graph/nodes  │                        │
│                    │  GET /v1/stats        │                        │
│                    └───────────┬───────────┘                        │
└────────────────────────────────┼────────────────────────────────────┘
                                 │ nginx proxy
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Store Node (port 9000)                            │
│                                                                     │
│  ┌──────────────────────────────────────────────┐                   │
│  │  UI Bridge (src/p2p/ui_bridge.py)            │                   │
│  │  - WS /v1/ws: snapshot + topology polling    │                   │
│  │  - GET /v1/graph/nodes: Neo4j query          │                   │
│  │  - GET /v1/stats: network + knowledge counts │                   │
│  └──────────────────────────────────────────────┘                   │
│                       │                                             │
│       ┌───────────────┼───────────────┐                             │
│       ▼               ▼               ▼                             │
│    Routing         P2P Events      Neo4j                            │
│    Table           (local listener) (TripleStore)                   │
└─────────────────────────────────────────────────────────────────────┘
```

The UI bridge sits on the store node (which has Neo4j access). It translates P2P `PeerState` into the `AgentStatus` format the React frontend expects and forwards memory events via WebSocket.

---

## P2P Data Sources

The UI gets its data from the P2P protocol messages flowing through the connected node:

| UI Panel | P2P Data Source |
|---|---|
| Agent Topology | `RoutingTable` (all known peers, capabilities, status) |
| Event Stream | `event` envelopes (observe, claim, inference, contradiction) |
| Graph View | Neo4j queries via any store-capable node |
| System Stats | Derived from routing table + event counts |

### Topology Data

The connected node's routing table provides the full network view:

```json
{
    "type": "topology",
    "peers": [
        {
            "node_id": "node-a3f8b2c1",
            "capabilities": ["store", "llm"],
            "status": "alive",
            "http_url": "http://store-node:9000",
            "heartbeat_seq": 142
        },
        {
            "node_id": "node-7d2e4f90",
            "capabilities": ["inference"],
            "status": "alive",
            "http_url": "http://inference-node:9001",
            "heartbeat_seq": 89
        }
    ]
}
```

### Event Data

Memory events are broadcast via P2P event flooding:

```json
{
    "type": "event",
    "event_type": "observe",
    "data": {
        "id": "obs-456",
        "content": "User prefers dark mode",
        "source_node": "node-a3f8b2c1",
        "timestamp": "2026-01-28T12:00:00Z"
    }
}
```

---

## UI Components

### 1. Agent Topology Panel

Two-column layout: D3 force-directed mesh graph on the left, status sidebar on the right.

```
┌──────────────────────────────┬────────────────────┐
│                              │  Network           │
│    STORE ◄──── INF           │  Total: 4          │
│      ▲          ▲            │  Active: 4         │
│      │          │            │  WS Clients: 1     │
│      ▼          ▼            │                    │
│    CLI ◄────► VAL            │  Knowledge         │
│                              │  Obs: 12           │
│  (D3 mesh, all nodes equal)  │  Claims: 8         │
│                              │  Entities: 5       │
│                              │                    │
│                              │  Store (1)         │
│                              │  ● node-a3f8 running│
│                              │                    │
│                              │  Inference (1)     │
│                              │  ● node-7d2e running│
└──────────────────────────────┴────────────────────┘
```

**D3 Graph (left):**
- **Nodes**: Color-coded by primary capability (all peers equal, P2P mesh)
  - Store: Purple (`#a371f7`)
  - Inference: Blue (`#58a6ff`)
  - Validation: Green (`#3fb950`)
  - CLI: Orange (`#d29922`)
- **Edges**: Gossip connections between all peers
- **Status glow**: Green = running, Yellow = suspect, Gray = dead
- **Drag/zoom/pan**: Interactive, state preserved across data updates

**Status Sidebar (right, 210px):**
- **Network section**: Total/active nodes, WebSocket clients
- **Knowledge section**: Observations, claims, entities, triples, relationships
- **Per-type sections**: Each node type (Store, Inference, Validator, CLI) shows cards with status dot, short ID, uptime, capabilities
- Data fetched from `/v1/stats` every 10 seconds

### 2. Event Stream Panel

Live feed of memory events (observations, claims, inferences, contradictions). Events forwarded from P2P network via the UI bridge's event listener.

### 3. Graph View Panel

D3 force-directed knowledge graph visualization. Always renders the SVG element (no conditional mounting). Fetches data from `/v1/graph/nodes` and auto-refreshes on memory events.

**Node types and colors:**
- Entity: Blue (`#58a6ff`)
- Observation: Gray (`#8b949e`)
- Claim: Green (`#3fb950`)
- ExtractedTriple: Yellow (`#d29922`)

Edges show relationship types as labels. Interactive legend toggles node type visibility.

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

/* Node capabilities */
--node-store: #a371f7;
--node-inference: #58a6ff;
--node-validator: #3fb950;
--node-cli: #d29922;

/* Peer status */
--peer-alive: #3fb950;
--peer-suspect: #d29922;
--peer-dead: #6e7681;

/* Event types */
--event-observation: #58a6ff;
--event-claim: #3fb950;
--event-inference: #a371f7;
--event-contradiction: #f85149;
```

---

## Project Structure

```
ui/
├── Dockerfile
├── nginx.conf                    # Proxies /v1/ to store-node:9000
├── package.json
├── vite.config.ts
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── components/
│   │   ├── AgentTopology/        # D3 mesh graph + NodeStatusSidebar
│   │   ├── EventStream/          # Live memory event feed
│   │   ├── GraphView/            # D3 knowledge graph (always-rendered SVG)
│   │   └── StatusBar/            # Footer: connection, counts, version
│   ├── hooks/
│   │   └── useWebSocket.ts       # Connect to /v1/ws via nginx proxy
│   ├── stores/
│   │   ├── agentStore.ts         # Zustand store for agent/peer state
│   │   ├── eventStore.ts         # Memory events
│   │   └── graphStore.ts         # Knowledge graph nodes/edges
│   ├── types/
│   │   └── index.ts              # AgentStatus, MemoryEvent, GraphNode, SystemStats
│   └── styles/
│       └── globals.css
└── tsconfig.json
```

---

## Implementation Notes

### UI Bridge Approach

Rather than modifying the React frontend to speak the P2P protocol directly, a bridge layer (`src/p2p/ui_bridge.py`) was added to the store node's FastAPI app. This provides the same `/v1/` endpoints the UI was built for:

- **WS `/v1/ws`**: Sends `snapshot` on connect with all peers as agents. Polls routing table every 2s for changes, forwards P2P memory events.
- **GET `/v1/graph/nodes`**: Queries Neo4j for all `Node` entities and relationships.
- **GET `/v1/stats`**: Returns structured stats with `network`, `knowledge`, and per-node-type `nodes` sections.

### PeerState → AgentStatus Translation

```python
CAPABILITY_PRIORITY = ["cli", "inference", "validation", "store", "llm"]
STATUS_MAP = {"alive": "running", "suspect": "stale", "dead": "dead"}
```

Primary capability is chosen by priority order (first match). A node with `{store, llm}` capabilities shows as type `store` in the UI.

### D3 Rendering Fix

The knowledge graph SVG is always rendered (not conditionally gated on `nodes.length > 0`). Status messages overlay the SVG. This prevents D3 initialization from running before the SVG element is mounted.

---

## See Also

- [Agent Status Pattern](agent_status_pattern.md) - P2P gossip-based status
- [Design Tracking](design_tracking.md) - Full system architecture
- [Graph Patterns](graph_patterns.md) - Neo4j data model

---

*Document version: 0.3*
*Last updated: 2026-01-29*
