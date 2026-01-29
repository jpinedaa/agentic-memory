# Visual UI Design

This document defines the design for the real-time visual dashboard for the Agentic Memory System.

> **v0.3 note:** The UI was originally built against the centralized FastAPI + Redis backend (v0.2). It needs to be reconnected to the P2P architecture — connecting to any node's transport server instead of a central API. This is tracked as an open item.

---

## Overview

A React + D3.js dashboard providing real-time visualization of:
1. **Agent Topology** - Live view of P2P nodes, connections, and capability distribution
2. **Event Stream** - Flowing observations, claims, and inferences
3. **Graph View** - Neo4j knowledge graph visualization

The UI runs as a separate container, connecting to any P2P node via WebSocket.

---

## Architecture (v0.3 target)

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
│                    │  (connect to any node)│                        │
│                    └───────────┬───────────┘                        │
└────────────────────────────────┼────────────────────────────────────┘
                                 │
                    WebSocket ws://node:9000/p2p/ws
                                 │
┌────────────────────────────────┼────────────────────────────────────┐
│                      Any PeerNode                                   │
│                    ┌───────────┴───────────┐                        │
│                    │  TransportServer      │                        │
│                    │  (FastAPI + WS)       │                        │
│                    └───────────┬───────────┘                        │
│                                │                                    │
│    ┌───────────┬───────────────┼───────────────┐                    │
│    │           │               │               │                    │
│    ▼           ▼               ▼               ▼                    │
│ Routing    Gossip          Events          Health                   │
│ Table      Protocol        (P2P flood)     Checks                  │
└─────────────────────────────────────────────────────────────────────┘
```

Key change from v0.2: The UI no longer depends on a central API. It connects to any node's WebSocket endpoint and receives the same gossip/event data that nodes exchange with each other.

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

A force-directed graph showing P2P nodes and their WebSocket connections.

```
     ┌──────────┐
     │ STORE+LLM│
     └────┬─────┘
          │ ws
    ┌─────┼─────────┐
    │     │         │
    ▼     ▼         ▼
┌──────┐ ┌──────┐ ┌──────┐
│ INF  │ │ VAL  │ │ CLI  │
└──────┘ └──────┘ └──────┘
```

**Visual Elements:**
- **Nodes**: Color-coded by capability set (not centralized hub — all peers are equal)
  - Store+LLM: Purple
  - Inference: Blue
  - Validator: Green
  - CLI: Orange
- **Connection lines**: WebSocket connections between neighbors
- **Status glow**: Green = alive, Yellow = suspect, Gray = dead
- **Capability badges**: Small icons showing what each node can do
- **Metrics tooltip**: Hover to see heartbeat_seq, uptime, capabilities

### 2. Event Stream Panel

Unchanged from v0.2 — still a flowing list of memory events.

### 3. Graph View Panel

Unchanged from v0.2 — still a D3 force-directed knowledge graph. Data source changes from REST API to P2P request to a store-capable node.

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
├── package.json
├── vite.config.ts
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── components/
│   │   ├── AgentTopology/
│   │   ├── EventStream/
│   │   ├── GraphView/
│   │   ├── StatusBar/
│   │   └── common/
│   ├── hooks/
│   │   ├── useP2PSocket.ts      # Connect to any node's WS
│   │   ├── useTopology.ts       # Build topology from gossip
│   │   └── useGraphData.ts
│   ├── stores/
│   │   ├── topologyStore.ts     # Zustand store for peer state
│   │   ├── eventStore.ts
│   │   └── graphStore.ts
│   ├── types/
│   │   └── index.ts
│   └── styles/
│       └── globals.css
└── tsconfig.json
```

---

## Migration TODO

The UI currently works against the v0.2 centralized API. To reconnect it to v0.3 P2P:

1. Replace `useWebSocket` hook — connect to any node's `/p2p/ws` endpoint
2. Replace `useAgentStatus` — derive from gossip topology instead of agent registry
3. Update `AgentTopology` — render P2P mesh instead of hub-and-spoke
4. Update `GraphView` data fetching — route queries via P2P to store-capable nodes
5. Update Docker config — `VITE_WS_URL` points to any node, not central API

---

## See Also

- [Agent Status Pattern](agent_status_pattern.md) - P2P gossip-based status
- [Design Tracking](design_tracking.md) - Full system architecture
- [Graph Patterns](graph_patterns.md) - Neo4j data model

---

*Document version: 0.2*
*Last updated: 2026-01-28*
