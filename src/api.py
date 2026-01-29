"""FastAPI application for the Agentic Memory System.

Wraps MemoryService as an HTTP API. Publishes events to Redis
after observe/claim operations. Includes agent status tracking
and WebSocket support for real-time visualization.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.agent_registry import AgentRegistry, AgentStatus
from src.events import EventBus
from src.interfaces import MemoryService
from src.llm import LLMTranslator
from src.store import StoreConfig, TripleStore
from src.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)

# Suppress noisy Neo4j warnings about unknown labels/properties on empty databases
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
logging.getLogger("neo4j").setLevel(logging.WARNING)


# -- Request/Response models --

class ObserveRequest(BaseModel):
    text: str
    source: str

class ObserveResponse(BaseModel):
    observation_id: str

class ClaimRequest(BaseModel):
    text: str
    source: str

class ClaimResponse(BaseModel):
    claim_id: str

class RememberRequest(BaseModel):
    query: str

class RememberResponse(BaseModel):
    response: str

class InferRequest(BaseModel):
    observation_text: str

class InferResponse(BaseModel):
    claim_text: str | None

class StatusResponse(BaseModel):
    status: str

class AgentRegisterRequest(BaseModel):
    agent_type: str
    tags: list[str] = []
    hostname: str = "unknown"
    pid: int = 0

class AgentRegisterResponse(BaseModel):
    agent_id: str
    push_interval_seconds: float

class AgentStatusRequest(BaseModel):
    agent_id: str
    agent_type: str
    tags: list[str] = []
    timestamp: str = ""
    started_at: str = ""
    uptime_seconds: float = 0.0
    status: str = "running"
    last_action: str = ""
    last_action_at: str | None = None
    items_processed: int = 0
    queue_depth: int = 0
    processing_time_avg_ms: float = 0.0
    error_count: int = 0
    memory_mb: float = 0.0
    push_interval_seconds: float = 30.0

class AgentStatusResponse(BaseModel):
    received: bool
    push_interval_seconds: float
    server_time: str

class PushIntervalRequest(BaseModel):
    push_interval_seconds: float


# -- App lifecycle --

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect to Neo4j + Redis. Shutdown: close connections."""
    config = StoreConfig(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        username=os.environ.get("NEO4J_USERNAME", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "memory-system"),
    )
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    llm_model = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")

    store = await TripleStore.connect(config)
    llm = LLMTranslator(api_key=anthropic_key, model=llm_model)
    event_bus = EventBus(redis_url=redis_url)
    registry = AgentRegistry(redis_url=redis_url)
    ws_manager = WebSocketManager()

    # Clean up dead agents from previous sessions
    await registry.list_agents()

    # Wire up status updates to WebSocket broadcasting
    async def on_status_update(status: AgentStatus):
        await ws_manager.broadcast_agent_status(status.to_dict())

    registry.add_status_listener(on_status_update)

    app.state.memory = MemoryService(store=store, llm=llm)
    app.state.event_bus = event_bus
    app.state.store = store
    app.state.registry = registry
    app.state.ws_manager = ws_manager

    logger.info("API server started (Neo4j + Redis + Agent Registry connected)")
    yield

    await store.close()
    await event_bus.close()
    await registry.close()
    logger.info("API server shut down")


app = FastAPI(
    title="Agentic Memory API",
    version="0.2.0",
    lifespan=lifespan,
)

# Allow CORS for UI container
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Helpers --

def _memory() -> MemoryService:
    return app.state.memory

def _events() -> EventBus:
    return app.state.event_bus

def _registry() -> AgentRegistry:
    return app.state.registry

def _ws() -> WebSocketManager:
    return app.state.ws_manager


# -- Core endpoints --

@app.post("/v1/observe", response_model=ObserveResponse)
async def observe(req: ObserveRequest):
    obs_id = await _memory().observe(req.text, req.source)
    event_data = {
        "id": obs_id,
        "source": req.source,
        "raw_content": req.text,
    }
    await _events().publish_observation(event_data)
    await _ws().broadcast_memory_event("observation", event_data)
    return ObserveResponse(observation_id=obs_id)


@app.post("/v1/claim", response_model=ClaimResponse)
async def claim(req: ClaimRequest):
    claim_id = await _memory().claim(req.text, req.source)
    event_data = {
        "id": claim_id,
        "source": req.source,
        "text": req.text,
    }
    await _events().publish_claim(event_data)
    await _ws().broadcast_memory_event("claim", event_data)
    return ClaimResponse(claim_id=claim_id)


