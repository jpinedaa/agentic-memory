"""FastAPI application for the Agentic Memory System.

Wraps MemoryService as an HTTP API. Publishes events to Redis
after observe/claim operations.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.events import EventBus
from src.interfaces import MemoryService
from src.llm import LLMTranslator
from src.store import StoreConfig, TripleStore

logger = logging.getLogger(__name__)


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

    app.state.memory = MemoryService(store=store, llm=llm)
    app.state.event_bus = event_bus
    app.state.store = store

    logger.info("API server started (Neo4j + Redis connected)")
    yield

    await store.close()
    await event_bus.close()
    logger.info("API server shut down")


app = FastAPI(
    title="Agentic Memory API",
    version="0.1.0",
    lifespan=lifespan,
)


# -- Helpers --

def _memory() -> MemoryService:
    return app.state.memory

def _events() -> EventBus:
    return app.state.event_bus


# -- Core endpoints --

@app.post("/v1/observe", response_model=ObserveResponse)
async def observe(req: ObserveRequest):
    obs_id = await _memory().observe(req.text, req.source)
    await _events().publish_observation({
        "id": obs_id,
        "source": req.source,
        "raw_content": req.text,
    })
    return ObserveResponse(observation_id=obs_id)


@app.post("/v1/claim", response_model=ClaimResponse)
async def claim(req: ClaimRequest):
    claim_id = await _memory().claim(req.text, req.source)
    await _events().publish_claim({
        "id": claim_id,
        "source": req.source,
        "text": req.text,
    })
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
    import json

    async def generate():
        async for event in _events().listen(CHANNEL_OBSERVATION, CHANNEL_CLAIM):
            channel = event.pop("_channel", "unknown")
            event_type = "observation" if "observation" in channel else "claim"
            yield {"event": event_type, "data": json.dumps(event)}

    return EventSourceResponse(generate())
