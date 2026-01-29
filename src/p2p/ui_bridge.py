"""UI bridge: translates P2P network state into the /v1/ API the React frontend expects."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

if TYPE_CHECKING:
    from src.p2p.node import PeerNode
    from src.store import TripleStore

logger = logging.getLogger(__name__)

STATUS_MAP = {"alive": "running", "suspect": "stale", "dead": "dead"}

# Priority order for picking "agent_type" from capabilities
CAPABILITY_PRIORITY = ["cli", "inference", "validation", "store", "llm"]


def _peer_to_agent(peer_state) -> dict[str, Any]:
    """Convert a PeerState into the AgentStatus format the UI expects."""
    caps = sorted(c.value for c in peer_state.info.capabilities)
    # Pick primary capability as agent_type
    agent_type = "node"
    for cap in CAPABILITY_PRIORITY:
        if cap in caps:
            agent_type = cap
            break

    now = time.time()
    started = peer_state.info.started_at

    return {
        "agent_id": peer_state.info.node_id,
        "agent_type": agent_type,
        "tags": caps,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "uptime_seconds": now - started,
        "status": STATUS_MAP.get(peer_state.status, "running"),
        "last_action": "",
        "last_action_at": None,
        "items_processed": 0,
        "queue_depth": 0,
        "processing_time_avg_ms": 0,
        "error_count": 0,
        "memory_mb": 0,
        "push_interval_seconds": 5.0,
    }


def create_ui_bridge(node: PeerNode, store: TripleStore) -> APIRouter:
    """Create a FastAPI router with /v1/ endpoints for the React UI."""
    router = APIRouter(prefix="/v1")
    ui_clients: list[WebSocket] = []

    async def _broadcast_to_ui(msg: dict[str, Any]) -> None:
        """Send a message to all connected UI WebSocket clients."""
        dead = []
        payload = json.dumps(msg, default=str)
        for ws in ui_clients:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(payload)
                else:
                    dead.append(ws)
            except Exception:
                dead.append(ws)
        for ws in dead:
            ui_clients.remove(ws)

    async def _on_network_event(event_type: str, data: dict[str, Any]) -> None:
        """Forward P2P memory events to UI clients."""
        event_map = {"observe": "observation", "claim": "claim"}
        await _broadcast_to_ui({
            "type": "memory_event",
            "data": {
                "id": data.get("id", ""),
                "event": event_map.get(event_type, event_type),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source": data.get("source", ""),
                "text": data.get("text", ""),
                "raw_content": data.get("text", ""),
            },
        })

    # Register as event listener on the node
    node.add_event_listener(_on_network_event)

    @router.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        ui_clients.append(websocket)
        logger.info("UI client connected")

        try:
            # Send initial snapshot with all known peers + self
            from src.p2p.types import PeerState
            own_state = PeerState(
                info=node.info,
                status="alive",
                last_seen=time.time(),
                heartbeat_seq=node._heartbeat_seq,
            )
            all_agents = [_peer_to_agent(own_state)]
            for ps in node.routing.get_all_peers():
                all_agents.append(_peer_to_agent(ps))

            await websocket.send_json({
                "type": "snapshot",
                "data": {"agents": all_agents},
            })

            # Keep connection alive, poll for topology changes
            known_peers: dict[str, str] = {}  # node_id -> status
            for a in all_agents:
                known_peers[a["agent_id"]] = a["status"]

            while True:
                # Check for topology changes every 2 seconds
                await asyncio.sleep(2)

                current = {}
                own = PeerState(
                    info=node.info,
                    status="alive",
                    last_seen=time.time(),
                    heartbeat_seq=node._heartbeat_seq,
                )
                current[node.node_id] = _peer_to_agent(own)
                for ps in node.routing.get_all_peers():
                    current[ps.info.node_id] = _peer_to_agent(ps)

                # Detect changes
                for nid, agent in current.items():
                    prev_status = known_peers.get(nid)
                    if prev_status is None or prev_status != agent["status"]:
                        await websocket.send_json({
                            "type": "agent_status",
                            "data": agent,
                        })

                # Detect removed peers
                for nid in list(known_peers.keys()):
                    if nid not in current:
                        await websocket.send_json({
                            "type": "agent_lifecycle",
                            "data": {
                                "event": "deregistered",
                                "agent_id": nid,
                                "agent_type": "unknown",
                            },
                        })

                known_peers = {a["agent_id"]: a["status"] for a in current.values()}

        except WebSocketDisconnect:
            logger.info("UI client disconnected")
        except Exception:
            logger.debug("UI WebSocket error", exc_info=True)
        finally:
            if websocket in ui_clients:
                ui_clients.remove(websocket)

    @router.get("/graph/nodes")
    async def graph_nodes(limit: int = Query(default=200)) -> dict[str, Any]:
        """Return graph nodes and edges for the knowledge graph visualization."""
        try:
            # Get all nodes
            nodes_raw = await store.raw_query(
                "MATCH (n:Node) RETURN n LIMIT $limit",
                {"limit": limit},
            )
            nodes = []
            for record in nodes_raw:
                n = dict(record["n"])
                nodes.append({
                    "id": n.get("id", ""),
                    "type": n.get("type", "Unknown"),
                    "data": n,
                })

            # Get edges
            edges_raw = await store.get_all_relationships(limit=limit * 2)
            edges = [
                {"source": e["source"], "target": e["target"], "type": e["type"]}
                for e in edges_raw
            ]

            return {"nodes": nodes, "edges": edges}
        except Exception:
            logger.debug("Error fetching graph data", exc_info=True)
            return {"nodes": [], "edges": []}

    @router.get("/stats")
    async def stats() -> dict[str, Any]:
        """Return system statistics with per-node-type breakdown."""
        from src.p2p.types import PeerState

        # Build node-type breakdown from routing table
        own_state = PeerState(
            info=node.info,
            status="alive",
            last_seen=time.time(),
            heartbeat_seq=node._heartbeat_seq,
        )
        all_peers = [own_state] + node.routing.get_all_peers()
        nodes_by_type: dict[str, list[dict[str, Any]]] = {}
        for ps in all_peers:
            agent = _peer_to_agent(ps)
            atype = agent["agent_type"]
            if atype not in nodes_by_type:
                nodes_by_type[atype] = []
            nodes_by_type[atype].append({
                "agent_id": agent["agent_id"],
                "status": agent["status"],
                "uptime_seconds": agent["uptime_seconds"],
                "capabilities": agent["tags"],
            })

        alive_count = sum(
            1 for ps in all_peers if ps.status == "alive"
        )

        try:
            obs_count = await store.raw_query(
                "MATCH (n:Node {type: 'Observation'}) RETURN count(n) AS c"
            )
            claim_count = await store.raw_query(
                "MATCH (n:Node {type: 'Claim'}) RETURN count(n) AS c"
            )
            entity_count = await store.raw_query(
                "MATCH (n:Node {type: 'Entity'}) RETURN count(n) AS c"
            )
            triple_count = await store.raw_query(
                "MATCH (n:Node {type: 'ExtractedTriple'}) RETURN count(n) AS c"
            )
            rel_count = await store.raw_query(
                "MATCH ()-[r]->() RETURN count(r) AS c"
            )

            return {
                "network": {
                    "total_nodes": len(all_peers),
                    "active_nodes": alive_count,
                    "websocket_clients": len(ui_clients),
                    "nodes_by_type": {
                        t: len(ns) for t, ns in nodes_by_type.items()
                    },
                },
                "knowledge": {
                    "observations": obs_count[0]["c"] if obs_count else 0,
                    "claims": claim_count[0]["c"] if claim_count else 0,
                    "entities": entity_count[0]["c"] if entity_count else 0,
                    "triples": triple_count[0]["c"] if triple_count else 0,
                    "relationships": rel_count[0]["c"] if rel_count else 0,
                },
                "nodes": nodes_by_type,
                # Keep legacy fields for backward compat
                "total_agents": len(all_peers),
                "active_agents": alive_count,
                "total_observations": obs_count[0]["c"] if obs_count else 0,
                "total_claims": claim_count[0]["c"] if claim_count else 0,
                "total_entities": entity_count[0]["c"] if entity_count else 0,
                "websocket_clients": len(ui_clients),
            }
        except Exception:
            logger.debug("Error fetching stats", exc_info=True)
            return {
                "network": {
                    "total_nodes": len(all_peers),
                    "active_nodes": alive_count,
                    "websocket_clients": len(ui_clients),
                    "nodes_by_type": {
                        t: len(ns) for t, ns in nodes_by_type.items()
                    },
                },
                "knowledge": {
                    "observations": 0,
                    "claims": 0,
                    "entities": 0,
                    "triples": 0,
                    "relationships": 0,
                },
                "nodes": nodes_by_type,
                "total_agents": len(all_peers),
                "active_agents": alive_count,
                "total_observations": 0,
                "total_claims": 0,
                "total_entities": 0,
                "websocket_clients": len(ui_clients),
            }

    return router