@app.post("/v1/remember", response_model=RememberResponse)
async def remember(req: RememberRequest):
    response = await _memory().remember(req.query)
    return RememberResponse(response=response)


@app.post("/v1/infer", response_model=InferResponse)
async def infer(req: InferRequest):
    claim_text = await _memory().infer(req.observation_text)
    return InferResponse(claim_text=claim_text)


# -- Query endpoints --

@app.get("/v1/observations/recent")
async def get_recent_observations(limit: int = 10) -> dict[str, Any]:
    observations = await _memory().get_recent_observations(limit=limit)
    return {"observations": observations}


@app.get("/v1/claims/recent")
async def get_recent_claims(limit: int = 20) -> dict[str, Any]:
    claims = await _memory().get_recent_claims(limit=limit)
    return {"claims": claims}


@app.get("/v1/contradictions/unresolved")
async def get_unresolved_contradictions() -> dict[str, Any]:
    contradictions = await _memory().get_unresolved_contradictions()
    return {
        "contradictions": [
            {"c1": c1, "c2": c2} for c1, c2 in contradictions
        ]
    }


@app.get("/v1/entities")
async def get_entities() -> dict[str, Any]:
    entities = await _memory().get_entities()
    return {"entities": entities}


# -- Agent status endpoints --

@app.post("/v1/agents/register", response_model=AgentRegisterResponse)
async def register_agent(req: AgentRegisterRequest):
    agent_id, push_interval = await _registry().register(
        agent_type=req.agent_type,
        tags=req.tags,
        hostname=req.hostname,
        pid=req.pid,
    )
    await _ws().broadcast_agent_lifecycle("registered", agent_id, req.agent_type)
    return AgentRegisterResponse(
        agent_id=agent_id,
        push_interval_seconds=push_interval,
    )


@app.post("/v1/agents/status", response_model=AgentStatusResponse)
async def post_agent_status(req: AgentStatusRequest):
    from datetime import datetime

    status = AgentStatus(
        agent_id=req.agent_id,
        agent_type=req.agent_type,
        tags=req.tags,
        timestamp=req.timestamp,
        started_at=req.started_at,
        uptime_seconds=req.uptime_seconds,
        status=req.status,
        last_action=req.last_action,
        last_action_at=req.last_action_at,
        items_processed=req.items_processed,
        queue_depth=req.queue_depth,
        processing_time_avg_ms=req.processing_time_avg_ms,
        error_count=req.error_count,
        memory_mb=req.memory_mb,
        push_interval_seconds=req.push_interval_seconds,
    )

    push_interval = await _registry().update_status(status)

    return AgentStatusResponse(
        received=True,
        push_interval_seconds=push_interval,
        server_time=datetime.utcnow().isoformat() + "Z",
    )


@app.post("/v1/agents/{agent_id}/deregister")
async def deregister_agent(agent_id: str):
    # Get type before deregistering for the lifecycle event
    status = await _registry().get_status(agent_id)
    agent_type = status.agent_type if status else "unknown"

    await _registry().deregister(agent_id)
    await _ws().broadcast_agent_lifecycle("deregistered", agent_id, agent_type)
    return {"deregistered": True}


