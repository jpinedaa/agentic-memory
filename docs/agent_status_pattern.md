# Agent Status Pattern

This document defines how agents report presence and health in the P2P network.

> **v0.3 update:** The centralized API + Redis heartbeat model (v0.2) has been replaced by gossip-based peer discovery. Agents are now P2P nodes that announce themselves via the gossip protocol.

---

## Overview

Every node in the network maintains a `PeerState` that is propagated to all other nodes via push-based gossip. There is no central registry — each node builds its own view of the network from gossip messages.

```
┌─────────────┐   gossip (WS)   ┌─────────────┐   gossip (WS)   ┌─────────────┐
│  Store Node │ ◄─────────────► │  Inference  │ ◄─────────────► │  Validator  │
│  (9000)     │                 │  Node (9001)│                 │  Node (9002)│
└─────────────┘                 └─────────────┘                 └─────────────┘
       ▲                                                               │
       │                    gossip (WS)                                │
       └───────────────────────────────────────────────────────────────┘
```

---

## PeerState Data Model

```python
@dataclass
class PeerState:
    info: PeerInfo          # Identity (node_id, capabilities, URLs)
    status: str = "alive"   # alive | suspect | dead
    last_seen: float = 0.0  # timestamp of last gossip received
    heartbeat_seq: int = 0  # monotonic counter, only owner increments
    metadata: dict = {}     # extensible (metrics, tags, etc.)
```

### PeerInfo (immutable identity)

```python
@dataclass(frozen=True)
class PeerInfo:
    node_id: str                        # "node-a3f8b2c1"
    capabilities: frozenset[Capability] # {STORE, LLM}
    http_url: str                       # "http://host:9000"
    ws_url: str                         # "ws://host:9000/p2p/ws"
    started_at: float
    version: str = "0.3.0"
```

---

## Heartbeat Mechanism

Each node increments its own `heartbeat_seq` every 5 seconds and pushes its full peer table to `min(3, len(neighbors))` random neighbors via WebSocket gossip messages.

```python
# In GossipProtocol._gossip_loop()
async def _gossip_loop(self):
    while self._running:
        self._increment_own_heartbeat()
        targets = self._select_gossip_targets()
        for target in targets:
            await self._send_gossip(target)
        await asyncio.sleep(self._interval)  # default 5s
```

### Convergence

Higher `heartbeat_seq` always wins when merging gossip:

```python
def _merge_peer_state(self, incoming: PeerState) -> bool:
    existing = self._routing.get_peer(incoming.info.node_id)
    if existing is None or incoming.heartbeat_seq > existing.heartbeat_seq:
        self._routing.update_peer(incoming)
        return True  # new information
    return False
```

Convergence time for N nodes: ~`log₃(N) × 5s`.

---

## Health Detection

Each node runs a health check loop that monitors peer liveness:

| Condition | Threshold | Action |
|---|---|---|
| No gossip from peer | 15 seconds | Mark `suspect` |
| No gossip from peer | 30 seconds | Mark `dead`, remove from routing |
| Gossip resumes | Any | Restore to `alive` |

Dead peers are skipped by `RoutingTable.route_method()` and their WebSocket connections are replaced with new neighbors.

---

## Agent Lifecycle

### Join

1. Node starts with `--bootstrap` URLs
2. Sends `join` envelope to each bootstrap peer
3. Receives `welcome` with list of known peers
4. Opens WebSocket connections to up to 8 neighbors (preferring complementary capabilities)
5. Begins gossip loop — all peers learn about the new node within seconds

### Running

- Gossip propagates `PeerState` continuously
- `heartbeat_seq` increments prove liveness without explicit heartbeat endpoints
- Any node can query its local `RoutingTable` for the full network view

### Leave (graceful)

1. Node sends `leave` envelope to all WebSocket neighbors
2. Neighbors immediately mark peer as dead and propagate via gossip
3. Network converges to remove the departed node

### Crash (ungraceful)

- No `leave` message sent
- Neighbors detect missing heartbeats via health check loop
- After 30s of silence, node is marked dead and removed

---

## Comparison with v0.2

| Aspect | v0.2 (Centralized) | v0.3 (P2P) |
|---|---|---|
| Registry | Redis-backed `AgentRegistry` | Gossip-built `RoutingTable` |
| Heartbeat | `POST /v1/agents/status` to API | `heartbeat_seq` in gossip |
| Discovery | Static API URL | Seed node bootstrap + gossip |
| Failure detection | 3x/5x push interval timeout | 15s suspect, 30s dead |
| Push rate config | Server-controlled via Redis | Fixed gossip interval (5s) |
| Single point of failure | API + Redis | None (fully decentralized) |

---

## Code References

- `src/p2p/types.py` — `PeerInfo`, `PeerState`, `Capability`
- `src/p2p/gossip.py` — `GossipProtocol` (heartbeat + gossip loop)
- `src/p2p/routing.py` — `RoutingTable` (peer tracking + capability routing)
- `src/p2p/node.py` — `PeerNode` (health check loop, neighbor management)
- `src/agents/base.py` — `WorkerAgent` (event-driven wakeup via `asyncio.Event`)

---

*Document version: 0.2*
*Last updated: 2026-01-28*