@app.get("/v1/agents")
async def list_agents(
    type: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    agents = await _registry().list_agents(agent_type=type, tag=tag)
    return {"agents": [a.to_dict() for a in agents]}


@app.get("/v1/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict[str, Any]:
    status = await _registry().get_status(agent_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return status.to_dict()


@app.get("/v1/agents/{agent_id}/config")
async def get_agent_config(agent_id: str) -> dict[str, Any]:
    status = await _registry().get_status(agent_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    interval = await _registry().get_push_interval(
        agent_id, status.agent_type, status.tags
    )
    return {"push_interval_seconds": interval}


@app.put("/v1/agents/{agent_id}/config")
async def set_agent_config(agent_id: str, req: PushIntervalRequest):
    await _registry().set_push_interval_for_agent(agent_id, req.push_interval_seconds)
    return {"updated": True, "push_interval_seconds": req.push_interval_seconds}


@app.put("/v1/agents/config/type/{agent_type}")
async def set_type_config(agent_type: str, req: PushIntervalRequest):
    await _registry().set_push_interval_for_type(agent_type, req.push_interval_seconds)
    return {"updated": True, "agent_type": agent_type, "push_interval_seconds": req.push_interval_seconds}


@app.put("/v1/agents/config/tag/{tag}")
async def set_tag_config(tag: str, req: PushIntervalRequest):
    await _registry().set_push_interval_for_tag(tag, req.push_interval_seconds)
    return {"updated": True, "tag": tag, "push_interval_seconds": req.push_interval_seconds}


@app.put("/v1/agents/config/default")
async def set_default_config(req: PushIntervalRequest):
    await _registry().set_default_push_interval(req.push_interval_seconds)
    return {"updated": True, "push_interval_seconds": req.push_interval_seconds}


# -- System stats --

@app.get("/v1/stats")
async def get_system_stats() -> dict[str, Any]:
    agents = await _registry().list_agents()
    active = [a for a in agents if a.status in ("running", "idle")]
    observations = await _memory().get_recent_observations(limit=1000)
    claims = await _memory().get_recent_claims(limit=1000)
    entities = await _memory().get_entities()

    return {
        "total_agents": len(agents),
        "active_agents": len(active),
        "total_observations": len(observations),
        "total_claims": len(claims),
        "total_entities": len(entities),
        "websocket_clients": _ws().connection_count,
    }


# -- Graph data endpoints (for UI) --

@app.get("/v1/graph/nodes")
async def get_graph_nodes(limit: int = 200) -> dict[str, Any]:
    """Get all nodes and edges for graph visualization."""
    observations = await _memory().get_recent_observations(limit=limit)
    claims = await _memory().get_recent_claims(limit=limit)
    entities = await _memory().get_entities()

    nodes = []
    node_ids = set()
    for obs in observations:
        nid = obs.get("id", "")
        nodes.append({"id": nid, "type": "Observation", "data": obs})
        node_ids.add(nid)
    for claim in claims:
        nid = claim.get("id", "")
        nodes.append({"id": nid, "type": "Claim", "data": claim})
        node_ids.add(nid)
    for entity in entities:
        nid = entity.get("id", "")
        nodes.append({"id": nid, "type": "Entity", "data": entity})
        node_ids.add(nid)

    # Get relationships, filtering to only include edges between returned nodes
    all_rels = await app.state.store.get_all_relationships(limit=limit * 3)
    edges = []
    for rel in all_rels:
        src = rel.get("source", "")
        tgt = rel.get("target", "")
        if src in node_ids and tgt in node_ids:
            edges.append({
                "source": src,
                "target": tgt,
                "type": rel.get("type", "RELATED"),
            })

    return {"nodes": nodes, "edges": edges, "count": len(nodes)}


# -- Admin --

@app.post("/v1/admin/clear", response_model=StatusResponse)
async def clear():
    await _memory().clear()
    return StatusResponse(status="ok")


@app.get("/v1/health", response_model=StatusResponse)
async def health():
    try:
        await app.state.store._driver.verify_connectivity()
        return StatusResponse(status="ok")
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# -- SSE event stream --

@app.get("/v1/events/stream")
async def event_stream():
    from sse_starlette.sse import EventSourceResponse
    from src.events import CHANNEL_OBSERVATION, CHANNEL_CLAIM

    async def generate():
        async for event in _events().listen(CHANNEL_OBSERVATION, CHANNEL_CLAIM):
            channel = event.pop("_channel", "unknown")
            event_type = "observation" if "observation" in channel else "claim"
            yield {"event": event_type, "data": json.dumps(event)}

    return EventSourceResponse(generate())


# -- WebSocket endpoint --

@app.websocket("/v1/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_id = await _ws().connect(websocket)

    # Send initial snapshot
    agents = await _registry().list_agents()
    await _ws().send_to_client(client_id, {
        "type": "snapshot",
        "data": {
            "agents": [a.to_dict() for a in agents],
        },
    })

    try:
        while True:
            data = await websocket.receive_json()
            await _ws().handle_message(client_id, data)

            # Handle snapshot requests
            if data.get("type") == "request_snapshot":
                agents = await _registry().list_agents()
                await _ws().send_to_client(client_id, {
                    "type": "snapshot",
                    "data": {
                        "agents": [a.to_dict() for a in agents],
                    },
                })

            # Handle push rate changes from UI
            if data.get("type") == "set_push_rate":
                agent_id = data.get("agent_id")
                interval = data.get("interval_seconds")
                if agent_id and interval:
                    await _registry().set_push_interval_for_agent(agent_id, float(interval))

    except WebSocketDisconnect:
        await _ws().disconnect(client_id)
    except Exception:
        logger.exception(f"WebSocket error for client {client_id}")
        await _ws().disconnect(client_id)
